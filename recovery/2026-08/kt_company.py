import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "app/src/main/java/com/example/hjp/search/CardGazetteer.kt"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, n=1):
    global s
    assert s.count(old) == n, f"{s.count(old)}건(기대 {n}) -> {old[:70]!r}"
    s = s.replace(old, new)


# ── 1) 회사 핵심어 어휘 ─────────────────────────────────────────────────────
rep('''    private val companies = HashSet<String>()''',
'''    private val companies = HashSet<String>()

    /**
     * 회사 **핵심어** 어휘. [companies]는 회사명 전체 문자열이라("유한회사 앰버")
     * 질의 토큰 하나로는 절대 안 맞는다 — 그래서 질의에 회사를 댔는데도 조건이 안 걸렸다.
     * 실측: "샤인기계 백다인씨 직급"이 백다인 두 장을 다 가져왔고, 몇 턴 뒤
     * "백다인씨 전화번호"가 엉뚱한 쪽을 답했다(통합 벤치 v1.3 실패 3건이 전부 이 모양).
     * 법인 표기(주식회사·유한회사)는 197·160장이 공유하므로 뺀다 — 넣으면 그게
     * 필터가 되어 357장이 한 덩어리가 된다.
     */
    private val companyTerms = HashSet<String>()''')

rep('''            if (comp.isNotBlank()) companies.add(KeywordSearchRanker.normalize(comp))''',
'''            if (comp.isNotBlank()) {
                val normalizedCompany = KeywordSearchRanker.normalize(comp)
                companies.add(normalizedCompany)
                normalizedCompany.split(" ")
                    .filter { it.length >= 2 && it !in COMPANY_STOPWORDS }
                    .forEach { companyTerms.add(it) }
            }''')

rep('''    fun isKnownAddressTerm(token: String): Boolean = token in addressTerms''',
'''    fun isKnownAddressTerm(token: String): Boolean = token in addressTerms

    fun isKnownCompanyTerm(token: String): Boolean = token in companyTerms''')

# ── 2) 필터 자료구조 ────────────────────────────────────────────────────────
rep('''data class FieldFilters(
    val names: List<String> = emptyList(),
    val locations: List<String> = emptyList(),
    val titles: List<String> = emptyList(),
) {
    val isEmpty: Boolean get() = names.isEmpty() && locations.isEmpty() && titles.isEmpty()''',
'''data class FieldFilters(
    val names: List<String> = emptyList(),
    val locations: List<String> = emptyList(),
    val titles: List<String> = emptyList(),
    val companies: List<String> = emptyList(),
) {
    val isEmpty: Boolean
        get() = names.isEmpty() && locations.isEmpty() && titles.isEmpty() && companies.isEmpty()''')

rep('''        if (titles.isNotEmpty()) add("직함=${titles.joinToString(",")}")''',
'''        if (titles.isNotEmpty()) add("직함=${titles.joinToString(",")}")
        if (companies.isNotEmpty()) add("회사=${companies.joinToString(",")}")''')

# ── 3) 질의에서 회사 뽑기 ───────────────────────────────────────────────────
rep('''        if (gazetteer.isKnownAddressTerm(token)) locs.add(token)
    }
    return FieldFilters(names.sorted(), locs.sorted(), titles.sorted())''',
'''        if (gazetteer.isKnownAddressTerm(token)) locs.add(token)
    }
    // 회사는 마지막이다. 이름/직함/지역이 먼저 가져간 토큰은 건드리지 않는다 — 회사
    // 핵심어가 사람 이름이나 지역과 겹칠 수 있고, 그때 우선순위를 뒤집으면 이름 검색이
    // 깨진다. 파이썬 쪽(extract_field_filters)과 같은 순서를 유지할 것.
    val comps = LinkedHashSet<String>()
    for (token in analyzed.keywordTokens) {
        if (token in names || token in titles || token in locs) continue
        if (gazetteer.isKnownCompanyTerm(token)) comps.add(token)
    }
    return FieldFilters(names.sorted(), locs.sorted(), titles.sorted(), comps.sorted())''')

# ── 4) 필터 적용 ────────────────────────────────────────────────────────────
rep('''    val titleOk = filters.titles.isEmpty() || filters.titles.any { it in titleWords }
    nameOk && locOk && titleOk''',
'''    val titleOk = filters.titles.isEmpty() || filters.titles.any { it in titleWords }
    // 회사도 단어 단위다. 부분 문자열이면 "대성전자"가 "대성"에 걸린다.
    val companyWords = KeywordSearchRanker.normalize(card.company.orEmpty()).split(" ")
    val companyOk = filters.companies.isEmpty() || filters.companies.any { it in companyWords }
    nameOk && locOk && titleOk && companyOk''')

# ── 5) 법인 표기 상수 ───────────────────────────────────────────────────────
rep('''data class FieldFilters(''',
'''/**
 * 법인 표기. normalize가 괄호를 지우므로 "(주)"는 "주", "(유)"는 "유"가 되는데 둘 다
 * 한 글자라 길이 조건에서 이미 걸러진다. 여기 남기는 것은 두 글자 이상인 것들이다.
 */
private val COMPANY_STOPWORDS = setOf("주식회사", "유한회사")

data class FieldFilters(''')

io.open(p, "w", encoding="utf-8").write(s)
print("Kotlin 회사 필터 OK")
