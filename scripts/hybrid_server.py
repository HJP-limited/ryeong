# 로컬 완전 하이브리드 채팅 백엔드.
# 앱과 동일한 파이프라인을 노트북에서 재현한다:
#   질문 → 대명사 치환 → [키워드(KeywordSearchRanker 포팅) + 시맨틱(EmbeddingGemma)] → RRF → Gemma(serve) 답변
# eval_search.py의 키워드/벡터/RRF 로직을 그대로 재사용한다(드리프트 방지).
#   실행: (먼저 litert-lm serve 가 9379에 떠 있어야 함) python scripts/hybrid_server.py
import json
import struct
import sys
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
    is_ellip = any(trimmed.startswith(n) for n in ATTRIBUTE_NOUNS)
    if not has_pron and not is_ellip:
        return question, False
    q = question
    for p in PRONOUNS:
        q = q.replace(p, focus)
    if q == question:
        q = focus + " " + question
    return q, True


print("[hybrid] 카드/벡터/모델 로딩 중… (EmbeddingGemma 1.2GB — 30초~1분 걸릴 수 있음)")
CARDS = json.loads(ev.CARDS_PATH.read_text(encoding="utf-8"))
CARDS_BY_ID = {c["id"]: c for c in CARDS}
PREPARED = []
for c in CARDS:
    t = ev.card_original_text(c)
    PREPARED.append((t, set(t.split())))
IDS = json.loads(ev.IDS_PATH.read_text(encoding="utf-8"))
_raw = ev.VECTORS_PATH.read_bytes()
DOC_MAT = np.frombuffer(_raw, dtype="<f4").reshape(len(IDS), ev.DIM).copy()
from sentence_transformers import SentenceTransformer  # noqa: E402
MODEL = SentenceTransformer(str(ev.MODEL_PATH))
print(f"[hybrid] 준비 완료: 카드 {len(CARDS)}장, 벡터 {DOC_MAT.shape}, 서버 :{PORT}")


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
    kw = ev.keyword_ranking(CARDS, PREPARED, rq)
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

    focus_new = CARDS_BY_ID[hy[0]]["name"] if hy else focus
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
