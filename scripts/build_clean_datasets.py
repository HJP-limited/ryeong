# 합성 명함 라벨(out/final/labels/*.json)에서 '검색 테스트에 바로 쓸 수 있는' 데이터셋 2개를 만든다.
#
# 왜 새로 만드는가 — 기존 data/cards_5000.json 의 실측 문제:
#   1) location 42% 오염: 주소 없는 카드에서 라벨 프리픽스 잔재("A.")가 그대로 들어가,
#      "A.에 있는 매니저 찾아줘" 같은 말이 안 되는 평가 질의가 생성됐다.
#   2) location 과 address 불일치 가능: 별도 필드로 취급돼 정합성 보장이 없었다.
#   3) industry / tags / memo 가 5000장 전부 비어 있어(0%) 개념 검색(직군·분야)을 못 걸었다.
#   4) 이름 근사 중복이 많아(강서연/강서영/서서연) 채팅 테스트에서 버그와 데이터 노이즈를 구분 못 했다.
#
# 이 스크립트의 규칙:
#   - 주소가 있는 카드만 사용 -> location 을 주소 첫 토큰에서 파생 (항상 일치, 오염 불가)
#   - industry / tags 를 직함·부서·회사명에서 규칙 유도 -> 개념 검색 가능
#   - 라벨 프리픽스 제거는 기존 build_cards_json.py 규칙 재사용
#   - 큰 셋(정량 평가용)과 작은 셋(정성/채팅 테스트용)을 같은 규칙으로 생성해 두 환경의 결과를 비교 가능하게 함
#   - 작은 셋은 이름 근사 중복을 배제하고, 동명이인을 '의도한 개수만' 남긴다
#
# 사용법: python scripts/build_clean_datasets.py
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
LABELS_DIR = REPO.parent / "HJP_limitededition-main" / "out" / "final" / "labels"
OUT_LARGE = REPO / "data" / "cards_clean_large.json"
OUT_SMALL = REPO / "data" / "cards_clean_small.json"

SMALL_TARGET = 60          # 정성 테스트용 크기
SMALL_DUP_NAME_PAIRS = 2   # 동명이인 쌍 수(의도적으로 남길 것)

LABEL_PREFIXES = ("Mobile.", "Tel.", "TEL.", "E-mail.", "Email.", "Address.", "Fax.", "H.P.", "M.", "E.", "A.", "T.")

# 직함/부서 -> (industry, tags) 규칙. 개념 검색("법률 자문 해줄 사람")이 성립하게 하려면
# 카드에 분야 정보가 있어야 한다. 문자 그대로 겹치지 않는 어휘를 tags 에 넣는다.
DOMAIN_RULES = [
    # (판정 키워드들, industry, tags)
    (("변호사", "법무", "고문변호"), "legal", "법률, 자문, 계약, 소송"),
    (("전문의", "진료", "원장", "간호", "약사"), "healthcare", "의료, 진료, 건강, 병원"),
    (("회계", "재무", "CFO", "세무"), "finance", "회계, 재무, 세무, 감사"),
    (("펀드", "투자", "증권", "자산"), "finance", "투자, 금융, 자산운용"),
    (("디자이너", "Designer", "디자인"), "design", "디자인, UX, 브랜딩, 시각"),
    (("Engineer", "SRE", "개발", "Platform", "Staff"), "it", "개발, 엔지니어링, 소프트웨어"),
    (("Data Scientist", "데이터", "AI", "머신러닝"), "it", "인공지능, 데이터, 머신러닝, 분석"),
    (("PM", "Product", "프로덕트", "프로젝트", "기획"), "it", "기획, 제품관리, 로드맵"),
    (("마케팅", "브랜드", "홍보", "CMO", "광고"), "marketing", "마케팅, 브랜딩, 홍보, 광고"),
    (("영업", "세일즈", "사업개발", "파트너"), "sales", "영업, 제휴, 사업개발"),
    (("연구", "R&D", "책임연구", "선임연구", "수석연구"), "research", "연구개발, 실험, 논문"),
    (("물류", "SCM", "유통", "구매"), "logistics", "물류, 유통, 공급망"),
    (("생산", "품질", "QA", "제조"), "manufacturing", "생산, 품질관리, 제조"),
    (("인사", "인재", "총무", "경영지원"), "hr", "인사, 채용, 조직관리"),
    (("보안", "정보보안"), "security", "보안, 침해대응, 인증"),
    (("중개사", "부동산"), "realestate", "부동산, 중개, 임대"),
    (("사무관", "서기관", "주무관"), "public", "공공, 행정, 정책"),
    (("CEO", "대표이사", "회장", "사장", "부사장", "전무", "상무", "본부장", "COO", "CTO", "CPO", "CDO"), "management", "경영, 전략, 의사결정"),
]
DEFAULT_DOMAIN = ("business", "일반사무, 실무")


def strip_label_prefix(text: str) -> str:
    stripped = (text or "").strip()
    for prefix in LABEL_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def region_texts(label: dict) -> dict:
    out = {}
    for region in label.get("regions", []):
        field = region.get("field", "")
        if not field or field in out:
            continue
        out[field] = strip_label_prefix(region.get("text") or "")
    return out


def domain_for(title: str, department: str, company: str):
    """직함 -> 부서 -> 회사명 순으로 분야를 추론한다(먼저 맞는 규칙 채택)."""
    for source in (title, department, company):
        if not source:
            continue
        for keywords, industry, tags in DOMAIN_RULES:
            if any(k.lower() in source.lower() for k in keywords):
                return industry, tags
    return DEFAULT_DOMAIN


def location_from_address(address: str) -> str:
    """'서울특별시 영등포구 영중로 640' -> '서울특별시 영등포구' (시/도 + 시군구까지)."""
    parts = address.split()
    if not parts:
        return ""
    if len(parts) >= 2 and re.search(r"(시|군|구)$", parts[1]):
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def memo_for(company: str, location: str) -> str:
    """검색·RAG 테스트에서 참고할 수 있는 짧은 맥락. 실제 필드가 비어 있으면 검색 신호가 준다."""
    where = location.split()[0] if location else ""
    if company and where:
        return f"{where} {company} 미팅에서 명함 교환"
    if company:
        return f"{company} 미팅에서 명함 교환"
    return "행사에서 명함 교환"


def build_cards():
    """라벨에서 규칙에 맞는 카드만 뽑는다. 주소 없는 카드는 제외(location 오염 원천 차단)."""
    cards = []
    skipped_no_address = skipped_no_name = 0
    for path in sorted(LABELS_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            label = json.load(f)
        fields = region_texts(label)
        name = fields.get("name_ko", "")
        address = fields.get("address_ko", "")
        if not name:
            skipped_no_name += 1
            continue
        if not address:
            skipped_no_address += 1
            continue
        location = location_from_address(address)
        if not location:
            skipped_no_address += 1
            continue
        title = fields.get("title", "")
        department = fields.get("department", "")
        company = fields.get("company_ko", "")
        industry, tags = domain_for(title, department, company)
        cards.append(
            {
                "id": "",  # 아래에서 셋별로 부여
                "name": name,
                "nameEn": fields.get("name_en", ""),
                "company": company,
                "title": title,
                "department": department,
                "industry": industry,
                "location": location,
                "phone": fields.get("mobile", "") or fields.get("tel_office", ""),
                "email": fields.get("email", ""),
                "address": address,
                "memo": memo_for(company, location),
                "tags": tags,
            }
        )
    return cards, skipped_no_address, skipped_no_name


def pick_small(cards, target, dup_pairs):
    """
    정성 테스트용 소규모 셋.
    - 이름 근사 중복(성 제외 2글자가 같은 경우 등)을 배제해 '버그 vs 데이터 노이즈' 구분이 되게 한다.
    - 동명이인은 의도한 쌍 수만 남긴다.
    - 회사는 최대한 겹치지 않게(동료 케이스는 소수만) 고른다.
    """
    by_name = defaultdict(list)
    for c in cards:
        by_name[c["name"]].append(c)

    # 1) 동명이인 후보: 같은 이름이 2명 이상이고 회사가 서로 다른 것
    dup_candidates = [
        name for name, group in sorted(by_name.items())
        if len(group) >= 2 and len({g["company"] for g in group if g["company"]}) >= 2
    ]

    chosen = []
    used_names = set()
    used_given = set()   # 성을 뗀 이름(근사 중복 차단용)
    used_companies = set()

    def given_of(name):
        return name[1:] if len(name) >= 2 else name

    def is_near_dup(name):
        """
        혼동 가능한 이름을 배제한다. 이름 전체(성 포함)를 기준으로 비교해야
        '강도윤 vs 강미영'처럼 성이 같아 헷갈리는 조합도 걸러진다.
        - 성을 뗀 이름이 이미 쓰였으면 배제 (강서연 vs 이서연)
        - 전체 이름이 한 글자만 달라도 배제 (강서연 vs 강서영)
        """
        g = given_of(name)
        if g in used_given:
            return True
        if any(len(g) == len(u) and sum(a != b for a, b in zip(g, u)) <= 1 for u in used_given):
            return True
        return any(
            len(name) == len(u_full) and sum(a != b for a, b in zip(name, u_full)) <= 1
            for u_full in used_names
        )

    for name in dup_candidates:
        if len([1 for c in chosen if c["name"] == name]) or is_near_dup(name):
            continue
        group = [g for g in by_name[name] if g["company"]]
        pair = []
        for g in group:
            if g["company"] not in {p["company"] for p in pair}:
                pair.append(g)
            if len(pair) == 2:
                break
        if len(pair) < 2:
            continue
        chosen.extend(pair)
        used_names.add(name)
        used_given.add(given_of(name))
        used_companies.update(p["company"] for p in pair)
        if sum(1 for n in used_names) >= dup_pairs:
            break

    # 2) 나머지는 이름이 혼동되지 않는 카드로 채운다.
    #    1차: 회사도 유일하게(대부분) -> 2차: 목표 수를 못 채우면 회사 중복을 허용(동료 케이스)
    for allow_same_company in (False, True):
        for c in cards:
            if len(chosen) >= target:
                break
            if not c["company"] or not c["title"]:
                continue
            if c["name"] in used_names or is_near_dup(c["name"]):
                continue
            if not allow_same_company and c["company"] in used_companies:
                continue
            chosen.append(c)
            used_names.add(c["name"])
            used_given.add(given_of(c["name"]))
            used_companies.add(c["company"])
        if len(chosen) >= target:
            break

    return chosen[:target]


def assign_ids(cards, prefix):
    out = []
    for i, c in enumerate(cards):
        d = dict(c)
        d["id"] = f"{prefix}{i:05d}"
        out.append(d)
    return out


def report(name, cards):
    from collections import Counter
    print(f"\n[{name}] {len(cards)}장")
    for f in ("name", "company", "title", "department", "industry", "location", "phone", "email", "address", "memo", "tags"):
        filled = sum(1 for c in cards if (c[f] or "").strip())
        print(f"    {f:11s} 채워짐 {filled}/{len(cards)} ({filled/len(cards):.0%})")
    # 정합성: location 이 address 의 접두어인가
    ok = sum(1 for c in cards if c["address"].startswith(c["location"]))
    print(f"    location↔address 정합 {ok}/{len(cards)} ({ok/len(cards):.0%})")
    names = Counter(c["name"] for c in cards)
    dups = {n: k for n, k in names.items() if k > 1}
    print(f"    동명이인 {len(dups)}종 {dups if len(dups) <= 5 else ''}")
    print(f"    회사 {len({c['company'] for c in cards})}종, 지역 {len({c['location'] for c in cards})}종, "
          f"industry {len({c['industry'] for c in cards})}종")


def main():
    if not LABELS_DIR.is_dir():
        sys.exit(f"labels dir not found: {LABELS_DIR}")
    cards, skipped_addr, skipped_name = build_cards()
    print(f"라벨에서 사용 가능 카드 {len(cards)}장 (주소 없어 제외 {skipped_addr}, 이름 없어 제외 {skipped_name})")

    large = assign_ids(cards, "L")
    small = assign_ids(pick_small(cards, SMALL_TARGET, SMALL_DUP_NAME_PAIRS), "T")

    OUT_LARGE.parent.mkdir(parents=True, exist_ok=True)
    OUT_LARGE.write_text(json.dumps(large, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    OUT_SMALL.write_text(json.dumps(small, ensure_ascii=False, indent=2), encoding="utf-8")

    report("정량 평가용(large)", large)
    report("정성/채팅 테스트용(small)", small)
    print(f"\nwrote {OUT_LARGE}")
    print(f"wrote {OUT_SMALL}")


if __name__ == "__main__":
    main()
