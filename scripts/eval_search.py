# 검색 품질 오프라인 평가: 키워드 / 시맨틱 / 하이브리드(RRF)를 5000장 합성 명함으로 측정한다.
#
# - 키워드 랭킹은 앱의 KeywordSearchRanker(Kotlin)를 충실히 포팅한 것 (드리프트 주의 — 로직 바꾸면 같이 갱신)
# - 시맨틱은 앱에 번들된 것과 동일한 사전 계산 문서 벡터 + 동일 모델의 쿼리 임베딩
# - 정답(ground truth)은 합성 데이터의 필드 값에서 자동 생성
#
# 사용법: python scripts/eval_search.py
import json
import random
import struct
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
CARDS_PATH = REPO / "data" / "cards_5000.json"
IDS_PATH = REPO / "app" / "src" / "main" / "assets" / "cards" / "cards_embeddings_ids.json"
VECTORS_PATH = REPO / "app" / "src" / "main" / "assets" / "cards" / "cards_embeddings.bin"
MODEL_PATH = REPO / "models" / "embeddinggemma-300m"

DIM = 768
TOP_K = 20
FUSION_POOL = 40  # searchHybrid가 각 축에서 상위 40개를 융합하는 것과 동일
RRF_K = 60.0

STOPWORDS = {
    "찾아줘", "찾아", "알려줘", "있는", "사람", "명함", "연락처", "누구",
    "please", "find", "show", "me", "who", "is", "are", "the", "a", "an",
}
PARTICLES = [
    "에서는", "에서", "에게", "한테", "으로", "이랑", "부터", "까지", "처럼", "밖에",
    "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "만", "랑", "로",
    # 존칭 — KeywordSearchRanker.kt와 동기화(드리프트 방지). "강서연씨" 매칭 실패 버그 수정.
    "씨", "님",
]


def has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㅣ" for ch in text)


def normalize(raw: str) -> str:
    out = []
    for ch in raw.lower():
        if ch.isspace():
            out.append(" ")
        elif unicodedata.category(ch)[0] in ("L", "N") or ch in "@._+-":
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def strip_particle(token: str) -> str:
    if not has_hangul(token):
        return token
    for particle in PARTICLES:
        if token.endswith(particle):
            stem = token[: -len(particle)]
            if len(stem) >= 2 and has_hangul(stem):
                return stem
    return token


def analyze(raw_query: str):
    normalized = normalize(raw_query)
    tokens = []
    for t in normalized.split():
        if len(t) < 2 or t in STOPWORDS:
            continue
        for v in (t, strip_particle(t)):
            digits = "".join(c for c in v if c.isdigit())
            variants = [v, digits] if len(digits) >= 3 and digits != v else [v]
            for x in variants:
                if x not in STOPWORDS and x not in tokens:
                    tokens.append(x)
    ngrams = []
    for t in tokens:
        if len(t) >= 3 and has_hangul(t):
            for i in range(len(t) - 1):
                bg = t[i : i + 2]
                if bg not in ngrams:
                    ngrams.append(bg)
    return tokens, ngrams, (normalized or raw_query)


FIELDS = ["name", "nameEn", "company", "title", "department", "industry", "location", "phone", "email", "address", "memo", "tags"]


def card_original_text(card: dict) -> str:
    phone_digits = "".join(c for c in card.get("phone", "") if c.isdigit())
    parts = [card.get(f, "") for f in FIELDS[:8]] + [phone_digits] + [card.get(f, "") for f in FIELDS[8:]]
    return normalize(" ".join(parts))


def score(card_text: str, card_tokens: set, tokens, ngrams) -> float:
    if not tokens:
        return 1.0
    s = 0.0
    for token in tokens:
        if token in card_tokens:
            s += 40.0
        elif any(t.startswith(token) for t in card_tokens):
            s += 25.0
        elif any(len(t) >= 2 and token.startswith(t) for t in card_tokens):
            s += 20.0
        elif token in card_text:
            s += 12.0
    for ng in ngrams:
        if ng in card_text:
            s += 4.0
    return s


def keyword_ranking(cards, prepared, query: str):
    tokens, ngrams, _ = analyze(query)
    scored = []
    for card, (text, tok_set) in zip(cards, prepared):
        s = score(text, tok_set, tokens, ngrams)
        if s > 0.0:
            scored.append((card["id"], s, card["name"]))
    scored.sort(key=lambda x: (-x[1], x[2]))
    return [cid for cid, _, _ in scored]


def rrf_fuse(keyword_ids, vector_scores, cards_by_id):
    kw_rank = {cid: i + 1 for i, cid in enumerate(keyword_ids[:FUSION_POOL])}
    vec_sorted = sorted(vector_scores.items(), key=lambda x: -x[1])[:FUSION_POOL]
    vec_rank = {cid: i + 1 for i, (cid, _) in enumerate(vec_sorted)}
    candidates = list(dict.fromkeys(list(kw_rank) + [cid for cid, _ in vec_sorted]))
    def rrf(rank):
        return 1.0 / (RRF_K + rank) if rank else 0.0
    rows = [
        (cid, rrf(kw_rank.get(cid)) + rrf(vec_rank.get(cid)), vector_scores.get(cid, 0.0), cards_by_id[cid]["name"])
        for cid in candidates
    ]
    rows.sort(key=lambda x: (-x[1], -x[2], x[3]))
    return [cid for cid, _, _, _ in rows]


def build_eval_queries(cards, rng):
    """합성 데이터 필드에서 정답이 확정되는 질의를 자동 생성한다."""
    queries = []  # (type, query, relevant_ids)
    by_company, by_name, by_loc_title = defaultdict(list), defaultdict(list), defaultdict(list)
    for c in cards:
        if c["company"]:
            core = c["company"]
            for prefix in ("(주)", "주식회사 ", "(유)", "유한회사 ", "(사)", "(주) "):
                core = core.removeprefix(prefix)
            core = core.strip()
            if len(core) >= 2:
                by_company[core].append(c["id"])
        if c["name"]:
            by_name[c["name"]].append(c["id"])
        if c["location"] and c["title"] and has_hangul(c["title"]):
            by_loc_title[(c["location"], c["title"])].append(c["id"])

    for core in rng.sample(sorted(by_company), 40):
        # 같은 핵심 상호를 포함하는 모든 회사(접두어 다른 변형 포함)를 정답으로 본다
        relevant = [c["id"] for c in cards if core in c["company"]]
        queries.append(("회사명", core, relevant))
    for name in rng.sample(sorted(by_name), 40):
        queries.append(("이름", name, by_name[name]))
    phone_cards = rng.sample(cards, 30)
    for c in phone_cards:
        digits = "".join(ch for ch in c["phone"] if ch.isdigit())
        if len(digits) >= 8:
            frag = digits[3:]
            relevant = [x["id"] for x in cards if frag in "".join(ch for ch in x["phone"] if ch.isdigit())]
            queries.append(("전화(하이픈X)", frag, relevant))
    pairs = [k for k, v in by_loc_title.items() if v]
    for loc, title in rng.sample(sorted(pairs), 40):
        q = f"{loc}에 있는 {title} 찾아줘"  # 조사·명령어 처리까지 함께 검증
        queries.append(("지역+직함(문장)", q, by_loc_title[(loc, title)]))
    return queries


def evaluate(name, rankings, queries):
    recall1 = recall5 = recall20 = mrr = 0.0
    per_type = defaultdict(lambda: [0.0, 0.0, 0])  # r5, mrr, n
    for (qtype, _, relevant), ranked in zip(queries, rankings):
        rel = set(relevant)
        top20 = ranked[:TOP_K]
        r1 = len(rel & set(top20[:1])) / min(len(rel), 1)
        r5 = len(rel & set(top20[:5])) / min(len(rel), 5)
        r20 = len(rel & set(top20)) / min(len(rel), TOP_K)
        rr = 0.0
        for i, cid in enumerate(top20):
            if cid in rel:
                rr = 1.0 / (i + 1)
                break
        recall1 += r1; recall5 += r5; recall20 += r20; mrr += rr
        pt = per_type[qtype]; pt[0] += r5; pt[1] += rr; pt[2] += 1
    n = len(queries)
    print(f"\n[{name}]  (질의 {n}개)")
    print(f"  Recall@1={recall1/n:.3f}  Recall@5={recall5/n:.3f}  Recall@20={recall20/n:.3f}  MRR={mrr/n:.3f}")
    for qtype, (r5, rr, cnt) in sorted(per_type.items()):
        print(f"    - {qtype:<12} (n={cnt:2d}): Recall@5={r5/cnt:.3f}  MRR={rr/cnt:.3f}")


def main():
    rng = random.Random(42)
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    cards_by_id = {c["id"]: c for c in cards}
    prepared = []
    for c in cards:
        text = card_original_text(c)
        prepared.append((text, set(text.split())))

    ids = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    raw = VECTORS_PATH.read_bytes()
    doc_vecs = {
        cid: struct.unpack_from(f"<{DIM}f", raw, i * DIM * 4)
        for i, cid in enumerate(ids)
    }

    queries = build_eval_queries(cards, rng)
    print(f"질의 {len(queries)}개 생성 (정답은 합성 데이터 필드에서 자동 유도)")

    print("쿼리 임베딩 계산 중 (온디바이스와 동일 모델/프롬프트)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(MODEL_PATH))
    q_vecs = model.encode_query([q for _, q, _ in queries], batch_size=32, show_progress_bar=True)

    kw_rankings, sem_rankings, hy_rankings = [], [], []
    for (qtype, q, rel), qv in zip(queries, q_vecs):
        kw = keyword_ranking(cards, prepared, q)
        sims = {cid: sum(a * b for a, b in zip(qv, dv)) for cid, dv in doc_vecs.items()}
        sem = [cid for cid, _ in sorted(sims.items(), key=lambda x: -x[1])[:TOP_K]]
        hy = rrf_fuse(kw, sims, cards_by_id)
        kw_rankings.append(kw[:TOP_K])
        sem_rankings.append(sem)
        hy_rankings.append(hy[:TOP_K])

    evaluate("키워드 전용", kw_rankings, queries)
    evaluate("시맨틱 전용", sem_rankings, queries)
    evaluate("하이브리드 (RRF)", hy_rankings, queries)


if __name__ == "__main__":
    main()
