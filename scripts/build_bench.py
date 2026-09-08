"""
통합 멀티턴 벤치마크 **출제 도구**.

이 파일은 채점표가 아니라 **시험지를 찍어내는 기계**다. 한 번 찍어서 동결하고
(`bench/hjp_multiturn_v1.json`), 그 뒤로는 동결본만 채점한다. 생성기를 고쳐도
동결본은 안 바뀌므로 **시간에 걸친 비교**가 성립한다.

왜 새로 만드나 — 기존 두 방식은 장점이 서로 다른 층에 있었다.

  외부 제작 고정셋(Final50 v3)의 장점 = **시나리오 구조**
    · 채점 대상 턴이 정확히 하나. 나머지는 전부 설정·방해 문맥이다.
      -> 난이도를 '거리'와 '방해 인물 수'로 **조절**할 수 있다.
    · 지시어가 **최근이 아닌** 인물을 가리킨다(그냥 최근 focus 를 쓰면 틀리게 설계).
    · 답할 수 없는 문제는 **실제로 비어 있는 카드**로만 만든다.

  우리 생성기의 장점 = **생산 방식**
    · 정답을 카드 데이터에서 자동으로 끌어낸다(손으로 안 써도 된다).
    · 발화 풀로 같은 뜻을 여러 말투로 낸다(말투 하나만 되는 것을 '된다'고 말하지 않기 위해).
    · 유형을 넓게 깐다.

구조는 앞에서, 생산은 뒤에서 가져왔다.

**난이도는 라벨이 아니라 계산값이다.** 아래 다섯 개에서 유도한다 —
그래야 "이건 어려운 문제야" 가 감이 아니라 재현 가능한 정의가 된다.

  distance     근거를 준 턴과 채점 턴 사이의 거리(턴 수)
  distractors  그 사이에 등장한 **다른 실제 인물** 수
  reference    채점 턴이 대상을 어떻게 가리키나 (이름 / 대명사 / 무명 순서 / 정정)
  answerable   답이 있는가 (없으면 '없다'고 말해야 한다)
  ops          답까지 필요한 좁히기·선택 연산 수

가드레일(외부 고정셋의 것을 그대로 계승한다):
  · 모든 인물과 정답은 cards 에 실제로 존재해야 한다. 제3자 사실을 지어내지 않는다.
  · 시나리오마다 채점 대상 턴은 **정확히 하나**다.
  · 정정은 명시적인 정정 표현을 포함한다.
  · 장거리 재활성화는 대상 이후에 **다른 실제 인물의 방해 턴**을 포함한다.
  · 지시어 참조는 **최근이 아닌** 인물을 가리킨다.
  · 답할 수 없는 문제는 그 카드의 그 칸이 **실제로 비어 있을 때만** 만든다.

사용:
  python scripts/build_bench.py --out bench/hjp_multiturn_v1.json
  python scripts/build_bench.py --out ... --scenarios 120 --holdout 0.2 --seed 20260826
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import card_fingerprint as cfp  # noqa: E402

CARDS_PATH = ROOT / "data" / "cards_eval1000.json"

# 거절 표현 — '없다'고 말해야 하는 문제에서 must 로, 답이 있는 문제에서 must_not 으로 쓴다.
# 채점기(eval_multiturn)와 **같은 목록을 쓴다**. 따로 적었더니 이미 어긋나 있었다
# (여기만 "정보가 없" 이 있었다). 시험지의 정답 기준과 채점기의 판정이 다르면
# 어느 쪽이 맞는지 아무도 모른다.
REJECTIONS = list(ev.REJECTIONS)

FIELD_NOUN = {
    "company": "회사", "title": "직급", "department": "부서",
    "phone": "전화번호", "email": "이메일", "address": "주소",
}

# ── 발화 풀 ──────────────────────────────────────────────────────────────────
# 같은 뜻을 여러 말투로 낸다. 말투 하나만 되는 것을 "된다" 고 말하지 않기 위해서다
# (실측: 생략형 후속 판정이 startsWith 라 속성 명사로 시작해야만 인정됐고,
#  그 한 가지가 안 되자 대화가 통째로 무너졌다).
ASK_NAMED = {
    "company": ["{n}씨 회사가 어디야?", "{n}씨 어느 회사 다녀?", "{n}씨 회사 알려줘",
                "{n}씨는 어디 소속이야?"],
    "title": ["{n}씨 직급은?", "{n}씨 직함이 뭐야?", "{n}씨 직책 알려줘"],
    "department": ["{n}씨 부서는?", "{n}씨 어느 부서야?", "{n}씨 부서 알려줘"],
    "phone": ["{n}씨 전화번호는?", "{n}씨 연락처 알려줘", "{n}씨 번호 뭐야?"],
    "email": ["{n}씨 이메일은?", "{n}씨 메일 주소는?", "{n}씨 이메일 알려줘"],
    "address": ["{n}씨 주소는?", "{n}씨 주소가 어떻게 돼?", "{n}씨 주소 알려줘"],
}
# 이름을 대지 않고 **앞서 나온** 사람을 가리킨다. 최근 focus 를 쓰면 틀린다.
ASK_ORDINAL = {
    "company": ["처음 언급한 사람 회사는?", "맨 처음 물어본 사람 회사 알려줘",
                "첫 번째로 물어본 사람 어느 회사야?"],
    "title": ["처음 언급한 사람 직급은?", "맨 처음 물어본 사람 직함 알려줘"],
    "department": ["처음 언급한 사람 부서는?", "맨 처음 물어본 사람 부서 알려줘"],
    "phone": ["처음 언급한 사람 전화번호는?", "맨 처음 물어본 사람 연락처 알려줘"],
    "email": ["처음 언급한 사람 이메일은?", "맨 처음 물어본 사람 메일 주소는?"],
    "address": ["처음 언급한 사람 주소는?", "맨 처음 물어본 사람 주소 알려줘"],
}
# 대명사 — 직전 사람이 아니라 **그 앞** 사람을 가리키게 배치한다.
ASK_PRONOUN = {
    "company": ["그 사람 회사는?", "그분 회사 어디야?"],
    "title": ["그 사람 직급은?", "그분 직함이 뭐야?"],
    "department": ["그 사람 부서는?", "그분 부서 알려줘"],
    "phone": ["그 사람 전화번호는?", "그분 연락처 알려줘"],
    "email": ["그 사람 이메일은?", "그분 메일 주소는?"],
    "address": ["그 사람 주소는?", "그분 주소 알려줘"],
}
CORRECT_TARGET = ["아니 {a}씨 말고 {b}씨 {f} 알려줘", "{a}씨가 아니라 {b}씨 {f}야",
                  "{b}씨 {f} 말한 거야. {a}씨 말고"]

# **명함에 없는 사람** 이름. 실존 카드의 성 + 흔한 이름을 붙여 그럴듯하게 만들되,
# cards 에 그 이름이 없는 것만 쓴다(생성 시 검증한다).
#
# 왜 필요한가: 답 없는 문제가 "있는 사람의 빈 칸" 뿐이면 미등록 연락처 지표가 시험이
# 안 된다 — 실재 인물만 물으니 지어낼 유인이 없고, 실제로 v1.1 에서 1.000 이 나왔다.
# 없는 사람의 전화·이메일을 물어야 **지어내는지**를 실제로 본다.
ABSENT_GIVEN = ["도현", "서준", "지호", "예준", "하준", "주원", "지후", "준서",
                "서연", "지우", "하은", "서윤", "지유", "채원", "수아", "다은"]
ASK_ABSENT = {
    "phone": ["{n}씨 전화번호 알려줘", "{n}씨 연락처는?"],
    "email": ["{n}씨 이메일 알려줘", "{n}씨 메일 주소는?"],
}


def pick(rng, pool, **kw):
    return rng.choice(pool).format(**kw)


def variants(field, value):
    """표기 변형 — 채점에서 '주식회사 A' 와 'A' 를 같은 답으로 본다."""
    v = (value or "").strip()
    if not v:
        return []
    out = [v]
    if field == "company":
        core = v
        for w in ("주식회사", "유한회사", "(주)", "(유)", "㈜"):
            core = core.replace(w, "")
        core = core.strip()
        if len(core) >= 2 and core != v:
            out.append(core)
    if field == "phone":
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) >= 9:
            out.append(digits[-4:])
    if field == "address":
        parts = v.split()
        if len(parts) >= 2:
            out.append(" ".join(parts[-2:]))
    return out


# ── 난이도 ───────────────────────────────────────────────────────────────────
REF_COST = {"named": 0, "pronoun": 2, "ordinal": 3, "correction": 3}


def difficulty(distance, distractors, reference, answerable, ops):
    """
    다섯 값에서 난이도를 **계산**한다. 라벨을 손으로 붙이지 않는 이유는,
    붙이는 사람의 감이 곧 기준이 되어 버려서 나중에 재현도 반박도 안 되기 때문이다.

    가중치는 '무엇이 실제로 우리를 깨뜨렸나' 에서 왔다:
      · 이름을 안 대는 참조(대명사·순서·정정)가 가장 자주 깨졌다 -> 2~3점
      · 최근 4턴 원문 창(메시지 8개)을 넘어가면 요약으로 접혀 정보가 준다 -> 거리 5부터 가산
      · 방해 인물은 focus 를 빼앗는다 -> 2명마다 1점.
        **단 대상을 이름으로 부르면 세지 않는다** — 이름이 있으면 참조를 풀 필요가
        없어서 방해가 실제로 방해가 아니다. 처음엔 무조건 셌는데, 그러면 "6턴 대화
        끝에 이름 대고 묻기" 가 L2 로 잡혀 **쉬운 문제가 어려운 칸을 차지**했다.
      · '없다고 말하기' -> 2점. 외부 고정셋에서 빈 칸 기권이 5/10 으로 가장 낮았다.
        옆 칸 값으로 때우는 실패가 잦아 이름 참조만큼 어렵다고 본다.
      · 좁히기 단계마다 앞 조건이 새는지 봐야 한다 -> 단계당 1점
    """
    score = REF_COST.get(reference, 0)
    score += max(0, distance - 4) // 2      # 원문 창 밖으로 나간 만큼
    if reference != "named":
        score += distractors // 2
    score += 0 if answerable else 2
    score += ops
    if score <= 1:
        return "L1", score
    if score <= 3:
        return "L2", score
    if score <= 5:
        return "L3", score
    return "L4", score


def turn(text, *, target=False, must=None, must_not=None, gold=None, note=None):
    t = {"user": text, "target": bool(target)}
    if must is not None:
        t["must"] = must
    if must_not is not None:
        t["must_not"] = must_not
    if gold is not None:
        t["gold"] = gold
    if note:
        t["note"] = note
    return t


def filler_turn(rng, card, field):
    """방해 턴 — **실재하는 다른 사람**에게 실제로 답이 있는 것을 묻는다."""
    return turn(pick(rng, ASK_NAMED[field], n=card["name"]))

# ── 깊이 층 ──────────────────────────────────────────────────────────────────
# **채점 턴이 몇 번째 턴인가.** 거리(distance)와는 다른 값이다 — 깊이 10 이어도
# 바로 앞 턴이 근거면 거리는 1 이다. 둘을 따로 제어해야 "대화가 길어서 틀렸나,
# 근거에서 멀어져서 틀렸나" 를 가를 수 있다.
#
# D 층(6턴째 이상)이 중요하다. 우리 시스템은 최근 4턴(메시지 8개)만 원문으로 넣고
# 그 앞은 요약으로 접는다. **그 경계 밖에서만 드러나는 실패**가 있다.
DEPTH_TIERS = {
    "A_1턴째": (1, 1),
    "B_2턴째": (2, 2),
    "C_3~5턴째": (3, 5),
    "D_6턴째+": (6, 16),
}

# 깊이 x 난이도 **교차 할당**. 한쪽만 층화하면 다른 쪽이 그 안에 숨는다 —
# 실제로 옛 시험지는 3턴째 이후가 전부 쉬운 유형이라 **깊어질수록 쉬워졌고**,
# 그래서 깊이별 표가 비단조로 나왔다(2턴째 최악, 3턴째+ 회복). 그 착시를 막는다.
#
# **비어 있는 칸은 결함이 아니라 사실이다.** 1턴째에는 문맥이 없으므로 '문맥 난이도'가
# 존재할 수 없다 — 이름을 대고 한 칸을 묻는 것과 빈 칸을 묻는 것 둘뿐이라 L1·L2 만 난다.
# 2턴째도 대명사가 성립하려면 최소 3턴이 필요해 L4 까지는 못 간다.
# 억지로 채우면 난이도 정의를 문제에 맞춰 비틀게 되므로, 못 만드는 칸은 비워 두고
# **실제로 만들어진 표를 그대로 보고**한다.
#
# **v1.2 에서 어려운 쪽으로 옮겼다.** v1.1 은 수정 후 120/120 만점이라 더 잴 것이 없었다 —
# 1.000 은 "완벽" 이 아니라 "이 시험지로는 더 못 잰다" 는 뜻이다. 일반적인 벤치마크의
# 난이도(멀티턴 상태추적 JGA 0.5~0.6, 검색 nDCG 0.4~0.5)에 견주면 우리가 지나치게 쉬웠다.
# 목표는 0.7~0.85 — 개선 여지가 보이면서 회귀도 잡히는 구간이다.
#
# L1(이름 명시)은 **회귀 탐지용으로만** 남긴다. 절제 실험에서 재작성을 다 꺼도 27/27
# 만점이었다 — 이 유형은 어떤 설정에서도 안 깨진다. 그래서 비중을 줄인다.
QUOTA = {
    "A_1턴째":   {"L1": 8,  "L2": 16, "L3": 0,  "L4": 0},
    "B_2턴째":   {"L1": 4,  "L2": 10, "L3": 20, "L4": 0},
    "C_3~5턴째": {"L1": 4,  "L2": 8,  "L3": 16, "L4": 16},
    "D_6턴째+":  {"L1": 2,  "L2": 4,  "L3": 12, "L4": 24},
}


def scale_quota(quota, total):
    """기본 표(합 120)를 원하는 규모로 비례 조정한다. 각 칸은 최소 1 을 유지한다."""
    base = sum(v for row in quota.values() for v in row.values())
    if total == base:
        return {d: dict(r) for d, r in quota.items()}
    out, acc = {}, 0
    cells = [(d, lv) for d in quota for lv in quota[d]]
    for d, lv in cells:
        n = max(1, round(quota[d][lv] * total / base))
        out.setdefault(d, {})[lv] = n
        acc += n
    # 반올림 오차는 가장 큰 칸에서 흡수한다.
    while acc != total:
        d, lv = max(cells, key=lambda c: out[c[0]][c[1]])
        step = 1 if acc < total else -1
        if out[d][lv] + step >= 1:
            out[d][lv] += step
            acc += step
        else:
            break
    return out


# ── 시나리오 제작기 ──────────────────────────────────────────────────────────
# 하나의 함수가 **모든** 시나리오를 만든다. 유형별로 따로 쓰지 않는 이유는,
# 유형을 손으로 늘리면 난이도가 유형에 딸려 들어가 교차 층화가 깨지기 때문이다.
# 대신 다섯 개의 손잡이(거리·방해·참조방식·답가능·연산수)로 모양을 만든다.

def make_scenario(rng, sid, cards, empty_by_field, depth, reference, answerable, ops,
                  distractor_target, unique_names=None):
    unique_names = unique_names if unique_names is not None else {c["name"] for c in cards}
    """
    가드레일(외부 고정셋에서 계승):
      · 모든 인물과 정답은 카드에 실재해야 한다. 제3자 사실을 지어내지 않는다.
      · 채점 대상 턴은 **정확히 하나**다.
      · 지시어 참조는 **최근이 아닌** 인물을 가리킨다.
      · 답할 수 없는 문제는 그 칸이 **실제로 비어 있는** 카드로만 만든다.
    """
    field = rng.choice(["company", "title", "department", "phone", "email", "address"])

    # 대상은 **이름이 고유한** 카드만. 기준선에서 '주정우' 가 두 장이라 전화번호 둘 중
    # 하나를 답했고 그게 실패로 찍혔다 — 모델 잘못이 아니라 문제가 모호한 것이다.
    # 동명이인 처리는 별도 유형(회귀용 생성 셋 '동명이인')에서 잰다.
    if not answerable:
        pool = [c for c in (empty_by_field.get(field) or []) if c["name"] in unique_names]
        if not pool:
            field = max(empty_by_field, key=lambda f: len(empty_by_field[f]))
            pool = [c for c in empty_by_field[field] if c["name"] in unique_names]
        target = rng.choice(pool)
    else:
        pool = [c for c in cards if (c.get(field) or "").strip() and c["name"] in unique_names]
        target = rng.choice(pool)

    # 방해 인물 — 대상과 다른 실재 인물. 이름이 겹치면 채점이 흐려지므로 배제한다.
    others = [c for c in cards
              if c["id"] != target["id"] and c["name"] != target["name"]
              and (c.get("company") or "").strip()]
    rng.shuffle(others)

    turns, evidence_depth = [], 1
    if reference == "named":
        # 대상을 이름으로 부른다. 앞선 턴들은 순수한 방해다.
        for i in range(depth - 1):
            turns.append(filler_turn(rng, others[i], "company"))
        ask = pick(rng, ASK_NAMED[field], n=target["name"])
        evidence_depth = depth
    elif reference == "pronoun":
        # 대명사는 **직전 사람이 아니라 그 앞** 사람을 가리켜야 한다.
        # 그냥 최근 focus 를 쓰면 맞는 문제는 대명사 해소를 재지 못한다.
        lead = max(1, depth - 2)
        for i in range(lead - 1):
            turns.append(filler_turn(rng, others[i], "company"))
        turns.append(turn(pick(rng, ASK_NAMED["company"], n=target["name"])))
        evidence_depth = len(turns)
        while len(turns) < depth - 1:
            turns.append(filler_turn(rng, others[len(turns)], "company"))
        ask = pick(rng, ASK_PRONOUN[field])
    elif reference == "ordinal":
        # 이름을 대지 않고 **처음 나온 사람**을 되살린다. 사이에 방해가 많을수록 어렵다.
        turns.append(turn(pick(rng, ASK_NAMED["company"], n=target["name"])))
        evidence_depth = 1
        while len(turns) < depth - 1:
            turns.append(filler_turn(rng, others[len(turns)], "company"))
        ask = pick(rng, ASK_ORDINAL[field])
    else:  # correction
        wrong = others[0]
        while len(turns) < depth - 2:
            turns.append(filler_turn(rng, others[len(turns) + 1], "company"))
        turns.append(turn(pick(rng, ASK_NAMED[field], n=wrong["name"])))
        evidence_depth = len(turns)
        ask = pick(rng, CORRECT_TARGET,
                   a=wrong["name"], b=target["name"], f=FIELD_NOUN[field])

    # 좁히기 연산 — 답 앞에 조건을 한 겹씩 더 씌운다.
    for _ in range(ops):
        turns.append(turn("그중에 " + (target.get("title") or "").split()[0] + "만"
                          if (target.get("title") or "").strip() else "그중에 첫 번째"))

    value = (target.get(field) or "").strip()
    if reference == "absent":
        # 명함에 없는 사람의 연락처를 묻는다. **없다고 말해야** 하고, 어떤 번호·메일도
        # 답에 나오면 안 된다(그건 지어낸 것이다). must_not 은 채점기가 미등록 연락처
        # 검사로 따로 잡으므로 여기서는 거절 표현만 요구한다.
        target_turn = turn(ask, target=True, gold=[],
                           must=[REJECTIONS],
                           note=f"{absent_name} 은 명함에 없는 사람이다 — 지어내면 안 된다")
    elif answerable:
        target_turn = turn(ask, target=True, gold=[target["id"]],
                           must=[variants(field, value)], must_not=REJECTIONS,
                           note=f"{target['name']}의 {FIELD_NOUN[field]}")
    else:
        # 없는 칸을 물으면 **없다고 말해야** 한다. 옆 칸 값으로 때우면 실패다.
        neighbours = [v for f, v in target.items()
                      if f in FIELD_NOUN and f != field and (v or "").strip()]
        target_turn = turn(ask, target=True, gold=[target["id"]],
                           must=[REJECTIONS], must_not=neighbours[:4],
                           note=f"{target['name']}의 {FIELD_NOUN[field]} 는 비어 있다")
    turns.append(target_turn)

    distance = len(turns) - evidence_depth
    distractors = sum(1 for t in turns[:-1] if not t.get("target"))
    level, score = difficulty(distance, distractors, reference, answerable, ops)
    return {
        "id": sid,
        "reference": reference,
        "field": field,
        "answerable": answerable,
        "target_card_id": target["id"],
        "depth": len(turns),
        "distance": distance,
        "distractors": distractors,
        "ops": ops,
        "difficulty": level,
        "difficulty_score": score,
        "turns": turns,
    }


UNANSWERABLE_CAP = 0.30   # 답 없는 문제 상한. 실제 사용에서 대부분의 질문은 답이 있다.


def build(cards, total, holdout_ratio, seed, ambiguous_weight=1):
    rng = random.Random(seed)
    empty_by_field = {f: [c for c in cards if not (c.get(f) or "").strip()]
                      for f in FIELD_NOUN}
    from collections import Counter as _C
    _nc = _C(c["name"] for c in cards)
    unique_names = {n for n, k in _nc.items() if k == 1}
    # v1 기준선은 채점 턴의 **58% 가 '없다' 문제**였다. 손잡이 조합에서 답없음이 난이도를
    # 올리는 가장 쉬운 길이라 과다 선택된 것이다. 실제 사용은 대부분 답이 있는 질문이므로
    # 상한을 두고, 넘으면 같은 난이도의 답있음 조합으로 바꿔 뽑는다.
    unans_budget = int(total * UNANSWERABLE_CAP)
    unans_used = 0
    quota = scale_quota(QUOTA, total)

    # 난이도 목표치를 맞추는 손잡이 조합. difficulty() 의 정의에서 거꾸로 고른다.
    # 손잡이 조합. difficulty() 의 정의에서 거꾸로 고른 것이고, 실제로 그 난이도가
    # 나오는지는 만든 뒤 다시 검사한다(정의와 라벨이 어긋나면 표가 거짓말을 한다).
    KNOBS = {
        "L1": [("named", True, 0)],
        "L2": [("named", True, 1), ("named", False, 0), ("pronoun", True, 0)],
        "L3": [("pronoun", True, 1), ("ordinal", True, 0), ("correction", True, 0),
               ("correction", False, 0), ("pronoun", False, 0)],
        "L4": [("ordinal", True, 1), ("ordinal", False, 0), ("correction", True, 1),
               ("correction", False, 1), ("pronoun", False, 1)],
    }

    scenarios, sid = [], 0
    shortfalls = {}
    for tier, (lo, hi) in DEPTH_TIERS.items():
        for level, n in quota[tier].items():
            made = 0
            guard = 0
            while made < n and guard < n * 60:
                guard += 1
                reference, answerable, ops = rng.choice(KNOBS[level])
                if not answerable and unans_used >= unans_budget:
                    alt = [k for k in KNOBS[level] if k[1]]
                    if not alt:
                        continue
                    reference, answerable, ops = rng.choice(alt)
                depth = rng.randint(lo, hi)
                # 참조 방식이 요구하는 최소 깊이를 못 채우면 다시 뽑는다.
                need = {"named": 1, "pronoun": 3, "ordinal": 2, "correction": 2}[reference]
                if depth < need:
                    continue
                sid += 1
                sc = make_scenario(rng, f"HJP-{sid:04d}", cards, empty_by_field,
                                   depth, reference, answerable, ops,
                                   distractor_target=None, unique_names=unique_names)
                # 계산된 난이도가 목표 칸과 다르면 버린다 — 라벨과 정의가 어긋나면
                # 난이도별 표가 거짓말을 한다.
                if sc["difficulty"] != level:
                    continue
                sc["depth_tier"] = tier
                scenarios.append(sc)
                made += 1
                if not answerable:
                    unans_used += 1
            if made < n:
                # 못 채운 몫은 **같은 깊이 층 안에서** 메운다. 다른 층으로 넘기면
                # 깊이 분포가 틀어져 깊이별 표가 못 쓰게 된다.
                short = n - made
                shortfalls.setdefault(tier, 0)
                shortfalls[tier] += short
                print(f"  [알림] {tier}/{level} 목표 {n} 중 {made}개 "
                      f"— {short}개는 이 깊이에서 그 난이도가 구조적으로 안 나온다",
                      flush=True)

    # 층별 부족분을 그 층에서 실제로 만들어지는 난이도로 메운다.
    for tier, short in shortfalls.items():
        lo, hi = DEPTH_TIERS[tier]
        made = 0
        guard = 0
        while made < short and guard < short * 200:
            guard += 1
            level = rng.choice(["L1", "L2", "L3", "L4"])
            reference, answerable, ops = rng.choice(KNOBS[level])
            depth = rng.randint(lo, hi)
            need = {"named": 1, "pronoun": 3, "ordinal": 2, "correction": 2}[reference]
            if depth < need:
                continue
            sid += 1
            if not answerable and unans_used >= unans_budget:
                continue
            sc = make_scenario(rng, f"HJP-{sid:04d}", cards, empty_by_field,
                               depth, reference, answerable, ops, distractor_target=None,
                               unique_names=unique_names)
            sc["depth_tier"] = tier
            scenarios.append(sc)
            made += 1
            if not answerable:
                unans_used += 1

    rng.shuffle(scenarios)
    n_hold = int(round(len(scenarios) * holdout_ratio))
    # 홀드아웃도 층별로 고르게 뗀다 — 한쪽에 몰리면 두 값이 비교 불가가 된다.
    by_cell = {}
    for sc in scenarios:
        by_cell.setdefault((sc["depth_tier"], sc["difficulty"]), []).append(sc)
    holdout = set()
    cells = sorted(by_cell, key=lambda c: -len(by_cell[c]))
    i = 0
    while len(holdout) < n_hold and cells:
        cell = cells[i % len(cells)]
        for sc in by_cell[cell]:
            if sc["id"] not in holdout:
                holdout.add(sc["id"])
                break
        i += 1
        if i > n_hold * 10:
            break
    for sc in scenarios:
        sc["split"] = "holdout" if sc["id"] in holdout else "public"
    scenarios.sort(key=lambda s: s["id"])
    return scenarios


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bench" / "hjp_multiturn_v1.json"))
    ap.add_argument("--scenarios", type=int, default=120)
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=20260826)
    ap.add_argument("--ambiguous-weight", type=int, default=1,
                    help="동명이인 손잡이를 몇 배로 뽑을지. 표본이 적어 신뢰구간이 "
                         "넓을 때 올린다(v1.4 는 6 — 20개에서 60개로)")
    ap.add_argument("--built-at", default="", help="동결 시각(문자열). 재현을 위해 밖에서 준다")
    args = ap.parse_args()

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    scenarios = build(cards, args.scenarios, args.holdout, args.seed)

    payload = {
        "schema_version": 1,
        "dataset_version": "hjp_multiturn_v1.1",
        "built_at": args.built_at,
        "seed": args.seed,
        "description": (
            "외부 고정셋의 **구조**(채점 대상 턴 1개 + 방해 문맥, 거리·방해 제어)와 "
            "생성기의 **생산 방식**(카드에서 정답 자동 유도, 발화 풀)을 합친 통합 셋. "
            "한 번 찍어 동결한다 — 생성기를 고쳐도 이 파일은 안 바뀌므로 시간에 걸친 비교가 성립한다."
        ),
        "guardrails": [
            "모든 인물과 정답은 cards_eval1000.json 에 실재해야 한다. 제3자 사실을 지어내지 않는다.",
            "시나리오마다 채점 대상 턴은 정확히 하나다. 나머지는 설정·방해 문맥이다.",
            "지시어 참조는 최근이 아닌 인물을 가리킨다.",
            "정정은 명시적인 정정 표현을 포함한다.",
            "답할 수 없는 문제는 그 카드의 그 칸이 실제로 비어 있을 때만 만든다.",
            "난이도는 라벨이 아니라 거리·방해수·참조방식·답가능·연산수에서 계산한다.",
            "깊이와 난이도를 교차 층화한다 — 한쪽만 층화하면 다른 쪽이 그 안에 숨는다.",
        ],
        "cards": {
            "path": "data/cards_eval1000.json",
            "count": len(cards),
            "answer_fingerprint": cfp.answer_fingerprint(cards),
        },
        "generator": {
            "path": "scripts/build_bench.py",
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "scenarios": scenarios,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    import collections
    depth_tier = collections.Counter(s["depth_tier"] for s in scenarios)
    diff = collections.Counter(s["difficulty"] for s in scenarios)
    split = collections.Counter(s["split"] for s in scenarios)
    turns = sum(len(s["turns"]) for s in scenarios)
    print(f"\n{out}  —  시나리오 {len(scenarios)}개 / 턴 {turns}개 "
          f"(채점 대상 {len(scenarios)}턴, 설정·방해 {turns - len(scenarios)}턴)")
    print(f"  깊이 층 : {dict(sorted(depth_tier.items()))}")
    print(f"  난이도  : {dict(sorted(diff.items()))}")
    print(f"  분할    : {dict(split)}")
    print("\n  깊이 x 난이도 교차")
    print(f"    {'':<12}" + "".join(f"{lv:>6}" for lv in ("L1", "L2", "L3", "L4")))
    for tier in DEPTH_TIERS:
        row = collections.Counter(s["difficulty"] for s in scenarios if s["depth_tier"] == tier)
        print(f"    {tier:<12}" + "".join(f"{row.get(lv, 0):>6}" for lv in ("L1", "L2", "L3", "L4")))


if __name__ == "__main__":
    main()
