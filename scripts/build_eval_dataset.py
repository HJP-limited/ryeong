# 평가·단위테스트 공용 데이터셋(1000장)을 만든다.
#
# 왜 만드는가:
#   - cards_5000.json(프로덕션/APK 시드)은 실전 분포는 맞지만, 기권 검증에 필요한
#     '데이터에 없는 값'이 거의 없다(세종특별자치시가 63장 들어 있어 "없는 지역" 테스트 불가).
#   - cards_test.json(60장)은 그걸 위해 통제된 셋이지만 규모가 작고 분포가 실전과 달라서
#     (예: 'AI'가 60장은 직함에, 5000장은 부서에만 있음) 소규모셋 결과를 일반화하면 틀린다.
#     실제로 이 차이 때문에 "직함 필터가 이득"이라는 잘못된 결론을 낸 적이 있다.
#   => 실전 분포 + 통제 시나리오를 한 셋에 담아, 평가와 단위테스트가 같은 데이터를 쓰게 한다.
#
# 사용법: python scripts/build_eval_dataset.py
#   그 다음 임베딩도 만들어야 시맨틱 축을 평가할 수 있다:
#   python scripts/precompute_embeddings.py --cards data/cards_eval1000.json \
#       --out-ids data/cards_eval1000_ids.json --out-vectors data/cards_eval1000_vectors.bin
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
BIG_PATH = REPO / "data" / "cards_5000.json"
SMALL_PATH = REPO / "data" / "cards_test.json"
OUT_PATH = REPO / "data" / "cards_eval1000.json"

TARGET = 1000
SEED = 42

# 기권("없는 걸 없다고 하는가")을 검증하려면 이 값들이 데이터에 **없어야** 한다.
# 5000장에는 세종특별자치시가 63장 있어서 그대로 쓰면 이 테스트가 성립하지 않는다.
ABSENT_REGIONS = ("세종특별자치시",)

# 반드시 들어가야 하는 시나리오 — 개수는 '최소 보장치'다.
# (이 세션에서 실제로 버그가 났던 지점들이라 회귀 검증에 필요하다)
REQUIRED = {
    # 직함/지역 충돌: '상무'는 직함이면서 광주 '상무대로'의 어간이기도 하다.
    # 판정 순서(직함 우선)가 깨지면 진짜 상무가 전멸하므로 양쪽 다 있어야 한다.
    "title_상무": (lambda c: "상무" in (c.get("title") or "").split(), 30),
    "addr_상무대로": (lambda c: "상무대로" in (c.get("address") or ""), 8),
    "title_수석": (lambda c: "수석" in (c.get("title") or "").split(), 20),
    # 합성 직함: '변호사'(단어)와 '고문변호사'(붙여쓰기)가 같이 있어야
    # 단어 매칭 한계와 정렬 동작을 검증할 수 있다.
    "title_변호사": (lambda c: "변호사" in (c.get("title") or "").split(), 40),
    "title_고문변호사": (lambda c: (c.get("title") or "").strip() == "고문변호사", 20),
    # 부서에만 있는 값(카운트 경로 전용 어휘) — "AI 개발자 몇 명?"
    "dept_ai": (lambda c: "ai" in (c.get("department") or "").lower(), 20),
    # 지역 조건/카운트
    "addr_판교": (lambda c: "판교" in (c.get("address") or ""), 8),
}


# ---------------------------------------------------------------------------
# 주소 재생성용 — 시/도 ↔ 시군구 대응표
#
# 원본은 Faker(ko_KR)가 광역시/도와 시군구를 **무작위로 조합**해서 만들어 지리적으로
# 말이 안 되는 주소가 5.3% 있었다("대전광역시 동작구", "대구광역시 송파구" — 동작구·송파구는
# 서울 전용). Faker 의 provider 자체가 둘을 따로 들고 랜덤 결합하는 구조라 그대로는 못 고친다.
# 그래서 올바른 대응표를 두고 여기서만 뽑는다.
REGION_DISTRICTS = {
    "서울특별시": ["종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구",
                "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구",
                "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구",
                "서초구", "강남구", "송파구", "강동구"],
    "부산광역시": ["중구", "서구", "동구", "영도구", "부산진구", "동래구", "남구", "북구",
                "해운대구", "사하구", "금정구", "강서구", "연제구", "수영구", "사상구", "기장군"],
    "대구광역시": ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군"],
    "인천광역시": ["중구", "동구", "미추홀구", "연수구", "남동구", "부평구", "계양구", "서구", "강화군"],
    "광주광역시": ["동구", "서구", "남구", "북구", "광산구"],
    "대전광역시": ["동구", "중구", "서구", "유성구", "대덕구"],
    "울산광역시": ["중구", "남구", "동구", "북구", "울주군"],
    "경기도": ["수원시 장안구", "수원시 팔달구", "수원시 영통구", "성남시 분당구",
             "성남시 수정구", "고양시 일산동구", "고양시 덕양구", "용인시 기흥구",
             "용인시 수지구", "부천시", "안양시 동안구", "안산시 단원구", "화성시",
             "남양주시", "평택시", "시흥시", "파주시", "김포시", "광명시", "군포시"],
    "강원특별자치도": ["춘천시", "원주시", "강릉시", "동해시", "속초시", "삼척시", "홍천군", "평창군"],
    "충청북도": ["청주시 상당구", "청주시 서원구", "청주시 흥덕구", "충주시", "제천시", "음성군", "진천군"],
    "충청남도": ["천안시 동남구", "천안시 서북구", "아산시", "서산시", "당진시", "공주시", "논산시"],
    "전북특별자치도": ["전주시 완산구", "전주시 덕진구", "군산시", "익산시", "정읍시", "남원시"],
    "전라남도": ["목포시", "여수시", "순천시", "나주시", "광양시", "무안군", "해남군"],
    "경상북도": ["포항시 남구", "포항시 북구", "경주시", "구미시", "안동시", "김천시", "경산시"],
    "경상남도": ["창원시 성산구", "창원시 의창구", "진주시", "김해시", "양산시", "거제시", "통영시"],
    "제주특별자치도": ["제주시", "서귀포시"],
}

# 지역색이 없는 일반 도로명 — 어느 지역에 붙어도 어색하지 않다.
GENERIC_ROADS = ["중앙로", "중앙대로", "시청로", "역전로", "대학로", "산업로", "번영로",
                 "평화로", "고운로", "새터로", "한밭로", "가온로", "미래로", "행복로",
                 "우암로", "학사로", "月드컵로".replace("月", "월"), "공단로", "송정로", "만세로"]

# 그 지역에 실제로 있는 도로명 — 지역 검색 테스트에 쓰이므로 정확히 붙인다.
REGION_ROADS = {
    ("경기도", "성남시 분당구"): ["판교역로", "분당내곡로", "황새울로"],
    ("광주광역시", "서구"): ["상무대로", "상무중앙로", "치평로"],
    ("서울특별시", "강남구"): ["테헤란로", "봉은사로", "영동대로"],
    ("서울특별시", "송파구"): ["올림픽로", "위례성대로"],
    ("부산광역시", "해운대구"): ["해운대해변로", "센텀중앙로"],
    ("대전광역시", "유성구"): ["대덕대로", "엑스포로"],
}

# 부서 — 직함과 어울리는 것을 붙인다(실제 명함처럼 보이게).
# 원본은 부서가 68% 비어 있었고 종류도 적었다.
DEPARTMENTS_BY_ROLE = {
    "법무": ["법무팀", "송무팀", "법무지원팀", "컴플라이언스팀", "자문팀"],
    "디자인": ["디자인팀", "UX팀", "브랜드디자인팀", "프로덕트디자인팀", "크리에이티브팀"],
    "개발": ["개발1팀", "개발2팀", "플랫폼개발팀", "모바일개발팀", "프론트엔드팀",
           "백엔드팀", "인프라팀", "DevOps팀", "QA팀", "데이터플랫폼팀"],
    "AI": ["AI개발팀", "AI연구소", "데이터사이언스팀", "ML플랫폼팀"],
    "재무": ["재무팀", "회계팀", "자금팀", "세무팀", "IR팀"],
    "영업": ["국내영업팀", "해외영업팀", "영업기획팀", "채널영업팀", "파트너십팀"],
    "마케팅": ["마케팅팀", "브랜드전략팀", "퍼포먼스마케팅팀", "홍보팀", "콘텐츠팀"],
    "인사": ["인사팀", "인재개발팀", "채용팀", "노무팀"],
    "기획": ["전략기획팀", "사업기획팀", "프로덕트팀", "서비스기획팀", "PMO"],
    "의료": ["진료부", "간호본부", "약제팀", "의료지원팀"],
    "연구": ["연구개발팀", "R&D센터", "선행연구팀", "기술연구소"],
    "생산": ["생산관리팀", "품질관리팀", "구매팀", "물류팀", "설비팀"],
    "경영": ["경영지원팀", "총무팀", "경영기획실", "감사팀"],
    "고객": ["고객관리팀", "CS팀", "고객경험팀"],
}

# 직함에 이 단어가 있으면 해당 부서군에서 뽑는다.
ROLE_KEYWORDS = [
    ("법무", ["변호사", "법무", "법률"]),
    ("AI", ["ai", "데이터", "data", "scientist", "머신러닝"]),
    ("개발", ["개발자", "엔지니어", "engineer", "sre", "devops", "프론트엔드", "백엔드",
            "아키텍트", "테크", "cto", "보안"]),
    ("디자인", ["디자이너", "디자인", "ux", "ui", "크리에이티브", "cdo"]),
    ("재무", ["회계", "재무", "cfo", "펀드", "자금", "세무", "감사"]),
    ("영업", ["영업", "세일즈", "sales", "중개사"]),
    ("마케팅", ["마케팅", "브랜드", "홍보", "cmo", "광고", "콘텐츠", "pd"]),
    ("인사", ["인사", "hr", "채용", "노무"]),
    ("기획", ["기획", "pm", "product manager", "프로젝트매니저", "프로덕트", "컨설턴트", "cpo"]),
    ("의료", ["의사", "전문의", "간호", "약사", "진료", "원장"]),
    ("연구", ["연구", "researcher", "선임연구원", "책임연구원"]),
    ("생산", ["생산", "품질", "구매", "물류", "현장", "설비", "건축", "시공"]),
    ("고객", ["고객", "cs", "상담"]),
]

# 임원은 부서를 안 적는 경우가 많다 — 그 현실성을 남긴다.
EXECUTIVE_TITLES = ("대표이사", "회장", "사장", "부사장", "전무", "상무", "이사", "본부장", "센터장")

# 부서를 채울 비율(임원 제외 대상 중). 100% 로 채우면 오히려 부자연스럽다.
DEPARTMENT_FILL_RATE = 0.85


# 복성(남궁·독고·황보)은 원본 5000장에 33건 있고, **원본의 nameEn 이 이미 깨져 있다**:
#   남궁민서 -> "Gungminseo Nam"  (성을 '남', 이름을 '궁민서'로 오분해)
#   독고우진 -> "Goujin Dog"
# 그래서 이 쌍을 그대로 학습하면 이름 풀에 '궁민서'·'고우진'·'보름' 같은 조각이 들어가고,
# 그게 아무 성에나 붙어 '라궁지아'·'하고우진' 같은 없는 이름이 만들어진다(실제로 153건 발생).
#
# 대응: 성/이름 로마자를 학습할 때 복성으로 시작하는 카드를 **통째로 건너뛴다**.
# 5000장 중 33건뿐이라 풀 손실은 무시할 수준이고, 오염원을 입구에서 막는 게 가장 확실하다.
# (복성을 '2글자 성'으로 분해하는 쪽은 시도했다가 '황보름'을 '황보'+'름'으로 잘못 갈라
#  '남궁름' 같은 이름을 만들었다. 원본 로마자가 없어 복원할 근거도 없다.)
COMPOUND_SURNAMES = ("남궁", "독고", "황보", "선우", "제갈", "사공", "서문")

# 동명이인 비율 목표. 합성 데이터가 이름 풀이 좁아 5000장은 83.9%, 원본 1000장은 51.4%가
# 동명이인이었다(김서영 30명). 그러면 이름 기반 휴리스틱을 검증할 수가 없고 이름 질의
# 지표도 부풀려진다(정답이 30명이면 top-5를 아무렇게나 채워도 다 맞음).
# 실제 명함첩에 가깝게 낮추되, 동명이인 처리 자체는 검증해야 하므로 0 으로 만들지는 않는다.
DUPLICATE_RATE = 0.03

# 테스트가 의존하는 이름은 개수까지 보존한다(CardGazetteerTest).
PINNED_NAMES = {"안정우": 1, "하채원": 2}


def split_name(name):
    """성/이름 분리. 이 데이터는 성이 항상 1글자다(위 주석 참고)."""
    return name[:1], name[1:]


def build_roman_maps(*card_sets):
    """
    데이터의 (name, nameEn) 쌍에서 성/이름 로마자 표기를 학습한다.
    복성 카드는 원본 nameEn 이 깨져 있으므로 학습에서 제외한다(위 주석 참고).
    """
    sur, giv = {}, {}
    for cards in card_sets:
        for c in cards:
            nm = (c.get("name") or "").strip()
            en = (c.get("nameEn") or "").strip()
            if len(nm) < 2 or " " not in en:
                continue
            if nm.startswith(COMPOUND_SURNAMES):
                continue
            given_en, sur_en = en.rsplit(" ", 1)
            s, g = split_name(nm)
            sur.setdefault(s, sur_en)
            giv.setdefault(g, given_en)
    return sur, giv


def regenerate_names(cards, rng, sur_map, giv_map):
    """
    이름을 넓은 풀에서 다시 배정해 동명이인을 현실적인 수준으로 낮춘다.
    nameEn/email 도 함께 바꿔 일관성을 유지한다(email 은 로마자 이름에서 파생되므로,
    이름만 바꾸면 '김정' 카드에 'anjunseo@...' 같은 불일치가 생긴다).
    원본의 빈값/접두어("E. ") 패턴과 도메인은 그대로 보존한다.
    """
    combos = [(s, g) for s in sur_map for g in giv_map]
    rng.shuffle(combos)
    banned = {"정하은", "홍길동"}  # 기권 검증용으로 없어야 하는 이름
    combos = [(s, g) for s, g in combos if s + g not in banned and s + g not in PINNED_NAMES]

    n = len(cards)
    n_dup_cards = int(n * DUPLICATE_RATE)
    pinned_total = sum(PINNED_NAMES.values())

    # 배정할 이름 목록을 먼저 만든다: 고정 이름 + 중복 이름 + 나머지 고유 이름
    assign = []
    for nm, cnt in PINNED_NAMES.items():
        assign += [nm] * cnt
    idx = 0
    while len(assign) < pinned_total + n_dup_cards:
        s, g = combos[idx]; idx += 1
        assign += [s + g] * 2
    while len(assign) < n:
        s, g = combos[idx]; idx += 1
        assign.append(s + g)
    assign = assign[:n]
    rng.shuffle(assign)

    for card, nm in zip(cards, assign):
        s, g = split_name(nm)
        card["name"] = nm
        roman_given, roman_sur = giv_map.get(g, g), sur_map.get(s, s)
        if (card.get("nameEn") or "").strip():
            card["nameEn"] = f"{roman_given} {roman_sur}"
        old_email = card.get("email") or ""
        if old_email:
            prefix = ""
            body = old_email
            if not old_email.lower().startswith(("a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
                                                 "k", "l", "m", "n", "o", "p", "q", "r", "s", "t",
                                                 "u", "v", "w", "x", "y", "z")) or old_email[1:2] == ".":
                # "E.  jiugim@corp.kr" 처럼 라벨 접두어가 붙은 경우 보존
                head, sep, tail = old_email.partition("  ")
                if sep and "@" in tail:
                    prefix, body = head + sep, tail
            domain = body.split("@", 1)[1] if "@" in body else "example.com"
            card["email"] = f"{prefix}{(roman_given + roman_sur).lower()}@{domain}"
    return cards


# --- 한글 로마자 변환 (개정 로마자 표기법의 단순형) --------------------------
# 회사 도메인을 회사명에서 만들기 위한 것. 음운 동화(신라->Silla)까지는 하지 않는다 —
# 도메인은 실제로도 회사가 임의로 정하므로 '읽으면 그 회사'면 충분하다.
_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj",
        "ch", "k", "t", "p", "h"]
_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo",
         "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
# 종성 28개(받침 없음 포함). 개수가 어긋나면 '광'->gwat, '빛'->bik 처럼 통째로 밀린다.
_JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l",
         "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]
assert len(_CHO) == 19 and len(_JUNG) == 21 and len(_JONG) == 28


def romanize_syllables(text):
    """음절 단위 로마자 조각을 돌려준다. 도메인을 음절 경계에서 자르려고 분리해 둔다."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_CHO[code // 588] + _JUNG[(code % 588) // 28] + _JONG[code % 28])
        elif ch.isalnum():
            out.append(ch.lower())
    return out


def romanize(text):
    # 받침 ㄹ + 초성 ㄹ 은 'lr' 이 아니라 'll' 로 적는다(블루 -> beullu).
    return re.sub(r"lr", "ll", "".join(romanize_syllables(text)))


# 법인격 표기 — 도메인에는 넣지 않는다.
_CORP_FORMS = ("주식회사", "유한회사", "(주)", "(유)", "(재)", "(사)", "㈜")
# 실제 명함에서 흔한 순서대로.
_TLDS = [".co.kr"] * 5 + [".com"] * 4 + [".kr"] * 2 + [".net"]
# 회사가 없는 사람(프리랜서 등)은 개인 메일을 쓴다.
_PERSONAL_DOMAINS = ["naver.com", "gmail.com", "daum.net", "kakao.com"]


def company_domain(company, rng):
    """회사명에서 도메인을 만든다. 긴 이름은 음절 경계에서 끊는다(중간에 자르면 읽히지 않는다)."""
    core = company
    for form in _CORP_FORMS:
        core = core.replace(form, " ")
    parts, acc = romanize_syllables(core.strip()), ""
    for p in parts:
        if len(acc) + len(p) > 18:
            break
        acc += p
    acc = re.sub(r"lr", "ll", acc)
    return (acc or "company") + rng.choice(_TLDS)


def unify_company_addresses(cards):
    """
    같은 회사면 같은 주소를 쓰게 한다(35개사가 서로 다른 주소를 갖고 있었다).
    시나리오 주소를 심기 **전에** 돌려야 한다 — 나중에 돌리면 판교 같은 지정 주소를 덮는다.
    """
    addresses = {}
    for c in cards:
        comp = (c.get("company") or "").strip()
        addr = (c.get("address") or "").strip()
        if comp and addr and comp not in addresses:
            addresses[comp] = (addr, c.get("location") or "")
    for c in cards:
        comp = (c.get("company") or "").strip()
        if comp and (c.get("address") or "").strip() and comp in addresses:
            c["address"], c["location"] = addresses[comp]
    return cards


def align_email_domains(cards, rng):
    """
    이메일 도메인을 회사명에서 만든다.

    원본은 example.com/sample.kr 같은 자리표시자 21종을 893개 회사가 돌려쓰고 있었고,
    같은 회사인데 도메인이 다른 곳도 12개사였다. 진짜 명함이라면 도메인은 회사에서 나온다.
    이름 재배정(regenerate_names) **뒤에** 돌려야 한다 — 로컬파트가 그때 확정된다.
    """
    domains = {}
    for c in cards:
        comp = (c.get("company") or "").strip()
        if comp and comp not in domains:
            domains[comp] = company_domain(comp, rng)
    for c in cards:
        old = (c.get("email") or "").strip()
        if not old or "@" not in old:
            continue
        comp = (c.get("company") or "").strip()
        local = old.split("@", 1)[0]
        c["email"] = f"{local}@{domains[comp]}" if comp \
            else f"{local}@{rng.choice(_PERSONAL_DOMAINS)}"
    return cards


def strip_label_prefixes(cards):
    """
    OCR 라벨 접두어("M.  010-...", "E.  a@b.c", "A.  서울...")를 벗긴다.
    원본은 OCR 노이즈를 흉내내려고 넣은 것인데, 지금은 '진짜 명함처럼 보이는' 데이터가
    필요하므로 제거한다. location 의 오염값("A.", "Address." 등)도 비운다.
    """
    polluted = {"", "A.", "Address.", "M.", "E."}
    for c in cards:
        for f in ("phone", "email", "address", "name", "nameEn", "company", "title", "department"):
            v = (c.get(f) or "").strip()
            # "M.  010-..." 처럼 라벨 + 공백2개 형태
            v = re.sub(r"^[AME]\.\s+", "", v)
            v = re.sub(r"^Address\.\s+", "", v)
            c[f] = v.strip()
        loc = (c.get("location") or "").strip()
        c["location"] = "" if loc in polluted or loc.endswith(".") else loc
    return cards


def regenerate_addresses(cards, rng):
    """
    지리적으로 맞는 주소로 다시 만든다(시/도 ↔ 시군구 대응표에서만 조합).
    주소가 비어 있던 카드는 비운 채로 둔다 — 결측도 실제 명함첩의 특성이다.
    location 은 주소의 '시/도 시군구'와 일치시킨다(예전엔 서로 따로 놀았다).
    """
    regions = list(REGION_DISTRICTS)
    for c in cards:
        if not (c.get("address") or "").strip():
            c["location"] = ""
            continue
        region = rng.choice(regions)
        district = rng.choice(REGION_DISTRICTS[region])
        roads = REGION_ROADS.get((region, district), GENERIC_ROADS)
        road = rng.choice(roads)
        num = rng.randint(1, 999)
        suffix = f"-{rng.randint(1, 40)}" if rng.random() < 0.25 else ""
        c["address"] = f"{region} {district} {road} {num}{suffix}"
        c["location"] = f"{region} {district}"
    return cards


def ensure_address_scenarios(cards, rng):
    """
    회귀 검증에 필요한 주소를 최소 개수만큼 심는다.
    - 판교: 지역 조건/카운트 테스트
    - 상무대로: '상무'(직함) vs '상무대로'(지역) 충돌 테스트
    둘 다 실제로 존재하는 지역-도로명 조합이라 지리적으로도 맞다.
    """
    targets = [
        ("경기도", "성남시 분당구", "판교역로", lambda c: "판교" in (c.get("address") or ""), 9),
        ("광주광역시", "서구", "상무대로", lambda c: "상무대로" in (c.get("address") or ""), 10),
    ]
    for region, district, road, pred, want in targets:
        have = sum(1 for c in cards if pred(c))
        if have >= want:
            continue
        # 주소가 있는 카드 중 아직 대상이 아닌 것을 골라 덮어쓴다
        pool = [c for c in cards if (c.get("address") or "").strip() and not pred(c)]
        rng.shuffle(pool)
        for c in pool[: want - have]:
            num = rng.randint(1, 999)
            c["address"] = f"{region} {district} {road} {num}"
            c["location"] = f"{region} {district}"
    return cards


def fill_departments(cards, rng):
    """
    부서를 직함에 어울리게 채운다. 원본은 68%가 비어 있고 종류도 적었다.
    임원은 부서를 안 적는 경우가 많아 그대로 비워 둔다(현실성).
    """
    for c in cards:
        title = (c.get("title") or "").strip()
        if not title:
            continue
        if title in EXECUTIVE_TITLES:
            # 임원은 대부분 공란, 일부만 경영 조직
            c["department"] = rng.choice(DEPARTMENTS_BY_ROLE["경영"]) if rng.random() < 0.2 else ""
            continue
        if rng.random() > DEPARTMENT_FILL_RATE:
            c["department"] = ""
            continue
        low = title.lower()
        group = None
        for g, keys in ROLE_KEYWORDS:
            if any(k in low for k in keys):
                group = g
                break
        if group is None:
            group = rng.choice(["기획", "경영", "영업", "개발"])
        c["department"] = rng.choice(DEPARTMENTS_BY_ROLE[group])
    return cards


def ensure_department_scenarios(cards, rng, want_ai=25):
    """
    'AI' 는 부서에만 있는 값의 대표 사례라 카운트 경로 테스트가 여기에 걸려 있다.
    직함 기반으로 부서를 채우면 AI 부서가 줄어들 수 있어 최소 개수를 보장한다.
    직함이 개발/연구 계열인 사람에게만 붙여 어색하지 않게 한다.
    """
    def has_ai(c):
        return "ai" in (c.get("department") or "").lower()

    have = sum(1 for c in cards if has_ai(c))
    if have >= want_ai:
        return cards
    # 기술 직군을 우선 쓰되, 모자라면 일반 직급도 쓴다.
    # 한국 명함은 '과장 · AI개발팀'처럼 직급+부서 조합이 자연스러워서 어색하지 않다.
    techy = ("개발", "엔지니어", "engineer", "sre", "devops", "연구", "데이터", "data",
             "scientist", "architect", "테크", "cto")
    def eligible(c):
        t = (c.get("title") or "").strip()
        return bool(t) and t not in EXECUTIVE_TITLES and not has_ai(c)

    # 'AI' 글자가 실제로 들어간 부서명만 쓴다 — DEPARTMENTS_BY_ROLE["AI"] 에는
    # '데이터사이언스팀'처럼 AI 가 안 들어간 이름도 있어서, 그걸 배정하면 카운트가 안 늘어난다.
    ai_names = [d for d in DEPARTMENTS_BY_ROLE["AI"] if "ai" in d.lower()]
    first_ids = set()
    first = []
    for c in cards:
        if eligible(c) and any(k in (c.get("title") or "").lower() for k in techy):
            first.append(c)
            first_ids.add(c["id"])
    second = [c for c in cards if eligible(c) and c["id"] not in first_ids]
    rng.shuffle(first)
    rng.shuffle(second)
    for c in (first + second)[: want_ai - have]:
        c["department"] = rng.choice(ai_names)
    still = want_ai - sum(1 for c in cards if has_ai(c))
    if still > 0:
        raise SystemExit(f"AI 부서를 붙일 후보가 부족하다({still}장 모자람)")
    return cards


def region_of(card):
    addr = (card.get("address") or "").strip()
    if not addr:
        return ""
    for tok in addr.split():
        if tok.endswith(("특별시", "광역시", "특별자치시", "특별자치도", "도")):
            return tok
    return ""


def main():
    rng = random.Random(SEED)
    big = json.loads(BIG_PATH.read_text(encoding="utf-8"))
    small = json.loads(SMALL_PATH.read_text(encoding="utf-8"))

    # 1) 기권용으로 비워야 하는 지역 카드는 후보에서 제외
    pool = [c for c in big
            if not any(r in ((c.get("location") or "") + " " + (c.get("address") or ""))
                       for r in ABSENT_REGIONS)]

    picked, picked_ids = [], set()

    def take(card):
        if card["id"] in picked_ids:
            return False
        picked.append(card)
        picked_ids.add(card["id"])
        return True

    # 2) 60장 통제셋 전부 포함 — 5000장에 없는 직함 22종(AI 개발자, 회계사 …)과
    #    넓은 지역 분포를 가져온다. id 충돌이 없는지 확인해 둔다.
    big_ids = {c["id"] for c in big}
    for c in small:
        if c["id"] in big_ids:
            raise SystemExit(f"id 충돌: {c['id']} — 병합 전에 id 체계를 정리할 것")
        take(c)

    # 3) 필수 시나리오를 최소 보장치까지 채운다
    for label, (pred, need) in REQUIRED.items():
        have = sum(1 for c in picked if pred(c))
        if have >= need:
            continue
        cands = [c for c in pool if c["id"] not in picked_ids and pred(c)]
        rng.shuffle(cands)
        for c in cands[: need - have]:
            take(c)

    # 4) 남은 자리는 실전 분포 그대로 무작위 표본으로 채운다
    rest = [c for c in pool if c["id"] not in picked_ids]
    rng.shuffle(rest)
    for c in rest:
        if len(picked) >= TARGET:
            break
        take(c)

    picked = picked[:TARGET]
    picked = [dict(c) for c in picked]  # 원본 리스트를 건드리지 않게 복사

    # 5) 실제 명함처럼 다듬는다.
    #    순서 주의: 라벨 제거 → 주소 재생성 → 시나리오 주소 심기 → 부서 채우기
    #    (주소를 다시 만들면 '판교'·'상무대로'가 사라지므로 그 다음에 다시 심어야 한다)
    picked = strip_label_prefixes(picked)
    picked = regenerate_addresses(picked, rng)
    picked = unify_company_addresses(picked)
    picked = ensure_address_scenarios(picked, rng)
    picked = fill_departments(picked, rng)
    picked = ensure_department_scenarios(picked, rng)

    # 6) 이름 재배정 — 합성 데이터의 좁은 이름 풀 때문에 동명이인이 과도했다(원본 51.4%).
    #    그 다음 이메일 도메인을 회사에서 파생시킨다(로컬파트가 확정된 뒤여야 한다).
    sur_map, giv_map = build_roman_maps(big, small)
    picked = regenerate_names(picked, rng, sur_map, giv_map)
    picked = align_email_domains(picked, rng)

    OUT_PATH.write_text(json.dumps(picked, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 검수 리포트 ----
    print(f"생성: {OUT_PATH.name} — {len(picked)}장")
    print("\n[필수 시나리오]")
    ok = True
    for label, (pred, need) in REQUIRED.items():
        n = sum(1 for c in picked if pred(c))
        mark = "OK " if n >= need else "부족"
        if n < need:
            ok = False
        print(f"  {mark} {label:<18} {n}장 (최소 {need})")

    print("\n[기권 검증용 — 없어야 하는 값]")
    for r in ABSENT_REGIONS + ("울릉도", "백령도"):
        n = sum(1 for c in picked
                if r in ((c.get("location") or "") + " " + (c.get("address") or "")))
        mark = "OK " if n == 0 else "실패"
        if n:
            ok = False
        print(f"  {mark} {r}: {n}장")
    names = Counter(c.get("name") for c in picked)
    for nm in ("정하은", "홍길동"):
        n = names.get(nm, 0)
        if n:
            ok = False
        print(f"  {'OK ' if n == 0 else '실패'} 이름 {nm}: {n}명")

    print("\n[테스트가 의존하는 이름]")
    for nm, want in PINNED_NAMES.items():
        got = names.get(nm, 0)
        if got != want:
            ok = False
        print(f"  {'OK ' if got == want else '실패'} {nm}: {got}명 (기대 {want})")

    print("\n[동명이인]")
    dup_names = {k: v for k, v in names.items() if v >= 2}
    dup_cards = sum(dup_names.values())
    print(f"  이름 {len(dup_names)}종 / 카드 {dup_cards}장 ({dup_cards / len(picked) * 100:.1f}%)")
    print(f"  최다: {names.most_common(3)}")
    if dup_cards / len(picked) > 0.15:
        ok = False
        print("  실패 — 동명이인이 여전히 많다")

    print("\n[이름 무결성]")
    # 이름과 영문명/이메일이 따로 노는지 — 이름만 바꾸고 파생 필드를 안 고치면 생긴다.
    # 복성 처리를 잘못 넣었을 때 '황보름' -> nameEn 'Boleum Hwang' 같은 불일치가 났다.
    mismatched = []
    for c in picked:
        en = (c.get("nameEn") or "").strip()
        if not en or " " not in en:
            continue
        given_en, sur_en = en.rsplit(" ", 1)
        s, g = split_name(c["name"])
        if sur_map.get(s) != sur_en or giv_map.get(g) != given_en:
            mismatched.append((c["name"], en))
    print(f"  {'OK ' if not mismatched else '실패'} 이름↔영문명 불일치: {len(mismatched)}건 {mismatched[:3]}")
    if mismatched:
        ok = False

    # 이름 조각 오염 — 이걸 검사하지 않아서 '라궁지아'·'하고우진' 153건이 그냥 통과했다.
    # 한국 이름은 성 1글자 + 이름 1~2글자라 4글자가 나오면 성/이름 분해가 틀린 것이다.
    # (원본의 복성 카드 nameEn 이 '남궁민서 -> Gungminseo Nam' 으로 깨져 있어서,
    #  그걸 학습하면 이름 풀에 '궁민서' 같은 조각이 섞여 들어간다.)
    too_long = [c["name"] for c in picked if len(c["name"]) >= 4]
    print(f"  {'OK ' if not too_long else '실패'} 4글자 이상 이름: {len(too_long)}건 {too_long[:5]}")
    if too_long:
        ok = False
    # 2글자 조각('궁준' <- 남궁준)은 길이로는 못 잡는다. 원본과 대조한다:
    # 복성이 아닌 카드에서 한 번이라도 쓰인 이름만 정상으로 본다.
    # ('보름'은 조보름·김보름이 있으니 정상, '궁준'은 남궁준에서만 나오니 조각이다.)
    legit_given = {split_name(c["name"])[1] for cards in (big, small) for c in cards
                   if (c.get("name") or "").strip()
                   and not c["name"].startswith(COMPOUND_SURNAMES)}
    frag = sorted({c["name"] for c in picked if split_name(c["name"])[1] not in legit_given})
    print(f"  {'OK ' if not frag else '실패'} 원본에 없는 이름 조각: {len(frag)}건 {frag[:5]}")
    if frag:
        ok = False

    print("\n[회사 파생 필드]")
    # 이메일 도메인은 회사에서 나와야 한다. 원본은 example.com/sample.kr 21종을 돌려썼다.
    from collections import defaultdict as _dd
    doms, addrs = _dd(set), _dd(set)
    for c in picked:
        comp = (c.get("company") or "").strip()
        if not comp:
            continue
        email = (c.get("email") or "").strip()
        if "@" in email:
            doms[comp].add(email.split("@", 1)[1])
        if (c.get("address") or "").strip():
            addrs[comp].add(c["address"])
    d_bad = {k: v for k, v in doms.items() if len(v) > 1}
    a_bad = {k: v for k, v in addrs.items() if len(v) > 1}
    placeholder = [c["email"] for c in picked
                   if re.search(r"@(example|sample|corp|company|mail)\.", c.get("email") or "")]
    print(f"  {'OK ' if not d_bad else '실패'} 회사별 도메인 불일치: {len(d_bad)}개사")
    print(f"  {'OK ' if not placeholder else '실패'} 자리표시자 도메인: {len(placeholder)}건 {placeholder[:3]}")
    print(f"  {'OK ' if len(a_bad) <= 3 else '실패'} 회사별 주소 불일치: {len(a_bad)}개사 (시나리오 심기로 3개사까지 허용)")
    if d_bad or placeholder or len(a_bad) > 3:
        ok = False
    print(f"  도메인 {len(set().union(*doms.values())) if doms else 0}종 / 회사 {len(doms)}곳")

    print("\n[라벨 접두어 제거]")
    pref = sum(1 for c in picked for f in ("phone", "email", "address", "location")
               if re.match(r"^([AME]\.|Address\.)\s", (c.get(f) or "")))
    print(f"  {'OK ' if pref == 0 else '실패'} 접두어 남은 필드: {pref}건")
    if pref:
        ok = False

    print("\n[주소 지리 정합성]")
    bad_geo = []
    for c in picked:
        addr = (c.get("address") or "").strip()
        if not addr:
            continue
        parts = addr.split()
        region = parts[0]
        valid = REGION_DISTRICTS.get(region)
        if valid is None:
            bad_geo.append((c["name"], addr, "알 수 없는 시/도"))
            continue
        if not any(addr.startswith(f"{region} {d} ") for d in valid):
            bad_geo.append((c["name"], addr, "시/도와 시군구 불일치"))
    n_addr = sum(1 for c in picked if (c.get("address") or "").strip())
    print(f"  {'OK ' if not bad_geo else '실패'} 주소 {n_addr}장 중 부정합 {len(bad_geo)}건 {bad_geo[:2]}")
    if bad_geo:
        ok = False
    # location 이 주소와 일치하는지
    loc_mismatch = [c["name"] for c in picked
                    if (c.get("location") or "") and not (c.get("address") or "").startswith(c["location"])]
    print(f"  {'OK ' if not loc_mismatch else '실패'} location↔address 불일치 {len(loc_mismatch)}건")
    if loc_mismatch:
        ok = False

    print("\n[부서]")
    dept_filled = sum(1 for c in picked if (c.get("department") or "").strip())
    dept_kinds = len({(c.get("department") or "").strip() for c in picked if (c.get("department") or "").strip()})
    print(f"  채움 {dept_filled}장 ({dept_filled / len(picked) * 100:.0f}%) / 종류 {dept_kinds}개")

    print("\n[분포]")
    titles = {(c.get("title") or "").strip() for c in picked if (c.get("title") or "").strip()}
    depts = {(c.get("department") or "").strip() for c in picked if (c.get("department") or "").strip()}
    regions = {region_of(c) for c in picked} - {""}
    dup = sum(1 for v in names.values() if v >= 2)
    print(f"  직함 {len(titles)}종 / 부서 {len(depts)}종 / 광역지역 {len(regions)}종")
    print(f"  고유 이름 {len(names)} / 동명이인 있는 이름 {dup}")

    if not ok:
        print("\n검수 실패 — 조건을 만족하지 못했다.")
        sys.exit(1)
    print("\n검수 통과")


if __name__ == "__main__":
    main()
