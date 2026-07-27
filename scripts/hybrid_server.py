# 로컬 완전 하이브리드 채팅 백엔드.
# 앱과 동일한 파이프라인을 노트북에서 재현한다:
#   질문 → 대명사 치환 → [키워드(KeywordSearchRanker 포팅) + 시맨틱(EmbeddingGemma)] → RRF → Gemma(serve) 답변
# eval_search.py의 키워드/벡터/RRF 로직을 그대로 재사용한다(드리프트 방지).
#   실행: (먼저 litert-lm serve 가 9379에 떠 있어야 함) python scripts/hybrid_server.py
import json
import os
import sqlite3
import struct
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_search as ev  # 키워드 랭킹/벡터/RRF 재사용

import numpy as np

GEMMA_URL = "http://127.0.0.1:9379/v1/chat/completions"
GEMMA_MODEL = "gemma4e2b"
TOP_N = 5           # Gemma에 넣을 카드 수(앱 ragContext(3)보다 여유 있게 5)
PORT = 8100
ALLOWED_ORIGINS = {"http://127.0.0.1:8000", "http://localhost:8000"}

RAG_FIELDS = ["name", "company", "title", "department", "industry", "location", "phone", "email", "address", "memo", "tags"]

# 앱 MainActivity.kt 의 대명사/생략형 후속 처리 포팅
PRONOUNS = ["그 사람의", "그 사람", "그사람", "그 분", "그분", "이 사람", "이사람", "저 사람", "저사람",
            "걔", "그 회사", "그회사", "방금 그", "그 명함", "이 분", "이분"]
ATTRIBUTE_NOUNS = ["전화번호", "전화", "번호", "연락처", "핸드폰", "휴대폰", "메일", "이메일",
                   "직급", "직함", "직책", "회사", "소속", "주소", "위치", "지역", "부서", "이름"]


def resolve_query(question: str, focus):
    if not focus:
        return question, False
    trimmed = question.lstrip()
    has_pron = any(p in question for p in PRONOUNS)
    # 질문에 숫자(전화번호 뒷자리 등 새 검색값)가 있으면 생략형으로 보지 않는다.
    has_new_value = any(ch.isdigit() for ch in question)
    is_ellip = (not has_new_value) and any(trimmed.startswith(n) for n in ATTRIBUTE_NOUNS)
    if not has_pron and not is_ellip:
        return question, False
    q = question
    for p in PRONOUNS:
        q = q.replace(p, focus)
    if q == question:
        q = focus + " " + question
    return q, True


# HJP_TEST_CARDS=data/cards_test50.json 처럼 지정하면 5000장 대신 소규모 통제 데이터셋을 쓴다.
# (이름 근사중복이 적어 멀티턴/키워드 테스트 노이즈가 줄어듦 — scripts/generate_test50.py 참고)
TEST_CARDS_PATH = os.environ.get("HJP_TEST_CARDS")

print("[hybrid] 카드/벡터/모델 로딩 중… (EmbeddingGemma 1.2GB — 30초~1분 걸릴 수 있음)")
from sentence_transformers import SentenceTransformer  # noqa: E402
MODEL = SentenceTransformer(str(ev.MODEL_PATH))

if TEST_CARDS_PATH:
    CARDS = json.loads(Path(TEST_CARDS_PATH).read_text(encoding="utf-8"))
    CARDS_BY_ID = {c["id"]: c for c in CARDS}
    PREPARED = []
    for c in CARDS:
        t = ev.card_original_text(c)
        PREPARED.append((t, set(t.split())))
    IDS = [c["id"] for c in CARDS]
    doc_texts = [ev.card_text(c) if hasattr(ev, "card_text") else ", ".join(
        c.get(f, "") for f in ["name", "nameEn", "company", "title", "department", "industry", "location", "memo", "tags"] if c.get(f)
    ) for c in CARDS]
    DOC_MAT = np.asarray(MODEL.encode_document(doc_texts), dtype="<f4")
    print(f"[hybrid] 테스트 데이터셋 사용: {TEST_CARDS_PATH} ({len(CARDS)}명, 임베딩 실시간 계산)")
else:
    CARDS = json.loads(ev.CARDS_PATH.read_text(encoding="utf-8"))
    CARDS_BY_ID = {c["id"]: c for c in CARDS}
    PREPARED = []
    for c in CARDS:
        t = ev.card_original_text(c)
        PREPARED.append((t, set(t.split())))
    IDS = json.loads(ev.IDS_PATH.read_text(encoding="utf-8"))
    _raw = ev.VECTORS_PATH.read_bytes()
    DOC_MAT = np.frombuffer(_raw, dtype="<f4").reshape(len(IDS), ev.DIM).copy()

# 키워드 검색: 저쪽(검색 담당) 방식 = FTS4 unicode61 티어드(phrase→allTerms→prefix→LIKE).
# eval에서 내 LIKE+점수 방식보다 상위 정확도가 높아(특히 전화번호) 이걸 채택.
_FTS = sqlite3.connect(":memory:", check_same_thread=False)
_FTS.execute("CREATE VIRTUAL TABLE fts USING fts4(cardId, text, tokenize=unicode61)")
_FTS.executemany("INSERT INTO fts(cardId, text) VALUES (?,?)",
                 [(CARDS[i]["id"], PREPARED[i][0]) for i in range(len(CARDS))])
_FTS.commit()
_FTS_LOCK = threading.Lock()


def _fts_match(match: str):
    with _FTS_LOCK:
        try:
            return [r[0] for r in _FTS.execute("SELECT cardId FROM fts WHERE text MATCH ?", (match,)).fetchall()]
        except sqlite3.OperationalError:
            return []


def _query_tokens(query: str):
    out = []
    for t in ev.normalize(query).split():
        if len(t) < 2 or t in ev.STOPWORDS:
            continue
        s = ev.strip_particle(t)
        if len(s) >= 2 and s not in out:
            out.append(s)
    return out


# 키워드 동의어 확장 — 앱 CardSearchService.kt의 SYNONYMS와 동기화(드리프트 주의).
# LIKE 폴백(가장 느슨한 티어)에만 적용 — 정밀한 ①②③ 티어는 원래 토큰만 쓴다.
SYNONYMS = {
    "ai": ["ai", "인공지능", "머신러닝", "개발", "연구"],
    "인공지능": ["ai", "인공지능", "머신러닝", "개발", "연구"],
    "개발": ["개발", "개발자", "엔지니어", "소프트웨어", "it", "ai"],
    "디자인": ["디자인", "디자이너", "브랜드", "크리에이티브"],
    "투자": ["투자", "벤처", "금융", "vc"],
    "영업": ["영업", "세일즈", "파트너십", "비즈니스"],
    "마케팅": ["마케팅", "브랜드", "광고", "홍보"],
    "의료": ["의료", "헬스케어", "제약", "병원"],
    "대표": ["대표", "ceo", "창업", "창업자"],
    "변호사": ["변호사", "법무", "법률"],
    "회계": ["회계", "회계사", "재무", "감사"],
}


def _expand_synonyms_for_fallback(terms):
    out = []
    for t in terms:
        if t not in out:
            out.append(t)
        for syn in SYNONYMS.get(t.lower(), []):
            if syn not in out:
                out.append(syn)
    return out


def keyword_ranking_fts(query: str):
    toks = _query_tokens(query)
    if not toks:
        return []
    out = []
    def add(ids):
        for i in ids:
            if i not in out:
                out.append(i)
    add(_fts_match('"%s"' % " ".join(toks)))          # 1) 정확 구문(인접)
    add(_fts_match(" ".join(toks)))                    # 2) 전체 단어(AND)
    add(_fts_match(" ".join(t + "*" for t in toks)))   # 3) 접두어(AND)
    # 4) LIKE 폴백 — 동의어까지 확장해서 term-by-term으로 처리(순서=우선순위, 앱과 동일하게).
    for t in _expand_synonyms_for_fallback(toks):
        add([CARDS[i]["id"] for i in range(len(CARDS)) if t in PREPARED[i][0]])
    return out


print(f"[hybrid] 준비 완료: 카드 {len(CARDS)}장, 벡터 {DOC_MAT.shape}, 키워드=FTS4 티어드, 서버 :{PORT}")


def names(id_list, n=5):
    return [CARDS_BY_ID[i]["name"] + " · " + (CARDS_BY_ID[i].get("company") or "") for i in id_list[:n]]


def rag_context(id_list):
    blocks = []
    for cid in id_list:
        c = CARDS_BY_ID[cid]
        blocks.append("\n".join(f"{f}: {c.get(f, '')}" for f in RAG_FIELDS))
    return "\n\n".join(blocks)


def build_prompt(history, question, ctx):
    hist = ""
    if history:
        hist = "이전 대화:\n" + "\n".join(f"사용자: {h['q']}\n어시스턴트: {h['a']}" for h in history) + "\n\n"
    return (
        "You are an on-device assistant for a business card app.\n"
        "Answer in Korean using only the business card context below.\n"
        '- "그 사람" 같은 표현은 이전 대화에서 다룬 인물을 가리킨다. 그 인물 기준으로 답하라.\n'
        "- 컨텍스트에 이름이 비슷한 사람이 여러 명 있어도, 이전 대화의 인물과 일치하는 사람을 골라 답하라.\n"
        "- 명함 컨텍스트에 있다고 해서 전부 질문과 관련 있는 건 아니다. 질문과 실제로 관련된\n"
        "  사람만 답하고, 무관해 보이는 사람은 완전히 무시하라.\n"
        "- 되묻지 말고, 컨텍스트에 답이 있으면 바로 답하라. 정말 없을 때만 없다고 말하라.\n\n"
        f"{hist}명함 컨텍스트:\n{ctx}\n\n질문:\n{question}"
    )


def call_gemma(prompt):
    body = json.dumps({
        "model": GEMMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(GEMMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def run_turn(question, history, focus):
    rq, changed = resolve_query(question, focus)

    t0 = time.time()
    kw = keyword_ranking_fts(rq)  # 저쪽(검색 담당) FTS4 티어드 방식
    kw_ms = (time.time() - t0) * 1000

    t1 = time.time()
    qv = np.asarray(MODEL.encode_query([rq])[0], dtype="<f4")
    sims_arr = DOC_MAT @ qv
    order = np.argsort(-sims_arr)
    sims = {IDS[i]: float(sims_arr[i]) for i in range(len(IDS))}
    sem = [IDS[i] for i in order[:ev.TOP_K]]
    sem_ms = (time.time() - t1) * 1000

    hy = ev.rrf_fuse(kw, sims, CARDS_BY_ID)
    top_ids = hy[:TOP_N]

    t2 = time.time()
    try:
        answer = call_gemma(build_prompt(history, question, rag_context(top_ids)))
        err = None
    except Exception as e:  # noqa: BLE001
        answer, err = "", f"{type(e).__name__}: {e}"
    gen_ms = (time.time() - t2) * 1000

    # 질문이 실제로 이름을 지목했으면 그 이름을 우선 지칭 대상으로 삼는다.
    # 없으면(대명사/생략형 후속) 하이브리드 1등으로 대체 — "1등이면 무조건 focus"였던
    # 방식은 유사 이름 오매칭 시 focus가 엉뚱한 사람으로 튀는 문제가 있었음(실측 확인).
    result_names = list(dict.fromkeys(CARDS_BY_ID[cid]["name"] for cid in hy))
    named_in_question = next((n for n in result_names if n in question), None)
    focus_new = named_in_question or (result_names[0] if result_names else focus)
    return {
        "answer": answer,
        "error": err,
        "resolved_query": rq,
        "changed": changed,
        "keyword_top": names(kw),
        "semantic_top": names(sem),
        "hybrid_top": names(hy),
        "kw_ms": round(kw_ms, 1),
        "sem_ms": round(sem_ms, 1),
        "gen_ms": round(gen_ms, 1),
        "focus": focus_new,
        # 조회된 상위 명함(하이브리드 top N)의 필드 — 프런트에서 명함 카드로 렌더링.
        "cards": [
            {k: (CARDS_BY_ID[cid].get(k) or "") for k in ("name", "company", "title", "department", "phone", "email", "address", "location")}
            for cid in top_ids
        ],
    }


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "")
        allow = origin if origin in ALLOWED_ORIGINS else "http://127.0.0.1:8000"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "cards": len(CARDS)}).encode("utf-8"))
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_POST(self):
        if self.path != "/chat":
            self.send_response(404); self._cors(); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        result = run_turn(payload.get("question", ""), payload.get("history", []), payload.get("focus"))
        out = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass  # 조용히


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
