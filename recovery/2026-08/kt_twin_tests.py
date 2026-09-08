import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "app/src/test/java/com/example/hjp/MainActivityTest.kt"
s = io.open(p, encoding="utf-8").read()

anchor = "    private fun sampleSearchResponse(names: List<String>): CardSearchResponse {"
tests = '''    // ---- 동명이인 되부르기 ----

    private fun twinResponse(names: List<String>) = CardSearchResponse(
        query = "q", engine = "test", retrieval = "keyword",
        keywordQuery = "q", semanticQuery = "q",
        fieldFilters = FieldFilters(names = listOf("백다인")),
        results = listOf(
            CardSearchHit(repairCard("백다인", "샤인기계").also { it.id = "c1" }, 1.0, 0, null, 0f),
            CardSearchHit(repairCard("백다인", "앰버").also { it.id = "c2" }, 0.9, 1, null, 0f),
        ).filter { it.card.id in names },
    )

    @Test
    fun `앞에서 정해 둔 동명이인만 남긴다`() {
        // 회사로 한 명을 특정한 뒤 몇 턴 지나 이름만으로 다시 부르는 경우다. focus 도
        // 직전 카드 id 도 그새 방해 인물로 덮여서, 이 기억이 없으면 어느 쪽인지 모른다
        // (통합 벤치 v1.3 실패 3건이 전부 이 모양이었고 되묻지도 않고 틀린 값을 줬다).
        val search = twinResponse(listOf("c1", "c2"))
        val pinned = pinAmbiguousTwin(search, "백다인=c2")
        assertEquals(listOf("c2"), pinned.results.map { it.card.id })
    }

    @Test
    fun `정해 둔 적이 없으면 후보를 그대로 둔다`() {
        // 애매한 채로 지나간 대화를 확신으로 둔갑시키지 않는다.
        val search = twinResponse(listOf("c1", "c2"))
        assertEquals(listOf("c1", "c2"), pinAmbiguousTwin(search, null).results.map { it.card.id })
        assertEquals(listOf("c1", "c2"),
            pinAmbiguousTwin(search, "신민재=c9").results.map { it.card.id })
    }

    @Test
    fun `후보가 한 장뿐이면 건드리지 않는다`() {
        val search = twinResponse(listOf("c1"))
        assertEquals(listOf("c1"), pinAmbiguousTwin(search, "백다인=c2").results.map { it.card.id })
    }

    @Test
    fun `기억은 같은 이름이 다시 확정되면 최신으로 덮는다`() {
        // 대화 중에 사용자가 다른 쪽으로 옮겨갈 수 있고, 그때는 최근 확정이 맞다.
        val once = appendSubjectCard(null, "백다인", "c1")
        assertEquals("백다인=c1", once)
        val twice = appendSubjectCard(once, "백다인", "c2")
        assertEquals("백다인=c2", twice)
        val other = appendSubjectCard(twice, "신민재", "c9")
        assertEquals("백다인=c2,신민재=c9", other)
        assertEquals("c2", subjectCardFor(other, "백다인"))
        assertEquals("c9", subjectCardFor(other, "신민재"))
        assertNull(subjectCardFor(other, "남다은"))
        assertNull(subjectCardFor(null, "백다인"))
    }

    private fun sampleSearchResponse(names: List<String>): CardSearchResponse {'''

assert s.count(anchor) == 1, s.count(anchor)
s = s.replace(anchor, tests)
io.open(p, "w", encoding="utf-8").write(s)
print("동명이인 시험 OK")
