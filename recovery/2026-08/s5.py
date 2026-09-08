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


# ── 그럴듯한 부재(hard negative) 생성기 ─────────────────────────────────────
rep('''def build_eval_queries(cards, rng, include_concept=True, include_no_result=True):''',
'''# 그럴듯한 이름을 만들 때 쓰는 흔한 이름. 실존 카드의 **성**에 붙여서, 있을 법한데
# 코퍼스에는 없는 사람을 만든다(멀티턴 벤치의 absent 유형과 같은 방식).
PLAUSIBLE_GIVEN = ["도현", "서준", "지호", "예준", "하준", "주원", "지후", "준서",
                   "서연", "지우", "하은", "서윤", "지유", "채원", "수아", "다은"]


def build_hard_negative_queries(cards, rng, per_kind=5):
    """
    **그럴듯한데 없는 것들**(hard negative)로 기권을 시험한다.

    기존 기권 셋 20개 중 16개는 한눈에 가짜다("우주비행사", "zzzz@zzzz.zzz").
    그건 "가짜를 가짜로 아는가" 만 재고, 정작 우리가 실제로 틀렸던 것 —
    **비슷한 것으로 때우지 않는가** — 는 못 잰다(코드 주석에 "서커스 단장" 이
    우연히 정답 처리된 기록이 남아 있다). 일반 검색 벤치의 기권 시험은 전부
    hard negative 로 만든다.

    세 갈래를 만들고, 만들 때마다 **코퍼스에 정말 없는지 확인**한다. 추측으로 넣으면
    정답이 있는 질의를 '정답 0개' 로 라벨링하는 사고가 난다.
      · 있을 법한 사람 이름  — 실존 성 + 흔한 이름
      · 실재 회사와 한 글자 다른 회사명
      · 실재 지역 + 실재 직함인데 그 조합은 0명
    """
    names = {(c.get("name") or "").strip() for c in cards}
    companies = {(c.get("company") or "").strip() for c in cards if (c.get("company") or "").strip()}
    surnames = sorted({n[0] for n in names if len(n) >= 2})
    out = []

    made = set()
    while len(made) < per_kind and len(made) < 200:
        cand = rng.choice(surnames) + rng.choice(PLAUSIBLE_GIVEN)
        if cand not in names and cand not in made:
            made.add(cand)
            out.append(("기권(그럴듯한 부재)", f"{cand}씨 연락처 알려줘", []))

    # 회사명 한 글자 바꾸기. 바꾼 결과가 다른 실재 회사와 같아지면 버린다.
    swapped = set()
    pool = sorted(companies)
    for _ in range(400):
        if len(swapped) >= per_kind:
            break
        base = rng.choice(pool)
        core = [w for w in base.split() if w not in COMPANY_STOPWORDS and len(w) >= 3]
        if not core:
            continue
        word = core[-1]
        i = rng.randrange(len(word))
        # 한글 한 글자를 이웃 음절로 민다 — 형태는 그대로 두고 글자만 다르게.
        ch = chr(ord(word[i]) + 1) if "가" <= word[i] <= "힣" else word[i]
        cand = word[:i] + ch + word[i + 1:]
        if cand == word or cand in swapped:
            continue
        if any(cand in c for c in companies):
            continue
        swapped.add(cand)
        out.append(("기권(그럴듯한 부재)", f"{cand} 다니는 사람 찾아줘", []))

    # 실재 지역 + 실재 직함인데 그 조합은 0명.
    sido, titles = set(), set()
    have = set()
    for c in cards:
        addr = (c.get("address") or "").strip()
        region = addr.split()[0] if addr else ""
        title = (c.get("title") or "").strip()
        if region:
            sido.add(region)
        if title:
            titles.add(title)
        if region and title:
            have.add((region, title))
    empty = sorted({(r, t) for r in sido for t in titles} - have)
    for r, t in rng.sample(empty, min(per_kind, len(empty))):
        out.append(("기권(그럴듯한 부재)", f"{r}에 있는 {t} 찾아줘", []))
    return out


def build_eval_queries(cards, rng, include_concept=True, include_no_result=True):''')

rep('''        for region, q in NO_RESULT_REGION_CANDIDATES:
            exists = any(region in (c.get("address") or "") or region in (c.get("location") or "") for c in cards)
            if not exists:
                queries.append(("기권(정답없음)", q, []))
    return queries''',
'''        for region, q in NO_RESULT_REGION_CANDIDATES:
            exists = any(region in (c.get("address") or "") or region in (c.get("location") or "") for c in cards)
            if not exists:
                queries.append(("기권(정답없음)", q, []))
        # 유형을 나눠서 낸다. 합치면 "한눈에 가짜" 16개가 분모를 채워 진짜 어려운
        # 쪽의 실패를 가린다 — 헤드라인 기권 정확도가 실제보다 좋게 보인다.
        queries.extend(build_hard_negative_queries(cards, rng))
    return queries''')

# ── 기권 정확도를 유형별로 낸다 ─────────────────────────────────────────────
rep('''    if not queries:
        return
    correct = 0
    for (_, _, relevant), ranked in zip(queries, rankings):
        assert not relevant, "no-result 평가에는 정답이 비어있는 질의만 넣어야 한다"
        if not ranked:
            correct += 1
    print(f"\\n[{name}] 기권 정확도(no-result accuracy) = {correct}/{len(queries)} = {correct/len(queries):.3f}")
    print("  * 0.000 이면 '없는 것을 없다고 말하지 못한다'는 뜻 — 점수 컷오프/필드 필터 미구현 상태를 반영")''',
'''    if not queries:
        return
    correct = 0
    by_kind = defaultdict(lambda: [0, 0])
    misses = []
    for (kind, q, relevant), ranked in zip(queries, rankings):
        assert not relevant, "no-result 평가에는 정답이 비어있는 질의만 넣어야 한다"
        cell = by_kind[kind]
        cell[1] += 1
        if not ranked:
            correct += 1
            cell[0] += 1
        elif kind.startswith("기권(그럴듯"):
            misses.append(q)
    print(f"\\n[{name}] 기권 정확도(no-result accuracy) = {correct}/{len(queries)} = {correct/len(queries):.3f}")
    # **유형을 나눠서 본다.** 합쳐 놓으면 한눈에 가짜인 질의들이 분모를 채워서
    # 진짜 어려운 쪽(그럴듯한 부재)의 실패를 가린다.
    for kind in sorted(by_kind):
        ok, n = by_kind[kind]
        print(f"    {kind:<18} {ok}/{n} = {ok / n:.3f}")
    if misses:
        print(f"    ! 비슷한 것으로 때운 질의 {len(misses)}개 중 앞 3개: {misses[:3]}")
    print("  * 0.000 이면 '없는 것을 없다고 말하지 못한다'는 뜻 — 점수 컷오프/필드 필터 미구현 상태를 반영")''')

io.open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("S5 그럴듯한 부재 OK")
