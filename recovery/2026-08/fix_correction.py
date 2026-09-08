"""
정정 어순 버그 수정 — **기준선 실행이 끝난 뒤에** 적용한다 (실행 중 서버를 바꾸면 측정이 섞인다).

  "구예원씨 직급 말한 거야. 예하린씨 말고"  ->  '예하린 예하린씨 말고'   (버릴 이름을 고름)

원인 둘:
  1. "마지막에 말한 이름이 정정 대상" — 대상이 앞, 버릴 이름이 뒤면 뒤집힌다.
  2. 옛 이름 삭제가 ordered[:-1] 즉 **위치 기준** — 대상이 앞에 오면 대상을 지우고 버릴 이름을 남긴다.
수정:
  1. 거절 표지("말고"·"아니라"·"아니고")에 붙은 이름이 **버릴** 이름, 나머지가 대상.
     표지에 붙은 이름이 없을 때만 옛 규칙(마지막 이름)으로 물러난다.
  2. 삭제는 **대상이 아닌 이름** 기준.
앱(MainActivity.resolveCorrection)과 서버(resolve_correction) 둘 다 같은 규칙이라 둘 다 고친다.
"""
import io, sys, ast
sys.stdout.reconfigure(encoding="utf-8")


def patch(path, pairs, py=False):
    s = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert s.count(old) == 1, f"{path}: {s.count(old)}건 -> {old[:70]!r}"
        s = s.replace(old, new)
    io.open(path, "w", encoding="utf-8").write(s)
    if py:
        ast.parse(s)
    print(f"OK {path}")


# ── 서버 ─────────────────────────────────────────────────────────────────────
patch("scripts/hybrid_server.py", [
    ('''    ordered = sorted(names, key=lambda n: question.find(n))
    target = ordered[-1]''',
     '''    ordered = sorted(names, key=lambda n: question.find(n))
    # 거절 표지 바로 앞의 이름이 **버릴** 이름이다. "X씨 직급 말한 거야. Y씨 말고" 에서
    # 마지막 이름(Y)을 대상으로 잡으면 뒤집힌다(통합 벤치 v1 기준선 2/2 실패).
    rejected = {n for n in names
                if re.search(re.escape(n) + r"(?:씨|님)?(?:가|이|은|는)?\\s*(?:말고|아니라|아니고)", question)}
    kept = [n for n in ordered if n not in rejected]
    target = kept[-1] if kept and rejected else ordered[-1]'''),
    ('''    for n in ordered[:-1]:
        tail = tail.replace(n + "씨", " ").replace(n, " ")''',
     '''    for n in ordered:
        if n == target:          # 위치가 아니라 **대상 여부**로 지운다 — 대상이 앞에 올 수 있다
            continue
        tail = tail.replace(n + "씨", " ").replace(n, " ")'''),
], py=True)

# ── 앱 ───────────────────────────────────────────────────────────────────────
patch("app/src/main/java/com/example/hjp/MainActivity.kt", [
    ('''    val ordered = knownNames.sortedBy { question.indexOf(it) }
    val target = ordered.last()''',
     '''    val ordered = knownNames.sortedBy { question.indexOf(it) }
    // 거절 표지 바로 앞의 이름이 **버릴** 이름이다. "X씨 직급 말한 거야. Y씨 말고" 에서
    // 마지막 이름(Y)을 대상으로 잡으면 뒤집힌다(통합 벤치 v1 기준선 2/2 실패).
    val rejected = knownNames.filter { n ->
        Regex(Regex.escape(n) + "(?:씨|님)?(?:가|이|은|는)?\\\\s*(?:말고|아니라|아니고)").containsMatchIn(question)
    }.toSet()
    val kept = ordered.filterNot { it in rejected }
    val target = if (kept.isNotEmpty() && rejected.isNotEmpty()) kept.last() else ordered.last()'''),
    ('''    for (n in ordered.dropLast(1)) tail = tail.replace("${n}씨", " ").replace(n, " ")''',
     '''    // 위치가 아니라 **대상 여부**로 지운다 — 대상이 앞에 올 수 있다.
    for (n in ordered) if (n != target) tail = tail.replace("${n}씨", " ").replace(n, " ")'''),
])

# ── 앱 테스트 ─────────────────────────────────────────────────────────────────
patch("app/src/test/java/com/example/hjp/MainActivityTest.kt", [
    ('''    @Test
    fun `주어만 바꾸는 후속의 세 갈래를 모두 이어받는다`() {''',
     '''    @Test
    fun `정정에서 대상이 앞에 와도 버릴 이름을 고르지 않는다`() {
        val names = listOf("구예원", "예하린")
        // 실측(통합 벤치 v1): 대상 선행 어순에서 버릴 이름(예하린)을 골라 '예하린 예하린씨 말고' 가 됐다.
        val fixed = resolveCorrection("구예원씨 직급 말한 거야. 예하린씨 말고", names)
        assertTrue(fixed.startsWith("구예원"))
        assertFalse("예하린" in fixed)
        // 기존 어순(버릴 이름이 앞)은 그대로 동작해야 한다.
        val legacy = resolveCorrection("아니 예하린씨 말고 구예원씨 직급 알려줘", names)
        assertTrue(legacy.startsWith("구예원"))
        assertFalse("예하린" in legacy)
    }

    @Test
    fun `주어만 바꾸는 후속의 세 갈래를 모두 이어받는다`() {'''),
])
print("정정 어순 수정 준비 완료 — 기준선 끝난 뒤 적용")
