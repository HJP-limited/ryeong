import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "app/src/test/java/com/example/hjp/search/CardGazetteerTest.kt"
s = io.open(p, encoding="utf-8").read()

# ── card() 헬퍼에 회사 칸을 연다 ────────────────────────────────────────────
old = '''        fun card(
            id: String,
            name: String,
            title: String = "",
            address: String = "",
            location: String = "",
            department: String = "",
        ): BusinessCardEntity = BusinessCardEntity(
            id, name, "", "", title, department, "", location, "", "", address, "", "", 0L,
        )'''
new = '''        fun card(
            id: String,
            name: String,
            title: String = "",
            address: String = "",
            location: String = "",
            department: String = "",
            company: String = "",
            phone: String = "",
        ): BusinessCardEntity = BusinessCardEntity(
            id, name, "", company, title, department, "", location, phone, "", address, "", "", 0L,
        )'''
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

# ── 회사 필터 시험 ──────────────────────────────────────────────────────────
anchor = '''    @Test
    fun `데이터에 없는 섬 이름도 기권한다`() {'''
tests = '''    // ---- 회사 필터: 질의에 회사를 대면 실제 조건으로 걸린다 ----

    private val twins = listOf(
        card(id = "c1", name = "백다인", title = "디렉터",
             company = "샤인기계", phone = "010-2975-8509"),
        card(id = "c2", name = "백다인", title = "과장",
             company = "유한회사 앰버", phone = "010-9717-8079"),
        card(id = "c3", name = "신민재", title = "상무", company = "주식회사 대성전자"),
    )

    @Test
    fun `회사 핵심어가 조건으로 걸려 동명이인을 가른다`() {
        // 이게 없을 때 "샤인기계 백다인씨"가 백다인 두 장을 다 가져왔고, 몇 턴 뒤
        // "백다인씨 전화번호"가 엉뚱한 쪽을 답했다(통합 벤치 v1.3 실패 3건).
        val gz = CardGazetteer(twins)
        val f = extractFieldFilters(analyze("샤인기계 백다인씨 직급 뭐야?"), gz)
        assertEquals(listOf("백다인"), f.names)
        assertEquals(listOf("샤인기계"), f.companies)
        assertEquals(listOf("c1"), applyFieldFilters(twins, f).map { it.id })
    }

    @Test
    fun `법인 표기는 회사 조건이 되지 않는다`() {
        // "유한회사"는 160장이 공유한다. 이게 조건이 되면 그 전부가 한 덩어리로 남는다.
        val gz = CardGazetteer(twins)
        val f = extractFieldFilters(analyze("유한회사 앰버 다니는 백다인씨 주소는?"), gz)
        assertEquals(listOf("앰버"), f.companies)
        assertEquals(listOf("c2"), applyFieldFilters(twins, f).map { it.id })
    }

    @Test
    fun `회사 조건은 단어 단위로 맞춘다`() {
        // 부분 문자열이면 "대성전자"가 "대성"에 걸린다. 직함 매칭과 같은 원칙이다.
        val gz = CardGazetteer(twins)
        val f = FieldFilters(companies = listOf("대성"))
        assertTrue(applyFieldFilters(twins, f).isEmpty())
    }

    @Test
    fun `이름이 먼저 가져간 토큰은 회사가 되지 않는다`() {
        // 회사 핵심어가 사람 이름과 겹칠 수 있다. 우선순위를 뒤집으면 이름 검색이 깨진다.
        val overlap = listOf(
            card(id = "o1", name = "한선우", company = "한선우컴퍼니"),
            card(id = "o2", name = "김도윤", company = "다른회사"),
        )
        val gz = CardGazetteer(overlap)
        val f = extractFieldFilters(analyze("한선우씨 전화번호는?"), gz)
        assertEquals(listOf("한선우"), f.names)
        assertTrue("이름을 회사로도 잡았다: ${f.companies}", f.companies.isEmpty())
    }

    @Test
    fun `데이터에 없는 섬 이름도 기권한다`() {'''
assert s.count(anchor) == 1
s = s.replace(anchor, tests)

io.open(p, "w", encoding="utf-8").write(s)
print("회사 필터 시험 OK")
