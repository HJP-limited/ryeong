"""
한글+영어 혼용 명함 합성 데이터셋 생성기
- 다양한 레이아웃/색상/폰트로 명함 이미지 생성
- 각 텍스트 필드에 대한 바운딩박스 JSON 어노테이션 함께 저장
"""

import os
import json
import random
from PIL import Image, ImageDraw, ImageFont
from faker import Faker

# ─── 설정 ──────────────────────────────────────────────────
OUTPUT_DIR   = "business_card_dataset"
NUM_CARDS    = 50          # 생성할 명함 수 (원하는 대로 변경)
CARD_W, CARD_H = 1050, 600  # 명함 크기 (px), 실제 비율 3.5:2 인치 기준

# ─── 폰트 경로 ─────────────────────────────────────────────
FONT_SANS_REG   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_SANS_BOLD  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_SERIF_REG  = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
FONT_SERIF_BOLD = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

# ─── 랜덤 데이터 ───────────────────────────────────────────
fake_ko = Faker("ko_KR")
fake_en = Faker("en_US")

KO_TITLES = [
    "대표이사", "부대표", "이사", "상무이사", "전무이사",
    "부장", "차장", "과장", "대리", "주임", "사원",
    "수석 연구원", "선임 연구원", "책임 매니저", "팀장",
    "디자이너", "개발자", "마케터", "컨설턴트", "기획자",
]
EN_TITLES = [
    "CEO", "CTO", "CFO", "COO", "Director",
    "Senior Manager", "Manager", "Lead Developer",
    "UX Designer", "Product Manager", "Consultant",
    "Marketing Manager", "Business Analyst", "Engineer",
]
KO_DEPARTMENTS = [
    "개발팀", "마케팅팀", "영업팀", "기획팀", "디자인팀",
    "경영지원팀", "인사팀", "재무팀", "연구개발팀", "전략팀",
]
KO_COMPANIES = [
    "테크놀로지", "솔루션즈", "파트너스", "그룹", "코퍼레이션",
    "이노베이션", "시스템즈", "네트웍스", "벤처스", "홀딩스",
]

# ─── 색상 팔레트 ───────────────────────────────────────────
PALETTES = [
    # (배경색, 강조색, 텍스트색, 부제목색)
    ("#FFFFFF", "#1A3A6B", "#1A1A2E", "#555577"),  # 화이트 & 네이비
    ("#1A1A2E", "#E8C87A", "#FFFFFF", "#AAAACC"),  # 다크 & 골드
    ("#F5F0E8", "#8B2635", "#2C1810", "#6B4C3B"),  # 아이보리 & 버건디
    ("#0D2137", "#00C9A7", "#FFFFFF", "#7FBCB0"),  # 다크 & 민트
    ("#FAFAFA", "#333333", "#111111", "#777777"),  # 모노크롬
    ("#2D4739", "#F5C842", "#FFFFFF", "#A8C4A2"),  # 다크그린 & 옐로우
    ("#FFF8F0", "#C0392B", "#2C2C2C", "#888888"),  # 크림 & 레드
    ("#1C1C1C", "#4DA8DA", "#EEEEEE", "#999999"),  # 차콜 & 블루
]

# ─── 레이아웃 타입 ─────────────────────────────────────────
LAYOUTS = ["left", "center", "right", "split"]


def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def random_person():
    """한글+영어 혼용 명함 데이터 생성"""
    last  = fake_ko.last_name()
    first = fake_ko.first_name()
    name_ko = f"{last}{first}"
    name_en = f"{fake_en.last_name()}, {fake_en.first_name()}"

    company_prefix = random.choice(["(주)", "㈜", ""])
    company_suffix = random.choice(KO_COMPANIES)
    co_name = fake_en.company().split(",")[0].split(" and ")[0]
    company_ko = f"{company_prefix}{last}{company_suffix}"
    company_en = f"{co_name} Korea"

    title_ko = random.choice(KO_TITLES)
    title_en = random.choice(EN_TITLES)
    dept     = random.choice(KO_DEPARTMENTS)

    phone    = f"010-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
    tel      = f"02-{random.randint(100,999)}-{random.randint(1000,9999)}"
    email    = f"{fake_en.user_name()}@{fake_en.domain_name()}"
    website  = f"www.{fake_en.domain_name()}"
    address  = f"서울특별시 {fake_ko.city()} {fake_ko.street_address()}"

    return {
        "name_ko":    name_ko,
        "name_en":    name_en,
        "company_ko": company_ko,
        "company_en": company_en,
        "title_ko":   title_ko,
        "title_en":   title_en,
        "department": dept,
        "phone":      phone,
        "tel":        tel,
        "email":      email,
        "website":    website,
        "address":    address,
    }


def draw_text_bbox(draw, text, x, y, font, color):
    """텍스트를 그리고 바운딩박스 반환 [x1,y1,x2,y2]"""
    bbox = draw.textbbox((x, y), text, font=font)
    draw.text((x, y), text, font=font, fill=color)
    return list(bbox)


def add_decorative_elements(draw, layout, palette, w, h):
    """배경 장식 요소 추가"""
    bg, accent, text_c, sub_c = palette

    if layout == "left":
        # 왼쪽 강조 바
        draw.rectangle([(0, 0), (12, h)], fill=accent)
        # 하단 라인
        draw.rectangle([(12, h-4), (w, h)], fill=accent)

    elif layout == "center":
        # 상단/하단 가로선
        draw.rectangle([(60, 30), (w-60, 34)], fill=accent)
        draw.rectangle([(60, h-34), (w-60, h-30)], fill=accent)

    elif layout == "right":
        # 오른쪽 강조 바
        draw.rectangle([(w-12, 0), (w, h)], fill=accent)
        draw.rectangle([(0, h-4), (w-12, h)], fill=accent)

    elif layout == "split":
        # 왼쪽 절반 강조 배경
        r, g, b = tuple(int(accent.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
        draw.rectangle([(0, 0), (w//3, h)], fill=accent)


def generate_card(idx, person, layout, palette):
    bg, accent, text_c, sub_c = palette
    img  = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    # 폰트 세트
    use_serif = random.random() > 0.5
    bold_path = FONT_SERIF_BOLD if use_serif else FONT_SANS_BOLD
    reg_path  = FONT_SERIF_REG  if use_serif else FONT_SANS_REG

    f_company = load_font(bold_path, 28)
    f_name    = load_font(bold_path, 46)
    f_name_en = load_font(reg_path,  22)
    f_title   = load_font(reg_path,  24)
    f_sub     = load_font(reg_path,  20)
    f_contact = load_font(reg_path,  19)

    add_decorative_elements(draw, layout, palette, CARD_W, CARD_H)

    annotations = []  # {"label": "...", "text": "...", "bbox": [x1,y1,x2,y2]}

    def record(label, text, x, y, font, color):
        bb = draw_text_bbox(draw, text, x, y, font, color)
        annotations.append({"label": label, "text": text, "bbox": bb})

    # ── 레이아웃별 좌표 배치 ────────────────────────────────
    if layout == "left":
        mx, my = 50, 0   # 마진
        # 회사명
        record("company_ko", person["company_ko"], mx+20, 60,  f_company, accent)
        record("company_en", person["company_en"], mx+20, 96,  f_sub,     sub_c)
        # 이름
        record("name_ko",    person["name_ko"],    mx+20, 160, f_name,    text_c)
        record("name_en",    person["name_en"],    mx+20, 214, f_name_en, sub_c)
        # 직함
        record("title_ko",   person["title_ko"],   mx+20, 254, f_title,   accent)
        record("title_en",   person["title_en"],   mx+20, 284, f_sub,     sub_c)
        record("department", person["department"], mx+20, 314, f_sub,     sub_c)
        # 연락처
        record("phone",   "M. " + person["phone"],   mx+20, 380, f_contact, text_c)
        record("tel",     "T. " + person["tel"],      mx+20, 408, f_contact, text_c)
        record("email",   "E. " + person["email"],    mx+20, 436, f_contact, text_c)
        record("website", "W. " + person["website"],  mx+20, 464, f_contact, sub_c)
        record("address", person["address"],           mx+20, 500, f_contact, sub_c)

    elif layout == "center":
        def cx(text, font):
            bb = draw.textbbox((0,0), text, font=font)
            return (CARD_W - (bb[2]-bb[0])) // 2

        record("company_ko", person["company_ko"], cx(person["company_ko"], f_company), 55,  f_company, accent)
        record("company_en", person["company_en"], cx(person["company_en"], f_sub),     90,  f_sub,     sub_c)
        draw.line([(CARD_W//2-120, 130),(CARD_W//2+120, 130)], fill=accent, width=2)
        record("name_ko",    person["name_ko"],    cx(person["name_ko"],    f_name),    148, f_name,    text_c)
        record("name_en",    person["name_en"],    cx(person["name_en"],    f_name_en), 202, f_name_en, sub_c)
        record("title_ko",   person["title_ko"],   cx(person["title_ko"],   f_title),   240, f_title,   accent)
        record("department", person["department"], cx(person["department"], f_sub),     272, f_sub,     sub_c)
        draw.line([(CARD_W//2-120, 316),(CARD_W//2+120, 316)], fill=sub_c, width=1)
        record("phone",   person["phone"],   cx(person["phone"],   f_contact), 330, f_contact, text_c)
        record("email",   person["email"],   cx(person["email"],   f_contact), 358, f_contact, text_c)
        record("website", person["website"], cx(person["website"], f_contact), 386, f_contact, sub_c)
        record("address", person["address"], cx(person["address"], f_contact), 420, f_contact, sub_c)

    elif layout == "right":
        rpad = CARD_W - 50

        def rx(text, font):
            bb = draw.textbbox((0,0), text, font=font)
            return rpad - (bb[2]-bb[0])

        record("company_ko", person["company_ko"], rx(person["company_ko"], f_company), 60,  f_company, accent)
        record("company_en", person["company_en"], rx(person["company_en"], f_sub),     96,  f_sub,     sub_c)
        record("name_ko",    person["name_ko"],    rx(person["name_ko"],    f_name),    160, f_name,    text_c)
        record("name_en",    person["name_en"],    rx(person["name_en"],    f_name_en), 214, f_name_en, sub_c)
        record("title_ko",   person["title_ko"],   rx(person["title_ko"],   f_title),   254, f_title,   accent)
        record("title_en",   person["title_en"],   rx(person["title_en"],   f_sub),     284, f_sub,     sub_c)
        record("department", person["department"], rx(person["department"], f_sub),     314, f_sub,     sub_c)
        record("phone",   "M. " + person["phone"],   rx("M. "+person["phone"],   f_contact), 380, f_contact, text_c)
        record("email",   "E. " + person["email"],   rx("E. "+person["email"],   f_contact), 408, f_contact, text_c)
        record("website", "W. " + person["website"], rx("W. "+person["website"], f_contact), 436, f_contact, sub_c)
        record("address", person["address"],          rx(person["address"],       f_contact), 472, f_contact, sub_c)

    elif layout == "split":
        # 왼쪽 1/3: 강조색 배경 → 이름/직함 (텍스트 색상 반전)
        split_x = CARD_W // 3 + 20
        left_tc = "#FFFFFF" if accent.startswith("#") and int(accent[1:3],16)<128 else "#111111"

        record("name_ko",  person["name_ko"],  30, 160, f_name,    left_tc)
        record("name_en",  person["name_en"],  30, 214, f_name_en, left_tc)
        record("title_ko", person["title_ko"], 30, 260, f_title,   left_tc)
        record("title_en", person["title_en"], 30, 292, f_sub,     left_tc)

        # 오른쪽 2/3: 회사+연락처
        record("company_ko", person["company_ko"], split_x, 60,  f_company, accent)
        record("company_en", person["company_en"], split_x, 96,  f_sub,     sub_c)
        record("department", person["department"], split_x, 130, f_sub,     sub_c)
        draw.line([(split_x, 170),(CARD_W-50, 170)], fill=sub_c, width=1)
        record("phone",   "M. " + person["phone"],   split_x, 190, f_contact, text_c)
        record("tel",     "T. " + person["tel"],      split_x, 218, f_contact, text_c)
        record("email",   "E. " + person["email"],    split_x, 246, f_contact, text_c)
        record("website", "W. " + person["website"],  split_x, 274, f_contact, sub_c)
        record("address", person["address"],           split_x, 310, f_contact, sub_c)

    # ── 저장 ────────────────────────────────────────────────
    img_name  = f"card_{idx:04d}.jpg"
    json_name = f"card_{idx:04d}.json"

    img.save(os.path.join(OUTPUT_DIR, "images", img_name), "JPEG", quality=95)

    annotation = {
        "image":      img_name,
        "width":      CARD_W,
        "height":     CARD_H,
        "layout":     layout,
        "palette_bg": palette[0],
        "fields":     annotations,
    }
    with open(os.path.join(OUTPUT_DIR, "annotations", json_name), "w", encoding="utf-8") as f:
        json.dump(annotation, f, ensure_ascii=False, indent=2)

    return annotation


# ─── 메인 ──────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(f"{OUTPUT_DIR}/images",      exist_ok=True)
    os.makedirs(f"{OUTPUT_DIR}/annotations", exist_ok=True)

    summary = []
    for i in range(NUM_CARDS):
        person  = random_person()
        layout  = random.choice(LAYOUTS)
        palette = random.choice(PALETTES)
        ann     = generate_card(i, person, layout, palette)
        summary.append({"image": ann["image"], "layout": layout})
        print(f"[{i+1:3d}/{NUM_CARDS}] {ann['image']}  layout={layout}")

    # 전체 인덱스 저장
    with open(f"{OUTPUT_DIR}/index.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료! {NUM_CARDS}장 생성 → ./{OUTPUT_DIR}/")
    print(f"   이미지:      ./{OUTPUT_DIR}/images/")
    print(f"   어노테이션:  ./{OUTPUT_DIR}/annotations/")
    print(f"   인덱스:      ./{OUTPUT_DIR}/index.json")
