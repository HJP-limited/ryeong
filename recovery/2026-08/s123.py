import ast
import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "scripts/eval_search.py"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, n=1):
    global s
    assert s.count(old) == n, f"{s.count(old)}건(기대 {n}) -> {old[:70]!r}"
    s = s.replace(old, new)


# ── S2. 전화 말투를 셋으로 ──────────────────────────────────────────────────
rep('''    phone_cards = rng.sample(cards, 30)
    for c in phone_cards:
        digits = "".join(ch for ch in c["phone"] if ch.isdigit())
        if len(digits) >= 8:
            frag = digits[3:]
            relevant = [x["id"] for x in cards if frag in "".join(ch for ch in x["phone"] if ch.isdigit())]
            queries.append(("전화(하이픈X)", frag, relevant))''',
'''    # **전화는 말투가 셋이다.** 예전에는 하이픈 없는 가운데 8자리(digits[3:]) 하나만
    # 썼는데, 실제 사용자는 그렇게 치지 않는다 — 전체를 붙여넣거나("010-1234-5678"),
    # 뒷 8자리를 하이픈째 말하거나("1234-5678"), 뒷 4자리만 기억한다("5678").
    # 한 말투만 시험하면 나머지 둘이 깨져도 지표가 안 움직인다.
    #
    # 뒷 4자리는 1000장 안에서 충돌이 나 정답이 여럿이 된다 — 그래서 이 갈래만
    # 진짜 랭킹 시험이 되고, 나머지 둘은 조회에 가깝다.
    def digits_of(card):
        return "".join(ch for ch in card["phone"] if ch.isdigit())

    for c in rng.sample(cards, 30):
        digits = digits_of(c)
        if len(digits) < 8:
            continue
        for kind, q, frag in (
            ("전화(전체)", c["phone"], digits),
            ("전화(뒷8자리)", f"{digits[-8:-4]}-{digits[-4:]}", digits[-8:]),
            ("전화(뒷4자리)", digits[-4:], digits[-4:]),
        ):
            relevant = [x["id"] for x in cards if digits_of(x).endswith(frag)]
            queries.append((kind, q, relevant))''')

# ── S3. 지역을 시·도 수준으로 ───────────────────────────────────────────────
rep('''    pairs = [k for k, v in by_loc_title.items() if v]
    for loc, title in rng.sample(sorted(pairs), 40):
        q = f"{loc}에 있는 {title} 찾아줘"  # 조사·명령어 처리까지 함께 검증
        queries.append(("지역+직함(문장)", q, by_loc_title[(loc, title)]))''',
'''    pairs = [k for k, v in by_loc_title.items() if v]
    for loc, title in rng.sample(sorted(pairs), 40):
        q = f"{loc}에 있는 {title} 찾아줘"  # 조사·명령어 처리까지 함께 검증
        queries.append(("지역+직함(주소수준)", q, by_loc_title[(loc, title)]))

    # **시·도 수준 지역**. 위의 주소 수준("광주광역시 남구")은 직함과 겹치면 정답이
    # 1장으로 떨어져 사실상 식별자 조회다 — 그래서 R@5 가 1.000 이었다. 사람은
    # "광주 사장" 이라고 말하고, 그러면 정답이 여럿이라 **순위가 문제**가 된다.
    # 정답 3명 이상인 조합만 쓴다(2명 이하는 여전히 조회에 가깝다).
    by_sido_title = defaultdict(list)
    for c in cards:
        addr = (c.get("address") or "").strip()
        region = addr.split()[0] if addr else ""
        title = (c.get("title") or "").strip()
        if region and title and has_hangul(title):
            by_sido_title[(region, title)].append(c["id"])
    plural = sorted(k for k, v in by_sido_title.items() if len(v) >= 3)
    for region, title in rng.sample(plural, min(40, len(plural))):
        q = f"{region}에 있는 {title} 찾아줘"
        queries.append(("지역+직함(시도수준)", q, by_sido_title[(region, title)]))''')

# ── S1. 식별자 제외 지표를 병기한다 ─────────────────────────────────────────
rep('''    for label, rankings in systems:
        evaluate(label, pick(rankings, rank_idx), rank_queries)''',
'''    for label, rankings in systems:
        evaluate(label, pick(rankings, rank_idx), rank_queries)

    # **식별자를 뺀 값을 병기한다.** 이름·회사명·전화는 정답 문자열이 카드에 그대로
    # 있어서 검색이 아니라 조회다(BEIR·MS MARCO 같은 일반 검색 벤치에는 이 유형이
    # 아예 없다). 그런데 이 셋이 질의의 절반이 넘고 전부 만점이라, 헤드라인 R@5 는
    # 그 만점에 희석된 값이다. 진짜 시험은 개념형과 지역+직함이다.
    IDENTIFIER = ("이름", "회사명", "전화")
    concept_idx = [i for i in rank_idx
                   if not queries[i][0].startswith(IDENTIFIER)]
    if concept_idx:
        print("\\n" + "=" * 70)
        print(f"[식별자 제외]  이름·회사명·전화를 뺀 {len(concept_idx)}질의 — "
              f"이쪽이 '검색' 이다")
        for label, rankings in systems:
            evaluate(label, pick(rankings, concept_idx), pick(queries, concept_idx))''')

# ── 기권 실패 질의를 유형 가리지 않고 찍는다 ────────────────────────────────
rep('''        elif kind.startswith("기권(그럴듯"):
            misses.append(q)''',
'''        else:
            misses.append((kind, q))''')

rep('''    if misses:
        print(f"    ! 비슷한 것으로 때운 질의 {len(misses)}개 중 앞 3개: {misses[:3]}")''',
'''    if misses:
        # 무엇에 걸렸는지 보이게 전부 찍는다. 숫자만 보면 "무엇을 고쳐야 하나" 에
        # 답이 안 나온다 — 실패 질의가 곧 할 일 목록이다.
        print(f"    ! 때운 질의 {len(misses)}개:")
        for kind, q in misses:
            print(f"        [{kind}] {q}")''')

io.open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("S1·S2·S3 + 실패 질의 출력 OK")
