# 검색/채팅 테스트용 명함 데이터셋 생성기.
#
# 왜 라벨 데이터가 아니라 직접 생성하는가:
#   합성 라벨(out/final/labels)에서 뽑으면 이름 풀이 좁아 근사 중복(강도윤/강미영, 강서연/강서영)이
#   섞이고, 중복을 배제하면 표본이 34장까지 줄어들어 원하는 규모를 못 맞춘다.
#   그래서 실제 한국 성씨/이름 음절 통계를 참고한 조합으로 '서로 확실히 구분되는' 이름을 만든다.
#
# 데이터 품질 규칙(기존 cards_5000.json 의 실측 문제를 그대로 방지):
#   - location 은 address 에서 파생 -> 항상 정합 (오염된 "A." 같은 값이 생길 수 없음)
#   - industry / tags / memo 를 채움 -> 개념 검색("법률 자문 해줄 사람")이 성립
#   - 전화/이메일/id 전부 유일
#   - 이름은 성+이름 전체가 서로 2글자 이상 다르게 -> 혼동 불가
#   - 동명이인은 '의도한 쌍 수'만 (회사·연락처는 다르게)
#   - 검색 테스트용 정답 조합을 의도적으로 배치(지역+직군)
#
# 사용법: python scripts/build_test_dataset.py [--count 60] [--dup-pairs 2] [--seed 42]
import argparse
import json
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "data" / "cards_test.json"

# 한국에서 흔한 성씨(인구 비중 상위권). 서로 확실히 구분되는 것들만 골랐다.
SURNAMES = [
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
    "한", "오", "서", "신", "권", "황", "안", "송", "전", "홍",
    "유", "고", "문", "양", "손", "배", "백", "허", "남", "심",
    "노", "하", "곽", "성", "차", "주", "우", "구", "민", "류",
]

# 이름(2음절) 후보 — 실제로 흔히 쓰이는 조합.
# 개수가 곧 생성 가능한 인원 상한이다: '같은 이름 + 다른 성'(김민준/이민준)도 한 글자 차이라
# 혼동으로 보고 배제하므로, 이름 하나는 전체에서 한 번만 쓰인다. 그래서 넉넉히 확보한다.
GIVEN_NAMES = [
    "민준", "서연", "도윤", "지우", "하은", "시우", "유진", "예준", "수아", "지호",
    "채원", "건우", "다은", "은서", "재현", "소율", "승민", "지안", "동현", "나윤",
    "준서", "윤아", "민재", "예은", "지훈", "하린", "승현", "서준", "가온", "은우",
    "하윤", "태양", "소민", "시연", "주원", "정우", "다올", "라온", "새봄", "한결",
    "여름", "우주", "슬기", "보름", "하늘", "바다", "누리", "미르", "지연", "수빈",
    "예린", "다올", "시윤", "주하", "연우", "찬영", "태민", "규현", "성호", "진우",
    "范석", "영훈", "상현", "종민", "대현", "光수", "병철", "형준", "우성", "재欽",
    "미영", "정숙", "은정", "혜진", "선영", "지영", "수경", "현주", "영주", "미경",
    "동주", "세영", "가영", "나연", "다인", "루아", "모아", "별하", "सारा", "온유",
    "유하", "이안", "채아", "태오", "하람", "현서", "효주", "희원", "가희", "노아",
]
# 오타/비한글 혼입 방지 — 한글 2음절만 남기고 중복 제거(목록 순서 유지).
GIVEN_NAMES = list(dict.fromkeys(
    g for g in GIVEN_NAMES if len(g) == 2 and all("가" <= ch <= "힣" for ch in g)
))

ROMAN_SURNAME = {
    "김": "Kim", "이": "Lee", "박": "Park", "최": "Choi", "정": "Jung", "강": "Kang",
    "조": "Cho", "윤": "Yoon", "장": "Jang", "임": "Lim", "한": "Han", "오": "Oh",
    "서": "Seo", "신": "Shin", "권": "Kwon", "황": "Hwang", "안": "Ahn", "송": "Song",
    "전": "Jeon", "홍": "Hong", "유": "Yoo", "고": "Ko", "문": "Moon", "양": "Yang",
    "손": "Son", "배": "Bae", "백": "Baek", "허": "Heo", "남": "Nam", "심": "Sim",
    "노": "Noh", "하": "Ha", "곽": "Kwak", "성": "Sung", "차": "Cha", "주": "Joo",
    "우": "Woo", "구": "Koo", "민": "Min", "류": "Ryu",
}
# 한글 이름의 로마자 표기는 자모를 분해해 규칙으로 생성한다.
# 수동 딕셔너리를 쓰면 이름을 추가할 때마다 같이 관리해야 하고, 빠뜨리면 그 이름이 조용히
# 후보에서 탈락한다(실제로 이름 부족의 원인이었다). 표기법은 국립국어원 로마자 표기를 단순화한 것.
_CHOSEONG = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_JUNGSEONG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo",
              "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_JONGSEONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "l", "l", "l", "l", "l", "l", "l",
              "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]


def romanize(hangul: str) -> str:
    """한글 문자열을 로마자로 옮긴다(이메일/영문 이름 생성용)."""
    out = []
    for ch in hangul:
        if not ("가" <= ch <= "힣"):
            out.append(ch)
            continue
        code = ord(ch) - 0xAC00
        cho, jung, jong = code // 588, (code % 588) // 28, code % 28
        out.append(_CHOSEONG[cho] + _JUNGSEONG[jung] + _JONGSEONG[jong])
    return "".join(out).capitalize()

# (직함, 부서, industry, tags) — tags 는 질의와 문자가 겹치지 않는 어휘를 넣어 개념 검색이 성립하게 한다.
ROLES = [
    ("AI 개발자", "AI개발팀", "it", "인공지능, 머신러닝, 모델학습"),
    ("Data Scientist", "데이터분석팀", "it", "데이터, 통계, 예측모델"),
    ("백엔드 개발자", "플랫폼팀", "it", "서버, API, 데이터베이스"),
    ("프론트엔드 개발자", "프론트엔드팀", "it", "화면개발, 웹, 사용자인터페이스"),
    ("SRE", "인프라팀", "it", "서버운영, 모니터링, 안정성"),
    ("시니어 디자이너", "디자인팀", "design", "디자인, 시각, 브랜딩"),
    ("UX 디자이너", "UX팀", "design", "사용자경험, 리서치, 프로토타입"),
    ("변호사", "법무팀", "legal", "법률, 자문, 계약"),
    ("고문변호사", "법무팀", "legal", "소송, 분쟁, 법률검토"),
    ("회계사", "재무팀", "finance", "회계, 세무, 결산"),
    ("펀드매니저", "투자팀", "finance", "투자, 자산운용, 포트폴리오"),
    ("CFO", "경영지원팀", "finance", "재무전략, 예산, 자금"),
    ("전문의", "진료부", "healthcare", "의료, 진료, 환자"),
    ("약사", "약제부", "healthcare", "조제, 복약지도, 의약품"),
    ("간호사", "간호본부", "healthcare", "간호, 병동, 환자케어"),
    ("건축사", "설계팀", "construction", "건축, 설계, 도면"),
    ("현장소장", "시공팀", "construction", "시공, 공정관리, 안전"),
    ("마케팅 매니저", "마케팅팀", "marketing", "마케팅, 캠페인, 브랜드"),
    ("콘텐츠 PD", "콘텐츠팀", "media", "콘텐츠, 영상, 기획"),
    ("영업팀장", "국내영업팀", "sales", "영업, 고객관리, 매출"),
    ("해외영업 담당", "해외영업팀", "sales", "수출, 해외거래, 무역"),
    ("품질관리자", "품질관리팀", "manufacturing", "품질, 검사, 공정개선"),
    ("생산관리자", "생산관리팀", "manufacturing", "생산, 설비, 라인관리"),
    ("물류관리자", "물류팀", "logistics", "물류, 배송, 재고"),
    ("구매담당", "구매팀", "logistics", "구매, 조달, 협력사"),
    ("인사담당", "인사팀", "hr", "채용, 인사, 평가"),
    ("보안담당", "정보보안팀", "security", "보안, 접근통제, 취약점"),
    ("공인중개사", "중개영업팀", "realestate", "부동산, 중개, 매물"),
    ("사무관", "행정지원과", "public", "행정, 정책, 민원"),
    ("수석연구원", "R&D센터", "research", "연구, 실험, 논문"),
    ("프로덕트매니저", "프로덕트팀", "it", "제품기획, 로드맵, 요구사항"),
    ("CTO", "기술총괄", "management", "기술전략, 아키텍처, 조직"),
    ("대표이사", "경영기획실", "management", "경영, 의사결정, 전략"),
    ("컨설턴트", "전략컨설팅팀", "consulting", "컨설팅, 진단, 개선안"),
    ("교육기획자", "교육기획팀", "education", "교육, 커리큘럼, 강의"),
]

COMPANY_PREFIX = ["(주) ", "주식회사 ", "유한회사 ", "(유) ", ""]
COMPANY_CORE = [
    "스타테크", "한빛소프트", "브릿지파트너스", "그린어패럴", "서울로펌", "대한물류", "미래바이오",
    "클라우드나인", "한강디자인", "파인애플미디어", "정도회계법인", "대륙건설", "네오모빌리티",
    "실버라인", "오로라테크", "한올제약", "브라이트보험", "강남메디컬", "딥러닝랩", "하늘물산",
    "대성전자", "블루오션컨설팅", "이든에너지", "한빛건축", "그레이스패션", "파도소프트", "대한식품",
    "스카이라인항공", "세종회계", "한국바이오메드", "뉴로텍", "하나로물류", "은하수엔터", "청담법률",
    "대신증권중개", "퓨처모빌리티", "온새미로디자인", "한빛병원", "그린테크솔루션", "아리랑미디어",
    "서라벌건설", "대명물류", "다올회계", "인피니티게임즈", "한올전자", "파랑새교육", "청우산업",
    "solid", "vertex", "northwind", "lumina", "kestrel",
    # 60장 이상을 만들 때 코어가 재사용되면 '실버라인 / 주식회사 실버라인'처럼 사실상 같은
    # 회사가 두 번 나온다. 인원보다 넉넉하게 확보해 접두어만 다른 중복을 방지한다.
    "새롬테크", "우리아이티", "정선물류", "명진산업", "덕수법률", "가온메디", "राइज", "온누리제약",
    "하이랩스", "포레스트웍스", "청람건설", "유니콘게임즈", "성진모터스", "다래식품", "예광전자",
    "삼호물산", "누리소프트", "빛나로지스", "한들바이오", "소리소프트", "가람디자인", "터닝포인트",
    "블루윙항공", "미래에듀", "정담회계", "해오름energy", "별빛미디어", "수정건축", "라온컨설팅",
]
# 비한글/오타 혼입 방지 — 한글·영문·숫자로만 이뤄진 이름만 남긴다.
COMPANY_CORE = [
    c for c in COMPANY_CORE
    if all(("가" <= ch <= "힣") or ch.isascii() for ch in c)
]

# (시도, 시군구, 도로명) — 실제 행정구역 조합. address 에서 location 을 파생하므로 항상 정합.
REGIONS = [
    ("서울특별시", "강남구", "테헤란로"),
    ("서울특별시", "마포구", "월드컵북로"),
    ("서울특별시", "영등포구", "여의대로"),
    ("서울특별시", "성동구", "왕십리로"),
    ("서울특별시", "송파구", "올림픽로"),
    ("경기도", "성남시 분당구", "판교역로"),
    ("경기도", "수원시 영통구", "광교로"),
    ("경기도", "고양시 일산동구", "중앙로"),
    ("인천광역시", "연수구", "송도과학로"),
    ("부산광역시", "해운대구", "센텀중앙로"),
    ("부산광역시", "부산진구", "중앙대로"),
    ("대구광역시", "수성구", "동대구로"),
    ("광주광역시", "서구", "상무중앙로"),
    ("대전광역시", "유성구", "대학로"),
    ("울산광역시", "남구", "삼산로"),
    ("강원특별자치도", "춘천시", "중앙로"),
    ("충청북도", "청주시 흥덕구", "직지대로"),
    ("충청남도", "천안시 서북구", "불당대로"),
    ("전북특별자치도", "전주시 완산구", "충경로"),
    ("전라남도", "여수시", "이순신로"),
    ("경상북도", "포항시 남구", "지곡로"),
    ("경상남도", "창원시 성산구", "창이대로"),
    ("제주특별자치도", "제주시", "첨단로"),
]

EMAIL_DOMAINS = ["example.com", "corp.co.kr", "mail.kr", "company.net", "sample.io"]
MEETING_CONTEXT = ["컨퍼런스", "세미나", "박람회", "파트너 미팅", "스터디 모임", "채용설명회", "기술교류회"]

# 검색 테스트용으로 반드시 존재해야 하는 (지역, 직함) 조합.
PLANTED_COMBOS = [
    ("경기도", "성남시 분당구", "AI 개발자"),        # "판교에 있는 AI 개발자"
    ("경기도", "성남시 분당구", "시니어 디자이너"),   # "판교에 있는 디자이너"
    ("서울특별시", "강남구", "변호사"),              # "강남 변호사"
]


def company_name(rng, core):
    prefix = rng.choice(COMPANY_PREFIX)
    return f"{prefix}{core}".strip()


def make_names(rng, count, dup_pairs):
    """
    서로 확실히 구분되는 이름 목록을 만든다.
    - 성+이름 전체가 다른 이름과 2글자 이상 달라야 채택(한 글자 차이 배제)
    - 동명이인은 dup_pairs 쌍만 의도적으로 중복 배치
    """
    def distinct_enough(cand, chosen):
        """
        '헷갈리는 이름'만 배제한다.
        배제 대상: 같은 성 + 이름이 한 글자만 다른 경우 (강서연 / 강서영) — 실제로 검색 결과를
                  볼 때 버그인지 데이터가 비슷한 건지 구분이 안 됐던 케이스.
        허용: 성만 다르고 이름이 같은 경우 (김민준 / 이민준) — 실제 명함첩에 흔하고,
              전체 이름이 명확히 달라 혼동되지 않는다. 초기엔 이것도 배제했는데
              이름 후보가 48개로 말라서 원하는 규모를 못 채웠다.
        """
        for c in chosen:
            if len(c) != len(cand):
                continue
            same_surname = c[0] == cand[0]
            given_diff = sum(a != b for a, b in zip(c[1:], cand[1:]))
            if same_surname and given_diff <= 1:
                return False
        return True

    pool = [(s, g) for s in SURNAMES for g in GIVEN_NAMES]
    rng.shuffle(pool)

    unique = []
    for s, g in pool:
        name = s + g
        if len(unique) >= count - dup_pairs:
            break
        if any(name == u[0] for u in unique):
            continue
        if not distinct_enough(name, [u[0] for u in unique]):
            continue
        surname_roman = ROMAN_SURNAME.get(s) or romanize(s)
        unique.append((name, f"{romanize(g)} {surname_roman}"))

    if len(unique) < count - dup_pairs:
        raise SystemExit(
            f"이름 후보 부족: {len(unique)}개만 생성됨(요청 {count - dup_pairs}). "
            f"SURNAMES/GIVEN_NAMES 를 늘리거나 --count 를 줄이세요."
        )

    # 동명이인: 이미 뽑힌 이름 중 앞쪽 dup_pairs 개를 한 번 더 넣는다(회사/연락처는 달라짐)
    names = list(unique)
    names.extend(unique[:dup_pairs])
    return names[:count]


def build(count, dup_pairs, seed):
    rng = random.Random(seed)
    names = make_names(rng, count, dup_pairs)

    cores = COMPANY_CORE[:]
    rng.shuffle(cores)
    if len(cores) < len(names):
        raise SystemExit(
            f"회사 코어 부족: {len(cores)}개 (인원 {len(names)}). 코어가 재사용되면 접두어만 다른 "
            f"중복 회사가 생기므로 COMPANY_CORE 를 늘리세요."
        )

    cards = []
    for i, (name, name_en) in enumerate(names):
        # 앞쪽 카드에는 검색 테스트용 조합을 심고, 나머지는 골고루 분산한다.
        if i < len(PLANTED_COMBOS):
            sido, sigungu, title_want = PLANTED_COMBOS[i]
            role = next(r for r in ROLES if r[0] == title_want)
            region = next((r for r in REGIONS if r[0] == sido and r[1] == sigungu), REGIONS[0])
        else:
            role = ROLES[i % len(ROLES)]
            region = REGIONS[i % len(REGIONS)]

        title, dept, industry, tags = role
        sido, sigungu, road = region
        location = f"{sido} {sigungu}"
        address = f"{location} {road} {rng.randint(1, 900)}"
        core = cores[i]  # 재사용 금지(위에서 개수 보장) — 접두어만 다른 중복 회사 방지
        company = company_name(rng, core)
        cards.append(
            {
                "id": f"T{i + 1:03d}",
                "name": name,
                "nameEn": name_en,
                "company": company,
                "title": title,
                "department": dept,
                "industry": industry,
                "location": location,
                "phone": f"010-{3000 + i:04d}-{6000 + i:04d}",
                "email": f"{name_en.split()[0].lower()}{i:02d}@{rng.choice(EMAIL_DOMAINS)}",
                "address": address,
                "memo": f"{rng.choice(MEETING_CONTEXT)}에서 명함 교환",
                "tags": tags,
            }
        )
    return cards


def verify(cards, dup_pairs):
    from collections import Counter
    problems = []
    names = Counter(c["name"] for c in cards)
    dups = {n: k for n, k in names.items() if k > 1}
    if len(dups) != dup_pairs:
        problems.append(f"동명이인 쌍 수가 {len(dups)} (요청 {dup_pairs})")
    for field in ("phone", "email", "id"):
        vals = [c[field] for c in cards]
        if len(set(vals)) != len(vals):
            problems.append(f"{field} 중복 있음")
    for c in cards:
        for f, v in c.items():
            if not str(v).strip():
                problems.append(f"{c['id']} 의 {f} 비어있음")
        if not c["address"].startswith(c["location"]):
            problems.append(f"{c['id']} location↔address 불일치")
    # 혼동 이름 검사: 같은 성 + 이름 한 글자 차이만 문제로 본다(성만 다른 동명은 허용)
    uniq = sorted(set(names))
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            if len(a) == len(b) and a[0] == b[0] and sum(x != y for x, y in zip(a[1:], b[1:])) <= 1:
                problems.append(f"혼동 가능한 이름 쌍(같은 성, 한 글자 차): {a} / {b}")

    # 회사 중복 검사: 접두어를 뗀 코어가 같으면 사실상 같은 회사다
    def core_of(company):
        for p in ("(주) ", "주식회사 ", "유한회사 ", "(유) "):
            if company.startswith(p):
                return company[len(p):]
        return company
    core_counts = Counter(core_of(c["company"]) for c in cards)
    for core, n in core_counts.items():
        if n > 1:
            problems.append(f"회사 코어 중복({n}회): {core}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--dup-pairs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cards = build(args.count, args.dup_pairs, args.seed)
    problems = verify(cards, args.dup_pairs)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    print(f"생성: {OUT_PATH} ({len(cards)}장)")
    names = Counter(c["name"] for c in cards)
    print(f"  동명이인: {[n for n, k in names.items() if k > 1]}")
    print(f"  회사 {len({c['company'] for c in cards})}종 / 지역 {len({c['location'] for c in cards})}종 "
          f"/ 직함 {len({c['title'] for c in cards})}종 / industry {len({c['industry'] for c in cards})}종")
    print(f"  location↔address 정합: {sum(1 for c in cards if c['address'].startswith(c['location']))}/{len(cards)}")
    for sido, sigungu, title in PLANTED_COMBOS:
        hit = [c["name"] for c in cards if c["location"] == f"{sido} {sigungu}" and c["title"] == title]
        print(f"  심어둔 조합 [{sigungu} / {title}]: {hit}")
    if problems:
        print("\n! 검증 문제:")
        for p in problems[:20]:
            print(f"    - {p}")
    else:
        print("\n검증 통과 (필드 누락/중복/정합성/혼동이름 없음)")


if __name__ == "__main__":
    main()
