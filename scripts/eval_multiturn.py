"""멀티턴 평가 — 라우팅 / JGA(슬롯) / 턴별 Hit@5·R@5·MRR / 체크리스트 / Relevancy·Faithfulness / pass^k.

왜 이 지표들인가
----------------
이 시스템은 답변의 상당수가 **LLM을 거치지 않는다**(카운트·기권·문맥참조·자기참조).
23문항 라이브에서 8개(35%)가 결정적 경로였다. 그런 턴은 답변이 고정 문자열이라
답변 텍스트를 채점해 봐야 라우팅만 맞으면 자동 통과다 — 정보가 없다.
반대로 실제로 겪은 실패는 전부 '어느 경로로 갔나'였다
(판교 디자이너가 완화 경로로 새서 오답, 개념형이 카운트 형식으로 새서 가짜 총계).

그래서 **주 지표는 라우팅 + JGA + 턴별 Hit@5**(1~3층)이고, 답변 텍스트 채점은
**LLM이 실제로 생성한 턴에만** 매기는 보조 지표(4~5층)다. 전체를 뭉쳐 하나의
통과율로 내면 고정 문자열 턴이 숫자를 채워서 어려운 턴의 성능을 가린다.

두 가지 모드
------------
    python scripts/eval_multiturn.py
        1~3층. 생성을 건너뛰므로(dry-run) 180턴이 ~30초. 매 변경마다 돌리는 회귀망.

    python scripts/eval_multiturn.py --generate --sample 25
        4~5층. 실제로 답변을 만들어 체크리스트로 채점한다. 턴당 ~10초라 표본을 쓴다.
        표본은 **유형별 층화 추출**이다 — 균등 무작위로 뽑으면 개수가 적은 유형이
        통째로 빠져서, 지표는 1.000 인데 정작 최근 고친 것들이 한 번도 안 돌아간다
        (실측: --sample 18 균등 추출에서 20종 중 12종 누락). 25 이상이면 전 유형이 들어간다.
        --repeat 3 을 주면 pass^3(3번 다 통과해야 인정)까지 낸다 — 샘플링 흔들림 때문에
        1~2개 차이로 순위를 매기면 안 된다는 문제를 지표에 반영하는 방법이다.

지표
----
- **라우팅 정확도** — 의도한 경로로 갔는가
  (search / abstain / filtered_count / total_count / context_answer / followup / self_reference)
- **JGA (Joint Goal Accuracy)** — 그 턴의 **모든** 슬롯이 정답과 정확히 일치한 턴의 비율.
  슬롯은 focus 인물 + 필드 조건(이름/직함/지역). 대화상태추적의 표준 지표를 우리 슬롯에 적용.
- **슬롯 F1** — JGA는 하나만 틀려도 0이라 부분 점수를 같이 본다.
- **턴별 Hit@5** — 정답 카드가 상위 5개 안에 **하나라도** 있는가. 정답이 1장인 턴
  (전체의 76.4%)에서는 recall 과 같은 값이다.
- **턴별 R@5** — 상한을 1.0 으로 맞춘 형태(분모 min(정답수,5)). `eval_search.py` 와 같은 공식.
  날것의 Recall@5(분모=정답수)는 안 쓴다 — 이 시나리오 집합에서 **완벽한 검색기의 상한이
  0.924** 이고, 유형별로는 '조사 변형 카운트' 0.096 · '없는 조합->복구' 0.206 처럼 크게
  눌려서 잘해도 낮게 나온다(측정값). 상한이 왜곡된 지표로 유형을 비교하면 안 된다.
- **턴별 MRR** — 첫 정답의 역순위. 정답 수에 좌우되지 않는다.
- **체크리스트 통과율** — 답변에 필수 문자열이 있고 금지 문자열이 없는가(LLM 턴만).
- **pass^k** — 같은 시나리오를 k번 돌려 k번 다 통과한 비율.

시나리오는 `cards_eval1000.json` 에서 생성한다. 외부 대화 코퍼스를 못 쓰는 이유는
거기에 우리 카드가 없어서 "이 턴의 정답"을 정의할 수 없기 때문이다.
데이터를 다시 만들면 시나리오도 같이 갱신되므로 낡지 않는다.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent))
import card_fingerprint as _cfp
import argparse
import json
import random
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows 기본 콘솔은 cp949 라 한글/기호가 깨진다

REPO = Path(__file__).resolve().parent.parent
CARDS_PATH = REPO / "data" / "cards_eval1000.json"
ENDPOINT = "http://127.0.0.1:8100/chat"
SEED = 42

# 답변이 "못 찾았다"고 말하는 표현 — 답이 있어야 하는 턴에서는 금지어다.
REJECTIONS = ["찾지 못했", "찾을 수 없", "없습니다만", "해당하는 명함"]

# 생성이 실제로 일어나는 경로. 체크리스트는 여기에만 매긴다.
# empty_result 도 LLM 을 부른다(후보가 0장인 채로 프롬프트가 들어간다).
GENERATING_ROUTES = {"search", "followup", "empty_result"}

# 개념형 질의 — 데이터에 그 단어가 없어서 의미로 풀어야 한다. 정답은 직함 정규식으로 정의한다.
CONCEPT_QUERIES = [
    ("돈 관리하는 사람 찾아줘", r"회계|재무|CFO|세무|펀드|경리"),
    ("코드 짜는 사람 찾아줘", r"개발|engineer|developer|sre|백엔드|프론트|CTO|데이터"),
    ("소송 맡길 사람 찾아줘", r"변호사|법무|송무"),
    ("디자인하는 사람 찾아줘", r"디자이너|디자인"),
    ("환자 보는 사람 찾아줘", r"의사|간호|약사|원장|전문의"),
    ("사람 뽑는 일 하는 사람 찾아줘", r"인사|HR|채용|피플"),
]


def norm_tokens(s):
    return re.sub(r"[^0-9a-z가-힣]+", " ", (s or "").lower()).split()


def company_variants(company):
    """LLM 이 "주식회사"를 떼고 말하는 일이 잦아 핵심어도 정답으로 인정한다."""
    core = company
    for form in ("주식회사", "유한회사", "(주)", "(유)", "(재)", "(사)", "㈜"):
        core = core.replace(form, " ")
    core = core.strip()
    return [v for v in {company, core} if len(v) >= 2]


def address_variants(address):
    """주소는 괄호나 시/도를 생략하고 답하는 일이 잦아 '도로명 + 번지'만 봐도 인정한다."""
    head = address.split(" (")[0].strip()
    parts = head.split()
    out = {address, head}
    if len(parts) >= 2:
        out.add(" ".join(parts[-2:]))
    return [v for v in out if len(v) >= 4]


def turn(q, route=None, slots=None, gold=None, must=None, must_not=None, no_cards=False):
    """
    must 의 각 원소는 '대안 목록'이다 — 그중 하나만 답변에 있으면 통과.
    no_cards: 화면에 카드가 뜨면 안 되는 턴(명함과 무관한 요청). 카드를 지우는 일은
    답변을 본 뒤에 일어나므로 **생성 모드에서만** 검사한다.
    """
    return {"q": q, "route": route, "slots": slots, "gold": gold,
            "must": must or [], "must_not": must_not or [], "no_cards": no_cards}


# ---------------------------------------------------------------------------
# 발화 표현 풀 — 같은 뜻을 여러 말투로 둔다.
#
# **왜 필요한가(측정)**: 유형당 표현이 1개면 분모만 크고 덮는 범위는 좁다. 실측으로
# 386턴이 '틀' 93종뿐이었고 상위 10개 틀이 전체의 69%였다. 그 상태에서 외부 고정셋
# (Final50 v3, 50시나리오)이 우리가 못 잡던 버그 5개를 찾아냈다 — 같은 의도를 10가지로
# 말해 보니 0/10 으로 전멸한 유형이 있었다("처음에 물어본 사람" 계열).
#
# 표현만 바꾸고 **기대 route·슬롯·정답은 그대로**여야 한다. 뜻이 달라지는 변형은 넣지 않는다.
# 한 발화에 속성 명사를 두 개 넣지 않는다 — 여러 칸 요청으로 잡혀 다른 경로를 탄다.
# rng 로 고르므로 seed 가 같으면 재현된다.
ASK_COMPANY = [
    "{n}씨 회사가 어디야?", "{n}씨 어디 다녀?", "{n}씨 직장이 어디지?",
    # "{n}씨 소속이 어디야?" 는 뺐다 — '소속'은 회사로도 부서로도 읽혀 정답이 하나로 정해지지
    # 않는다(실측: 모델이 QA팀·경영기획실·R&D센터를 답했고, 그걸 틀렸다고 할 근거가 없다).
    # 모호한 항목은 모델 결함이 아니라 시험 설계 결함이다.
    "{n}씨 회사 알려줘", "{n}씨 어느 회사 다녀?",
]
ASK_DEPARTMENT_NAMED = [
    "{n}씨 부서는?", "{n}씨 어느 부서야?", "{n}씨 부서 알려줘", "{n}씨 소속 부서가 뭐야?",
]
ASK_ONLY_NAME = ["{n}씨는?", "{n}씨도?", "{n}씨는 어때?", "그럼 {n}씨는?"]

# 주어를 생략한 후속. 속성 명사로 시작해야 focus 가 앞에 붙는다(resolveSearchQuery).
ELLIPTIC = {
    "address": ["주소는?", "주소 알려줘", "주소가 어떻게 돼?", "주소는 뭐야?"],
    "title": ["직급은?", "직함이 뭐야?", "직급 알려줘", "직책은?"],
    "department": ["부서는?", "부서 알려줘", "어느 부서야?", "부서가 뭐야?"],
    "email": ["이메일은?", "이메일 알려줘", "메일 주소는?", "이메일이 뭐야?"],
    "phone": ["전화번호는?", "연락처 알려줘", "전화번호 뭐야?", "번호는?"],
}

PLURAL_FOLLOWUP = [
    "그 사람들 회사 알려줘", "그분들 회사는?", "그 사람들 어디 다녀?",
    "그 사람들 소속 알려줘",
]
RECALL_COMPANY = [
    "아까 말한 회사 뭐였지", "방금 말한 회사가 뭐였더라", "앞서 말한 회사 뭐였어",
    "아까 찾은 회사 뭐였지",
]
SEARCH_LOC_TITLE = [
    "{loc}에 있는 {t} 찾아줘", "{loc} {t} 알려줘", "{loc}에서 일하는 {t} 찾아줘",
    "{loc}에 {t} 있어?",
]


def pick(rng, pool, **kw):
    """표현 풀에서 하나 고른다. seed 가 같으면 같은 것이 나온다."""
    return rng.choice(pool).format(**kw)


# ---------------------------------------------------------------------------
# 날조 값 검사 — 답변에 **어느 카드에도 없는** 연락처가 나오는지 본다.
#
# 고정셋의 forbidden_contains 는 '그 대화에 나온 다른 사람 값'을 **수작업으로 열거**한
# 것이라, 목록에 없는 값이나 완전히 지어낸 값은 못 잡는다.
#   정답 손다은 / 금지 [같은 대화 4명의 번호] / 답변 "010-7777-8888" -> 통과해 버린다
# 이건 규칙 하나로 전 구간을 덮는다 — 작성자가 무엇을 떠올렸는지에 의존하지 않는다.
#
# 전화·이메일만 본다. 정확 문자열이라 **오탐이 0**이다: 1000장 어디에도 없는 번호가
# 답변에 있으면 모델이 지어낸 것 말고 설명이 없다. 회사·부서명은 표기 흔들림이 있어 뺐다.
# (이 앱에서 가장 위험한 거짓말이기도 하다 — 없는 번호로 전화를 걸게 된다.)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\d[\d\-\s]{8,}\d")


def build_contact_index(cards):
    """데이터에 실재하는 연락처 집합. 전화는 숫자만 남겨 표기 차이를 없앤다."""
    emails, phones = set(), set()
    for c in cards:
        e = (c.get("email") or "").strip().lower()
        if e:
            emails.add(e)
        digits = re.sub(r"\D", "", c.get("phone") or "")
        if len(digits) >= 9:
            phones.add(digits)
    return emails, phones


def fabricated_contacts(answer, emails, phones):
    """답변에서 뽑은 연락처 중 데이터에 없는 것들."""
    out = []
    for m in _EMAIL_RE.findall(answer or ""):
        if m.strip().lower() not in emails:
            out.append(m)
    for m in _PHONE_RE.findall(answer or ""):
        digits = re.sub(r"\D", "", m)
        # 뒷자리만 답하는 정상 응답("뒤 4자리는 4312")을 날조로 보지 않는다.
        if len(digits) < 9:
            continue
        if digits not in phones and not any(digits in p for p in phones):
            out.append(m.strip())
    return out

# ---------------------------------------------------------------------------
# 답변 품질 2종 — Faithfulness / Answer Relevancy (RAGAS, Es et al. 2023 의 정의를 따른다)
#
# 둘 다 **LLM 이 실제로 답을 만든 턴**에만 매긴다(체크리스트와 같은 범위). 검색 지표와는
# 완전히 별개다 — 검색은 '가져오기'를 재고, 이 둘은 '가져온 것으로 무엇을 했나'를 잰다.
#
# ── Faithfulness ────────────────────────────────────────────────────────────
#   표준 정의:  F = |컨텍스트가 뒷받침하는 주장| / |답변의 주장 전체|
#   표준 구현:  LLM 이 답변을 주장 단위로 쪼개고, LLM 이 각 주장을 컨텍스트와 대조한다.
#   우리 적응:  답변이 **필드 값 모양**("데이터플랫폼팀입니다", "010-3000-6000")이라
#              주장 = 필드 값이다. 그래서 쪼개기도 대조도 **결정적**으로 한다.
#     · 주장 추출: 전화·이메일은 정규식 / 회사·부서·주소는 1000장 데이터에 실재하는
#                값이 답변에 나타나는지로 잡는다(직함·이름은 2~3자라 부분 일치 오탐이
#                커서 제외 — 아래 '한계').
#     · 근거 판정: 그 값이 **그 턴의 프롬프트에 들어간 카드**(context_cards, narrow 전)
#                안에 있으면 근거 있음. 대화 이력에는 있지만 이번 카드에 없으면 근거 없음
#                — 그게 바로 "옛 인물 값을 답하는" 실패 모드다.
#   왜 타당한가: RAGAS 논문도 주장 분해가 가장 불안정한 단계라고 적는다. 우리 답변은
#              분해가 필요 없을 만큼 짧고 정형이라, 판정자 모델 없이 재현 가능하게 잰다.
#   한계:      데이터에 없는 회사명을 지어내면 못 잡는다(색인이 없으므로). 전화·이메일
#              날조는 정규식으로 잡힌다. 직함·이름은 주장으로 세지 않는다.
#
# ── Answer Relevancy ────────────────────────────────────────────────────────
#   표준 정의:  답변이 질문에 얼마나 부합하는가. 불완전하거나 딴소리면 낮다.
#   표준 구현:  LLM 이 답변에서 질문 N개를 역생성하고 원 질문과의 코사인 유사도 평균.
#   우리 적응:  우리 질문은 '누구의 어떤 속성'이다. 물은 속성 **유형**의 값을 답했으면 부합.
#     · 속성을 물었으면:  요청 필드마다 **그 유형의 값**(전화·이메일은 정규식, 회사·부서·
#                       주소·직함은 데이터에 실재하는 값)이 답변에 있나. 점수 = |답한 필드| / |요청 필드|
#                       컨텍스트 안인지는 **보지 않는다** — 그건 충실성의 몫이다. 남의 회사를
#                       답하면 관련성 1 · 충실성 0, 날조 번호면 관련성 1 · 충실성 0 으로 갈려야
#                       세 층이 서로 다른 것을 잰다(처음엔 컨텍스트로 쟀다가 둘이 겹쳐서 고쳤다).
#     · 속성 없는 질문(누구 찾기): 컨텍스트 카드 이름이 하나라도 답변에 있나.
#     · 정답이 있는데 거절 문구로 답하면 0(질문을 다루지 않았다).
#   체크리스트와의 차이: 체크리스트는 **정답 카드의 값**이 있나(맞는 값), 관련성은
#              **요청한 유형**의 값이 있나(맞는 종류)다. "회사 물었는데 주소 답함"은
#              관련성 0 · 충실성 1 · 체크리스트 0 으로 갈린다 — 이 분해가 진단 가치다.
#
# 세 층을 함께 읽는다:  관련성(맞는 종류?) → 충실성(컨텍스트에서?) → 체크리스트(맞는 값?)
# ---------------------------------------------------------------------------
ATTRIBUTE_FIELD = {  # hybrid_server.ATTRIBUTE_FIELD 와 같게 유지할 것
    "이메일 주소": "email", "메일 주소": "email", "이메일주소": "email", "메일주소": "email",
    "회사 주소": "address", "회사주소": "address",
    "전화번호": "phone", "전화": "phone", "번호": "phone", "연락처": "phone",
    "핸드폰": "phone", "휴대폰": "phone",
    "메일": "email", "이메일": "email",
    "직급": "title", "직함": "title", "직책": "title",
    "회사": "company", "직장": "company",
    "소속": "company|department",  # 모호어 — 관련성 판정에서 둘 다 인정한다
    # 명사 없이 회사를 묻는 말투. 실측: 이게 없으면 "어디 다녀?" 가 '누구 찾기'로 분류돼
    # 이름만 답한 실패(오늘 19건 중 다수)를 관련성 만점으로 통과시켰다.
    "어디 다녀": "company", "어디 다니": "company", "어디서 일": "company", "어디 근무": "company",
    "주소": "address", "위치": "address", "지역": "location",
    "부서": "department",
}
_DEMONSTRATIVES = ("그", "이", "저")


def requested_fields(question):
    """질문이 물은 필드들(말한 순서). 지시 관형사 뒤의 명사("그 회사 주소")는 요청이 아니다."""
    found, taken = [], []
    for noun in sorted(ATTRIBUTE_FIELD, key=len, reverse=True):
        field = ATTRIBUTE_FIELD[noun]
        if any(f == field for _, f in found):
            continue
        start = 0
        while True:
            pos = question.find(noun, start)
            if pos < 0:
                break
            before = question[:pos].rstrip()
            if before.endswith(_DEMONSTRATIVES) or any(a <= pos < b for a, b in taken):
                start = pos + 1
                continue
            taken.append((pos, pos + len(noun)))
            found.append((pos, field))
            break
    return [f for _, f in sorted(found)]


def _field_variants(field, value):
    """답변에 나타날 수 있는 표기들. 회사는 '주식회사'를 뗀 형태, 주소는 도로명+번지도 인정."""
    if not value:
        return []
    if field == "company":
        return [v for v in company_variants(value) if len(v) >= 3]
    if field == "address":
        return address_variants(value)
    if field == "phone":
        digits = re.sub(r"\D", "", value)
        return [value, digits, digits[-4:]] if len(digits) >= 9 else [value]
    return [value] if len(value) >= 2 else []


def build_value_index(cards):
    """faithfulness 주장 추출용 — 데이터에 실재하는 회사·부서·주소 값(정규화 표기 포함)."""
    # title 은 관련성(유형 판정)에만 쓴다. 충실성 주장으로는 세지 않는다(2~3자 부분 일치 오탐).
    idx = {"company": {}, "department": {}, "address": {}, "title": {}}
    for c in cards:
        for field in idx:
            v = (c.get(field) or "").strip()
            for variant in _field_variants(field, v):
                # 직함은 2글자가 대부분(차장·과장·팀장·수석). 3글자 컷을 두면 "직함이 뭐야?" ->
                # "차장" 이 관련성 0 으로 찍힌다(실측 오탐). 다른 필드는 3글자 미만이면 오탐이 커진다.
                if len(variant) >= (2 if field == "title" else 3):
                    idx[field].setdefault(variant, v)
    return idx


def faithfulness(answer, context_cards, value_index):
    """(근거 있는 주장 수, 전체 주장 수, 근거 없는 주장 목록). 주장이 없으면 (0, 0, [])."""
    answer = answer or ""
    claims = []  # (field, matched_text, canonical_value)
    for m in _EMAIL_RE.findall(answer):
        claims.append(("email", m.strip().lower(), m.strip().lower()))
    for m in _PHONE_RE.findall(answer):
        digits = re.sub(r"\D", "", m)
        if len(digits) >= 9:
            claims.append(("phone", digits, digits))
    claims += _extract_value_claims(answer, value_index)

    def supported(field, matched, canonical):
        for card in context_cards or []:
            cv = (card.get(field) or "").strip()
            if not cv:
                continue
            if field == "email" and cv.lower() == matched:
                return True
            if field == "phone" and re.sub(r"\D", "", cv) == matched:
                return True
            # 정규형이 같거나, 답변에 나온 표기가 이 카드 값의 표기 변형 중 하나면 근거 있음.
            # 정규형만 비교하면 같은 핵심어를 가진 **다른 카드**로 정규화된 주장이 오탐된다
            # (실측: '노블엔지니어링' 이 '유한회사 노블엔지니어링' 카드로 잡혀 근거 없음 처리).
            if field in ("company", "department", "address") and (
                cv == canonical or matched in _field_variants(field, cv)
            ):
                return True
        return False

    ok = [c for c in claims if supported(*c)]
    bad = [f"{f}:{m}" for f, m, _ in claims if (f, m, _) not in ok]
    return len(ok), len(claims), bad


def _extract_value_claims(answer, value_index):
    """
    답변에서 회사·부서·주소 주장을 뽑는다 — **최장 일치 우선, 구간 소진.**

    단순 부분 문자열로 뽑으면 오탐이 셋 생긴다(전부 실측):
      · 긴 값 안의 짧은 값: '프로덕트디자인팀' 안의 '디자인팀' 이 별도 주장으로 잡힘
      · 같은 핵심어의 다른 카드: '유한회사 넥스트푸드' 답변에서 '넥스트푸드' 카드로 정규화됨
      · 번지 접두: '우암로 1' 이 '우암로 144' 에 매치
    긴 매치를 먼저 잡고 그 글자 구간을 소진하면 앞의 둘이 사라지고, 주소는 번지 뒤에
    숫자가 이어지면 매치로 보지 않아 셋째가 사라진다.
    """
    cands = []
    for field in ("company", "department", "address"):
        for variant, canonical in value_index[field].items():
            start = 0
            while True:
                pos = answer.find(variant, start)
                if pos < 0:
                    break
                end = pos + len(variant)
                if field == "address" and end < len(answer) and answer[end].isdigit():
                    start = pos + 1
                    continue
                cands.append((pos, end, field, variant, canonical))
                start = pos + 1
    cands.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    taken, claims, seen = [], [], set()
    for s_, e_, field, variant, canonical in cands:
        if any(not (e_ <= ts or s_ >= te) for ts, te in taken):
            continue
        taken.append((s_, e_))
        if (field, canonical) in seen:
            continue
        seen.add((field, canonical))
        claims.append((field, variant, canonical))
    return claims


_SEARCH_INTENT = ("찾아", "알려줘", "있어", "있나", "누구", "명이야", "명인데", "명이", "몇")


def answer_relevancy(question, answer, context_cards, gold, value_index, prev_fields=None, must=None):
    """
    (답한 필드 수, 요청 필드 수). None 이면 채점 제외.

    prev_fields: 앞 턴이 물은 필드. "어민서씨도?" 처럼 **속성을 생략한 후속**은 질문만 봐서는
    무엇을 물었는지 알 수 없다 — 서버가 carryOverAttribute 로 앞 턴 속성을 이어 붙이는 것과
    같은 원리로, 채점기도 앞 턴 필드를 물려받는다(실측: 이게 없어서 회사를 맞게 답한 턴이
    '누구 찾기'로 분류돼 관련성 0 으로 찍혔다).
    """
    answer = answer or ""
    # **정답 카드가 없는 턴은 관련성이 정의되지 않는다** — 도메인 밖 질문("오늘 날씨 어때?"),
    # 본인 진술("내 회사는 블루오션이야"), 거절이 기대되는 턴이 여기 든다. 그 턴들이 제대로
    # 거절했는지는 '무관 요청 카드 억제'와 결정적 턴 체크리스트가 이미 잰다. 텍스트 휴리스틱
    # (물음표·must 대조)으로 가르려다 실패해서 이 한 기준으로 바꿨다 — 진술 안의 "회사"가
    # 요청 필드로 잡히는 식의 오탐이 사라진다.
    if not gold:
        return None
    if any(r in answer for r in REJECTIONS):
        return 0, 1  # 정답이 있는데 거절 — 질문을 다루지 않았다
    fields = requested_fields(question)
    if not fields and prev_fields and not any(w in question for w in _SEARCH_INTENT):
        fields = list(prev_fields)
    if not fields:
        names = [c.get("name") for c in context_cards or [] if c.get("name")]
        if not names:
            return None
        # '누구 찾기'에는 이름 나열도, "총 N명" 도 답이다 — 카드가 화면에 같이 뜨므로 개수만
        # 말해도 질문을 다룬 것이다. 체크리스트가 이미 그렇게 설계돼 있어 관련성도 맞춘다.
        ok = any(n in answer for n in names) or re.search(r"총\s*\d+\s*명", answer) is not None
        return (1 if ok else 0), 1
    hit = sum(1 for field in fields if _has_value_of_type(field, answer, context_cards, value_index))
    return hit, len(fields)


def _has_value_of_type(field, answer, context_cards, value_index):
    """답변에 그 **유형**의 값이 있나. 출처(컨텍스트 안/밖)는 묻지 않는다."""
    if "|" in field:
        return any(_has_value_of_type(f, answer, context_cards, value_index) for f in field.split("|"))
    if field == "phone":
        return any(len(re.sub(r"\D", "", m)) >= 9 for m in _PHONE_RE.findall(answer))
    if field == "email":
        return bool(_EMAIL_RE.search(answer))
    if field in value_index:
        return any(v in answer for v in value_index[field])
    # location 처럼 색인이 없는 필드는 컨텍스트 값으로만 본다.
    return any(v in answer for c in context_cards or []
               for v in _field_variants(field, (c.get(field) or "").strip()))


def rescore_from_dump(path, cards):
    """생성(75분)과 채점(초)을 분리한다 — 채점 기준을 고쳤을 때 답변을 다시 만들지 않는다."""
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    contacts = build_contact_index(cards)
    vi = build_value_index(cards)
    rel_hit = rel_n = f_ok = f_n = f_turns = f_bad = noclaim = fab_bad = llm = 0
    fails = []
    prev_fields, prev_key = None, None
    for r in rows:
        key = (r["kind"], r.get("scenario_idx"))
        if r["depth"] == 1:
            prev_fields = None  # 새 시나리오
        answer = r.get("answer") or ""
        if not answer or r.get("route") not in GENERATING_ROUTES or r.get("abstained"):
            continue
        llm += 1
        ctx = r.get("context_cards") or r.get("cards") or []
        rel = answer_relevancy(r["q"], answer, ctx, r.get("gold"), vi, prev_fields, r.get("must"))
        prev_fields = requested_fields(r["q"]) or prev_fields
        if rel is not None:
            rel_hit += rel[0]; rel_n += rel[1]
            if rel[0] < rel[1]:
                fails.append((r["kind"], r["depth"], r["q"], f"관련성 / 답변={answer[:40]!r}"))
        ok, n, bad = faithfulness(answer, ctx, vi)
        if n:
            f_ok += ok; f_n += n; f_turns += 1
            if bad:
                f_bad += 1
                fails.append((r["kind"], r["depth"], r["q"], f"충실성: {bad[0]} / 답변={answer[:40]!r}"))
        else:
            noclaim += 1
        if fabricated_contacts(answer, contacts[0], contacts[1]):
            fab_bad += 1
    print(f"\n재채점 — {path}  (LLM 턴 {llm}개, 생성 없음)")
    print(f"  답변 관련성(Relevancy)   {rel_hit / max(rel_n, 1):.3f}  ({rel_hit}/{rel_n} 요청 필드)")
    print(f"  답변 충실성(Faithfulness) {f_ok / max(f_n, 1):.3f}  ({f_ok}/{f_n} 주장 · 턴 {f_turns}개, "
          f"컨텍스트 밖 값 있는 턴 {f_bad}개, 주장 0건 {noclaim}개)")
    print(f"  연락처 날조 없음         {(llm - fab_bad) / max(llm, 1):.3f}  ({llm - fab_bad}/{llm})")
    print(f"\n[실패 {len(fails)}건]")
    for k, d, q, why in fails:
        print(f"  [{k}] {d}턴  {q}\n      {why}")


def build_scenarios(cards, rng):
    """
    시나리오를 카드 데이터에서 생성한다.

    **멀티턴 평가이므로 다중 턴이 주가 되어야 한다.** 처음에는 1턴 시나리오가 과반(57%)
    이었는데, 그러면 이름만 멀티턴이지 실제로 재는 건 단발 검색이다. 단발로만 확인할 수
    있는 것(자기참조·전체 카운트)만 1턴으로 남기고 나머지는 대화 안에 넣었다.

    **에이전트 도입을 염두에 둔 부분**: 지금 route 는 '우리 코드가 고른 경로'지만,
    도구가 여러 개가 되면 '모델이 고른 도구'로 의미가 바뀐다. 그래서 시나리오와 정답은
    도구 중립적으로 두고(질문 -> 기대 동작), 바뀌는 건 라벨 층 하나로 국한했다.
    '도구 범위 밖' 유형은 지금은 "명함으로 답하면 안 된다"를 재고, 캘린더 도구가 붙으면
    그대로 "캘린더로 라우팅돼야 한다"로 바뀌는 자리다.
    """
    name_counts = Counter(c["name"] for c in cards)
    unique = [c for c in cards if name_counts[c["name"]] == 1]
    by_id_all = {c["id"]: c for c in cards}
    title_counts = Counter()
    for c in cards:
        for t in norm_tokens(c.get("title")):
            title_counts[t] += 1
    scenarios = []

    def add(kind, turns, known_gap=False, generate_only=False):
        # known_gap: 지금 못 하는 게 확인된 케이스. 헤드라인 숫자에서 빼고 따로 보고한다 —
        # 회귀망을 계속 초록으로 유지하면서도 남은 간극을 잊지 않기 위해서다.
        # generate_only: 답변을 봐야 판정되는 시나리오(무관 턴이 focus 를 오염시키는지 등).
        # dry-run 은 답을 안 만들어 카드 정리가 일어나지 않으므로 건너뛴다 —
        # 재지 못하는 걸 실패로 세면 지표가 거짓말을 한다.
        scenarios.append({"kind": kind, "turns": turns, "known_gap": known_gap,
                          "generate_only": generate_only})

    pool = [c for c in unique if all(c.get(f) for f in ("company", "address", "title", "department"))]
    rng.shuffle(pool)

    def person_slots(c):
        return {"focus": c["name"], "names": [c["name"]], "titles": [], "locations": []}

    # (1) 이름 지목 -> 속성 생략형 후속 (4턴) — focus 이어짐 + 카드 유지
    for c in pool[:25]:
        gold, slots = [c["id"]], person_slots(c)
        add("이름+생략형후속", [
            turn(pick(rng, ASK_COMPANY, n=c["name"]), "search", slots, gold,
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["address"]), "search", slots, gold,
                 must=[address_variants(c["address"])], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["title"]), "search", slots, gold,
                 must=[[c["title"]]], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["department"]), "search", slots, gold,
                 must=[[c["department"]]], must_not=REJECTIONS),
        ])

    # (2) 6턴 장문 — 최근 창(메시지 8개 = 4턴)을 넘겨 historyDigest 로 접히는 구간
    for c in pool[25:35]:
        gold, slots = [c["id"]], person_slots(c)
        tail = re.sub(r"\D", "", c.get("phone") or "")[-4:]
        add("6턴 장문", [
            turn(pick(rng, ASK_COMPANY, n=c["name"]), "search", slots, gold,
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["address"]), "search", slots, gold,
                 must=[address_variants(c["address"])], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["title"]), "search", slots, gold,
                 must=[[c["title"]]], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["department"]), "search", slots, gold,
                 must=[[c["department"]]], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["email"]), "search", slots, gold,
                 must=[[c["email"]]], must_not=REJECTIONS),
            turn(pick(rng, ELLIPTIC["phone"]), "search", slots, gold,
                 must=[[c["phone"], tail]], must_not=REJECTIONS),
        ])

    # (3) 주제 전환 — 다른 사람으로 갔다가 처음 사람으로 돌아온다(focus 가 따라와야 한다)
    for a, b in zip(pool[35:43], pool[43:51]):
        add("주제 전환", [
            turn(pick(rng, ASK_COMPANY, n=a["name"]), "search", person_slots(a), [a["id"]],
                 must=[company_variants(a["company"])], must_not=REJECTIONS),
            turn(pick(rng, ASK_ONLY_NAME, n=b["name"]), "search", person_slots(b), [b["id"]],
                 must=[company_variants(b["company"])], must_not=REJECTIONS),
            turn(pick(rng, ASK_DEPARTMENT_NAMED, n=a["name"]), "search", person_slots(a), [a["id"]],
                 must=[[a["department"]]], must_not=REJECTIONS),
        ])

    # (4) 지역+직함 -> 복수 지시어 후속(followup 경로)
    combos = defaultdict(list)
    for c in cards:
        for loc in ("서울", "부산", "대전", "대구", "광주", "경기도", "판교"):
            if loc in (c.get("address") or ""):
                for t in norm_tokens(c.get("title")):
                    combos[(loc, t)].append(c["id"])
    viable = [(k, v) for k, v in combos.items() if 2 <= len(v) <= 12]
    rng.shuffle(viable)
    for (loc, title), ids in viable[:15]:
        want = [by_id_all[i]["name"] for i in ids] + [f"총 {len(ids)}명"]
        add("지역+직함->후속", [
            turn(pick(rng, SEARCH_LOC_TITLE, loc=loc, t=title), "search",
                 {"names": [], "titles": [title], "locations": [loc]}, ids,
                 must=[want], must_not=REJECTIONS),
            turn(pick(rng, PLURAL_FOLLOWUP), "followup", None, ids, must_not=REJECTIONS),
        ])

    # (5) 카운트 -> 좁히기 (결정적 경로에서 검색 경로로 넘어가는 전환)
    #     직함을 토큰으로 쪼개면 "Head of Engineering" 에서 of/head/engineer 같은 조각이
    #     나와 "대전에 있는 of은?" 같은 말이 안 되는 질의가 생긴다. 한글 직함만 쓴다.
    korean_titles = [t for t, _ in title_counts.most_common(60)
                     if len(t) >= 2 and re.fullmatch(r"[가-힣]+", t)]
    for title in korean_titles[:8]:
        ids = [c["id"] for c in cards if title in norm_tokens(c.get("title"))]
        narrowed = [i for i in ids if "대전" in (by_id_all[i].get("address") or "")]
        add("카운트->좁히기", [
            turn(f"{title} 몇 명이야?", "filtered_count", None, ids,
                 must=[[f"총 {len(ids)}명"]]),
            turn(f"대전에 있는 {title}은?", "search" if narrowed else "empty_result",
                 {"names": [], "titles": [title], "locations": ["대전"]},
                 narrowed or None),
        ])

    # (6) 개념형 -> 후속 (최대 약점. 이름 대신 "총 N명"만 답하면 실패로 잡힌다)
    for q, pattern in CONCEPT_QUERIES:
        rx = re.compile(pattern, re.I)
        ids = [c["id"] for c in cards if rx.search(c.get("title") or "")]
        if not ids:
            continue
        gold_names = [by_id_all[i]["name"] for i in ids]
        add("개념형->후속", [
            turn(q, "search", None, ids, must=[gold_names], must_not=REJECTIONS),
            turn("그 사람들 회사는?", "followup", None, ids, must_not=REJECTIONS),
        ])

    # (7) 기권에서 복구 — 없는 사람을 물어 기권한 뒤에도 앞 문맥이 살아 있어야 한다
    for c in pool[51:58]:
        gold, slots = [c["id"]], person_slots(c)
        add("기권 후 복구", [
            turn(f"{c['name']}씨 회사가 어디야?", "search", slots, gold,
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn("정하은씨 연락처", "abstain", None, None, must=[REJECTIONS]),
            turn("부서는?", "search", slots, gold, must=[[c["department"]]], must_not=REJECTIONS),
        ])

    # (8) 없는 조합 -> 복구 ("판교에 있는 디자이너" 이후 정상 질의로 돌아오기)
    # 직함을 토큰으로 쪼개면 "디자인 디렉터" -> 디자인/디렉터 조각이 나와서
    # "부산에 있는 디자인 찾아줘" 같은 말이 안 되는 질의가 만들어진다.
    # **띄어쓰기 없는 완전한 한글 직함**만 쓴다.
    whole_titles = {c["title"].strip() for c in cards if (c.get("title") or "").strip()}
    all_titles = {t for t in whole_titles
                  if " " not in t and re.fullmatch(r"[가-힣]{2,}", t)}
    empty_pairs = []
    for loc in ("판교", "대전", "부산", "광주", "대구"):
        loc_cards = [c for c in cards if loc in (c.get("address") or "")]
        if not loc_cards:
            continue
        # **토큰 단위로** 비교해야 한다. 완전 직함끼리만 비교했더니
        # "대구에 있는 디자이너"를 '없는 조합'으로 분류했는데, 실제로는 대구에
        # '시니어 디자이너'가 있어서 시스템이 맞고 시나리오가 틀렸다(held-out seed 7 에서
        # 발견 — seed 42 에서는 이 조합이 안 뽑혀 평가 결함이 드러나지 않았다).
        # 검색이 직함을 토큰으로 매칭하므로 정답 판정도 같은 기준이어야 한다.
        present = {t for c in loc_cards for t in norm_tokens(c.get("title"))}
        for t in sorted(all_titles - present):
            if len(t) >= 2 and title_counts.get(t, 0) >= 10:
                empty_pairs.append((loc, t, [c["id"] for c in loc_cards]))
    rng.shuffle(empty_pairs)
    for loc, title, loc_ids in empty_pairs[:8]:
        add("없는 조합->복구", [
            turn(f"{loc}에 있는 {title} 찾아줘", "empty_result",
                 {"names": [], "titles": [title], "locations": [loc]}, None, must=[REJECTIONS]),
            turn(f"그럼 {loc}에는 누가 있어?", "search",
                 {"names": [], "titles": [], "locations": [loc]}, loc_ids, must_not=REJECTIONS),
        ])

    # (9) 동명이인 — 두 명 다 후보에 남아야 하고, 되물으면 그 집합을 유지해야 한다
    dup_names = [n for n, k in name_counts.items() if k == 2]
    rng.shuffle(dup_names)
    for nm in dup_names[:6]:
        ids = [c["id"] for c in cards if c["name"] == nm]
        add("동명이인", [
            turn(f"{nm}씨 회사가 어디야?", "search",
                 {"names": [nm], "titles": [], "locations": []}, ids,
                 must=[[by_id_all[i]["company"] for i in ids if by_id_all[i].get("company")]]),
            turn("두 명인데?", "followup", None, ids),
        ])

    # (10) 문맥 참조 — 검색 없이 아는 것으로 답해야 한다
    for c in pool[58:66]:
        add("문맥참조", [
            turn(f"{c['name']}씨 회사가 어디야?", "search", person_slots(c), [c["id"]],
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn(pick(rng, RECALL_COMPANY), "context_answer"),
        ])

    # (11) 사실 정정 — 같은 key 를 덮어써야 한다(옛 값이 남으면 안 된다)
    add("사실 정정", [
        turn("내 회사는 블루오션이야"),
        turn("내 회사는 한빛테크야"),
        turn("아까 말한 내 회사 뭐였지", "context_answer",
             must=[["한빛테크"]], must_not=["블루오션"]),
    ])

    # (12) 도구 범위 밖 — 명함으로 답할 수 없는 요청. 지금은 "명함을 들이밀지 않는다"를
    #      재고, 캘린더/문자 도구가 붙으면 이 자리가 "그 도구로 라우팅돼야 한다"로 바뀐다.
    for c, req in zip(pool[66:70],
                      ["내일 3시에 일정 잡아줘", "오늘 날씨 어때?",
                       "이 사람한테 문자 보내줘", "환율 얼마야?"]):
        add("도구 범위 밖", [
            turn(f"{c['name']}씨 회사가 어디야?", "search", person_slots(c), [c["id"]],
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn(req, None, None, None, no_cards=True),
        ])

    # (13) 단발로만 확인되는 것 — 대화에 넣으면 의미가 흐려지므로 1턴으로 둔다
    #
    # 전체 개수는 **표현 변형이 핵심**이다. 실기기에서 "내가 가진 명함 개수 몇개야?",
    # "명함 몇 개 있어?" 가 전부 검색으로 빠져 "총 5명"이라 답했다(실제 1000).
    # "전체/총" 신호가 있어야만 통과시키던 게 원인이라, 자연스러운 표현들을 다 넣어 둔다.
    for phrasing in ("전체 몇 장이야?", "내가 가진 명함 개수 몇개야?", "명함 몇 개 있어?",
                     "내 명함 몇 장이야?", "저장된 명함 개수는?", "명함 몇 장 가지고 있어?"):
        add("전체 카운트", [turn(phrasing, "total_count", must=[[f"{len(cards)}명"]])])
    add("자기참조", [turn("너는 누구야?", "self_reference", must=[["어시스턴트"]])])
    add("기권(전화)", [turn("010-0000-0000", "abstain", must=[REJECTIONS])])

    # (13-b) 조사 변형 카운트 — 계사 관형형("~인 사람")을 쓰는 자연스러운 표현.
    #        실기기에서 "주소가 대전인 사람 몇 명이야?" 가 총 5명이라 답했다(실제 51).
    #        '대전인' 의 '인' 을 못 떼서 조건이 안 잡히고 검색으로 폴백한 것이다.
    for loc in ("대전", "부산"):
        ids = [c["id"] for c in cards if loc in (c.get("address") or "")]
        if ids:
            add("조사 변형 카운트", [
                turn(f"주소가 {loc}인 사람 몇 명이야?", "filtered_count", None, ids,
                     must=[[f"총 {len(ids)}명"]]),
            ])
    for title in korean_titles[:2]:
        ids = [c["id"] for c in cards if title in norm_tokens(c.get("title"))]
        add("조사 변형 카운트", [
            turn(f"직급이 {title}인 사람 몇 명이야?", "filtered_count", None, ids,
                 must=[[f"총 {len(ids)}명"]]),
        ])

    # (14) 본인 사실 vs 명함 인물 구분 — 예전에는 "그 사람 회사 어디야" 가
    #      contextAnswer 로 새서 **본인** 회사를 답했다(알려진 간극이었다).
    #      CONTEXT_REFERENCES 에서 대명사를 빼면서 해결됐고, 회귀 방지로 남긴다.
    gap = pool[70]
    add("본인사실 vs 명함인물", [
        turn("내 회사는 블루오션이야"),
        turn(f"{gap['name']}씨 찾아줘", "search",
             {"names": [gap["name"]], "titles": [], "locations": []}, [gap["id"]]),
        turn("그 사람 회사 어디야", "search", None, [gap["id"]],
             must=[company_variants(gap["company"])], must_not=["블루오션"]),
    ])

    # (15) 대명사 체인 — "그 사람"/"그 회사"로 속성을 새로 묻는다.
    #      되짚기(contextAnswer)가 아니라 focus 치환 후 정상 검색으로 가야 한다.
    for c in pool[71:78]:
        add("대명사 체인", [
            turn(f"{c['name']}씨 회사가 어디야?", "search", person_slots(c), [c["id"]],
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn("그 사람 부서는?", "search", None, [c["id"]],
                 must=[[c["department"]]], must_not=REJECTIONS),
            turn("그 회사 주소는?", "search", None, [c["id"]],
                 must=[address_variants(c["address"])], must_not=REJECTIONS),
        ])

    # (16) 잡담 삽입 후 복귀 — 명함과 무관한 턴이 focus 를 오염시키면 안 된다.
    #      실측: "오늘 날씨 어때?" 가 카드는 비웠는데 focus 를 검색 1등으로 바꿔서
    #      다음 "부서는?" 이 엉뚱한 사람 부서를 답했다.
    for c, chat in zip(pool[78:84],
                       ["오늘 날씨 어때?", "환율 얼마야?", "너 뭐 할 줄 알아?",
                        "내일 비 와?", "지금 몇 시야?", "고마워"]):
        add("잡담 후 복귀", [
            turn(f"{c['name']}씨 회사가 어디야?", "search", person_slots(c), [c["id"]],
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn(chat, None, None, None, no_cards=True),
            turn("부서는?", "search", person_slots(c), [c["id"]],
                 must=[[c["department"]]], must_not=REJECTIONS),
        ], generate_only=True)

    # (17) 같은 질문 반복 — 두 번 물어도 같은 사람을 답해야 한다(일관성).
    for c in pool[84:89]:
        gold, slots = [c["id"]], person_slots(c)
        add("반복 일관성", [
            turn(f"{c['name']}씨 부서는?", "search", slots, gold,
                 must=[[c["department"]]], must_not=REJECTIONS),
            turn(f"{c['name']}씨 부서는?", "search", slots, gold,
                 must=[[c["department"]]], must_not=REJECTIONS),
        ])

    # (18) 조건 누적(점진적 좁히기) — "대전에 있는 사람" -> "그중에 변호사만" 에서
    #      앞 턴의 지역 조건이 사라져 전국 변호사가 나왔다(알려진 간극이었다).
    #      applyNarrowing 으로 앞 턴 조건어를 이어 붙여 해결했고, 회귀 방지로 남긴다.
    loc_for_narrow = "대전"
    narrow_ids = [c["id"] for c in cards
                  if loc_for_narrow in (c.get("address") or "")
                  and "변호사" in norm_tokens(c.get("title"))]
    add("조건 누적", [
        turn(f"{loc_for_narrow}에 있는 사람 찾아줘", "search",
             {"names": [], "titles": [], "locations": [loc_for_narrow]}, None),
        turn("그중에 변호사만", "search",
             {"names": [], "titles": ["변호사"], "locations": [loc_for_narrow]},
             narrow_ids or None),
    ])

    # (19) 순서 지시("두 번째 사람") — 직전 집합에서 하나를 고르는 발화.
    #      미구현일 때는 새 검색으로 빠져 무관한 사람이 나왔다(알려진 간극이었다).
    order_ids = [c["id"] for c in cards
                 if "대전" in (c.get("address") or "") and "변호사" in norm_tokens(c.get("title"))]
    if len(order_ids) >= 2:
        add("순서 지시", [
            turn("대전에 있는 변호사 찾아줘", "search",
                 {"names": [], "titles": ["변호사"], "locations": ["대전"]}, order_ids),
            turn("두 번째 사람 연락처", "followup", None, [order_ids[1]]),
        ])

    return scenarios


# --- 실행 -------------------------------------------------------------------

def ask(question, history, focus, prev_ids, memory, dry_run, attempts=3):
    """
    한 턴을 서버에 묻는다. **타임아웃이면 다시 시도한다.**

    실측: 386턴 생성 모드에서 220건까지 중앙 8초로 정상이다가 한 건이 697초 걸려
    클라이언트 타임아웃에 걸렸고, 그 예외가 그대로 올라가면서 **1시간짜리 실행이
    통째로** 버려졌다(원인은 같은 디스크의 OneDrive 동기화로 추정 — 앞서 44분 지연도
    같은 패턴이었다). 단발 지연 때문에 전체를 잃지 않도록 재시도한다.
    """
    payload = json.dumps({
        "question": question, "history": history, "focus": focus,
        "prev_card_ids": prev_ids, "conversation_memory": memory,
        "dry_run": dry_run,
    }, ensure_ascii=False).encode()
    last = None
    for i in range(attempts):
        req = urllib.request.Request(ENDPOINT, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=600).read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [재시도 {i + 1}/{attempts}] {type(e).__name__}: {question[:30]}", flush=True)
    raise last


def slot_sets(expected, actual_filters, actual_focus):
    """
    기대/실제 슬롯을 (키, 값) 집합으로 편다. JGA·F1 둘 다 이 집합으로 계산한다.

    필드 조건(이름/직함/지역)은 질의로 완전히 정해지므로 **항상** 검사한다 —
    안 적었으면 비어 있어야 한다는 뜻이고, 엉뚱한 조건이 붙는 것도 잡아야 한다.
    focus 는 검색 결과 1등에서 파생돼 미리 알 수 없는 경우가 있으므로
    시나리오가 "focus" 키를 명시했을 때만 검사한다.
    """
    exp, act = set(), set()
    for key, field in (("names", "name"), ("titles", "title"), ("locations", "location")):
        exp |= {(key, v) for v in (expected.get(key) or [])}
        act |= {(key, v) for v in (actual_filters.get(field) or [])}
    if "focus" in expected:
        if expected["focus"] is not None:
            exp.add(("focus", expected["focus"]))
        if actual_focus:
            act.add(("focus", actual_focus))
    return exp, act


def check_answer(t, answer):
    """(통과 여부, 실패 사유). must 의 각 원소는 대안 목록 — 하나만 맞으면 된다."""
    for alts in t["must"]:
        if not any(a and a in answer for a in alts):
            return False, f"필수 누락: {alts[0]!r}"
    for bad in t["must_not"]:
        if bad in answer:
            return False, f"금지 등장: {bad!r}"
    return True, ""


def run_pass(scenarios, dry_run, stats, failures, gap_failures, contacts=None,
             value_index=None, dump=None):
    """시나리오 전체를 1회 실행하고 stats 를 채운다. 시나리오별 체크리스트 통과 여부를 돌려준다."""
    scenario_pass = {}
    for idx, sc in enumerate(scenarios):
        if dry_run and sc.get("generate_only"):
            continue
        history, focus, prev_ids, memory = [], None, [], None
        prev_fields = None  # 관련성 채점용 — 앞 턴이 물은 필드
        kind = sc["kind"]
        # 알려진 간극은 헤드라인 통계에서 빼고 따로 센다.
        st = stats["gap"] if sc.get("known_gap") else stats
        target_failures = gap_failures if sc.get("known_gap") else failures
        route_all_ok = True
        checks_all_ok = True
        for depth, t in enumerate(sc["turns"], start=1):
            try:
                res = ask(t["q"], history, focus, prev_ids, memory, dry_run)
            except Exception as e:  # noqa: BLE001
                # 재시도까지 실패하면 그 시나리오만 중단하고 계속 간다 —
                # 전체 실행을 잃는 것보다 낫다. 집계에는 실패로 남는다.
                target_failures.append((kind, depth, t["q"], f"요청 실패: {type(e).__name__}"))
                stats["request_error"] = stats.get("request_error", 0) + 1
                break
            answer = res.get("answer") or ""

            # 날조 검사 — 답변에 **어느 카드에도 없는** 연락처가 있으면 지어낸 것이다.
            # 생성 모드에서만 의미가 있다(dry-run 은 답변을 만들지 않는다).
            if contacts and not dry_run and answer:
                bogus = fabricated_contacts(answer, contacts[0], contacts[1])
                st["fab_n"] = st.get("fab_n", 0) + 1
                if bogus:
                    st["fab_bad"] = st.get("fab_bad", 0) + 1
                    target_failures.append(
                        (kind, depth, t["q"], f"데이터에 없는 연락처: {bogus[0]}"))
            route = res.get("route")

            if t["route"] is not None:
                st["route_n"] += 1
                st["kind"][kind]["route_n"] += 1
                if route == t["route"]:
                    st["route_ok"] += 1
                    st["kind"][kind]["route_ok"] += 1
                else:
                    route_all_ok = False
                    st["confusion"][(t["route"], route)] += 1
                    target_failures.append((kind, depth, t["q"], f"경로 {t['route']} 기대 -> {route}"))

            if t["slots"] is not None:
                exp, act = slot_sets(t["slots"], res.get("field_filters") or {}, res.get("focus"))
                st["jga_n"] += 1
                st["kind"][kind]["jga_n"] += 1
                if exp == act:
                    st["jga_ok"] += 1
                    st["kind"][kind]["jga_ok"] += 1
                else:
                    target_failures.append((kind, depth, t["q"], f"슬롯 {sorted(exp)} -> {sorted(act)}"))
                st["tp"] += len(exp & act)
                st["fp"] += len(act - exp)
                st["fn"] += len(exp - act)

            if t["gold"]:
                gold = set(t["gold"])
                top5 = (res.get("card_ids") or [])[:5]
                found = gold & set(top5)

                # Hit@5 — 정답이 **하나라도** top-5 에 있으면 성공.
                # 예전 이름이 'R@5' 였는데 계산은 이것이었다(HJP-limited/ymj 에서 지적).
                # 정답이 1장인 턴(76.4%)은 recall 과 같은 값이지만, 정답이 여럿인 턴에서는
                # 훨씬 후하다 — 정답 104장짜리 턴은 사실상 자동 통과다.
                st["hit5_n"] += 1
                st["kind"][kind]["hit5_n"] += 1
                if found:
                    st["hit5_ok"] += 1
                    st["kind"][kind]["hit5_ok"] += 1
                else:
                    target_failures.append((kind, depth, t["q"], "정답 카드가 top-5 에 없음"))

                # R@5 — 분모를 min(정답수, 5) 로 잘라 **상한을 1.0 으로** 맞춘 형태.
                # eval_search.py 의 R@5 와 같은 공식이라 두 스크립트를 나란히 볼 수 있다.
                # 날것의 Recall@5(분모=정답수)는 쓰지 않는다: 이 시나리오 집합에서 완벽한
                # 검색기의 상한이 0.924 이고, '조사 변형 카운트' 0.096 · '없는 조합->복구'
                # 0.206 처럼 유형별로 크게 눌려서 잘해도 낮게 나온다(측정값).
                st["r5_sum"] += len(found) / min(len(gold), 5)
                st["r5_n"] += 1
                st["kind"][kind]["r5_sum"] += len(found) / min(len(gold), 5)
                st["kind"][kind]["r5_n"] += 1

                # MRR — 첫 정답의 역순위. 정답 수에 좌우되지 않아 상한 문제가 없다.
                rr = next((1.0 / (i + 1) for i, cid in enumerate(top5) if cid in gold), 0.0)
                st["mrr_sum"] += rr
                st["kind"][kind]["mrr_sum"] += rr

            # 답변 품질 2종(Faithfulness / Relevancy) — LLM 이 실제로 답을 만든 턴에만.
            if not dry_run and answer and route in GENERATING_ROUTES and not res.get("abstained"):
                ctx = res.get("context_cards") or res.get("cards") or []
                rel = answer_relevancy(t["q"], answer, ctx, t["gold"], value_index or {}, prev_fields, t["must"])
                prev_fields = requested_fields(t["q"]) or prev_fields
                if rel is not None:
                    st["rel_hit"] += rel[0]
                    st["rel_n"] += rel[1]
                    if rel[0] < rel[1]:
                        target_failures.append((kind, depth, t["q"],
                            f"관련성: 물은 속성 유형을 안 답함 / 답변={answer[:40]!r}"))
                if value_index:
                    f_ok, f_n, f_bad = faithfulness(answer, ctx, value_index)
                    if f_n:
                        st["faith_ok"] += f_ok
                        st["faith_n"] += f_n
                        st["faith_turns"] += 1
                        if f_bad:
                            st["faith_bad_turns"] += 1
                            target_failures.append((kind, depth, t["q"],
                                f"충실성: 컨텍스트 밖 값 {f_bad[0]} / 답변={answer[:40]!r}"))
                    else:
                        st["faith_noclaim"] += 1
            if dump is not None:
                dump.write(json.dumps({
                    "kind": kind, "depth": depth, "q": t["q"], "route": route, "answer": answer,
                    "gold": t["gold"], "must": t["must"], "must_not": t["must_not"],
                    "abstained": bool(res.get("abstained")),
                    "context_cards": res.get("context_cards"), "cards": res.get("cards"),
                    "focus": res.get("focus"), "field_filters": res.get("field_filters"),
                }, ensure_ascii=False) + "\n")

            # 체크리스트는 생성 모드에서만, 그리고 **LLM 이 실제로 답을 만든 턴에만** 매긴다.
            if not dry_run and t["must"]:
                generated = route in GENERATING_ROUTES and not res.get("abstained")
                bucket = "chk_llm" if generated else "chk_det"
                st[bucket + "_n"] += 1
                ok, why = check_answer(t, answer)
                if ok:
                    st[bucket + "_ok"] += 1
                else:
                    checks_all_ok = False
                    target_failures.append((kind, depth, t["q"], f"{why} / 답변={answer[:60]!r}"))
                if generated:
                    st["kind"][kind]["chk_n"] += 1
                    if ok:
                        st["kind"][kind]["chk_ok"] += 1

            # 명함과 무관한 요청에 카드가 뜨면 안 된다. 카드를 지우는 판정은 답변을 본 뒤에
            # 일어나므로 생성 모드에서만 확인할 수 있다.
            if not dry_run and t.get("no_cards"):
                st["nocard_n"] += 1
                if not (res.get("card_ids") or []):
                    st["nocard_ok"] += 1
                else:
                    target_failures.append((kind, depth, t["q"],
                                            f"카드가 뜨면 안 되는데 {len(res['card_ids'])}장"))

            if res.get("gen_ms"):
                stats["gen_ms"].append(res["gen_ms"])

            # dry-run 은 답변을 만들지 않아 히스토리의 assistant 자리가 빈다.
            # context_answer 의 "직전 답변 재사용" 분기가 그 텍스트를 보므로, 비어 있으면
            # 실제로는 타는 경로가 평가에서만 안 타는 착시가 생긴다. 검색이 찾은 이름으로
            # 대신 채운다 — 답변이 언급했을 내용의 대역이다.
            # filter_terms: 서버가 "그중에 …" 질의에서 앞 턴 조건을 이어받는 데 쓴다
            # (앱에서는 AgentSession.KEY_LAST_FILTER_TERMS 가 같은 역할).
            ff = res.get("field_filters") or {}
            terms = " ".join(v for key in ("name", "location", "title")
                             for v in (ff.get(key) or []))
            history = history + [{
                "q": t["q"],
                "a": answer or ", ".join(res.get("hybrid_top") or []),
                "filter_terms": terms or None,
            }]
            focus = res.get("focus") or focus
            prev_ids = res.get("card_ids") or prev_ids
            memory = res.get("conversation_memory") or memory

        st["depth"][len(sc["turns"])]["n"] += 1
        if route_all_ok:
            st["depth"][len(sc["turns"])]["ok"] += 1
        scenario_pass[idx] = checks_all_ok
    return scenario_pass


def stratified_sample(scenarios, n, rng):
    """
    유형별 층화 추출 — **유형마다 최소 1개씩** 보장하고 남는 자리를 개수에 비례해 나눈다.

    균등 무작위로 뽑았더니 20종 중 12종이 통째로 빠졌다(실측: --sample 18 로 돌린 결과에
    문맥참조·대명사 체인·잡담 후 복귀·조건 누적·사실 정정 등이 0개). 개수가 적은 유형
    (조건 누적 1개, 사실 정정 1개)은 거의 확실히 탈락하고 많은 유형(이름+생략형후속 25개)만
    반복해서 뽑힌다. 그러면 지표는 1.000 이 나오는데 **정작 최근 고친 것들은 한 번도 안
    돌아간다** — 표본이 무엇을 확인해 주는지가 뒤집힌다.

    n 이 유형 수보다 작으면 전부는 못 담으므로, 그때는 개수가 적은(=희귀한) 유형부터
    채운다. 흔한 유형은 어차피 다른 실행에서 반복해서 뽑힌다.
    """
    by_kind = defaultdict(list)
    for sc in scenarios:
        by_kind[sc["kind"]].append(sc)
    for group in by_kind.values():
        rng.shuffle(group)

    # 희귀한 유형부터 1개씩
    kinds = sorted(by_kind, key=lambda k: (len(by_kind[k]), k))
    picked, cursor = [], {k: 0 for k in kinds}
    for k in kinds:
        if len(picked) >= n:
            break
        picked.append(by_kind[k][0])
        cursor[k] = 1

    # 남는 자리는 개수 비례로 라운드로빈
    while len(picked) < n:
        added = False
        for k in sorted(kinds, key=lambda k: -len(by_kind[k])):
            if len(picked) >= n:
                break
            if cursor[k] < len(by_kind[k]):
                picked.append(by_kind[k][cursor[k]])
                cursor[k] += 1
                added = True
        if not added:
            break
    return picked


def new_stats():
    return {
        "route_ok": 0, "route_n": 0, "jga_ok": 0, "jga_n": 0,
        "tp": 0, "fp": 0, "fn": 0,
        "hit5_ok": 0, "hit5_n": 0, "r5_sum": 0.0, "r5_n": 0, "mrr_sum": 0.0,
        "fab_n": 0, "fab_bad": 0,
        "rel_hit": 0, "rel_n": 0,
        "faith_ok": 0, "faith_n": 0, "faith_turns": 0, "faith_bad_turns": 0, "faith_noclaim": 0,
        "chk_llm_ok": 0, "chk_llm_n": 0, "nocard_ok": 0, "nocard_n": 0, "chk_det_ok": 0, "chk_det_n": 0,
        "gen_ms": [],
        "kind": defaultdict(lambda: {"route_ok": 0, "route_n": 0, "jga_ok": 0, "jga_n": 0,
                                     "hit5_ok": 0, "hit5_n": 0, "r5_sum": 0.0, "r5_n": 0,
                                     "mrr_sum": 0.0, "chk_ok": 0, "chk_n": 0}),
        "depth": defaultdict(lambda: {"ok": 0, "n": 0}),
        "confusion": Counter(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", default=None,
                    help="--dump 로 남긴 JSONL 을 읽어 관련성·충실성·날조만 다시 잰다. 서버·생성 불필요")
    ap.add_argument("--dump", default=None,
                    help="턴별 (질문·답변·컨텍스트 카드·정답) 을 JSONL 로 남긴다. 생성 없이 채점 기준만 바꿔 다시 잴 수 있게")
    ap.add_argument("--generate", action="store_true",
                    help="실제로 답변을 생성해 체크리스트까지 채점한다(턴당 ~10초)")
    ap.add_argument("--sample", type=int, default=0,
                    help="시나리오를 N개만 (유형별 층화 추출). 21종을 다 담으려면 25 이상")
    ap.add_argument("--repeat", type=int, default=1, help="k회 반복해 pass^k 를 낸다")
    ap.add_argument("--verbose", action="store_true", help="실패 건을 전부 출력")
    ap.add_argument("--seed", type=int, default=SEED,
                    help="시나리오 생성 seed. 기본 42 는 개발하면서 계속 보던 셋이라, "
                         "다른 값을 주면 **한 번도 안 본 시나리오**로 검증할 수 있다"
                         "(held-out). 코드를 시험에 맞춰 짠 게 아닌지 확인하는 용도")
    ap.add_argument("--latency", action="store_true",
                    help="생성 시간을 함께 출력한다. **실기기 지연이 아니라** LLM 서버를 "
                         "띄운 데스크톱 성능이므로 성능 지표로 인용하지 말 것. "
                         "같은 환경 안에서의 회귀 감지용")
    args = ap.parse_args()

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    if args.rescore:
        rescore_from_dump(args.rescore, cards)
        return
    contacts = build_contact_index(cards)
    value_index = build_value_index(cards)
    dump_fh = open(args.dump, "w", encoding="utf-8") if args.dump else None
    # 벡터가 지금 카드와 맞는지 먼저 본다. 안 맞으면 시맨틱이 옛날 내용으로
    # 돌아 지표가 조용히 틀어진다(id 는 그대로라 다른 검사로는 안 잡힌다).
    _st, _msg = _cfp.check_stamp(CARDS_PATH.parent / _cfp.STAMP_NAME, cards)
    if _st != "ok":
        print(_cfp.banner(_st, _msg), flush=True)

    scenarios = build_scenarios(cards, random.Random(args.seed))
    if args.sample and args.sample < len(scenarios):
        scenarios = stratified_sample(scenarios, args.sample, random.Random(args.seed))

    dry_run = not args.generate
    try:
        ask("워밍업", [], None, [], None, True)
    except Exception as e:  # noqa: BLE001
        print(f"[err] 서버에 연결하지 못했습니다({e}).")
        print("      python scripts/hybrid_server.py 를 먼저 띄우세요.")
        return 1

    n_turns = sum(len(s["turns"]) for s in scenarios)
    mode = "생성 채점" if args.generate else "dry-run — 생성 없음"
    print(f"\n시나리오 {len(scenarios)}개 / 턴 {n_turns}개  ({mode}, {args.repeat}회 반복)")

    stats = new_stats()
    stats["gap"] = new_stats()
    failures, gap_failures = [], []
    always_pass = None
    t0 = time.time()
    for rep in range(args.repeat):
        passes = run_pass(scenarios, dry_run, stats, failures, gap_failures, contacts,
                          value_index=value_index, dump=dump_fh)
        s = {i for i, ok in passes.items() if ok or scenarios[i].get("known_gap")}
        always_pass = s if always_pass is None else (always_pass & s)
    elapsed = time.time() - t0

    if stats.get("request_error"):
        print(f"\n[주의] 요청 실패 {stats['request_error']}건 — 서버 지연/중단으로 그만큼"
              " 시나리오가 덜 채점됐다. 지표를 그대로 인용하지 말 것.")

    def pct(a, b):
        return f"{a / b:.3f}" if b else "  -  "

    # --- 지표를 정직하게 읽히도록 표시를 붙인다 -------------------------------
    # 자체 감사에서 나온 것들이다. 팀원 지표(Slot Accuracy)를 "JGA 가 1.000 이면 중복"
    # 이라고 걸렀는데, 같은 잣대를 대면 **우리 지표도 절반이 걸린다**. 숫자를 지우는
    # 대신 한계를 같이 찍는다 — 지우면 회귀했을 때 진단할 근거가 사라진다.
    def ceiling(v, n):
        """천장에 붙은 지표는 '좋다'가 아니라 '안 나빠졌다'만 말한다."""
        return "   <- 천장, 회귀 탐지용" if n and v >= n else ""

    def power(n, need=30):
        """표본이 작으면 1건이 몇 %p 인지 같이 보여준다."""
        return f"   [표본 {n} — 1건이 {100 / n:.0f}%p]" if n and n < need else ""

    print("\n[1~3층 — 생성 불필요]")
    print(f"  라우팅 정확도   {pct(stats['route_ok'], stats['route_n'])}  ({stats['route_ok']}/{stats['route_n']})"
          f"{ceiling(stats['route_ok'], stats['route_n'])}")
    print(f"  JGA            {pct(stats['jga_ok'], stats['jga_n'])}  ({stats['jga_ok']}/{stats['jga_n']})"
          f"{ceiling(stats['jga_ok'], stats['jga_n'])}")
    prec = stats["tp"] / (stats["tp"] + stats["fp"]) if stats["tp"] + stats["fp"] else 0.0
    rec = stats["tp"] / (stats["tp"] + stats["fn"]) if stats["tp"] + stats["fn"] else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    # 슬롯 P/R/F1 은 JGA 가 1 아래로 내려갔을 때 **어디가** 틀렸는지 분해하는 용도다.
    # JGA 가 만점이면 이 셋도 필연적으로 만점이라 같은 사실의 네 번째 보고가 된다 —
    # 팀원의 Slot Accuracy 를 거른 것과 같은 이유이므로 우리 것도 그때만 찍는다.
    if stats["jga_ok"] < stats["jga_n"]:
        print(f"  슬롯 P/R/F1     {prec:.3f} / {rec:.3f} / {f1:.3f}   (JGA 실패분 분해)")
    print(f"  턴별 Hit@5     {pct(stats['hit5_ok'], stats['hit5_n'])}  ({stats['hit5_ok']}/{stats['hit5_n']})"
          f"   <- 아래 셋은 같은 사실을 셋으로 본다. 헤드라인은 하나만 쓸 것")
    n5 = stats["r5_n"] or 1
    print(f"  턴별 R@5       {stats['r5_sum'] / n5:.3f}  (분모 min(정답수,5) — eval_search.py 와 같은 공식)")
    print(f"  턴별 MRR       {stats['mrr_sum'] / n5:.3f}")

    if args.generate:
        print("\n[4~5층 — 생성 필요]")
        print(f"  체크리스트(LLM 턴)   {pct(stats['chk_llm_ok'], stats['chk_llm_n'])}"
              f"  ({stats['chk_llm_ok']}/{stats['chk_llm_n']})   <- 주 지표")
        # 체크리스트(결정적 턴)은 **동어반복**이라 헤드라인에서 뺐다 — 답변이 고정 문자열
        # 이므로 라우팅만 맞으면 반드시 통과한다. 즉 라우팅 정확도를 다시 세는 것이다.
        # 실패했을 때만 찍는다(그때는 라우팅이 이미 실패로 잡혔다는 뜻이라 교차 확인용).
        if stats["chk_det_ok"] < stats["chk_det_n"]:
            print(f"  체크리스트(결정적 턴) {pct(stats['chk_det_ok'], stats['chk_det_n'])}"
                  f"  ({stats['chk_det_ok']}/{stats['chk_det_n']})   * 라우팅 실패의 반영")
        if stats["rel_n"]:
            print(f"  답변 관련성(Relevancy)  {stats['rel_hit'] / stats['rel_n']:.3f}"
                  f"  ({stats['rel_hit']}/{stats['rel_n']} 요청 필드)   * 물은 속성 **유형**의 값을 답했나")
        if stats["faith_n"]:
            print(f"  답변 충실성(Faithfulness) {stats['faith_ok'] / stats['faith_n']:.3f}"
                  f"  ({stats['faith_ok']}/{stats['faith_n']} 주장 · 턴 {stats['faith_turns']}개, "
                  f"컨텍스트 밖 값 있는 턴 {stats['faith_bad_turns']}개)   * 값이 그 턴 카드 안에 있나")
            if stats["faith_noclaim"]:
                print(f"    (주장 추출 0건이라 제외한 LLM 턴 {stats['faith_noclaim']}개)")
        if stats.get("fab_n"):
            ok = stats["fab_n"] - stats["fab_bad"]
            print(f"  연락처 날조 없음        {pct(ok, stats['fab_n'])}"
                  f"  ({ok}/{stats['fab_n']})   * 답변의 전화·이메일이 1000장 안에 실재하나")
        if stats["nocard_n"]:
            print(f"  무관 요청 카드 억제      {pct(stats['nocard_ok'], stats['nocard_n'])}"
                  f"  ({stats['nocard_ok']}/{stats['nocard_n']}){power(stats['nocard_n'])}")
        if args.repeat > 1:
            print(f"  pass^{args.repeat}              {pct(len(always_pass), len(scenarios))}"
                  f"  ({len(always_pass)}/{len(scenarios)} 시나리오가 {args.repeat}번 모두 통과)"
                  f"{power(len(scenarios))}")
        # 생성 시간은 기본 출력에서 뺀다. --latency 로만 본다.
        #
        # 이 값은 hybrid_server 가 9379 포트(litert-lm serve)로 HTTP 왕복하는 시간이라
        # **그 서버를 띄운 데스크톱/노트북의 성능**이다. 우리 제품은 온디바이스 앱이고
        # 목표 기기는 갤럭시 S21급인데, ARM+델리게이트·메모리 압박·발열 스로틀링 때문에
        # 값이 전혀 다르다. 실기기 지연은 이 도구로 **측정할 수 없다**(폰은 앱 안의
        # LiteRtLmChatEngine 이 네이티브로 모델을 직접 로드한다).
        # 성능 지표로 인용되면 안 되므로 기본 출력에서 뺐다.
        #
        # 그래도 지우지 않은 이유: **같은 환경 안에서의 회귀 감지**에는 유효하다.
        # 실제로 "후보 0장인데 LLM 을 부르던" 버그를 이 값으로 잡았다(10초 -> 0.2초).
        # 프롬프트가 커지거나 불필요한 호출이 생기면 여기서 바로 드러난다.
        if args.latency and stats["gen_ms"]:
            g = sorted(stats["gen_ms"])

            def q(f):
                return g[min(len(g) - 1, max(0, int(round(f * (len(g) - 1)))))] / 1000

            # 평균만 보면 이상치에 끌려간다(실측: 평균 17.4초인데 P95 13.4초 —
            # 174건 중 9건이 ~98초였다. 웜업/부하 때문이지 평상시 지연이 아니다).
            print(f"  [개발환경 전용 · 실기기 아님] 생성 시간 중앙/평균/P95/최대   "
                  f"{q(0.5):.1f} / {sum(g)/len(g)/1000:.1f} / {q(0.95):.1f} / {g[-1]/1000:.1f}초")

    print("\n[유형별]  (n = 채점된 턴 수)")
    header = f"  {'유형':<18} {'라우팅':>13} {'JGA':>13} {'Hit@5':>13}"
    if args.generate:
        header += f" {'체크리스트':>13}"
    print(header)
    for kind, s in sorted(stats["kind"].items()):
        line = (f"  {kind:<18} {pct(s['route_ok'], s['route_n']):>7} n={s['route_n']:<4}"
                f" {pct(s['jga_ok'], s['jga_n']):>7} n={s['jga_n']:<4}"
                f" {pct(s['hit5_ok'], s['hit5_n']):>7} n={s['hit5_n']:<4}")
        if args.generate:
            line += f" {pct(s['chk_ok'], s['chk_n']):>7} n={s['chk_n']:<4}"
        print(line)

    print("\n[대화 길이별 — 시나리오 전 턴의 라우팅이 다 맞은 비율]")
    for d in sorted(stats["depth"]):
        s = stats["depth"][d]
        print(f"  {d}턴   {pct(s['ok'], s['n'])}  ({s['ok']}/{s['n']})")
    print("  * n 이 작으면 1~2개 차이로 순위를 매기지 말 것.")

    if stats["confusion"]:
        print("\n[라우팅 오분류]")
        for (want, got), n in stats["confusion"].most_common(10):
            print(f"  {want} -> {got}  {n}건")

    if failures:
        print(f"\n[실패 {len(failures)}건]")
        shown = failures if args.verbose else failures[:15]
        for kind, depth, q, why in shown:
            print(f"  [{kind}] {depth}턴  {q}\n      {why}")
        if not args.verbose and len(failures) > 15:
            print(f"  … 외 {len(failures) - 15}건 (--verbose 로 전부 보기)")

    print(f"\n실행 시간 {elapsed:.0f}초")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
