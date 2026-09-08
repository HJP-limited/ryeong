import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "app/src/test/java/com/example/hjp/search/CardGazetteerTest.kt"
s = io.open(p, encoding="utf-8").read()

old = '''    @Test
    fun `법인 표기는 회사 조건이 되지 않는다`() {
        // "유한회사"는 160장이 공유한다. 이게 조건이 되면 그 전부가 한 덩어리로 남는다.
        val gz = CardGazetteer(twins)
        val f = extractFieldFilters(analyze("유한회사 앰버 다니는 백다인씨 주소는?"), gz)
        assertEquals(listOf("앰버"), f.companies)
        assertEquals(listOf("c2"), applyFieldFilters(twins, f).map { it.id })
    }'''

new = '''    @Test
    fun `법인 표기 단독으로는 회사 조건이 되지 않는다`() {
        // "유한회사"는 160장이 공유한다. 이게 단독 조건이 되면 그 전부가 한 덩어리로 남는다.
        val gz = CardGazetteer(twins)
        val f = extractFieldFilters(analyze("유한회사 다니는 사람 찾아줘"), gz)
        assertTrue("법인 표기가 조건이 됐다: ${f.companies}", f.companies.isEmpty())
    }

    @Test
    fun `회사명과 함께 대면 법인 표기까지 조건이 된다`() {
        // 핵심어만 쓰면 "유한회사 경기전자"와 "주식회사 경기전자"가 한 덩어리가 되는데
        // 데이터에서 이 둘은 다른 회사다(핵심어가 겹치는 조합이 41조 있다).
        // 사용자가 법인 표기를 말했으면 그건 조건이지 군더더기가 아니다.
        val gz = CardGazetteer(twins)
        val f = extractFieldFilters(analyze("유한회사 앰버 다니는 백다인씨 주소는?"), gz)
        assertEquals(listOf("유한회사 앰버"), f.companies)
        assertEquals(listOf("c2"), applyFieldFilters(twins, f).map { it.id })
    }

    @Test
    fun `회사명을 안 가리고 부르면 후보를 좁히지 않는다`() {
        // "앰버 사람"은 앰버라는 이름을 쓰는 회사 전부가 맞다 — 사용자가 안 가렸으므로
        // 우리도 가리지 않는다. 여기서 한쪽을 고르면 그건 추측이다.
        val both = twins + card(id = "c4", name = "조은결", company = "주식회사 앰버")
        val gz = CardGazetteer(both)
        val f = extractFieldFilters(analyze("앰버 다니는 사람 찾아줘"), gz)
        assertEquals(listOf("앰버"), f.companies)
        assertEquals(listOf("c2", "c4"), applyFieldFilters(both, f).map { it.id })
    }'''

assert s.count(old) == 1, s.count(old)
io.open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("시험 갱신 OK")
