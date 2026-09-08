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


# ── 1) 회사 어휘 ────────────────────────────────────────────────────────────
rep('''        self.departments = set()
        self.department_terms = set()''',
'''        self.departments = set()
        self.department_terms = set()
        # company_terms: 회사 **핵심어** 어휘. companies 는 회사명 전체 문자열이라
        # ("유한회사 앰버") 질의 토큰 하나로는 절대 안 맞는다 — 그래서 질의에 회사를
        # 댔는데도 조건이 안 걸렸다. 실측: "샤인기계 백다인씨 직급" 이 백다인 두 장을
        # 다 가져왔고, 몇 턴 뒤 "백다인씨 전화번호" 가 엉뚱한 쪽을 답했다(v1.3 실패 3건이
        # 전부 이 모양). 법인 표기(주식회사·유한회사)는 197·160장이 공유하므로 뺀다.
        self.company_terms = set()''')

rep('''            comp = (c.get("company") or "").strip()
            if comp:
                self.companies.add(normalize(comp))''',
'''            comp = (c.get("company") or "").strip()
            if comp:
                normalized_company = normalize(comp)
                self.companies.add(normalized_company)
                for part in normalized_company.split():
                    if len(part) >= 2 and part not in COMPANY_STOPWORDS:
                        self.company_terms.add(part)''')

# ── 2) 법인 표기 목록 ───────────────────────────────────────────────────────
rep('''class Gazetteer''',
'''# 법인 표기. normalize 가 괄호를 지우므로 "(주)" 는 "주", "(유)" 는 "유" 가 되는데
# 둘 다 한 글자라 길이 조건에서 이미 걸러진다. 여기 남기는 것은 두 글자 이상인 것들이다.
COMPANY_STOPWORDS = frozenset({"주식회사", "유한회사"})


class Gazetteer''')

# ── 3) 질의에서 회사 뽑기 ───────────────────────────────────────────────────
rep('''    if locs:
        filters["location"] = sorted(set(locs))
    if titles:
        filters["title"] = sorted(set(titles))''',
'''    if locs:
        filters["location"] = sorted(set(locs))
    if titles:
        filters["title"] = sorted(set(titles))

    # 3) 회사. 이름/직함/지역이 먼저 가져간 토큰은 건드리지 않는다 — 회사 핵심어가
    #    사람 이름이나 지역과 겹칠 수 있고, 그때 우선순위를 뒤집으면 이름 검색이 깨진다.
    claimed = set(filters.get("name") or []) | set(titles) | set(locs)
    comps = [tok for tok in tokens
             if tok not in claimed and tok in gazetteer.company_terms]
    if comps:
        filters["company"] = sorted(set(comps))''')

# ── 4) 필터 적용 ────────────────────────────────────────────────────────────
rep('''        if "title" in filters:
            # 직함은 단어 단위로 맞춘다''',
'''        if "company" in filters:
            # 회사도 단어 단위다. 부분 문자열이면 "대성전자" 가 "대성" 에 걸린다.
            words = normalize(card.get("company") or "").split()
            ok = ok and any(term in words for term in filters["company"])
        if "title" in filters:
            # 직함은 단어 단위로 맞춘다''')

io.open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("회사 필터 OK")
