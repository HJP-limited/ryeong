# 검색 품질 오프라인 평가: 키워드 / 시맨틱 / 하이브리드(RRF)를 5000장 합성 명함으로 측정한다.
#
# - 키워드 랭킹은 앱의 KeywordSearchRanker(Kotlin)를 충실히 포팅한 것 (드리프트 주의 — 로직 바꾸면 같이 갱신)
# - 시맨틱은 앱에 번들된 것과 동일한 사전 계산 문서 벡터 + 동일 모델의 쿼리 임베딩
# - 정답(ground truth)은 합성 데이터의 필드 값에서 자동 생성
#
# 사용법: python scripts/eval_search.py
import json
import math
import os
import random
import re
import sqlite3
import struct
import sys
import threading
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent

# 기본은 APK 시드/단위테스트와 **같은** 데이터(cards_eval1000.json).
# 평가·테스트·앱이 전부 같은 셋을 봐야 "지표 = 앱 성능"이 성립한다.
# HJP_EVAL_DATASET=prod5000 으로 구 프로덕션 셋(5000장)을 잴 수 있다(비교용).
_DATASET = os.environ.get("HJP_EVAL_DATASET", "").strip()
if _DATASET == "prod5000":
    CARDS_PATH = REPO / "data" / "cards_5000.json"
    IDS_PATH = REPO / "data" / "cards_5000_ids.json"
    VECTORS_PATH = REPO / "data" / "cards_5000_vectors.bin"
else:
    CARDS_PATH = REPO / "data" / "cards_eval1000.json"
    IDS_PATH = REPO / "data" / "cards_eval1000_ids.json"
    VECTORS_PATH = REPO / "data" / "cards_eval1000_vectors.bin"
MODEL_PATH = REPO / "models" / "embeddinggemma-300m"

DIM = 768
TOP_K = 20
# 융합에 넣을 축별 후보 수. CardSearchService.FUSION_POOL 과 같은 값이어야 한다.
#
# 40 -> 150 (실측 근거): 개념형 질의는 정답이 60~147명인데 풀이 40이면 후보가 최대 80개라
# 완벽해도 P@R 상한이 0.5~0.6 에 걸린다. 늘렸더니 개념형(hard) 0.318 -> 0.403,
# (easy) 0.509 -> 0.614 로 올랐고 150 에서 포화됐다(300·1000 도 동일).
# 이름·전화·회사명은 정답이 1~2명이라 풀 크기와 무관하게 변화 없음.
# 대가는 '지역+직함' 0.923 -> 0.892(노이즈 유입). 개념형 이득이 훨씬 커서 채택했다.
# 비용은 융합 계산 0.7ms -> 1.4ms 뿐이다 — LLM 에 넘기는 건 여전히 top-5(TOP_N)라
# 온디바이스 생성 시간에는 영향이 없다.
FUSION_POOL = 150
RRF_K = 60.0

STOPWORDS = {
    "찾아줘", "찾아", "알려줘", "있는", "사람", "명함", "연락처", "누구",
    "please", "find", "show", "me", "who", "is", "are", "the", "a", "an",
}
PARTICLES = [
    "에서는", "에서", "에게", "한테", "으로", "이랑", "부터", "까지", "처럼", "밖에",
    # 보조사가 붙은 형태. "판교에는"이 안 벗겨져서 "그럼 판교에는 누가 있어?"에
    # 지역 조건이 아예 안 걸렸다. "판교에"는 되는데 "판교에는"만 안 되던 비대칭.
    "에는", "에도", "에만", "이나", "라도",
    # 계사(이다)의 관형형 "-인". "주소가 대전인 사람", "직급이 상무인 사람" 처럼
    # 조건을 서술하는 흔한 표현인데 안 떼면 '대전인' 이 가제티어의 '대전' 과 매칭되지
    # 않아 조건이 하나도 안 잡히고, 카운트 경로가 검색으로 폴백해 후보 5장을 보고
    # "총 5명" 이라 답한다(실측: 실제 51명).
    # 이름 12개가 '인' 으로 끝나지만(성다인 등) 떼도 다른 이름과 충돌하지 않고,
    # analyze 가 원본 토큰도 함께 남기므로 잃는 게 없다.
    "인",
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
        # 긴 숫자 토큰(전화번호 조각 등)은 부분일치가 곧 정답 근거다.
        # 기존에는 '역전방 일치'(카드의 짧은 토큰 "33" 등으로 질의가 시작) 규칙이 20점을
        # 주는 바람에, 실제로 그 번호를 가진 카드(부분일치 12점)를 엉뚱한 카드가 눌렀다.
        # 실측: 질의 '33395185'의 정답 카드가 12점/13위, 무관한 카드가 20점/1위.
        if len(token) >= 6 and token.isdigit():
            s += 60.0 if token in card_text else 0.0
            continue
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


def keyword_ranking_scored_like(cards, prepared, query: str):
    """
    LIKE + 점수 방식(구버전). **앱은 이 방식을 쓰지 않는다** — 아래 FTS4 티어드가 정본이다.
    점수 분포를 봐야 할 때를 위해 남겨 둔다.
    """
    tokens, ngrams, _ = analyze(query)
    scored = []
    for card, (text, tok_set) in zip(cards, prepared):
        s = score(text, tok_set, tokens, ngrams)
        if s > 0.0:
            scored.append((card["id"], s, card["name"]))
    scored.sort(key=lambda x: (-x[1], x[2]))
    return [(cid, s) for cid, s, _ in scored]


# ---- FTS4 티어드 키워드 랭킹 (앱 CardSearchService.keywordHits 와 같은 방식) ----
#
# 왜 평가도 이걸 써야 하는가: 예전에는 평가만 LIKE+점수 랭커를 쓰고 앱/챗서버는 FTS4
# 티어드를 썼다. 두 랭커는 순위가 실제로 갈려서, 평가 지표가 앱 성능을 대변하지 못했다
# (실측: 같은 실험이 LIKE에서는 1위 정확일치 92/92인데 FTS4에서는 86/92,
#  '지역+직함' R@5 도 0.995 vs 0.883). 정본(Kotlin)과 같은 축으로 재야 의미가 있다.
_FTS_UNSAFE = re.compile(r"[^\w]+", re.UNICODE)
_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}

# 동의어 확장 — 앱 CardSearchService.kt 의 SYNONYMS 와 동기화할 것(드리프트 주의).
# LIKE 폴백(가장 느슨한 티어)에만 쓴다. 정밀한 1~3 티어는 원래 토큰만 쓴다.
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

_fts_conn = None
_fts_ids = None
_fts_texts = None
_fts_lock = threading.Lock()


def _fts_index(cards, prepared):
    """카드 목록이 바뀌면 인덱스를 다시 만든다(평가는 한 데이터셋만 쓰므로 캐시로 충분)."""
    global _fts_conn, _fts_ids, _fts_texts
    ids = [c["id"] for c in cards]
    if _fts_conn is not None and _fts_ids == ids:
        return
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE VIRTUAL TABLE fts USING fts4(cardId, text, tokenize=unicode61)")
    conn.executemany("INSERT INTO fts(cardId, text) VALUES (?,?)",
                     [(ids[i], prepared[i][0]) for i in range(len(cards))])
    conn.commit()
    _fts_conn, _fts_ids, _fts_texts = conn, ids, [prepared[i][0] for i in range(len(cards))]


def _fts_match(expr: str):
    with _fts_lock:
        try:
            return [r[0] for r in _fts_conn.execute(
                "SELECT cardId FROM fts WHERE text MATCH ?", (expr,)).fetchall()]
        except sqlite3.OperationalError:
            return []


def _fts_safe_terms(query: str):
    """analyze() 토큰을 FTS 안전 문자열로. analyze 를 쓰는 이유는 '2033인'->'2033' 같은
    숫자 변형까지 포함되기 때문이다(자체 토큰화는 그걸 놓쳐 실제 번호를 못 찾았다)."""
    tokens, _, _ = analyze(query)
    out = []
    for t in tokens:
        t = _FTS_UNSAFE.sub("", t)
        if len(t) >= 2 and t.upper() not in _FTS_OPERATORS:
            out.append(t)
    return out


def _expand_synonyms_for_fallback(terms):
    out = []
    for t in terms:
        if t not in out:
            out.append(t)
        for syn in SYNONYMS.get(t.lower(), []):
            if syn not in out:
                out.append(syn)
    return out


def keyword_ranking(cards, prepared, query: str):
    """앱과 동일한 티어 순서: 정확 구문 -> 전체 단어(AND) -> 접두어(AND) -> LIKE 폴백(동의어)."""
    _fts_index(cards, prepared)
    terms = _fts_safe_terms(query)
    if not terms:
        return []
    out, seen = [], set()

    def add(ids):
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)

    add(_fts_match('"%s"' % " ".join(terms)))
    add(_fts_match(" ".join(terms)))
    add(_fts_match(" ".join(t + "*" for t in terms)))
    for t in _expand_synonyms_for_fallback(terms):
        add([_fts_ids[i] for i in range(len(_fts_ids)) if t in _fts_texts[i]])
    return out


def keyword_ranking_scored(cards, prepared, query: str):
    """
    기권 게이트용. FTS 티어드는 점수를 내지 않으므로 '매칭 존재 여부'만 1.0 으로 전달한다
    (hybrid_server 가 하는 것과 동일 — should_abstain 은 점수 크기가 아니라 매칭 유무를 본다).
    """
    return [(cid, 1.0) for cid in keyword_ranking(cards, prepared, query)]


# 기권(abstention) 임계값 — "해당하는 사람 없음"으로 판정하는 기준.
#
# 왜 '절대 유사도 컷오프'가 아닌가: 코사인 절대값 하나로는 못 가른다는 게 실측으로 확인됐다.
#   - "변호사 찾아줘"(정답 있음) top1 = 0.378
#   - "홍길동 회사?"(정답 없음)   top1 = 0.458  <- 오답이 정답보다 높다
# 그래서 절대 임계값(예: 0.45)은 진짜 정답을 버리면서 노이즈는 통과시킨다.
#
# 대신 두 축의 '합의'와 '상대적 우위'를 본다:
#   1) 키워드 최고점이 아주 낮으면(문자 근거가 사실상 없음) 그리고
#   2) 시맨틱 1등이 뒤 순위와 뚜렷하게 벌어지지 않으면(변별력 없음)
#   -> 아무것도 반환하지 않는다.
# "정답이 있을 때는 둘 중 하나라도 뚜렷한 근거를 낸다"는 관찰에 기반한다.
# ---------------------------------------------------------------------------
# 기권(abstention) — 가제티어(사전) 기반
#
# 점수 기반 기권은 측정 결과 '원리적으로 불가능'하다는 결론이 나왔다. 근거:
#   - 어떤 신호(절대 유사도/마진 5·10·20·50위)로도 개념형과 기권 질의의 분포가 겹친다.
#     예) 기권시켜야 하는 "세종특별자치시 디자이너"의 마진(0.175)이
#         살려야 하는 "디자인 총괄"(0.024)보다 7배 높다.
#   - 이유: 그 질의는 '세종특별자치시'(없는 지역)만 없고 '디자이너'는 데이터에 많아서
#     검색이 강하게 반응하는 게 당연하다. 즉 점수로 가릴 문제가 아니다.
#   - 임계값 스윕 결과 개념형 보존과 기권 성공이 동시에 되는 지점이 없었다
#     (0.04 -> 74%/44%, 0.06 -> 29%/63%, 0.20 -> 0%/100%).
#
# 그래서 '값의 존재 여부'로 판정한다: 명함 도메인은 지역·직함 값 집합이 유한(폐쇄 도메인)해서
# 질의가 특정 필드 값을 지목했는지, 그 값이 실제로 데이터에 있는지 확인할 수 있다.
# 이건 가제티어 기반 개체 인식(gazetteer NER)으로, 폐쇄 도메인에서 쓰는 정식 기법이다.
# ---------------------------------------------------------------------------

# 지역을 가리키는 접미사 — 이걸로 끝나면 '지역을 지목한 토큰'으로 본다.
#
# 단일 글자 접미사 중 '시/구/리/동/면/읍'은 쓰지 않는다: 일상 단어에 너무 흔해서 오탐이 난다.
# 실측 사례 — "번호 뒷자리 2033인 사람"의 '뒷자리'가 '리'로 끝나 지역으로 오인되어
# 존재하는 번호인데도 기권 처리됐다.
#
# '도'는 예외적으로 넣는다. 섬 이름(울릉도/백령도/독도)이 전부 여기 걸리는데,
# 이 데이터에서는 오탐 위험이 실측상 없었다:
#   - 평가 205질의에서 '도'로 끝나는 토큰은 실제 지역 18건(전부 데이터에 존재) +
#     기권 대상 3건(전부 부재)뿐이었다.
#   - 직함 어휘 중 '도'로 끝나는 것은 0개다.
# '경기도'처럼 존재하는 지역은 region_exists 가 True 라 기권으로 안 빠진다 —
# 이 규칙은 '지역처럼 생겼는데 데이터에 없는 값'만 기권시킨다.
REGION_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "자치도", "자치시", "도")


# 사람 이름을 지목하는 호칭 접미사 — "정하은씨", "정하은님" 처럼 붙으면 이름 지목으로 본다.
NAME_HONORIFICS = ("씨", "님", "군", "양")


class Gazetteer:
    """카드 데이터에서 실제 존재하는 필드 값 집합을 추출해 둔다."""

    def __init__(self, cards):
        # locations: '행정구역 단위' 어휘만 담는다(기권 판정 전용).
        #   여기에 주소 도로명 조각을 섞으면 없는 지역("세종특별자치시")이 어딘가의 조각과
        #   부분 매칭돼 "존재한다"고 오판하고 기권이 안 된다(실측: 기권 0.30 -> 0.15).
        self.locations = set()
        self.titles = set()
        self.companies = set()
        self.names = set()
        # address_terms: 필터 전용 어휘. "판교"(판교역로), "강남"(강남구)처럼 행정구역
        # 접미사가 없는 관용 표현으로도 필터를 걸 수 있게 한다. 기권 판정에는 쓰지 않는다.
        self.address_terms = set()
        # title_terms: 직함 어휘. 주소 도로명에서 뽑은 조각과 겹칠 수 있어서
        # (예: 광주 '상무중앙로' -> '상무' 가 직함 '상무' 와 충돌) 지역 필터에서 제외하는 데 쓴다.
        self.title_terms = set()
        # departments/department_terms: 부서 어휘("AI개발팀", "서초지점").
        # 'AI'처럼 title 에는 없고 department 에만 있는 값이 많아서(실측: 5000장에서
        # 'ai' 포함 title 0명 / department 42명) 이게 없으면 "AI 개발자 몇 명이야?"를
        # 셀 수가 없다.
        self.departments = set()
        self.department_terms = set()

        for c in cards:
            t = (c.get("title") or "").strip()
            if t:
                nt = normalize(t)
                self.titles.add(nt)
                for part in nt.split():
                    if len(part) >= 2:
                        self.title_terms.add(part)
            d = (c.get("department") or "").strip()
            if d:
                nd = normalize(d)
                self.departments.add(nd)
                for part in nd.split():
                    if len(part) >= 2:
                        self.department_terms.add(part)

        for c in cards:
            loc = (c.get("location") or "").strip()
            if is_valid_location(loc):
                self.locations.add(normalize(loc))
            addr = (c.get("address") or "").strip()
            if addr:
                parts = normalize(addr).split()
                # 주소 첫 토큰(광역 단위)만 지역 존재 판정 어휘로 인정한다
                if parts:
                    self.locations.add(parts[0])
                for part in parts:
                    if len(part) < 2 or part.isdigit():
                        continue
                    self.address_terms.add(part)
                    # "판교역로" -> "판교", "강남구" -> "강남" 처럼 접미사를 뗀 관용 표현도 등록.
                    for suffix in ("특별자치시", "특별자치도", "특별시", "광역시", "역로", "대로", "로", "길", "시", "군", "구", "동", "읍", "면"):
                        if part.endswith(suffix) and len(part) - len(suffix) >= 2:
                            self.address_terms.add(part[: -len(suffix)])
                            break
            for extra in (normalize(loc).split() if loc else []):
                if len(extra) >= 2 and not extra.isdigit():
                    self.address_terms.add(extra)
            comp = (c.get("company") or "").strip()
            if comp:
                self.companies.add(normalize(comp))
            nm = (c.get("name") or "").strip()
            if nm:
                self.names.add(normalize(nm))

        # 직함/지역이 겹치는 단어("상무" — 직함 상무 / 광주 '상무대로')는 지역 어휘에서
        # 빼는 정적 규칙이 있었는데 제거했다. 그 규칙은 어휘를 깎아서 충돌을 회피하는
        # 방식이라 부작용이 있었다: "상무 찾아줘"에 아무 조건도 안 걸려 후보가 전체 그대로였다.
        # 지금은 충돌 해소를 어휘가 아니라 '판정 순서'로 한다 — extract_field_filters 와
        # count_by_known_condition 이 둘 다 직함을 먼저 보고, 직함이면 지역으로 넘기지 않는다.
        # 우선순위가 결정 지점에 명시적으로 들어가서 규칙이 필요 없어졌다(실측 확인).

        # 호칭 없는 맨 이름("정하은")을 이름 지목으로 인정하기 위한 근거 어휘.
        # 성/이름을 따로 모아 두고, '아는 성 + 아는 이름'으로 조립된 토큰만 이름으로 본다.
        #
        # 왜 이렇게까지 좁히는가(실측): 처음에는 '아는 성으로 시작하는 3자 한글'만 봤는데,
        # 그러면 서커스·조련사·조종사·임원급·공무원 같은 일반 명사가 전부 이름으로 잡혔다.
        # 기권 정확도는 우연히 올라갔지만("서커스 단장"은 실제로 없는 사람이라 정답 처리됨)
        # 개념형 질의("임원급 찾아줘", "공무원 직급")를 같이 죽여서 R@5 가 0.660 -> 0.630 이
        # 됐다. 이름 판정이 실제로는 '모르는 3자 단어 판정'이었던 셈이다.
        self.surnames = {nm[0] for nm in self.names if len(nm) >= 2}
        self.given_names = {nm[1:] for nm in self.names if len(nm) >= 2}

    def region_exists(self, token: str) -> bool:
        """
        지역 토큰이 데이터에 존재하는가.
        '서울'이 '서울특별시'에 걸리도록 접두어 관계는 인정하지만, 아무 위치의 부분 문자열
        포함은 인정하지 않는다(느슨하게 잡으면 없는 지역도 존재한다고 오판한다).
        """
        return any(loc == token or loc.startswith(token) or token.startswith(loc) for loc in self.locations)

    def looks_like_region(self, token: str) -> bool:
        return len(token) >= 3 and token.endswith(REGION_SUFFIXES)

    def name_exists(self, token: str) -> bool:
        """이름 토큰이 데이터에 존재하는가. 성을 뗀 형태('하은')로 불렀을 수도 있어 부분 일치도 인정."""
        return any(token == nm or token in nm for nm in self.names)

    def looks_like_person_name(self, token: str) -> bool:
        """
        '이름을 지목한 토큰'인지 본다. 두 가지 경로로 인정한다.

        1) 호칭이 붙은 경우("정하은씨") — 호칭 자체가 사람 지목의 확실한 신호다.
        2) 호칭 없는 맨 3자 한글("정하은") — 데이터에 있는 성('정') + 데이터에 있는
           이름('하은', 백하은에서)으로 조립된 경우만 인정한다. 즉 "우리가 아는 부품으로
           만들어졌지만 명단에 없는 이름"이다. 이 조건이 없으면 서커스·공무원 같은
           일반 명사가 이름으로 잡혀 개념형 질의를 죽인다.
           이게 있어야 검색창에 이름만 친 경우("정하은")에 임베딩이 발음 비슷한
           사람(백하은/하지연/하채원)을 끌어오고 LLM 이 없는 사람 답을 지어내는 걸 막는다.
        """
        if not all("가" <= ch <= "힣" for ch in token):
            return False
        # 데이터에 지역/직함/회사로 실재하는 값이면 사람 이름이 아니다.
        # 호칭 분기에도 이 검사가 필요하다: '군'이 호칭 목록에 있어서 '음성군·평창군·울주군'이
        # "음성"+호칭"군"으로 잡혔고, 명단에 없는 이름이라 기권해 버렸다
        # (실측: "충청북도 음성군에 있는 프로덕트매니저 찾아줘" 가 정답이 있는데도 기권).
        if (token in self.address_terms or token in self.title_terms
                or token in self.titles or token in self.companies):
            return False
        if 3 <= len(token) <= 5 and token.endswith(NAME_HONORIFICS):
            return len(token) - 1 >= 2
        if len(token) == 3 and token[0] in self.surnames and token[1:] in self.given_names:
            return True
        return False

    def person_name_stem(self, token: str) -> str:
        return token[:-1] if token.endswith(NAME_HONORIFICS) else token


def should_abstain(query, keyword_scored, vector_scores, gazetteer=None) -> bool:
    """
    검색 결과를 반환할 근거가 있는지 판정한다. True면 빈 결과를 돌려준다.

    판정 규칙(점수를 쓰지 않는다):
      1) 식별자 질의(전화/이메일): 숫자·주소 문자열이 실제로 매칭됐는지만 본다.
         매칭이 전혀 없으면 그런 번호가 없는 것이므로 기권.
      2) 지역을 명시적으로 지목했는데(예: "세종특별자치시") 그 지역이 데이터에 없으면 기권.
         질의의 다른 부분("디자이너")이 아무리 많이 매칭돼도 그 조합은 존재하지 않는다.
      3) 사람 이름을 지목했는데(예: "정하은씨", 또는 검색창에 이름만 친 "정하은")
         그 이름이 데이터에 없으면 기권.
         이게 없으면 임베딩이 발음 비슷한 이름(백하은/하채원/하수경)을 끌어오고,
         LLM 이 없는 사람에 대해 답을 지어낸다(실측: "채용설명회에서 만났습니다").
         단 호칭 없는 맨 이름은 추가 안전장치를 둔다 — 아래 주석 참조.
      4) 그 외에는 기권하지 않는다 — 개념형 질의를 죽이지 않기 위한 보수적 기본값.
    """
    tokens, _, _ = analyze(query)

    if is_identifier_query(query):
        # 식별자는 '문자 그대로 매칭'이 유일한 근거다. 매칭이 없으면 존재하지 않는 번호/주소.
        return not keyword_scored

    if gazetteer is not None:
        for tok in tokens:
            if gazetteer.looks_like_region(tok) and not gazetteer.region_exists(tok):
                return True
            if gazetteer.looks_like_person_name(tok):
                stem = gazetteer.person_name_stem(tok)
                if gazetteer.name_exists(stem):
                    continue
                # 호칭이 붙었으면("정하은씨") 사람 지목이 확실하므로 바로 기권.
                if tok.endswith(NAME_HONORIFICS):
                    return True
                # 호칭 없는 맨 3자("정하은")는 성으로 시작하는 일반어("고객사", "정규직")일
                # 수 있다. 키워드가 무언가 찾았다면 그 토큰은 데이터에 실재하는 말이므로
                # 이름 오탐으로 보고 기권하지 않는다. 아무것도 못 찾았을 때만 기권한다.
                if not keyword_scored:
                    return True

    return False


# ---------------------------------------------------------------------------
# 필드 하드 필터 — 질의가 특정 필드 값을 지목했으면 그 조건을 만족하는 카드만 후보로 둔다.
#
# 왜 필요한가(실측): "판교에서 일하는 사람 몇명이지?" 에서 판교 근무자는 정확히 5명인데,
# 키워드는 그 5명을 찾았지만 RRF 융합 과정에서 시맨틱이 끌어온 무관한 사람(안정우, 일산)이
# 끼어들고 정작 판교인 고예린이 밀려났다. 지역·이름이 '점수 가산 요소'로만 쓰여서 그렇다.
# 조건을 필터로 쓰면 그 조합에 해당하는 사람만 남는다.
#
# 위험(그래서 좁게 적용한다): 필터가 틀리면 정답까지 잘려 결과가 0개가 된다.
# 그래서 '가제티어에 실제로 존재하는 값을 지목했을 때만' 필터를 건다. 존재하지 않는 값이면
# 필터가 아니라 기권(should_abstain)이 처리한다. 개념형 질의는 특정 값을 지목하지 않으므로
# 필터가 걸리지 않는다.
# ---------------------------------------------------------------------------

# 지역을 짧게 부르는 관용 표현("판교", "강남") — 행정구역 접미사가 없어 별도로 인식해야 한다.
# 데이터의 address 에서 실제로 등장하는 지명 조각만 쓰므로 임의 확장이 아니다.


def extract_field_filters(query, gazetteer, ranked_ids=None, cards_by_id=None):
    """
    질의에서 '실제 존재하는 필드 값'을 뽑는다.
    반환: {"location": [...], "name": [...], "title": [...]}
    값이 없으면 해당 키가 없다(필터 미적용).

    직함 조건을 지역보다 먼저 세운다. 예전에는 직함을 필터로 안 쓰고, 직함/주소가
    겹치는 단어를 지역 어휘에서 깎아내는 정적 규칙으로만 충돌을 막았다. 그러면
    "상무 찾아줘"에 아무 필터도 안 걸려서 후보가 5000명 그대로였다 —
    계단식 랭킹이 직함 상무 92명을 1~92위에 정확히 올려놓아도, 필터가 그 순위를
    안 보고 집합 조회만 하니 활용을 못 한 것이다.

    직함을 필터 조건으로 승격하면 그 정보가 실제로 쓰인다(실측, 204질의):
      P@5 0.682 -> 0.773, MRR 0.928 -> 0.955,
      '지역+직함' P@5 0.395 -> 0.815 / FullP 0.057 -> 0.777.
      개념형(easy/hard)과 기권 정확도는 변화 없음 — 개념형 질의는 데이터의 직함
      단어를 그대로 쓰지 않으므로 이 필터가 아예 발동하지 않는다.

    ranked_ids/cards_by_id 는 지금은 쓰지 않지만, 필드 판정에 랭킹 근거가 더
    필요해질 때를 위해 시그니처에 남겨 둔다.
    """
    if gazetteer is None:
        return {}
    tokens, _, _ = analyze(query)
    filters = {}

    # 1) 이름: 호칭이 붙은 형태("신혜진씨") 또는 이름 자체가 토큰인 경우
    names = []
    for tok in tokens:
        stem = gazetteer.person_name_stem(tok) if gazetteer.looks_like_person_name(tok) else tok
        if len(stem) >= 2 and stem in gazetteer.names:
            names.append(stem)
    if names:
        filters["name"] = sorted(set(names))

    # 2) 직함/지역. 직함을 먼저 본다 — "상무"처럼 둘 다에 해당하는 단어는 직함이 우선이다
    #    (계단식 랭킹도 직함 정확일치를 주소 접두어보다 위에 올린다).
    locs, titles = [], []
    for tok in tokens:
        if len(tok) < 2 or tok.isdigit():
            continue
        if tok in gazetteer.title_terms:
            titles.append(tok)
            continue
        if tok in gazetteer.address_terms:
            locs.append(tok)
    if locs:
        filters["location"] = sorted(set(locs))
    if titles:
        filters["title"] = sorted(set(titles))
    # 부서(department)는 여기서 뽑지 않는다 — 카운트 경로 전용이다.
    # 공용 필터에 넣어봤다가 뺐다(실측): ① 204질의 중 발동 0건이라 회귀 여부를 평가로
    # 검증할 수가 없었고(= 안전한 게 아니라 미검증), ② 정작 목표인 "AI 개발자 몇
    # 명이야?"는 못 고쳤다. 데이터 부서명이 "AI개발팀"(붙여쓰기)이라 어휘가 'ai개발팀'
    # 한 덩어리인데 질의는 ['ai','개발자']로 쪼개져 정확 일치가 안 되기 때문이다.
    # 카운트 경로(count_by_known_condition)에서는 부분 문자열로 맞춰서 이 문제를 푼다.
    return filters


def apply_field_filters(candidate_ids, cards_by_id, filters):
    """
    이름 조건은 필터 내에서 OR(둘 중 하나와 일치), 지역 조건도 필터 내에서 OR(언급된
    지역 중 하나라도 포함)로 적용한다. 필터가 없으면 원본 그대로.

    지역을 AND로 했었으나 실측으로 버그를 발견했다: "판교랑 강남 중에 사람 더 많은
    곳이 어디야?" 같은 비교 질문은 extract_field_filters가 두 지역을 모두 뽑아서
    {"location": ["강남", "판교"]}가 되는데, AND면 "주소에 강남과 판교가 동시에
    있어야 함"이 되어 그런 사람은 존재할 수 없으므로 무조건 0명 → 기권으로 빠졌다.
    OR로 바꾸면 "언급된 지역 중 하나에 해당하는 사람"이 되어 비교 질문에 필요한
    후보군이 정상적으로 모인다. 단일 지역 질의("판교에 있는 디자이너")는 항목이
    하나뿐이라 AND/OR 결과가 같아서 회귀가 없다.
    """
    if not filters:
        return candidate_ids
    # 직함이 유일한 조건이면 '지우지' 말고 '정렬'한다.
    # 직함 정확 일치자를 앞으로 안정 정렬하고, 나머지(유사 직함)는 뒤에 그대로 남긴다.
    #
    # 왜 필터(삭제)가 아닌가: 필터는 시맨틱이 찾아낸 유사 직함을 후보에서 없애 버린다
    # ('고문변호사'는 "변호사" 질의에서 시맨틱 1위인데 삭제됐다). 정확 일치자가 적은
    # 직함에서는 그 자리를 채울 후보가 사라진다.
    #
    # 왜 그냥 두면(=미적용) 안 되는가: RRF 융합에서 시맨틱 1위가 키워드 1위를 뒤집어
    # 유사 직함이 정확 일치자보다 위로 올라온다. 앱의 FTS4 티어드 기준 실측(단독 직함
    # 질의 92개)에서 '1위가 정확 일치'인 질의가 92/92 -> 86/92 로 떨어졌다
    # ("변호사 있나?" 1위가 '고문변호사', "주임 있나?" 1위가 '책임').
    # 시맨틱은 같은 직군 안에서 순서를 못 가린다 — 변호사 계열이 전부 0.38~0.40 에
    # 몰려 있어 1·2위 차이가 0.002 수준의 노이즈다. 그 순서를 그대로 믿으면 안 된다.
    #
    # 정렬 방식은 필터의 정확도(엄격 460, 관련 460, 1위 92/92)를 그대로 내면서
    # 유사 직함을 후보에 보존한다 — 두 방식의 장점을 모두 가진다.
    #
    # 주의: 직함 조건을 '추출'하는 것 자체는 유지해야 한다. extract_field_filters 가
    # "상무"를 직함으로 선점해야 지역 조건으로 새지 않는다 — 지역으로 새면 광주
    # '상무대로' 사람만 남고 진짜 상무 92명이 전멸한다.
    # 직함이 유일한 조건이면 '지우지' 말고 '정렬'한다.
    #
    # 직함을 다른 조건과 함께일 때도 정렬로 바꿔 보는 실험을 했다("판교에 있는 개발자"가
    # 기권하는 게 일관성 없어서). 순위 지표는 그대로였지만(R@5 1.000, P@R 0.850)
    # **결과 집합**이 무너졌다 — 지역+직함 Full P 0.578 -> 0.017, CountExact 0.275 -> 0.000.
    # 직함으로 걸러지지 않으니 "경기도에 상무 몇 명?" 이 경기도 사람 전원을 답으로 내놓는다.
    # 순위와 집합은 다른 요구다. 집합이 답인 질문(개수·카드 목록)에는 필터가 필요하다.
    if "title" in filters and len(filters) == 1:
        terms = filters["title"]
        return sorted(
            candidate_ids,
            key=lambda cid: 0 if any(
                t in normalize((cards_by_id.get(cid) or {}).get("title") or "").split()
                for t in terms
            ) else 1,
        )
    # 조건을 다 만족하는 사람이 없으면 빈 결과를 그대로 돌려준다 = 기권한다.
    #
    # 예전에는 직함 조건만 떼고 다시 찾는 '완화'가 있었다. "판교에 디자인 디렉터는
    # 있는데 단어가 정확히 '디자이너'가 아니라 0건이 되는 걸 구제한다"는 취지였다.
    # 실측해 보니 완화는 eval 203질의에서 **한 번도 발동하지 않았다** — 질의가 데이터에
    # 실제로 있는 조합으로 만들어지기 때문이다. 즉 어떤 지표도 떠받치지 않았다.
    # 반대로 사용자가 없는 조합을 물을 때만 발동해서 거짓말을 만들었다:
    #   "판교에 있는 디자이너 알려줘" -> 판교에 디자인 계열 0명인데 직함을 떼고
    #   판교 9명을 넘겨서, LLM 이 그중 주임 한 명을 디자이너인 양 답했다.
    # 없는 조합에는 없다고 답하는 게 맞다. 기권 판단과 같은 원리다.
    return _match_filters(candidate_ids, cards_by_id, filters)


def _match_filters(candidate_ids, cards_by_id, filters):
    kept = []
    for cid in candidate_ids:
        card = cards_by_id.get(cid)
        if not card:
            continue
        ok = True
        if "name" in filters:
            ok = ok and any(n == normalize(card.get("name") or "") for n in filters["name"])
        if "location" in filters:
            haystack = normalize((card.get("location") or "") + " " + (card.get("address") or ""))
            ok = ok and any(term in haystack for term in filters["location"])
        if "title" in filters:
            # 직함은 단어 단위로 맞춘다 — 부분 문자열이면 "대표이사"가 "이사"에 걸린다.
            #
            # 알려진 한계(고치려다 되돌림): 데이터에 띄어쓰기 없는 합성 직함이 섞여 있어서
            # ("고문변호사", "시니어매니저"), "변호사 있나?"에 '고문변호사'가 안 걸려
            # top-5에서 빠진다("시니어 변호사"는 띄어쓰기가 있어 걸리는데 — 표기 의존).
            # 두 가지 완화를 실측했는데 둘 다 순정보다 나빴다:
            #   부분 문자열       P@5 0.773 -> 0.761, 지역+직함 FullP 0.777 -> 0.685
            #   접미사(3글자 이상) P@5 0.773 -> 0.769, 지역+직함 FullP 0.777 -> 0.739
            # 그래서 단어 단위를 유지한다. 이 한계는 데이터 표기를 정규화하는 쪽이
            # 맞는 해법이지 매칭을 느슨하게 하는 쪽이 아니다.
            title_words = normalize(card.get("title") or "").split()
            ok = ok and any(term in title_words for term in filters["title"])
        if ok:
            kept.append(cid)
    return kept


def is_identifier_query(query: str) -> bool:
    """
    전화번호/이메일 같은 '식별자 조회' 질의인지 판정한다.

    근거(측정값): 전화번호 질의에서 시맨틱은 R@5=0.000(숫자를 의미로 이해할 수 없음)인데,
    RRF로 대등하게 섞으면 좋은 키워드 결과를 밀어내 하이브리드가 오히려 0.367 -> 0.033으로
    폭락했다. 이런 질의는 시맨틱 축을 융합에서 빼는 게 명확한 개선이다.
    """
    q = (query or "").strip()
    digits = "".join(ch for ch in q if ch.isdigit())
    # 4자리 이상: "번호 뒷자리 4312인 분" 같은 실제 사용 패턴을 포함해야 한다.
    # (6자리 기준이었을 때 4자리 뒷자리 질의가 시맨틱과 섞여 정확도가 떨어졌다)
    if len(digits) >= 4:
        return True
    if "@" in q:  # 이메일
        return True
    return False


def rrf_fuse(keyword_ids, vector_scores, cards_by_id, semantic_weight=1.0, keyword_weight=1.0):
    """
    가중 RRF. semantic_weight=0 이면 키워드 전용으로 동작한다(식별자 질의 라우팅용).
    가중치를 분리해 둔 이유: 질의 유형에 따라 두 축의 신뢰도가 크게 달라서, 하나의
    고정 융합 규칙으로는 한쪽이 다른 쪽을 망치는 경우가 실제로 측정됐다.
    """
    kw_rank = {cid: i + 1 for i, cid in enumerate(keyword_ids[:FUSION_POOL])}
    if semantic_weight > 0.0:
        vec_sorted = sorted(vector_scores.items(), key=lambda x: -x[1])[:FUSION_POOL]
    else:
        vec_sorted = []
    vec_rank = {cid: i + 1 for i, (cid, _) in enumerate(vec_sorted)}
    candidates = list(dict.fromkeys(list(kw_rank) + [cid for cid, _ in vec_sorted]))
    def rrf(rank):
        return 1.0 / (RRF_K + rank) if rank else 0.0
    rows = [
        (
            cid,
            keyword_weight * rrf(kw_rank.get(cid)) + semantic_weight * rrf(vec_rank.get(cid)),
            vector_scores.get(cid, 0.0) if semantic_weight > 0.0 else 0.0,
            cards_by_id[cid]["name"],
        )
        for cid in candidates
    ]
    rows.sort(key=lambda x: (-x[1], -x[2], x[3]))
    return [cid for cid, _, _, _ in rows]


def hybrid_search(query, keyword_ids, vector_scores, cards_by_id):
    """질의 유형에 따라 융합 방식을 라우팅한다(식별자 질의는 시맨틱 제외)."""
    if is_identifier_query(query):
        return rrf_fuse(keyword_ids, vector_scores, cards_by_id, semantic_weight=0.0)
    return rrf_fuse(keyword_ids, vector_scores, cards_by_id)


# 지역 어휘/질의로 쓸 값인지 본다. 앱의 CardGazetteer.isValidLocation 과 같은 규칙이다.
#
# 예전에는 "A."/"Address."/"M."/"E." 같은 OCR 라벨 접두어 잔재 목록으로 걸렀다
# (옛 데이터는 location 의 42%가 그렇게 오염돼 있었다). 데이터를 정리하면서 그 오염을
# 없앴고, 목록 방식은 목록에 없는 오염값을 못 거르는 한계도 있었다. 지금은 형태로만
# 판정한다 — 빈 값이 아니고 마침표로 끝나지 않으면 지역으로 본다.
def is_valid_location(value: str) -> bool:
    v = (value or "").strip()
    return bool(v) and not v.endswith(".")


# 개념형 질의 — 문자 일치로는 풀리지 않고 의미(임베딩)로 풀어야 하는 질의.
# 기존 평가셋은 이름/회사/전화가 전부 "정답 카드에 질의 문자열이 100% 그대로 존재"해서
# 키워드에 절대적으로 유리했고, 시맨틱의 기여를 측정할 수 없었다. 그 공백을 메운다.
#
# 정답은 카드 필드에서 규칙으로 유도한다(수작업 라벨 아님 — 재현 가능하게).
# 이 데이터의 제약: industry / memo / tags 필드는 5000장 전부 비어 있어(0%) 쓸 수 없고,
# department 도 27%만 채워져 있다. 그래서 판정은 title 위주 + department 보조로 짠다.
# 난이도 표기: easy=상위어 수준, hard=동의어/우회표현/영한 혼용(문자 겹침이 거의 없음)
CONCEPT_QUERIES = [
    # --- 개발/엔지니어링 ---
    ("소프트웨어 만드는 사람", "easy", lambda c: any(k in c["title"] for k in ("Engineer", "SRE", "개발")) or "개발팀" in c["department"]),
    ("코드 짜는 직군 찾아줘", "hard", lambda c: any(k in c["title"] for k in ("Engineer", "SRE")) or any(k in c["department"] for k in ("개발", "백엔드", "프론트엔드", "플랫폼"))),
    ("서버 인프라 담당자", "hard", lambda c: "SRE" in c["title"] or "Platform" in c["title"] or any(k in c["department"] for k in ("인프라", "DevOps", "백엔드"))),
    ("인공지능 연구하는 사람", "hard", lambda c: "AI" in c["department"] or "Data Scientist" in c["title"] or "데이터" in c["department"]),
    ("데이터 분석하는 사람", "easy", lambda c: "Data Scientist" in c["title"] or "데이터" in c["department"]),
    # --- 디자인 ---
    ("그림 그리고 화면 만드는 직군", "hard", lambda c: "디자이너" in c["title"] or "Designer" in c["title"] or any(k in c["department"] for k in ("디자인", "UX"))),
    ("UI 만드는 사람 찾아줘", "hard", lambda c: "디자이너" in c["title"] or "Designer" in c["title"] or any(k in c["department"] for k in ("디자인", "UX", "프론트엔드"))),
    ("디자인 총괄", "easy", lambda c: any(k in c["title"] for k in ("Head of Design", "디자인 디렉터", "리드 디자이너", "시니어 디자이너"))),
    # --- 법률 ---
    ("법률 자문 해줄 사람", "hard", lambda c: "변호사" in c["title"] or "법무" in c["department"]),
    ("소송 맡길 사람", "hard", lambda c: "변호사" in c["title"] or "법무" in c["department"]),
    ("법무 담당", "easy", lambda c: "변호사" in c["title"] or "법무" in c["department"]),
    # --- 재무/회계 ---
    ("돈 관리하는 사람", "hard", lambda c: "CFO" in c["title"] or any(k in c["department"] for k in ("재무", "회계"))),
    ("회계 처리 담당자", "easy", lambda c: any(k in c["department"] for k in ("재무", "회계")) or "CFO" in c["title"]),
    ("예산 책임자", "hard", lambda c: "CFO" in c["title"] or any(k in c["department"] for k in ("재무", "회계", "경영기획"))),
    # --- 의료 ---
    ("환자 보는 일 하는 사람", "hard", lambda c: any(k in c["title"] for k in ("전문의", "진료과장", "원장"))),
    ("병원에서 진료하는 사람", "hard", lambda c: any(k in c["title"] for k in ("전문의", "진료과장"))),
    # --- 경영/임원 ---
    ("회사 최고 책임자", "hard", lambda c: any(k in c["title"] for k in ("CEO", "대표이사", "회장", "사장"))),
    ("임원급 찾아줘", "easy", lambda c: any(k in c["title"] for k in ("이사", "상무", "전무", "부사장", "사장", "회장", "본부장"))),
    ("C레벨 임원", "hard", lambda c: any(c["title"].startswith(k) for k in ("CEO", "CFO", "CTO", "COO", "CMO", "CPO", "CDO"))),
    ("기술 총괄 책임자", "hard", lambda c: "CTO" in c["title"] or "기술개발팀" in c["department"]),
    # --- 마케팅/영업 ---
    ("물건 파는 일 하는 사람", "hard", lambda c: any(k in c["department"] for k in ("영업", "사업개발")) or "CMO" in c["title"]),
    ("광고 홍보 담당", "easy", lambda c: any(k in c["department"] for k in ("마케팅", "홍보", "브랜드")) or "CMO" in c["title"]),
    ("브랜드 전략 담당자", "easy", lambda c: any(k in c["department"] for k in ("브랜드", "마케팅", "전략기획"))),
    ("해외 거래 담당", "hard", lambda c: any(k in c["department"] for k in ("해외영업", "글로벌사업"))),
    # --- 제품/기획 ---
    ("제품 기획하는 사람", "easy", lambda c: any(k in c["title"] for k in ("Product Manager", "프로덕트매니저", "Senior PM", "Head of Product", "CPO")) or any(k in c["department"] for k in ("프로덕트", "서비스기획"))),
    ("PM 찾아줘", "easy", lambda c: any(k in c["title"] for k in ("PM", "Product Manager", "프로덕트매니저", "프로젝트매니저"))),
    ("프로젝트 관리 담당", "hard", lambda c: any(k in c["title"] for k in ("PM", "Product Manager", "프로덕트매니저", "프로젝트매니저", "매니저"))),
    # --- 연구 ---
    ("연구하는 사람 찾아줘", "easy", lambda c: "연구원" in c["title"] or any(k in c["department"] for k in ("R&D", "연구", "리서치"))),
    ("R&D 담당자", "easy", lambda c: "연구원" in c["title"] or any(k in c["department"] for k in ("R&D", "연구", "리서치"))),
    # --- 지원 부서 ---
    ("사람 뽑는 일 하는 사람", "hard", lambda c: any(k in c["department"] for k in ("인사", "인재개발"))),
    ("품질 검사하는 사람", "easy", lambda c: any(k in c["department"] for k in ("품질", "QA", "테스트"))),
    ("보안 담당자", "easy", lambda c: "정보보안팀" in c["department"]),
    ("고객 응대하는 사람", "hard", lambda c: any(k in c["department"] for k in ("CS", "고객관리", "운영"))),
    ("부동산 중개하는 사람", "easy", lambda c: "중개사" in c["title"]),
    ("공무원 직급", "hard", lambda c: any(k in c["title"] for k in ("사무관", "서기관", "주무관"))),
]

# 기권(no-result) 질의 — 데이터에 존재하지 않아 "없다"고 답해야 하는 질의.
#
# 주의: 지역 관련 기권 질의는 '그 지역이 정말 데이터에 없는지' 반드시 확인해야 한다.
# 초기에 "제주특별자치도에 있는 변호사", "세종특별자치시 디자이너"를 넣었는데, 확인해보니
# 제주에 변호사 5명, 세종에 디자이너 4명이 실제로 있었다. 정답 있는 질의를 정답 0개로
# 라벨링한 셈이어서 기권 지표가 부풀려졌다. 그래서 아래 지역들은 build 시점에
# 데이터에 없는지 자동 검증하고(assert), 실제로 존재하면 평가셋에서 자동 제외한다.
NO_RESULT_QUERIES = [
    # 존재하지 않는 직업군
    "우주비행사 찾아줘",
    "남극기지 근무자",
    "왕실전속조련사",
    "심해잠수정조종사",
    "등대지기 연락처",
    "서커스 단장",
    "포경선 선장",
    "화산 탐사대원",
    "고래 조련사",
    "열기구 조종사",
    # 형식은 그럴듯하나 존재하지 않는 식별자 — 검색이 "비슷한 것"으로 때우지 않는지 본다
    "010-0000-0000",
    "02-0000-0000",
    "nonexistent@nowhere.invalid",
    "zzzz@zzzz.zzz",
    # 존재하지 않는 회사/이름
    "주식회사없는회사이름테스트",
    "존재하지않는사람이름99",
]

# 지역 기반 기권 질의 후보 — (지역명, 질의). 지역이 데이터에 실제로 없을 때만 채택된다.
NO_RESULT_REGION_CANDIDATES = [
    ("울릉도", "울릉도 근무자"),
    ("백령도", "백령도에 있는 사람"),
    ("독도", "독도에 있는 사람 찾아줘"),
    ("세종특별자치시", "세종특별자치시 디자이너"),
    ("제주특별자치도", "제주특별자치도에 있는 변호사 찾아줘"),
]


def build_eval_queries(cards, rng, include_concept=True, include_no_result=True):
    """
    합성 데이터 필드에서 정답이 확정되는 질의를 자동 생성한다.

    유형 구성(왜 이렇게 나누는가):
      - 조회형(이름/회사/전화): 정답 카드에 질의 문자열이 그대로 존재 → 키워드가 유리한 게 정상
      - 지역+직함(문장): 조사·명령어 처리 검증. 오염 location 은 제외
      - 개념형: 질의 문자열이 카드에 없음 → 시맨틱만 풀 수 있음(하이브리드 가치 측정용)
      - no-result: 정답 0개 → 기권 능력 측정용(별도 집계, 랭킹 지표에서는 제외)
    """
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
        if is_valid_location(c["location"]) and c["title"] and has_hangul(c["title"]):
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

    if include_concept:
        for q, difficulty, predicate in CONCEPT_QUERIES:
            relevant = [c["id"] for c in cards if predicate(c)]
            # 정답이 아예 없거나 데이터의 절반을 넘으면 변별력이 없어 제외한다
            if 0 < len(relevant) <= len(cards) // 2:
                queries.append((f"개념형({difficulty})", q, relevant))
    if include_no_result:
        for q in NO_RESULT_QUERIES:
            queries.append(("기권(정답없음)", q, []))
        # 지역 기반 기권 질의: 그 지역이 데이터에 실제로 없을 때만 채택한다.
        # (추측으로 넣었다가 정답 있는 질의를 '정답 0개'로 라벨링하는 사고를 막는다)
        for region, q in NO_RESULT_REGION_CANDIDATES:
            exists = any(region in (c.get("address") or "") or region in (c.get("location") or "") for c in cards)
            if not exists:
                queries.append(("기권(정답없음)", q, []))
    return queries


def audit_queries(cards, queries):
    """
    평가셋 자체의 건전성 점검. 지표를 신뢰하기 전에 이걸 먼저 통과해야 한다.
      - 정답 0개인 질의가 랭킹 유형에 섞여 있지 않은가
      - 개념형이 실제로 '문자 일치로 안 풀리는' 질의인가(누출 검사)
      - 유형별 표본 수가 판단 가능한 수준인가
    """
    by_id = {c["id"]: c for c in cards}
    print("\n[평가셋 점검]")
    counts = Counter(t for t, _, _ in queries)
    for t in sorted(counts):
        print(f"  {t:<18} n={counts[t]}")
    small = [t for t, n in counts.items() if n < 10 and not t.startswith("기권")]
    if small:
        print(f"  ! 표본 10개 미만 유형(해석 주의): {small}")

    # 개념형 누출 검사: 질의 토큰이 정답 카드 텍스트에 그대로 있으면 '개념형'이 아니다
    leak_total = leak_hit = 0
    for t, q, rel in queries:
        if not t.startswith("개념형") or not rel:
            continue
        toks = [x for x in normalize(q).split() if len(x) >= 2 and x not in STOPWORDS]
        if not toks:
            continue
        for cid in rel[:50]:  # 표본만 확인(전량은 느림)
            text = card_original_text(by_id[cid])
            leak_total += 1
            if all(tok in text for tok in toks):
                leak_hit += 1
    if leak_total:
        rate = leak_hit / leak_total
        print(f"  개념형 문자 누출률 = {leak_hit}/{leak_total} = {rate:.1%} (낮아야 정상 — 높으면 키워드로도 풀려버림)")

    # 기권 질의 라벨 검증: 질의의 핵심 토큰이 카드에 실제로 있으면 '정답 0개' 라벨이 의심스럽다.
    # (실제로 "제주특별자치도 변호사"를 기권으로 잘못 넣었다가 변호사 5명이 있는 것을 발견했다)
    suspicious = []
    for t, q, rel in queries:
        if not t.startswith("기권") or rel:
            continue
        toks = [x for x in normalize(q).split() if len(x) >= 3 and x not in STOPWORDS]
        for tok in toks:
            hits = sum(1 for c in cards if tok in card_original_text(c))
            if hits > 0:
                suspicious.append((q, tok, hits))
                break
    if suspicious:
        print(f"  ! 기권 라벨 의심 {len(suspicious)}건 (질의 토큰이 카드에 실제 존재):")
        for q, tok, hits in suspicious[:6]:
            print(f"      '{q}' -> 토큰 '{tok}' 이 {hits}장에 존재")
    else:
        print("  기권 라벨 검증 통과 (질의 토큰이 카드에 존재하지 않음)")


def dcg(gains):
    """할인 누적 이득. 순위가 뒤일수록 log2 로 감쇠시킨다."""
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ranked, rel, k):
    """
    nDCG@k — 순위 품질의 사실상 표준 지표(TREC 등에서 관례적으로 인용).
    Recall과 달리 '정답을 몇 등에 놓았는지'를 로그 할인으로 반영하고,
    이상적 순위(IDCG)로 나눠 0~1 로 정규화한다.
    관련도 등급이 없는 이진 라벨이라 gain 은 1/0 을 쓴다.
    """
    gains = [1.0 if cid in rel else 0.0 for cid in ranked[:k]]
    ideal = [1.0] * min(len(rel), k)
    idcg = dcg(ideal)
    return dcg(gains) / idcg if idcg > 0 else 0.0


def evaluate(name, rankings, queries):
    """
    지표 구성(왜 이 조합인가):
      - Recall@k  : 정답을 놓치지 않는가. 분모는 min(정답수, k) — 정답이 k개보다 많은
                    질의에서 상한이 1 미만으로 깎여 유형 간 비교가 불공정해지는 것을 막는다.
      - Precision@k: 쓸데없는 걸 섞지 않는가. recall 만 보면 "정답 포함하되 노이즈 대량
                    반환"이 감지되지 않아 반드시 함께 본다.
      - P@R (R-precision): 정답이 R개면 상위 R개만 보고 잰다. **정답 수가 유형마다 다를 때는
                    P@5 로 유형을 비교하면 안 된다** — 정답이 1개인 질의는 P@5 가 아무리
                    잘해도 0.2 가 상한이라 '정밀도가 낮다'고 오독하게 된다.
                    실제로 '회사명' 유형 P@5=0.210 을 검색 결함으로 잘못 진단한 적이 있는데,
                    40개 중 38개가 정답 1명이라 이론 상한(0.210)에 이미 도달한 상태였다
                    (R@5=1.000 — 항상 찾아냄). P@R 은 그 상한 왜곡이 없다.
      - Full Recall/Precision: 검색기가 실제로 반환한 전체 결과 기준.
                    UI의 5개 표시 제한과 분리해 "정답을 전부 찾았는가"를 측정한다.
      - MRR       : 첫 정답을 얼마나 위에 올리는가.
      - nDCG@k    : 순위 품질 표준 지표. 여러 정답의 배치까지 반영.
    """
    agg = defaultdict(float)
    per_type = defaultdict(lambda: defaultdict(float))
    per_type_n = defaultdict(int)
    for (qtype, _, relevant), ranked in zip(queries, rankings):
        rel = set(relevant)
        top = ranked[:TOP_K]
        m = {
            "R@1": len(rel & set(top[:1])) / min(len(rel), 1),
            "R@5": len(rel & set(top[:5])) / min(len(rel), 5),
            "R@20": len(rel & set(top)) / min(len(rel), TOP_K),
            # Precision 은 분모가 '반환한 개수'다. 반환 결과가 k개보다 적으면
            # 그 실제 개수로 나눠야 "적게 반환한 것"이 부당하게 벌점받지 않는다.
            "P@1": len(rel & set(top[:1])) / max(len(top[:1]), 1),
            "P@5": len(rel & set(top[:5])) / max(len(top[:5]), 1),
            # R-precision: 정답 수(R)만큼만 잘라서 잰다. 정답이 적은 유형에서 P@5 가
            # 구조적으로 눌리는 문제가 없어 유형 간 비교에 쓸 수 있다.
            "P@R": (len(rel & set(ranked[:len(rel)])) / len(rel)) if rel else 0.0,
            "nDCG@5": ndcg_at(top, rel, 5),
            "nDCG@20": ndcg_at(top, rel, TOP_K),
        }
        full_hits = len(rel & set(ranked))
        full_recall = full_hits / len(rel)
        full_precision = full_hits / len(ranked) if ranked else 0.0
        m["FullRecall"] = full_recall
        m["FullPrecision"] = full_precision
        m["FullF1"] = (
            2.0 * full_recall * full_precision / (full_recall + full_precision)
            if full_recall + full_precision > 0.0 else 0.0
        )
        m["CountExact"] = 1.0 if len(ranked) == len(rel) else 0.0
        m["CountAbsError"] = abs(len(ranked) - len(rel))
        rr = 0.0
        for i, cid in enumerate(top):
            if cid in rel:
                rr = 1.0 / (i + 1)
                break
        m["MRR"] = rr
        for key, val in m.items():
            agg[key] += val
            per_type[qtype][key] += val
        per_type_n[qtype] += 1

    n = len(queries)
    print(f"\n[{name}]  (질의 {n}개)")
    print(f"  Recall@1={agg['R@1']/n:.3f}  Recall@5={agg['R@5']/n:.3f}  Recall@20={agg['R@20']/n:.3f}")
    print(f"  Precision@1={agg['P@1']/n:.3f}  Precision@5={agg['P@5']/n:.3f}  P@R={agg['P@R']/n:.3f}")
    print(f"  nDCG@5={agg['nDCG@5']/n:.3f}  nDCG@20={agg['nDCG@20']/n:.3f}  MRR={agg['MRR']/n:.3f}")
    print(
        f"  Full Recall={agg['FullRecall']/n:.3f}  Full Precision={agg['FullPrecision']/n:.3f}"
        f"  Full F1={agg['FullF1']/n:.3f}"
    )
    print(
        f"  Count exact={agg['CountExact']/n:.3f}"
        f"  Count MAE={agg['CountAbsError']/n:.2f}명"
    )
    for qtype in sorted(per_type):
        cnt = per_type_n[qtype]
        t = per_type[qtype]
        # 유형별 P@5 상한 — 정답이 5개 미만인 질의가 많으면 P@5 는 구조적으로 낮게 나온다.
        # 그 유형을 P@5 로 평가하면 안 된다는 신호이므로 같이 출력한다(P@R 을 볼 것).
        cap = sum(min(len(relv), 5) / 5.0
                  for (qt, _, relv) in queries if qt == qtype) / cnt
        print(
            f"    - {qtype:<16} (n={cnt:2d}): R@5={t['R@5']/cnt:.3f}  P@5={t['P@5']/cnt:.3f}"
            f"(상한{cap:.2f})  P@R={t['P@R']/cnt:.3f}"
            f"  FullR={t['FullRecall']/cnt:.3f}  FullP={t['FullPrecision']/cnt:.3f}"
            f"  CountExact={t['CountExact']/cnt:.3f}"
        )

    eligible = [
        (qtype, set(relevant), ranked)
        for (qtype, _, relevant), ranked in zip(queries, rankings)
        if len(relevant) >= 5
    ]
    if eligible:
        all_five = sum(
            1 for _, rel, ranked in eligible
            if len(ranked) >= 5 and all(cid in rel for cid in ranked[:5])
        )
        print(
            f"  All-relevant@5={all_five}/{len(eligible)}"
            f" = {all_five/len(eligible):.3f}"
            "  (정답이 5장 이상인 질의 중 상위 5장이 모두 정답)"
        )
        eligible_by_type = defaultdict(list)
        for qtype, rel, ranked in eligible:
            eligible_by_type[qtype].append(
                len(ranked) >= 5 and all(cid in rel for cid in ranked[:5])
            )
        print(
            "    "
            + " · ".join(
                f"{qtype}={sum(values)}/{len(values)}({sum(values)/len(values):.3f})"
                for qtype, values in sorted(eligible_by_type.items())
            )
        )


def evaluate_no_result(name, rankings, queries, score_lists=None):
    """
    기권(abstention) 능력 — "해당하는 사람이 없다"를 실제로 없다고 말할 수 있는가.
    정답이 0개인 질의만 대상으로, 상위 k에 무엇이든 반환하면 오답으로 본다.
    현재 검색은 점수 컷오프가 없어 항상 무언가를 반환하므로 이 값은 0에 가깝게 나온다 —
    그게 바로 "무관한 후보도 그대로 LLM 컨텍스트로 들어간다"는 문제의 정량 증거다.
    """
    if not queries:
        return
    correct = 0
    for (_, _, relevant), ranked in zip(queries, rankings):
        assert not relevant, "no-result 평가에는 정답이 비어있는 질의만 넣어야 한다"
        if not ranked:
            correct += 1
    print(f"\n[{name}] 기권 정확도(no-result accuracy) = {correct}/{len(queries)} = {correct/len(queries):.3f}")
    print("  * 0.000 이면 '없는 것을 없다고 말하지 못한다'는 뜻 — 점수 컷오프/필드 필터 미구현 상태를 반영")


def main():
    rng = random.Random(42)
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    cards_by_id = {c["id"]: c for c in cards}
    prepared = []
    for c in cards:
        text = card_original_text(c)
        prepared.append((text, set(text.split())))

    import numpy as np

    ids = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    raw = VECTORS_PATH.read_bytes()
    # 순수 파이썬 루프로 5000장 x 160질의 코사인을 돌리면 수 분이 걸려서 numpy 로 벡터화한다.
    doc_mat = np.frombuffer(raw, dtype="<f4").reshape(len(ids), DIM)

    gazetteer = Gazetteer(cards)
    print(f"가제티어: 지역 {len(gazetteer.locations)}종, 직함 {len(gazetteer.titles)}종, 회사 {len(gazetteer.companies)}종")

    queries = build_eval_queries(cards, rng)
    print(f"질의 {len(queries)}개 생성 (정답은 합성 데이터 필드에서 자동 유도)")
    audit_queries(cards, queries)

    print("쿼리 임베딩 계산 중 (온디바이스와 동일 모델/프롬프트)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(MODEL_PATH))
    q_vecs = model.encode_query([q for _, q, _ in queries], batch_size=32, show_progress_bar=True)

    kw_rankings, sem_rankings, hy_rankings, hy2_rankings = [], [], [], []
    for (qtype, q, rel), qv in zip(queries, q_vecs):
        kw_scored = keyword_ranking_scored(cards, prepared, q)
        kw = [cid for cid, _ in kw_scored]
        sim_arr = doc_mat @ np.asarray(qv, dtype="<f4")
        order = np.argsort(-sim_arr)
        sims = {ids[i]: float(sim_arr[i]) for i in range(len(ids))}
        # 각 검색 축의 실제 후보 풀(40개)을 보존한다. UI 표시 개수와
        # 평가 대상을 분리해야 전체 Recall/Precision을 계산할 수 있다.
        sem = [ids[i] for i in order[:FUSION_POOL]]
        hy = rrf_fuse(kw, sims, cards_by_id)                      # 기존(대등 융합)
        hy2 = hybrid_search(q, kw, sims, cards_by_id)              # 개선(식별자 질의 라우팅)
        # 개선(필드 하드 필터): 질의가 실제 존재하는 지역/이름을 지목했으면 그 조건을 만족하는
        # 카드만 남긴다. 지목한 값이 데이터에 없으면 필터가 아니라 아래 기권이 처리한다.
        hy2 = apply_field_filters(hy2, cards_by_id, extract_field_filters(q, gazetteer, kw, cards_by_id))
        if should_abstain(q, kw_scored, sims, gazetteer):           # 개선(기권 게이트)
            hy2 = []
        kw_rankings.append(kw[:FUSION_POOL])
        sem_rankings.append(sem)
        hy_rankings.append(hy)
        hy2_rankings.append(hy2)

    # 랭킹 지표는 정답이 있는 질의로만 계산한다(정답 0개는 recall/MRR 정의가 성립하지 않음).
    # no-result 질의는 별도로 '기권 능력'으로 집계한다.
    rank_idx = [i for i, (_, _, rel) in enumerate(queries) if rel]
    nores_idx = [i for i, (_, _, rel) in enumerate(queries) if not rel]

    def pick(seq, idx):
        return [seq[i] for i in idx]

    rank_queries = pick(queries, rank_idx)
    print(f"\n랭킹 평가 대상 {len(rank_queries)}개 / 기권 평가 대상 {len(nores_idx)}개")
    systems = (
        ("키워드 전용", kw_rankings),
        ("시맨틱 전용", sem_rankings),
        ("하이브리드 (RRF, 기존)", hy_rankings),
        ("하이브리드 (라우팅+기권, 개선)", hy2_rankings),
    )
    print(
        "\n[지표 읽는 법] 유형마다 중요한 지표가 다르다 — 전체 평균은 유형 구성비에 좌우되니\n"
        "  유형별 수치를 봐야 한다.\n"
        "  - 이름/전화(정답 보통 1개): MRR·R@1 이 핵심. 그 하나를 1등에 놓는가\n"
        "  - 회사/지역+직함(정답 다수): R@5·nDCG@5. 여러 명을 골고루 담는가\n"
        "  - 개념형(LLM에 넘길 후보): R@5 + P@5. 의미로 맞는 후보를 노이즈 없이 모으는가\n"
        "  - 기권: 랭킹 지표는 정의되지 않음. 아래 기권 정확도만 본다"
    )
    for label, rankings in systems:
        evaluate(label, pick(rankings, rank_idx), rank_queries)

    if nores_idx:
        nores_queries = pick(queries, nores_idx)
        print("\n" + "=" * 70)
        for label, rankings in systems:
            evaluate_no_result(label, pick(rankings, nores_idx), nores_queries)


if __name__ == "__main__":
    main()
