"""멀티턴 평가 — 라우팅 / JGA(슬롯) / 턴별 R@5 / 체크리스트 통과율 / pass^k.

왜 이 지표들인가
----------------
이 시스템은 답변의 상당수가 **LLM을 거치지 않는다**(카운트·기권·문맥참조·자기참조).
23문항 라이브에서 8개(35%)가 결정적 경로였다. 그런 턴은 답변이 고정 문자열이라
답변 텍스트를 채점해 봐야 라우팅만 맞으면 자동 통과다 — 정보가 없다.
반대로 실제로 겪은 실패는 전부 '어느 경로로 갔나'였다
(판교 디자이너가 완화 경로로 새서 오답, 개념형이 카운트 형식으로 새서 가짜 총계).

그래서 **주 지표는 라우팅 + JGA + 턴별 R@5**(1~3층)이고, 답변 텍스트 채점은
**LLM이 실제로 생성한 턴에만** 매기는 보조 지표(4~5층)다. 전체를 뭉쳐 하나의
통과율로 내면 고정 문자열 턴이 숫자를 채워서 어려운 턴의 성능을 가린다.

두 가지 모드
------------
    python scripts/eval_multiturn.py
        1~3층. 생성을 건너뛰므로(dry-run) 180턴이 ~30초. 매 변경마다 돌리는 회귀망.

    python scripts/eval_multiturn.py --generate --sample 20
        4~5층. 실제로 답변을 만들어 체크리스트로 채점한다. 턴당 ~10초라 표본을 쓴다.
        --repeat 3 을 주면 pass^3(3번 다 통과해야 인정)까지 낸다 — 샘플링 흔들림 때문에
        1~2개 차이로 순위를 매기면 안 된다는 문제를 지표에 반영하는 방법이다.

지표
----
- **라우팅 정확도** — 의도한 경로로 갔는가
  (search / abstain / filtered_count / total_count / context_answer / followup / self_reference)
- **JGA (Joint Goal Accuracy)** — 그 턴의 **모든** 슬롯이 정답과 정확히 일치한 턴의 비율.
  슬롯은 focus 인물 + 필드 조건(이름/직함/지역). 대화상태추적의 표준 지표를 우리 슬롯에 적용.
- **슬롯 F1** — JGA는 하나만 틀려도 0이라 부분 점수를 같이 본다.
- **턴별 R@5** — 정답 카드가 상위 5개 후보에 있는가.
- **체크리스트 통과율** — 답변에 필수 문자열이 있고 금지 문자열이 없는가(LLM 턴만).
- **pass^k** — 같은 시나리오를 k번 돌려 k번 다 통과한 비율.

시나리오는 `cards_eval1000.json` 에서 생성한다. 외부 대화 코퍼스를 못 쓰는 이유는
거기에 우리 카드가 없어서 "이 턴의 정답"을 정의할 수 없기 때문이다.
데이터를 다시 만들면 시나리오도 같이 갱신되므로 낡지 않는다.
"""
from __future__ import annotations

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
            turn(f"{c['name']}씨 회사가 어디야?", "search", slots, gold,
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn("주소는?", "search", slots, gold,
                 must=[address_variants(c["address"])], must_not=REJECTIONS),
            turn("직급은?", "search", slots, gold, must=[[c["title"]]], must_not=REJECTIONS),
            turn("부서는?", "search", slots, gold, must=[[c["department"]]], must_not=REJECTIONS),
        ])

    # (2) 6턴 장문 — 최근 창(메시지 8개 = 4턴)을 넘겨 historyDigest 로 접히는 구간
    for c in pool[25:35]:
        gold, slots = [c["id"]], person_slots(c)
        tail = re.sub(r"\D", "", c.get("phone") or "")[-4:]
        add("6턴 장문", [
            turn(f"{c['name']}씨 회사가 어디야?", "search", slots, gold,
                 must=[company_variants(c["company"])], must_not=REJECTIONS),
            turn("주소는?", "search", slots, gold,
                 must=[address_variants(c["address"])], must_not=REJECTIONS),
            turn("직급은?", "search", slots, gold, must=[[c["title"]]], must_not=REJECTIONS),
            turn("부서는?", "search", slots, gold, must=[[c["department"]]], must_not=REJECTIONS),
            turn("이메일은?", "search", slots, gold, must=[[c["email"]]], must_not=REJECTIONS),
            turn("전화번호는?", "search", slots, gold, must=[[c["phone"], tail]], must_not=REJECTIONS),
        ])

    # (3) 주제 전환 — 다른 사람으로 갔다가 처음 사람으로 돌아온다(focus 가 따라와야 한다)
    for a, b in zip(pool[35:43], pool[43:51]):
        add("주제 전환", [
            turn(f"{a['name']}씨 회사가 어디야?", "search", person_slots(a), [a["id"]],
                 must=[company_variants(a["company"])], must_not=REJECTIONS),
            turn(f"{b['name']}씨는?", "search", person_slots(b), [b["id"]],
                 must=[company_variants(b["company"])], must_not=REJECTIONS),
            turn(f"{a['name']}씨 부서는?", "search", person_slots(a), [a["id"]],
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
            turn(f"{loc}에 있는 {title} 찾아줘", "search",
                 {"names": [], "titles": [title], "locations": [loc]}, ids,
                 must=[want], must_not=REJECTIONS),
            turn("그 사람들 회사 알려줘", "followup", None, ids, must_not=REJECTIONS),
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
        present = {(c.get("title") or "").strip() for c in loc_cards}
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
            turn("아까 말한 회사 뭐였지", "context_answer"),
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
    add("전체 카운트", [turn("전체 몇 장이야?", "total_count", must=[[f"{len(cards)}명"]])])
    add("자기참조", [turn("너는 누구야?", "self_reference", must=[["어시스턴트"]])])
    add("기권(전화)", [turn("010-0000-0000", "abstain", must=[REJECTIONS])])

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

def ask(question, history, focus, prev_ids, memory, dry_run):
    payload = json.dumps({
        "question": question, "history": history, "focus": focus,
        "prev_card_ids": prev_ids, "conversation_memory": memory,
        "dry_run": dry_run,
    }, ensure_ascii=False).encode()
    req = urllib.request.Request(ENDPOINT, data=payload,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read().decode())


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


def run_pass(scenarios, dry_run, stats, failures, gap_failures):
    """시나리오 전체를 1회 실행하고 stats 를 채운다. 시나리오별 체크리스트 통과 여부를 돌려준다."""
    scenario_pass = {}
    for idx, sc in enumerate(scenarios):
        if dry_run and sc.get("generate_only"):
            continue
        history, focus, prev_ids, memory = [], None, [], None
        kind = sc["kind"]
        # 알려진 간극은 헤드라인 통계에서 빼고 따로 센다.
        st = stats["gap"] if sc.get("known_gap") else stats
        target_failures = gap_failures if sc.get("known_gap") else failures
        route_all_ok = True
        checks_all_ok = True
        for depth, t in enumerate(sc["turns"], start=1):
            res = ask(t["q"], history, focus, prev_ids, memory, dry_run)
            answer = res.get("answer") or ""
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
                st["r5_n"] += 1
                st["kind"][kind]["r5_n"] += 1
                if any(g in (res.get("card_ids") or [])[:5] for g in t["gold"]):
                    st["r5_ok"] += 1
                    st["kind"][kind]["r5_ok"] += 1
                else:
                    target_failures.append((kind, depth, t["q"], "정답 카드가 top-5 에 없음"))

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


def new_stats():
    return {
        "route_ok": 0, "route_n": 0, "jga_ok": 0, "jga_n": 0,
        "tp": 0, "fp": 0, "fn": 0, "r5_ok": 0, "r5_n": 0,
        "chk_llm_ok": 0, "chk_llm_n": 0, "nocard_ok": 0, "nocard_n": 0, "chk_det_ok": 0, "chk_det_n": 0,
        "gen_ms": [],
        "kind": defaultdict(lambda: {"route_ok": 0, "route_n": 0, "jga_ok": 0, "jga_n": 0,
                                     "r5_ok": 0, "r5_n": 0, "chk_ok": 0, "chk_n": 0}),
        "depth": defaultdict(lambda: {"ok": 0, "n": 0}),
        "confusion": Counter(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true",
                    help="실제로 답변을 생성해 체크리스트까지 채점한다(턴당 ~10초)")
    ap.add_argument("--sample", type=int, default=0, help="시나리오를 N개만 무작위 표본")
    ap.add_argument("--repeat", type=int, default=1, help="k회 반복해 pass^k 를 낸다")
    ap.add_argument("--verbose", action="store_true", help="실패 건을 전부 출력")
    args = ap.parse_args()

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    scenarios = build_scenarios(cards, random.Random(SEED))
    if args.sample and args.sample < len(scenarios):
        scenarios = random.Random(SEED).sample(scenarios, args.sample)

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
        passes = run_pass(scenarios, dry_run, stats, failures, gap_failures)
        s = {i for i, ok in passes.items() if ok or scenarios[i].get("known_gap")}
        always_pass = s if always_pass is None else (always_pass & s)
    elapsed = time.time() - t0

    def pct(a, b):
        return f"{a / b:.3f}" if b else "  -  "

    print("\n[1~3층 — 생성 불필요]")
    print(f"  라우팅 정확도   {pct(stats['route_ok'], stats['route_n'])}  ({stats['route_ok']}/{stats['route_n']})")
    print(f"  JGA            {pct(stats['jga_ok'], stats['jga_n'])}  ({stats['jga_ok']}/{stats['jga_n']})")
    prec = stats["tp"] / (stats["tp"] + stats["fp"]) if stats["tp"] + stats["fp"] else 0.0
    rec = stats["tp"] / (stats["tp"] + stats["fn"]) if stats["tp"] + stats["fn"] else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"  슬롯 P/R/F1     {prec:.3f} / {rec:.3f} / {f1:.3f}")
    print(f"  턴별 R@5       {pct(stats['r5_ok'], stats['r5_n'])}  ({stats['r5_ok']}/{stats['r5_n']})")

    if args.generate:
        print("\n[4~5층 — 생성 필요]")
        print(f"  체크리스트(LLM 턴)   {pct(stats['chk_llm_ok'], stats['chk_llm_n'])}"
              f"  ({stats['chk_llm_ok']}/{stats['chk_llm_n']})   <- 주 지표")
        print(f"  체크리스트(결정적 턴) {pct(stats['chk_det_ok'], stats['chk_det_n'])}"
              f"  ({stats['chk_det_ok']}/{stats['chk_det_n']})   * 고정 문자열이라 라우팅만 맞으면 통과")
        if stats["nocard_n"]:
            print(f"  무관 요청 카드 억제      {pct(stats['nocard_ok'], stats['nocard_n'])}"
                  f"  ({stats['nocard_ok']}/{stats['nocard_n']})")
        if args.repeat > 1:
            print(f"  pass^{args.repeat}              {pct(len(always_pass), len(scenarios))}"
                  f"  ({len(always_pass)}/{len(scenarios)} 시나리오가 {args.repeat}번 모두 통과)")
        if stats["gen_ms"]:
            g = sorted(stats["gen_ms"])
            def q(f):
                return g[min(len(g) - 1, max(0, int(round(f * (len(g) - 1)))))] / 1000
            # 평균만 보면 이상치에 끌려간다(실측: 평균 17.4초인데 P95 13.4초 —
            # 174건 중 9건이 ~98초였다. 웜업/부하 때문이지 평상시 지연이 아니다).
            # 중앙값과 최댓값을 같이 찍어서 그런 상황을 바로 알아보게 한다.
            print(f"  생성 시간 중앙/평균/P95/최대   "
                  f"{q(0.5):.1f} / {sum(g)/len(g)/1000:.1f} / {q(0.95):.1f} / {g[-1]/1000:.1f}초")

    print("\n[유형별]  (n = 채점된 턴 수)")
    header = f"  {'유형':<18} {'라우팅':>13} {'JGA':>13} {'R@5':>13}"
    if args.generate:
        header += f" {'체크리스트':>13}"
    print(header)
    for kind, s in sorted(stats["kind"].items()):
        line = (f"  {kind:<18} {pct(s['route_ok'], s['route_n']):>7} n={s['route_n']:<4}"
                f" {pct(s['jga_ok'], s['jga_n']):>7} n={s['jga_n']:<4}"
                f" {pct(s['r5_ok'], s['r5_n']):>7} n={s['r5_n']:<4}")
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
