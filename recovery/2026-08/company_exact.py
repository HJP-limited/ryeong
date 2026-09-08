import ast
import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

# ── 파이썬 ──────────────────────────────────────────────────────────────────
p = "scripts/eval_search.py"
s = io.open(p, encoding="utf-8").read()

old = '''    claimed = set(filters.get("name") or []) | set(titles) | set(locs)
    comps = [tok for tok in tokens
             if tok not in claimed and tok in gazetteer.company_terms]
    if comps:
        filters["company"] = sorted(set(comps))'''
new = '''    claimed = set(filters.get("name") or []) | set(titles) | set(locs)
    comps = [tok for tok in tokens
             if tok not in claimed and tok in gazetteer.company_terms]
    if comps:
        # **법인 표기까지 댔으면 그걸 살린다.** 핵심어만 쓰면 "유한회사 경기전자"와
        # "주식회사 경기전자"가 한 덩어리가 되는데, 데이터에서 이 둘은 다른 회사다
        # (핵심어가 겹치는 조합이 41조 있다). 사용자가 법인 표기를 말했으면 그건
        # 조건이지 군더더기가 아니다.
        #
        # 질의에 회사명 **전체**가 통째로 들어 있으면 그 전체를 조건으로 삼고,
        # 아니면 핵심어로 남긴다("경기전자 사람" 은 둘 다 맞는 게 맞다 — 사용자가
        # 안 가렸으므로 우리도 가리지 않는다).
        normalized_query = normalize(query)
        exact = [c for c in gazetteer.companies
                 if c in normalized_query and any(t in c.split() for t in comps)]
        filters["company"] = sorted(set(exact)) if exact else sorted(set(comps))'''
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

old = '''        if "company" in filters:
            # 회사도 단어 단위다. 부분 문자열이면 "대성전자" 가 "대성" 에 걸린다.
            words = normalize(card.get("company") or "").split()
            ok = ok and any(term in words for term in filters["company"])'''
new = '''        if "company" in filters:
            # 두 가지를 받는다: 회사명 **전체**("유한회사 경기전자")면 통째로 일치해야
            # 하고, 핵심어("경기전자")면 단어 단위로 맞춘다. 부분 문자열로 하면
            # "대성전자" 가 "대성" 에 걸린다.
            whole = normalize(card.get("company") or "")
            words = whole.split()
            ok = ok and any(term == whole or term in words for term in filters["company"])'''
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

io.open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("파이썬 OK")

# ── Kotlin ──────────────────────────────────────────────────────────────────
p = "app/src/main/java/com/example/hjp/search/CardGazetteer.kt"
k = io.open(p, encoding="utf-8").read()

old = '''    val comps = LinkedHashSet<String>()
    for (token in analyzed.keywordTokens) {
        if (token in names || token in titles || token in locs) continue
        if (gazetteer.isKnownCompanyTerm(token)) comps.add(token)
    }
    return FieldFilters(names.sorted(), locs.sorted(), titles.sorted(), comps.sorted())'''
new = '''    val comps = LinkedHashSet<String>()
    for (token in analyzed.keywordTokens) {
        if (token in names || token in titles || token in locs) continue
        if (gazetteer.isKnownCompanyTerm(token)) comps.add(token)
    }
    // **법인 표기까지 댔으면 그걸 살린다.** 핵심어만 쓰면 "유한회사 경기전자"와
    // "주식회사 경기전자"가 한 덩어리가 되는데 데이터에서 이 둘은 다른 회사다
    // (핵심어가 겹치는 조합이 41조 있다). 질의에 회사명 전체가 통째로 들어 있으면
    // 그 전체를 조건으로 삼고, 아니면 핵심어로 남긴다 — "경기전자 사람"은 사용자가
    // 안 가렸으므로 우리도 가리지 않는다.
    val companyFilter = if (comps.isEmpty()) emptyList() else {
        val normalizedQuery = KeywordSearchRanker.normalize(analyzed.rawQuery)
        val exact = gazetteer.companiesContainedIn(normalizedQuery, comps)
        if (exact.isNotEmpty()) exact.sorted() else comps.sorted()
    }
    return FieldFilters(names.sorted(), locs.sorted(), titles.sorted(), companyFilter)'''
assert k.count(old) == 1, k.count(old)
k = k.replace(old, new)

old = '''    fun isKnownCompanyTerm(token: String): Boolean = token in companyTerms'''
new = '''    fun isKnownCompanyTerm(token: String): Boolean = token in companyTerms

    /** 정규화된 질의 안에 통째로 들어 있는 회사명들. [cores] 중 하나를 포함하는 것만 본다. */
    fun companiesContainedIn(normalizedQuery: String, cores: Set<String>): List<String> =
        companies.filter { c -> c in normalizedQuery && cores.any { it in c.split(" ") } }'''
assert k.count(old) == 1
k = k.replace(old, new)

old = '''    val companyWords = KeywordSearchRanker.normalize(card.company.orEmpty()).split(" ")
    val companyOk = filters.companies.isEmpty() || filters.companies.any { it in companyWords }'''
new = '''    // 두 가지를 받는다: 회사명 **전체**("유한회사 경기전자")면 통째로 일치해야 하고,
    // 핵심어("경기전자")면 단어 단위로 맞춘다. 부분 문자열이면 "대성전자"가 "대성"에 걸린다.
    val companyWhole = KeywordSearchRanker.normalize(card.company.orEmpty())
    val companyWords = companyWhole.split(" ")
    val companyOk = filters.companies.isEmpty() ||
        filters.companies.any { it == companyWhole || it in companyWords }'''
assert k.count(old) == 1
k = k.replace(old, new)

io.open(p, "w", encoding="utf-8").write(k)
print("Kotlin OK (rawQuery 존재 확인 필요)")
