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
    ('''    tail = question
    for sep in (".", "!", "?"):
        parts = [p for p in tail.split(sep) if p.strip()]
        if len(parts) > 1:
            tail = parts[-1]
    for n in ordered:
        if n == target:          # 위치가 아니라 **대상 여부**로 지운다 — 대상이 앞에 올 수 있다
            continue
        tail = tail.replace(n + "씨", " ").replace(n, " ")
    for p in PRONOUNS:
        tail = tail.replace(p, " ")''',
     '''    # **요청이 담긴 문장**을 고른다. 무조건 마지막 문장을 쓰면
    # "X씨 회사 말한 거야. Y씨 말고" 에서 'Y씨 말고' 만 남아 물어본 칸이 사라진다
    # (실측: 통합 벤치 v1.1 기준선 실패 6건이 전부 이 어순이었다).
    parts = [p for p in re.split(r"[.!?]", question) if p.strip()]
    if len(parts) > 1:
        cand = [p for p in parts if target in p] or [p for p in parts if attribute_of(p)]
        tail = (cand or parts)[-1]
    else:
        tail = question
    # 이름은 **전부** 지운다 — 대상은 어차피 앞에 다시 붙인다. 조사까지 함께 걷어야
    # "손도윤씨가 아니라" 의 '가' 같은 조각이 안 남는다.
    for n in ordered:
        tail = re.sub(re.escape(n) + r"(?:씨|님)?(?:가|이|은|는|을|를|도|의)?", " ", tail)
    for p in PRONOUNS:
        tail = tail.replace(p, " ")
    # 정정 표지 자체도 요청이 아니다.
    for marker in ("말한 거야", "말한거야", "말고", "아니라", "아니고", "아니"):
        tail = tail.replace(marker, " ")'''),
], py=True)

# ── 앱 ───────────────────────────────────────────────────────────────────────
patch("app/src/main/java/com/example/hjp/MainActivity.kt", [
    ('''    var tail = question
    for (sep in listOf(".", "!", "?")) {
        val parts = tail.split(sep).filter { it.isNotBlank() }
        if (parts.size > 1) tail = parts.last()
    }
    // 위치가 아니라 **대상 여부**로 지운다 — 대상이 앞에 올 수 있다.
    for (n in ordered) if (n != target) tail = tail.replace("${n}씨", " ").replace(n, " ")
    for (p in FOLLOWUP_PRONOUNS) tail = tail.replace(p, " ")''',
     '''    // **요청이 담긴 문장**을 고른다. 무조건 마지막 문장을 쓰면
    // "X씨 회사 말한 거야. Y씨 말고" 에서 'Y씨 말고' 만 남아 물어본 칸이 사라진다
    // (실측: 통합 벤치 v1.1 기준선 실패 6건이 전부 이 어순이었다).
    val parts = question.split(Regex("[.!?]")).filter { it.isNotBlank() }
    var tail = if (parts.size > 1) {
        val cand = parts.filter { target in it }.ifEmpty { parts.filter { attributeOf(it) != null } }
        cand.ifEmpty { parts }.last()
    } else {
        question
    }
    // 이름은 **전부** 지운다 — 대상은 어차피 앞에 다시 붙인다. 조사까지 함께 걷어야
    // "손도윤씨가 아니라" 의 '가' 같은 조각이 안 남는다.
    for (n in ordered) {
        tail = tail.replace(Regex(Regex.escape(n) + "(?:씨|님)?(?:가|이|은|는|을|를|도|의)?"), " ")
    }
    for (p in FOLLOWUP_PRONOUNS) tail = tail.replace(p, " ")
    // 정정 표지 자체도 요청이 아니다.
    for (marker in listOf("말한 거야", "말한거야", "말고", "아니라", "아니고", "아니")) {
        tail = tail.replace(marker, " ")
    }'''),
])
print("꼬리 추출 수정 완료")
