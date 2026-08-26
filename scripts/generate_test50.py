# 깨끗한 50명 테스트 데이터셋 생성.
# 목적: cards_5000.json은 이름이 근사 중복(강서연/강서영/서서연 등)돼 있어 멀티턴/키워드
# 테스트에 노이즈가 낀다. 이 스크립트는 통제된 소규모 세트를 만든다:
#   - 인물 50명, 회사 45개(=5개 회사는 동료 2명씩), 이름은 48종 중 2종만 의도적으로 동명이인
#   - 모든 필드 채움(빈칸/오염 없음), 전화·이메일·id 전부 유일
#   - "판교+AI 개발자", "판교+디자이너" 등 실제로 찾아지는 조합을 의도적으로 포함
# 사용법: python scripts/generate_test50.py
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "cards_test50.json"

# (name, nameEn) — 48종, 서로 발음/표기가 명확히 구분되게 선정(근사 중복 없음)
NAMES = [
    ("김민준", "Minjun Kim"), ("이서연", "Seoyeon Lee"), ("박도윤", "Doyoon Park"),
    ("최지우", "Jiwoo Choi"), ("정하은", "Haeun Jung"), ("강시우", "Siwoo Kang"),
    ("조유진", "Yoojin Cho"), ("윤도현", "Dohyun Yoon"), ("장서아", "Seoah Jang"),
    ("임재현", "Jaehyun Lim"), ("한소율", "Soyul Han"), ("오승민", "Seungmin Oh"),
    ("서지안", "Jian Seo"), ("신동현", "Donghyun Shin"), ("권나윤", "Nayoon Kwon"),
    ("황준서", "Junseo Hwang"), ("안서윤", "Seoyoon Ahn"), ("송민재", "Minjae Song"),
    ("전예은", "Yeeun Jeon"), ("홍지훈", "Jihoon Hong"), ("유하린", "Harin Yoo"),
    ("문승현", "Seunghyun Moon"), ("양서준", "Seojun Yang"), ("배지호", "Jiho Bae"),
    ("조은우", "Eunwoo Jo"), ("백하윤", "Hayoon Baek"), ("남궁민", "Min Namgung"),
    ("곽서연2", "Seoyeon Kwak"), ("노준혁", "Junhyuk Noh"), ("하지민", "Jimin Ha"),
    ("성유나", "Yuna Sung"), ("차민서", "Minseo Cha"), ("우현우", "Hyunwoo Woo"),
    ("표소민", "Somin Pyo"), ("방지우", "Jiwoo Bang"), ("육서준", "Seojun Yook"),
    ("봉하은", "Haeun Bong"), ("진태양", "Taeyang Jin"), ("마시우", "Siwoo Ma"),
    ("도윤아", "Yoona Do"), ("위지안", "Jian Wi"), ("편서진", "Seojin Pyun"),
    ("감민준2", "Minjun Kam"), ("견우진", "Woojin Gyeon"), ("온하율", "Hayul On"),
    ("예서율", "Seoyul Ye"), ("반지훈", "Jihoon Ban"), ("탁서연2", "Seoyeon Tak"),
]
assert len(NAMES) == 48 and len(set(n for n, _ in NAMES)) == 48

COMPANIES = [
    "(주) 스타테크", "한빛소프트웨어", "유한회사 브릿지파트너스", "주식회사 그린어패럴",
    "(주) 서울로펌", "대한물류", "미래바이오", "(주) 클라우드나인", "한강디자인스튜디오",
    "주식회사 파인애플미디어", "(유) 정도회계법인", "대륙건설", "(주) 네오모빌리티",
    "유한회사 실버라인", "주식회사 오로라테크", "한올제약", "(주) 브라이트인슈어런스",
    "강남치과의원", "주식회사 딥러닝랩", "(유) 하늘물산", "대성전자",
    "주식회사 블루오션컨설팅", "(주) 이든에너지", "한빛건축사사무소", "주식회사 그레이스패션",
    "(유) 파도소프트", "대한식품", "(주) 스카이라인항공", "주식회사 세종회계",
    "한국바이오메드", "(주) 뉴로텍", "유한회사 하나로물류", "주식회사 은하수엔터",
    "(주) 청담법률사무소", "대신증권중개", "주식회사 퓨처모빌리티", "(유) 온새미로디자인",
    "한빛병원", "(주) 그린테크솔루션", "주식회사 아리랑미디어", "(유) 서라벌건설",
    "대명물류시스템", "(주) 다올회계법인", "주식회사 인피니티게임즈", "한올전자부품",
]
assert len(COMPANIES) == 45 and len(set(COMPANIES)) == 45

REGIONS = [
    ("서울특별시 강남구", "테헤란로 231"), ("서울특별시 마포구", "월드컵북로 396"),
    ("서울특별시 영등포구", "여의대로 108"), ("서울특별시 성동구", "왕십리로 115"),
    ("경기도 성남시 분당구", "판교역로 235"),  # 판교
    ("경기도 성남시 분당구", "판교역로 152"),  # 판교
    ("경기도 수원시 영통구", "광교로 107"), ("인천광역시 연수구", "송도과학로 32"),
    ("부산광역시 해운대구", "센텀중앙로 60"), ("대구광역시 수성구", "동대구로 366"),
    ("광주광역시 서구", "상무중앙로 61"), ("대전광역시 유성구", "대학로 291"),
    ("강원특별자치도 춘천시", "중앙로 1"), ("제주특별자치도 제주시", "첨단로 242"),
    ("울산광역시 남구", "삼산로 282"), ("경상남도 창원시 성산구", "창이대로 689"),
]

# (title, department, industry, tags) — 검색 테스트용 조합을 의도적으로 배치
ROLES = [
    ("AI 개발자", "AI개발팀", "it", "AI, 개발자, 머신러닝"),
    ("AI 개발자", "AI개발팀", "it", "AI, 개발자, 판교"),          # 판교+AI개발자 매치용
    ("시니어 디자이너", "디자인팀", "design", "디자인, UX, 판교"),   # 판교+디자이너 매치용
    ("디자이너", "브랜드디자인팀", "design", "디자인, 브랜드"),
    ("변호사", "법무팀", "legal", "법률, 자문, 계약"),
    ("변호사", "송무팀", "legal", "법률, 소송"),
    ("CTO", "기술총괄", "it", "경영, 기술, CTO"),
    ("COO", "경영지원팀", "consulting", "경영, 운영"),
    ("PM", "제품팀", "it", "기획, PM, 제품"),
    ("백엔드 개발자", "플랫폼팀", "it", "개발, 백엔드, 서버"),
    ("프론트엔드 개발자", "플랫폼팀", "it", "개발, 프론트엔드"),
    ("회계사", "재무팀", "finance", "회계, 재무, 감사"),
    ("펀드매니저", "투자팀", "finance", "투자, 금융"),
    ("건축사", "설계팀", "construction", "건축, 설계"),
    ("현장소장", "시공팀", "construction", "건설, 시공"),
    ("마케팅 매니저", "마케팅팀", "media", "마케팅, 브랜딩"),
    ("PD", "콘텐츠제작팀", "media", "콘텐츠, 미디어"),
    ("품질관리자", "품질혁신팀", "manufacturing", "제조, 품질"),
    ("생산관리자", "생산팀", "manufacturing", "제조, 생산"),
    ("물류관리자", "SCM팀", "logistics", "물류, 유통"),
    ("영업팀장", "영업팀", "consulting", "영업, 파트너십"),
    ("컨설턴트", "전략컨설팅팀", "consulting", "컨설팅, 전략"),
    ("연구원", "R&D센터", "biotech", "연구, 바이오"),
    ("약사", "약제팀", "healthcare", "제약, 약사"),
    ("간호사", "간호본부", "healthcare", "의료, 간호"),
    ("보험설계사", "고객관리팀", "insurance", "보험, 상담"),
    ("파일럿", "운항팀", "aviation", "항공, 운항"),
    ("게임 기획자", "기획팀", "entertainment", "게임, 기획"),
    ("교사", "교육기획팀", "education", "교육, 커리큘럼"),
    ("데이터 분석가", "데이터팀", "it", "데이터, 분석"),
]

def phone(i: int) -> str:
    return f"010-{2000 + i:04d}-{7000 + i:04d}"

def email(en: str, i: int, company_slug: str) -> str:
    first = en.split()[0].lower()
    return f"{first}{i:02d}@{company_slug}.com"

def slug(company: str) -> str:
    s = company.replace("(주)", "").replace("(유)", "").replace("주식회사", "").replace("유한회사", "")
    s = "".join(ch for ch in s if ch.isalnum())
    return s.lower()[:10] or "corp"

def build():
    people = []
    # 동명이인 2쌍: 회사/직무는 다르게 -> 각 이름 2회씩 등장(총 4명), 나머지는 46명 유일 이름
    dup_pairs = [
        ("김민준", "Minjun Kim"),  # NAMES 순서상 index 0
        ("이서연", "Seoyeon Lee"),  # index 1
    ]
    names_pool = list(NAMES)
    # 동명이인용 이름은 목록에서 이미 1회씩 들어있으므로, 각각 1명씩 더 추가해 총 50명을 맞춘다.
    all_names = names_pool + dup_pairs  # 48 + 2 = 50
    assert len(all_names) == 50

    companies_assignment = []
    # 45개 회사 중 5개는 2명씩(동료), 40개는 1명씩 -> 10 + 40 = 50명
    for c in COMPANIES[:5]:
        companies_assignment.extend([c, c])
    companies_assignment.extend(COMPANIES[5:])  # 40개
    assert len(companies_assignment) == 50

    for i, ((name, en), company) in enumerate(zip(all_names, companies_assignment)):
        region, road = REGIONS[i % len(REGIONS)]
        role_title, dept, industry, tags = ROLES[i % len(ROLES)]
        addr = f"{region} {road}"
        loc = region
        ph = phone(i)
        em = email(en, i, slug(company))
        memo = f"{['컨퍼런스', '세미나', '박람회', '파트너 미팅', '스터디 모임'][i % 5]}에서 명함을 교환함"
        people.append({
            "id": f"T{i+1:03d}",
            "name": name.replace("2", ""),  # 표기용 원본 이름(동명이인 구분용 접미사 제거)
            "nameEn": en,
            "company": company,
            "title": role_title,
            "department": dept,
            "industry": industry,
            "location": loc,
            "phone": ph,
            "email": em,
            "address": addr,
            "memo": memo,
            "tags": tags,
        })
    # 지역·직무가 독립 순환이라 우연히 안 맞을 수 있어, 테스트용 핵심 조합은 명시적으로 고정한다.
    pangyo_region, pangyo_road = REGIONS[4]  # 판교역로 235
    people[1]["location"] = pangyo_region          # index1 role="AI 개발자"(ROLES[1])
    people[1]["address"] = f"{pangyo_region} {pangyo_road}"
    people[2]["location"] = pangyo_region          # index2 role="시니어 디자이너"(ROLES[2])
    people[2]["address"] = f"{pangyo_region} {REGIONS[5][1]}"
    return people


def main():
    people = build()
    assert len(people) == 50
    names = [p["name"] for p in people]
    dup_names = {n for n in names if names.count(n) > 1}
    assert len(dup_names) == 2, f"동명이인 종류가 2개여야 함: {dup_names}"
    assert sum(names.count(n) for n in dup_names) == 4
    assert len(set(p["company"] for p in people)) == 45
    assert len(set(p["phone"] for p in people)) == 50
    assert len(set(p["email"] for p in people)) == 50
    assert len(set(p["id"] for p in people)) == 50
    for p in people:
        for k, v in p.items():
            assert v, f"{p['id']}의 {k} 필드가 비어있음"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(people, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"생성 완료: {OUT} ({len(people)}명)")
    print(f"동명이인: {sorted(dup_names)}")
    print(f"회사 수: {len(set(p['company'] for p in people))}종")
    pangyo_ai = [p for p in people if "판교" in p["location"] and "AI" in p["title"]]
    pangyo_designer = [p for p in people if "판교" in p["location"] and "디자이너" in p["title"]]
    print(f"판교+AI개발자: {[p['name'] for p in pangyo_ai]}")
    print(f"판교+디자이너: {[p['name'] for p in pangyo_designer]}")


if __name__ == "__main__":
    main()
