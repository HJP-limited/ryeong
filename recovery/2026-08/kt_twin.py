import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

# ── AgentSession: 기억 칸 ───────────────────────────────────────────────────
p = "app/src/main/java/com/example/hjp/agent/AgentSession.kt"
s = io.open(p, encoding="utf-8").read()
old = '''        const val KEY_SUBJECT_HISTORY = "subject_history"'''
new = '''        const val KEY_SUBJECT_HISTORY = "subject_history"

        /**
         * 이름 -> 카드 id 를 "이름=id" 로 이어 둔 목록. **동명이인을 이 대화가 어느 쪽으로
         * 정했는지** 기억한다.
         *
         * [KEY_SUBJECT_HISTORY] 는 이름만 담아서 "백다인이 나왔다"까지만 안다. 그런데
         * 카드에 백다인은 두 장이다. 회사로 한 명을 특정한 뒤("샤인기계 백다인씨") 몇 턴
         * 지나서 이름만으로 다시 부르면, focus 도 직전 카드 id 도 그새 방해 인물로 덮여서
         * 어느 백다인인지 알 길이 없다 — 통합 벤치 v1.3 실패 3건이 전부 이것이고,
         * 되묻지도 않고 틀린 번호를 줬다.
         *
         * 이름이 **한 장으로 좁혀진** 턴에서만 기록한다. 애매한 채로 지나간 턴을 기억하면
         * 나중에 그 애매함을 확신으로 둔갑시킨다.
         */
        const val KEY_SUBJECT_CARDS = "subject_cards"'''
assert s.count(old) == 1
io.open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("AgentSession OK")

# ── MainActivity ────────────────────────────────────────────────────────────
p = "app/src/main/java/com/example/hjp/MainActivity.kt"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, n=1):
    global s
    assert s.count(old) == n, f"{s.count(old)}건(기대 {n}) -> {old[:70]!r}"
    s = s.replace(old, new)


# 1) 기록 — 한 장으로 좁혀진 턴에서만
rep('''                    session.putToolContext(AgentSession.KEY_LAST_QUERY, question)''',
'''                    session.putToolContext(AgentSession.KEY_LAST_QUERY, question)
                    // 이름이 한 장으로 좁혀졌으면 그 짝을 기억한다(동명이인 되부르기).
                    // 회사로 특정한 턴("샤인기계 백다인씨")이 여기 해당한다.
                    val only = result.search?.results?.singleOrNull()?.card
                    if (only != null && question.contains(only.name.orEmpty())) {
                        session.putToolContext(
                            AgentSession.KEY_SUBJECT_CARDS,
                            appendSubjectCard(
                                session.toolContextValue(AgentSession.KEY_SUBJECT_CARDS),
                                only.name.orEmpty(), only.id,
                            ),
                        )
                    }''')

# 2) 되부르기 — 검색 직후, 기권 판정 전
rep('''    val search = try {
        searchService.searchHybrid(searchQuery, 5)
    } catch (e: Throwable) {
        return ChatResult("검색 중 문제가 있었습니다.", null, error = e.message ?: e.javaClass.simpleName)
    }''',
'''    val search = try {
        pinAmbiguousTwin(
            searchService.searchHybrid(searchQuery, 5),
            session.toolContextValue(AgentSession.KEY_SUBJECT_CARDS),
        )
    } catch (e: Throwable) {
        return ChatResult("검색 중 문제가 있었습니다.", null, error = e.message ?: e.javaClass.simpleName)
    }''')

# 3) 헬퍼
rep('''internal fun narrowByAnswer(''',
'''/**
 * "이름=id" 목록에 한 줄을 넣거나 갱신한다. 같은 이름이 다시 확정되면 최신 것으로 덮는다 —
 * 사용자가 대화 중에 다른 쪽으로 옮겨갈 수 있고, 그때는 최근 확정이 맞다.
 */
internal fun appendSubjectCard(existing: String?, name: String, cardId: String): String {
    if (name.isBlank() || cardId.isBlank()) return existing.orEmpty()
    val kept = existing.orEmpty().split(",")
        .filter { it.isNotBlank() && it.substringBefore("=") != name }
    return (kept + "$name=$cardId").joinToString(",")
}

/** "이름=id" 목록에서 그 이름에 대해 이 대화가 정한 카드 id 를 찾는다. */
internal fun subjectCardFor(existing: String?, name: String): String? =
    existing.orEmpty().split(",")
        .firstOrNull { it.substringBefore("=") == name && "=" in it }
        ?.substringAfter("=")
        ?.takeIf { it.isNotBlank() }

/**
 * **동명이인 되부르기.** 이름 조건이 하나인데 그 이름 카드가 여럿 남았고, 이 대화가
 * 앞에서 한 명으로 정해 둔 적이 있으면 그쪽만 남긴다. 사람은 한 번 정하면 다음부터
 * 이름만 댄다("샤인기계 백다인씨 직급" ... 세 턴 뒤 "백다인씨 전화번호는?").
 *
 * 규칙을 프롬프트에 적지 않고 여기서 결정적으로 거른다 — 이 저장소에서 프롬프트 규칙
 * 추가는 4전 4패, 결정적 우회는 9전 9승이다.
 */
internal fun pinAmbiguousTwin(
    search: CardSearchResponse,
    subjectCards: String?,
): CardSearchResponse {
    if (search.fieldFilters.names.size != 1) return search
    val pinnedId = subjectCardFor(subjectCards, search.fieldFilters.names.first()) ?: return search
    val pinned = search.results.firstOrNull { it.card.id == pinnedId } ?: return search
    val sameName = search.results.filter { it.card.name == pinned.card.name }
    if (sameName.size <= 1) return search
    return search.copy(results = search.results.filter { it.card.id == pinnedId || it !in sameName })
}

internal fun narrowByAnswer(''')

io.open(p, "w", encoding="utf-8").write(s)
print("MainActivity OK")
