"""
명함 합성 데이터셋 생성기 v2
────────────────────────────────────────────────────────────
• 해상도  : 300 DPI
• 이미지  : 가로형 90×50 mm → 1063×591 px
            세로형 50×90 mm → 591×1063 px
• 어노테이션: xyxy bbox (픽셀 단위)
• 폰트    : Noto Sans/Serif CJK KR (OFL 1.1 – 상업적 사용 가능)
• 로고    : 도형으로 자체 생성 (저작권 없음)
• 회사명  : 가상 리스트 (실존 기업명 미사용)
• 레이아웃: 12종 × 10장 = 120장
• 증강    : 없음 (원본만)
────────────────────────────────────────────────────────────
"""

import os, json, math, random, re
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from faker import Faker

# ══════════════════════════════════════════════════════════════
#  0. 기본 상수
# ══════════════════════════════════════════════════════════════
DPI          = 300
MM_PER_INCH  = 25.4
OUTPUT_DIR   = "/home/claude/bcd"

def mm2px(mm): return round(mm / MM_PER_INCH * DPI)

# 가로형 (landscape)
LS_W, LS_H = mm2px(90), mm2px(50)   # 1063 × 591
# 세로형 (portrait)
PT_W, PT_H = mm2px(50), mm2px(90)   # 591 × 1063

CARDS_PER_LAYOUT = 10               # 레이아웃별 생성 수

# ══════════════════════════════════════════════════════════════
#  1. 폰트
# ══════════════════════════════════════════════════════════════
NOTO = "/usr/share/fonts/opentype/noto"
FONT_FILES = {
    "sans_thin":      f"{NOTO}/NotoSansCJK-Thin.ttc",
    "sans_light":     f"{NOTO}/NotoSansCJK-Light.ttc",
    "sans_demilight": f"{NOTO}/NotoSansCJK-DemiLight.ttc",
    "sans_regular":   f"{NOTO}/NotoSansCJK-Regular.ttc",
    "sans_medium":    f"{NOTO}/NotoSansCJK-Medium.ttc",
    "sans_bold":      f"{NOTO}/NotoSansCJK-Bold.ttc",
    "sans_black":     f"{NOTO}/NotoSansCJK-Black.ttc",
    "serif_light":    f"{NOTO}/NotoSerifCJK-Light.ttc",
    "serif_regular":  f"{NOTO}/NotoSerifCJK-Regular.ttc",
    "serif_medium":   f"{NOTO}/NotoSerifCJK-Medium.ttc",
    "serif_bold":     f"{NOTO}/NotoSerifCJK-Bold.ttc",
    "serif_semibold": f"{NOTO}/NotoSerifCJK-SemiBold.ttc",
    "serif_black":    f"{NOTO}/NotoSerifCJK-Black.ttc",
}
_fcache = {}

def pt2px(pt): return max(6, round(pt * DPI / 72))

def fnt(key, pt):
    px = pt2px(pt)
    k  = (key, px)
    if k not in _fcache:
        try:
            _fcache[k] = ImageFont.truetype(FONT_FILES[key], px)
        except Exception:
            _fcache[k] = ImageFont.load_default()
    return _fcache[k]

# 폰트 조합 테마 (헤더폰트, 바디폰트)
FONT_THEMES = [
    ("sans_bold",     "sans_regular"),
    ("sans_black",    "sans_light"),
    ("sans_medium",   "sans_thin"),
    ("serif_bold",    "serif_regular"),
    ("serif_semibold","serif_light"),
    ("serif_black",   "serif_medium"),
    ("sans_bold",     "serif_regular"),
    ("serif_bold",    "sans_regular"),
]

# ══════════════════════════════════════════════════════════════
#  2. 색상 팔레트  (bg, bg2, primary_text, secondary_text, accent)
# ══════════════════════════════════════════════════════════════
PALETTES = [
    # 밝은 계열
    {"bg":(255,255,255), "bg2":None,          "pt":(15,15,15),    "st":(90,90,90),     "ac":(0,82,204)},
    {"bg":(245,247,250), "bg2":None,          "pt":(15,23,42),    "st":(71,85,105),    "ac":(99,102,241)},
    {"bg":(255,252,240), "bg2":None,          "pt":(28,25,23),    "st":(92,83,74),     "ac":(194,100,3)},
    {"bg":(240,253,244), "bg2":None,          "pt":(20,83,45),    "st":(34,110,60),    "ac":(21,128,61)},
    {"bg":(255,241,242), "bg2":None,          "pt":(136,19,55),   "st":(159,28,57),    "ac":(190,18,60)},
    {"bg":(239,246,255), "bg2":None,          "pt":(29,78,216),   "st":(37,99,235),    "ac":(37,99,235)},
    {"bg":(253,245,230), "bg2":None,          "pt":(40,26,13),    "st":(101,67,33),    "ac":(180,83,9)},
    # 어두운 계열
    {"bg":(15,23,42),    "bg2":None,          "pt":(248,250,252), "st":(148,163,184),  "ac":(99,102,241)},
    {"bg":(20,20,20),    "bg2":None,          "pt":(255,255,255), "st":(180,180,180),  "ac":(250,204,21)},
    {"bg":(30,41,59),    "bg2":None,          "pt":(226,232,240), "st":(148,163,184),  "ac":(56,189,248)},
    {"bg":(17,24,39),    "bg2":None,          "pt":(243,244,246), "st":(156,163,175),  "ac":(52,211,153)},
    {"bg":(20,83,45),    "bg2":None,          "pt":(240,253,244), "st":(187,247,208),  "ac":(74,222,128)},
    {"bg":(67,20,7),     "bg2":None,          "pt":(255,237,213), "st":(254,215,170),  "ac":(251,146,60)},
    {"bg":(44,9,51),     "bg2":None,          "pt":(250,232,255), "st":(233,168,255),  "ac":(192,132,252)},
    # 그라데이션 계열 (bg → bg2)
    {"bg":(219,234,254), "bg2":(191,219,254), "pt":(29,78,216),   "st":(37,99,235),    "ac":(29,78,216)},
    {"bg":(237,233,254), "bg2":(221,214,254), "pt":(109,40,217),  "st":(124,58,237),   "ac":(109,40,217)},
    {"bg":(220,252,231), "bg2":(187,247,208), "pt":(20,83,45),    "st":(21,128,61),    "ac":(21,128,61)},
    {"bg":(255,228,230), "bg2":(254,205,211), "pt":(159,18,57),   "st":(190,18,60),    "ac":(190,18,60)},
    {"bg":(30,41,59),    "bg2":(15,23,42),    "pt":(226,232,240), "st":(148,163,184),  "ac":(56,189,248)},
    {"bg":(20,20,20),    "bg2":(40,40,40),    "pt":(255,255,255), "st":(200,200,200),  "ac":(250,204,21)},
]

# ══════════════════════════════════════════════════════════════
#  3. 콘텐츠 데이터
# ══════════════════════════════════════════════════════════════
fake_ko = Faker("ko_KR")
fake_en = Faker("en_US")

COMPANIES_KR = [
    "넥스트솔루션","블루웨이브테크","그린라이트컨설팅","스카이브릿지","알파웍스",
    "퓨처링크","디지털포레스트","클라우드스페이스","이노베이션허브","테크트리",
    "스마트브릿지","오픈마인드그룹","비전소프트","데이터스트림","넥서스파트너스",
    "에코시스템즈","프라임솔루션","크리에이티브랩","솔리드테크","메타웍스코리아",
    "커넥트파이브","글로벌앵커","하이퍼링크","모던스페이스","퓨어테크",
    "리드이노베이션","핵심컨설팅그룹","블록스타디오","피크솔루션","신기술연구소",
]
COMPANIES_EN = [
    "Nexion Solutions","BlueWave Tech","GreenLight Consulting","SkyBridge Corp",
    "AlphaWorks Inc.","FutureLink Systems","Digital Forest","CloudSpace Global",
    "Innovation Hub","TechTree Partners","SmartBridge Co.","OpenMind Group",
    "VisionSoft Inc.","DataStream Labs","Nexus Partners","EcoSystems Corp.",
    "Prime Solutions","Creative Lab Co.","SolidTech Inc.","MetaWorks Korea",
    "ConnectFive","Global Anchor","HyperLink Corp.","ModernSpace Inc.","PureTech",
]
TITLES_KR = [
    "대표이사","부사장","이사","전무","상무","팀장","수석연구원",
    "책임매니저","선임컨설턴트","과장","차장","부장","프로젝트매니저",
    "시니어개발자","주임","연구원","컨설턴트","마케팅디렉터","영업이사",
    "CTO","CFO","CPO","CDO","기획팀장","개발팀장",
]
DEPARTMENTS_KR = [
    "개발팀","마케팅팀","영업부","인사팀","전략기획실",
    "디자인팀","고객지원팀","연구개발부","경영지원팀","데이터분석팀",
    "IT인프라팀","제품관리팀","법무팀","재무팀","글로벌사업팀",
]
SLOGANS = [
    "미래를 함께 만들어갑니다","혁신이 우리의 언어입니다",
    "신뢰와 전문성으로","더 나은 내일을 위해",
    "함께 성장하는 파트너","기술로 세상을 바꿉니다",
    "Excellence in Every Step","Innovation Drives Us",
    "Building Tomorrow Together","Your Success, Our Mission",
]

def gen_phone(mobile=False):
    if mobile:
        return f"010-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
    area = random.choice(["02","031","032","051","053","062","042"])
    mid  = random.randint(100, 9999)
    return f"{area}-{mid}-{random.randint(1000,9999)}"

def gen_email(company_en):
    user = random.choice([
        fake_en.last_name().lower(),
        f"{fake_en.first_name()[0].lower()}{fake_en.last_name().lower()}",
        f"{fake_en.last_name().lower()}{random.randint(10,99)}",
    ])
    domain = re.sub(r"[^a-z]", "", company_en.lower().split()[0])[:10]
    tld = random.choice([".com",".co.kr",".net",".kr",".io"])
    return f"{user}@{domain}{tld}"

def gen_website(company_en):
    domain = re.sub(r"[^a-z]", "", company_en.lower().split()[0])[:10]
    tld = random.choice([".com",".co.kr",".net"])
    return f"www.{domain}{tld}"

def gen_address():
    cities = ["서울특별시","경기도 성남시","부산광역시","인천광역시","대전광역시","대구광역시"]
    streets = ["강남구 테헤란로","마포구 월드컵북로","종로구 종로","서초구 서초대로",
               "분당구 판교역로","해운대구 마린시티로"]
    city   = random.choice(cities)
    street = random.choice(streets)
    num    = random.randint(10, 500)
    extra  = random.choice(["", f" {random.randint(1,20)}층", f" {random.randint(100,999)}호"])
    return f"{city} {street} {num}{extra}"

# 필드 라벨 정의
# 필수: name(0), company(1), title(2), phone(3), email(4)
# 선택: address(5), mobile(6), fax(7), website(8), logo(9), qr(10), dept(11), slogan(12)
FIELD_NAMES = {
    0:"name", 1:"company", 2:"title", 3:"phone", 4:"email",
    5:"address", 6:"mobile", 7:"fax", 8:"website",
    9:"logo", 10:"qr_code", 11:"department", 12:"slogan",
}
REQUIRED = {0,1,2,3,4}

def gen_content():
    company_en = random.choice(COMPANIES_EN)
    company_kr = random.choice(COMPANIES_KR)
    use_bilingual_company = random.random() < 0.3
    company_display = f"{company_kr}" if not use_bilingual_company else f"{company_kr} ({company_en})"

    name = fake_ko.name()
    content = {
        0: name,
        1: company_display,
        2: random.choice(TITLES_KR),
        3: gen_phone(mobile=False),
        4: gen_email(company_en),
    }
    # 선택 필드 (확률)
    opt_prob = {5:0.65, 6:0.70, 7:0.30, 8:0.50, 9:0.80, 10:0.25, 11:0.55, 12:0.20}
    for fid, prob in opt_prob.items():
        if random.random() < prob:
            if fid == 5:  content[fid] = gen_address()
            elif fid == 6: content[fid] = gen_phone(mobile=True)
            elif fid == 7: content[fid] = gen_phone(mobile=False)
            elif fid == 8: content[fid] = gen_website(company_en)
            elif fid == 9: content[fid] = "__LOGO__"
            elif fid == 10: content[fid] = "__QR__"
            elif fid == 11: content[fid] = random.choice(DEPARTMENTS_KR)
            elif fid == 12: content[fid] = random.choice(SLOGANS)
    return content, company_en

# ══════════════════════════════════════════════════════════════
#  4. 배경 / 패턴 그리기
# ══════════════════════════════════════════════════════════════

def draw_gradient(img, c1, c2, direction="v"):
    W, H = img.size
    for i in range(H if direction=="v" else W):
        t = i / max(1, (H-1 if direction=="v" else W-1))
        col = tuple(int(c1[j]*(1-t)+c2[j]*t) for j in range(3))
        if direction=="v": img.paste(col, [0,i,W,i+1])
        else:              img.paste(col, [i,0,i+1,H])

def draw_dot_pattern(draw, W, H, dot_color, spacing=None):
    if spacing is None: spacing = max(20, min(W,H)//20)
    r = max(2, spacing//8)
    for y in range(0, H+spacing, spacing):
        for x in range(0, W+spacing, spacing):
            draw.ellipse([x-r, y-r, x+r, y+r], fill=dot_color)

def draw_stripe_pattern(draw, W, H, stripe_color, stripe_w=None, angle=45):
    if stripe_w is None: stripe_w = max(15, min(W,H)//25)
    diag = int(math.hypot(W,H))*2
    for i in range(-diag, diag*2, stripe_w*2):
        pts = [(i,-diag),(i+stripe_w,-diag),(i+stripe_w+diag,diag),(i+diag,diag)]
        draw.polygon(pts, fill=stripe_color)

def draw_grid_pattern(draw, W, H, grid_color):
    step = max(25, min(W,H)//18)
    lw   = max(1, step//20)
    for x in range(0, W, step):
        draw.rectangle([x, 0, x+lw, H], fill=grid_color)
    for y in range(0, H, step):
        draw.rectangle([0, y, W, y+lw], fill=grid_color)

def draw_wave_pattern(draw, W, H, wave_color):
    amp   = max(8, H//15)
    freq  = 3
    steps = 4
    for s in range(steps):
        pts = []
        for x in range(0, W+2, 2):
            y = int(H*(s+1)//(steps+1) + amp * math.sin(freq * math.pi * x / W + s))
            pts.append((x, y))
        for x in range(W, -1, -2):
            y = int(H*(s+1)//(steps+1) + amp * math.sin(freq * math.pi * x / W + s) + 3)
            pts.append((x, y))
        if len(pts) >= 3:
            draw.polygon(pts, fill=wave_color)

def blend_color(c, bg, alpha=0.08):
    return tuple(int(c[i]*alpha + bg[i]*(1-alpha)) for i in range(3))

def make_background(img, palette, bg_pattern):
    W, H = img.size
    bg   = palette["bg"]
    bg2  = palette.get("bg2")
    pt   = palette["pt"]
    st   = palette["st"]
    ac   = palette["ac"]

    # 기본 배경
    if bg2:
        draw_gradient(img, bg, bg2, direction=random.choice(["v","h"]))
    else:
        img.paste(bg, [0,0,W,H])

    draw = ImageDraw.Draw(img, "RGBA")

    # 패턴 오버레이
    overlay_col = blend_color(ac, bg, 0.07)
    if bg_pattern == "dots":
        draw_dot_pattern(draw, W, H, overlay_col)
    elif bg_pattern == "stripes":
        draw_stripe_pattern(draw, W, H, overlay_col)
    elif bg_pattern == "grid":
        draw_grid_pattern(draw, W, H, overlay_col)
    elif bg_pattern == "waves":
        draw_wave_pattern(draw, W, H, overlay_col)
    # "plain" → 패턴 없음

# ══════════════════════════════════════════════════════════════
#  5. 로고 생성 (도형 기반, 저작권 없음)
# ══════════════════════════════════════════════════════════════

def draw_logo(draw, x, y, size, ac, bg):
    """6가지 스타일 도형 로고"""
    style = random.randint(0, 5)
    s  = size
    s2 = size // 2
    lw = max(2, size//12)

    if style == 0:
        # 원형 로고
        draw.ellipse([x,y,x+s,y+s], fill=ac)
        inner = s//3
        draw.ellipse([x+inner,y+inner,x+s-inner,y+s-inner], fill=bg)
    elif style == 1:
        # 정사각형 모서리 잘린 로고
        r = s//5
        draw.rounded_rectangle([x,y,x+s,y+s], radius=r, fill=ac)
        inner = s//4
        draw.rounded_rectangle([x+inner,y+inner,x+s-inner,y+s-inner],
                                radius=r//2, fill=bg)
    elif style == 2:
        # 다이아몬드
        cx_,cy_ = x+s2, y+s2
        pts = [(cx_,y),(x+s,cy_),(cx_,y+s),(x,cy_)]
        draw.polygon(pts, fill=ac)
        shrink = s//5
        pts2 = [(cx_,y+shrink),(x+s-shrink,cy_),(cx_,y+s-shrink),(x+shrink,cy_)]
        draw.polygon(pts2, fill=bg)
    elif style == 3:
        # 헥사곤
        pts = []
        for i in range(6):
            angle = math.pi/180 * (60*i - 30)
            pts.append((x+s2+s2*math.cos(angle), y+s2+s2*math.sin(angle)))
        draw.polygon(pts, fill=ac)
        pts2 = []
        r2 = s2 * 0.55
        for i in range(6):
            angle = math.pi/180 * (60*i - 30)
            pts2.append((x+s2+r2*math.cos(angle), y+s2+r2*math.sin(angle)))
        draw.polygon(pts2, fill=bg)
    elif style == 4:
        # 삼각형 2개 겹치기
        draw.polygon([(x,y+s),(x+s,y+s),(x+s2,y)], fill=ac)
        draw.polygon([(x+s2//2,y+s),(x+s-s2//2,y+s),(x+s2,y+s//2)], fill=bg)
    else:
        # 가로 바 3개 (ㅡ)
        bar_h = max(3, s//6)
        gap   = (s - 3*bar_h) // 4
        for i in range(3):
            bw = s - (i * s//5)
            bx = x + (s - bw)//2
            by = y + gap*(i+1) + bar_h*i
            draw.rectangle([bx, by, bx+bw, by+bar_h], fill=ac)

    # 로고 bbox 반환
    return [x, y, x+s, y+s]

# ══════════════════════════════════════════════════════════════
#  6. QR코드 생성
# ══════════════════════════════════════════════════════════════

def make_qr(data, size, ac, bg):
    qr = qrcode.QRCode(version=1, box_size=2, border=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=ac, back_color=bg).convert("RGB")
    return qr_img.resize((size, size), Image.LANCZOS)

# ══════════════════════════════════════════════════════════════
#  7. 텍스트 그리기 유틸
# ══════════════════════════════════════════════════════════════

def tw(draw, text, font):
    bb = draw.textbbox((0,0), text, font=font)
    return bb[2]-bb[0]

def th(draw, text, font):
    bb = draw.textbbox((0,0), text, font=font)
    return bb[3]-bb[1]

def put(draw, text, x, y, font, color):
    """텍스트 그리고 xyxy bbox 반환"""
    draw.text((x,y), text, font=font, fill=color)
    bb = draw.textbbox((x,y), text, font=font)
    return [int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])]

def put_icon_text(draw, icon, text, x, y, font, icon_font, color, sec_color):
    """아이콘 + 텍스트 같이 그리기"""
    iw = tw(draw, icon, icon_font)
    draw.text((x, y), icon, font=icon_font, fill=sec_color)
    bb = draw.textbbox((x+iw+4, y), text, font=font)
    draw.text((x+iw+4, y), text, font=font, fill=color)
    return [int(x), int(bb[1]), int(bb[2]), int(bb[3])]

def accent_line(draw, x1, y1, x2, y2, color, lw=3):
    draw.rectangle([x1, y1, x2, y2], fill=color)

# ══════════════════════════════════════════════════════════════
#  8. 어노테이션 기록 클래스
# ══════════════════════════════════════════════════════════════

class AnnotationRecorder:
    def __init__(self):
        self.fields = []

    def add(self, label_id, text, bbox):
        self.fields.append({
            "label_id":   label_id,
            "label_name": FIELD_NAMES[label_id],
            "text":       text,
            "bbox_xyxy":  [int(v) for v in bbox],
        })

# ══════════════════════════════════════════════════════════════
#  9. 레이아웃 렌더러 12종
# ══════════════════════════════════════════════════════════════

def _contact_block(draw, rec, content, x, y, f_reg, f_small, pt, st, W,
                   spacing=None, prefix=True):
    """공통 연락처 블록"""
    if spacing is None:
        spacing = th(draw, "A", f_reg) + max(4, pt2px(3))
    cy = y
    icons = {"phone":"T. ", "mobile":"M. ", "fax":"F. ", "email":"E. ", "website":"W. "}
    for fid, label in [(3,"phone"),(6,"mobile"),(7,"fax"),(4,"email"),(8,"website")]:
        if fid not in content: continue
        val   = content[fid]
        pfx   = icons[label] if prefix else ""
        full  = pfx + val
        bbox  = put(draw, full, x, cy, f_reg, pt if fid in {3,6,4} else st)
        rec.add(fid, val, bbox)
        cy   += spacing
    if 5 in content:
        bbox = put(draw, content[5], x, cy, f_small, st)
        rec.add(5, content[5], bbox)
        cy += spacing
    return cy


# ── L01: 클래식 좌측정렬 가로형 ──────────────────────────────
def render_L01(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    fh, fb = ftheme

    # 왼쪽 강조 바
    bar_w = max(8, W//80)
    accent_line(draw, 0, 0, bar_w, H, ac)
    # 하단 라인
    accent_line(draw, bar_w, H-max(3,H//60), W, H, ac)

    mx = bar_w + max(18, W//35)
    my = max(18, H//18)

    f_co  = fnt(fh, 13)
    f_nm  = fnt(fh, 22)
    f_ti  = fnt(fb, 11)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    cy = my
    # 회사명
    bbox = put(draw, content[1], mx, cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(4, H//60)
    if 11 in content:
        bbox = put(draw, content[11], mx, cy, f_ti, st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], f_ti) + max(2, H//80)
    if 12 in content:
        bbox = put(draw, content[12], mx, cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(3, H//70)

    # 구분선
    cy += max(4, H//60)
    accent_line(draw, mx, cy, mx + W//3, cy+max(1,H//180), st)
    cy += max(6, H//55)

    # 이름
    bbox = put(draw, content[0], mx, cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(3, H//80)
    # 직함
    bbox = put(draw, content[2], mx, cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(10, H//35)

    # 연락처
    _contact_block(draw, rec, content, mx, cy, f_reg, f_sml, pt, st, W)

    # 로고
    if 9 in content:
        logo_s = max(50, H//5)
        lx = W - logo_s - max(20, W//25)
        ly = max(18, H//18)
        lbbox = draw_logo(draw, lx, ly, logo_s, ac, palette["bg"])
        rec.add(9, "__LOGO__", lbbox)

    # QR
    if 10 in content:
        qr_s = max(60, H//4)
        qr_img = make_qr(content[4], qr_s, ac, palette["bg"])
        qx = W - qr_s - max(15, W//30)
        qy = H - qr_s - max(15, H//25)
        img.paste(qr_img, (qx, qy))
        rec.add(10, "__QR__", [qx, qy, qx+qr_s, qy+qr_s])

    return img, rec


# ── L02: 중앙정렬 가로형 ──────────────────────────────────────
def render_L02(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    fh, fb = ftheme

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 24)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    pad = max(18, H//18)

    def cx(text, font): return (W - tw(draw,text,font)) // 2

    cy = pad
    # 상단 가로선
    accent_line(draw, W//6, cy+max(5,H//40), W*5//6, cy+max(5,H//40)+max(1,H//120), ac)
    cy += max(14, H//25)

    # 회사명
    bbox = put(draw, content[1], cx(content[1],f_co), cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(2, H//80)
    if 11 in content:
        bbox = put(draw, content[11], cx(content[11],f_ti), cy, f_ti, st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], f_ti) + max(2, H//80)

    cy += max(5, H//60)
    accent_line(draw, W//3, cy, W*2//3, cy+max(1,H//180), st)
    cy += max(8, H//45)

    # 이름
    bbox = put(draw, content[0], cx(content[0],f_nm), cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(3, H//80)
    # 직함
    bbox = put(draw, content[2], cx(content[2],f_ti), cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(3, H//70)
    if 12 in content:
        bbox = put(draw, content[12], cx(content[12],fnt(fb,8)), cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(3, H//70)

    accent_line(draw, W//3, cy, W*2//3, cy+max(1,H//180), st)
    cy += max(8, H//45)

    # 연락처 중앙
    for fid, label in [(3,"phone"),(6,"mobile"),(4,"email"),(8,"website"),(5,"address")]:
        if fid not in content: continue
        val  = content[fid]
        font = f_reg if fid != 5 else f_sml
        col  = pt if fid in {3,6,4} else st
        bbox = put(draw, val, cx(val,font), cy, font, col)
        rec.add(fid, val, bbox)
        cy += th(draw, val, font) + max(3, H//80)

    # 하단 가로선
    accent_line(draw, W//6, H-pad, W*5//6, H-pad+max(1,H//120), ac)

    # 로고 (우측 상단)
    if 9 in content:
        logo_s = max(45, H//6)
        lx = W - logo_s - pad
        ly = pad
        lbbox = draw_logo(draw, lx, ly, logo_s, ac, palette["bg"])
        rec.add(9, "__LOGO__", lbbox)

    # QR (좌측 하단)
    if 10 in content:
        qr_s = max(55, H//5)
        qr_img = make_qr(content[4], qr_s, ac, palette["bg"])
        img.paste(qr_img, (pad, H-qr_s-pad))
        rec.add(10, "__QR__", [pad, H-qr_s-pad, pad+qr_s, H-pad])

    return img, rec


# ── L03: 우측정렬 가로형 ──────────────────────────────────────
def render_L03(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    fh, fb = ftheme

    bar_w = max(8, W//80)
    accent_line(draw, W-bar_w, 0, W, H, ac)
    accent_line(draw, 0, H-max(3,H//60), W-bar_w, H, ac)

    pad = max(20, W//30)
    rpad = W - bar_w - pad
    my = max(18, H//18)

    f_co  = fnt(fh, 13)
    f_nm  = fnt(fh, 22)
    f_ti  = fnt(fb, 11)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    def rx(text, font): return rpad - tw(draw, text, font)

    cy = my
    bbox = put(draw, content[1], rx(content[1],f_co), cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//70)
    if 11 in content:
        bbox = put(draw, content[11], rx(content[11],f_ti), cy, f_ti, st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], f_ti) + max(2, H//80)

    cy += max(6, H//55)
    accent_line(draw, rpad - W//3, cy, rpad, cy+max(1,H//180), st)
    cy += max(8, H//45)

    bbox = put(draw, content[0], rx(content[0],f_nm), cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(3, H//80)
    bbox = put(draw, content[2], rx(content[2],f_ti), cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(10, H//35)

    for fid in [3,6,7,4,8,5]:
        if fid not in content: continue
        val  = content[fid]
        font = f_reg if fid != 5 else f_sml
        col  = pt if fid in {3,6,4} else st
        bbox = put(draw, val, rx(val,font), cy, font, col)
        rec.add(fid, val, bbox)
        cy += th(draw, val, font) + max(3, H//80)

    if 9 in content:
        logo_s = max(50, H//5)
        lbbox = draw_logo(draw, pad, my, logo_s, ac, palette["bg"])
        rec.add(9, "__LOGO__", lbbox)

    if 10 in content:
        qr_s = max(60, H//4)
        qr_img = make_qr(content[4], qr_s, ac, palette["bg"])
        qx, qy = pad, H-qr_s-my
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L04: 세로 분할 (좌:강조/우:연락처) 가로형 ───────────────────
def render_L04(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    split = W * 2 // 5
    # 좌측 강조 배경
    is_dark = sum(ac) < 400
    left_bg = ac
    left_tc = (255,255,255) if sum(ac)/3 < 128 else (15,15,15)
    draw.rectangle([0,0,split,H], fill=left_bg)

    f_co  = fnt(fh, 11)
    f_nm  = fnt(fh, 20)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    pad = max(16, W//40)
    my  = max(20, H//15)

    # 좌측: 이름 / 직함 (수직 중앙)
    name_h = th(draw, content[0], f_nm)
    ti_h   = th(draw, content[2], f_ti)
    total  = name_h + ti_h + max(6, H//50)
    sy     = (H - total) // 2
    bbox = put(draw, content[0], pad, sy, f_nm, left_tc)
    rec.add(0, content[0], bbox)
    sy += name_h + max(6, H//50)
    bbox = put(draw, content[2], pad, sy, f_ti, left_tc)
    rec.add(2, content[2], bbox)
    if 12 in content:
        bbox = put(draw, content[12], pad, sy + ti_h + max(4,H//70),
                   fnt(fb,7), left_tc)
        rec.add(12, content[12], bbox)

    # 우측: 회사명 + 연락처
    rx = split + pad
    cy = my
    bbox = put(draw, content[1], rx, cy, f_co, pt)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//70)
    if 11 in content:
        bbox = put(draw, content[11], rx, cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//70)
    cy += max(6, H//55)
    accent_line(draw, rx, cy, W-pad, cy+max(1,H//180), st)
    cy += max(6, H//55)
    _contact_block(draw, rec, content, rx, cy, f_reg, f_sml, pt, st, W)

    if 9 in content:
        logo_s = max(35, H//7)
        lx = W - logo_s - pad
        ly = my
        lbbox = draw_logo(draw, lx, ly, logo_s, ac if sum(bg)/3>128 else (255,255,255), bg)
        rec.add(9, "__LOGO__", lbbox)

    if 10 in content:
        qr_s = max(50, H//4-5)
        qr_img = make_qr(content[4], qr_s, pt, bg)
        qx, qy = W-qr_s-pad, H-qr_s-max(10,H//30)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L05: 상단 헤더 + 하단 연락처 가로형 ─────────────────────────
def render_L05(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    header_h = H * 2 // 5
    # 상단 헤더 배경
    draw.rectangle([0,0,W,header_h], fill=ac)
    head_tc = (255,255,255) if sum(ac)/3 < 128 else (15,15,15)

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 22)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    pad = max(18, W//35)
    hpad = max(14, H//25)

    # 헤더: 이름 + 직함
    cy = hpad
    bbox = put(draw, content[0], pad, cy, f_nm, head_tc)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(4, H//60)
    bbox = put(draw, content[2], pad, cy, f_ti, head_tc)
    rec.add(2, content[2], bbox)

    # 헤더 우측: 로고
    if 9 in content:
        logo_s = max(40, header_h - hpad*2)
        lx = W - logo_s - pad
        ly = hpad
        lbbox = draw_logo(draw, lx, ly, logo_s, head_tc, ac)
        rec.add(9, "__LOGO__", lbbox)

    # 하단: 회사 + 연락처
    cy = header_h + hpad
    bbox = put(draw, content[1], pad, cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//70)
    if 11 in content:
        bbox = put(draw, content[11], pad, cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//70)
    if 12 in content:
        bbox = put(draw, content[12], pad, cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(3, H//70)
    cy += max(4, H//60)

    # 연락처 2컬럼
    left_fids  = [(3,"phone"),(6,"mobile"),(7,"fax")]
    right_fids = [(4,"email"),(8,"website"),(5,"address")]
    lcx = pad
    rcx = W // 2 + pad
    lcy = rcy = cy
    for fid, _ in left_fids:
        if fid not in content: continue
        val = content[fid]
        bbox = put(draw, val, lcx, lcy, f_reg, pt)
        rec.add(fid, val, bbox)
        lcy += th(draw, val, f_reg) + max(3, H//80)
    for fid, _ in right_fids:
        if fid not in content: continue
        val = content[fid]
        font = f_reg if fid != 5 else f_sml
        bbox = put(draw, val, rcx, rcy, font, pt if fid == 4 else st)
        rec.add(fid, val, bbox)
        rcy += th(draw, val, font) + max(3, H//80)

    if 10 in content:
        qr_s = max(55, H//4)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx, qy = W-qr_s-pad, H-qr_s-max(10,H//30)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L06: 미니멀 모던 (가로형, 로고 좌+텍스트 우) ────────────────
def render_L06(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    pad  = max(22, W//28)
    logo_s = max(70, H//3)
    f_co   = fnt(fh, 11)
    f_nm   = fnt(fh, 21)
    f_ti   = fnt(fb, 10)
    f_reg  = fnt(fb, 9)
    f_sml  = fnt(fb, 8)

    # 좌측 로고 + 회사명 수직 중앙
    ly = (H - logo_s) // 2
    if 9 in content:
        lbbox = draw_logo(draw, pad, ly, logo_s, ac, bg)
        rec.add(9, "__LOGO__", lbbox)
    co_x = pad + logo_s + max(12, W//50)
    co_y = ly + (logo_s - th(draw, content[1], f_co)) // 2
    bbox = put(draw, content[1], co_x, co_y, f_co, ac)
    rec.add(1, content[1], bbox)

    # 수직 구분선
    div_x = co_x + max(tw(draw,content[1],f_co), logo_s) + max(20, W//30)
    accent_line(draw, div_x, pad, div_x+max(1,W//200), H-pad, st)

    # 우측: 이름/직함/연락처
    rx = div_x + max(20, W//30)
    cy = max(22, H//15)
    bbox = put(draw, content[0], rx, cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(4, H//60)
    bbox = put(draw, content[2], rx, cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(3, H//70)
    if 11 in content:
        bbox = put(draw, content[11], rx, cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//70)
    cy += max(6, H//55)
    accent_line(draw, rx, cy, W-pad, cy+max(1,H//180), st)
    cy += max(6, H//55)
    _contact_block(draw, rec, content, rx, cy, f_reg, f_sml, pt, st, W)

    if 10 in content:
        qr_s = max(55, H//4)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx, qy = W-qr_s-pad, H-qr_s-max(12,H//28)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L07: 세로형 중앙정렬 ─────────────────────────────────────
def render_L07(content, palette, ftheme, bg_pattern, company_en):
    W, H = PT_W, PT_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 22)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    pad = max(20, W//15)

    def cx(text, font): return (W - tw(draw,text,font)) // 2

    # 상단 로고
    cy = max(25, H//20)
    if 9 in content:
        logo_s = max(60, W//4)
        lx = (W - logo_s) // 2
        lbbox = draw_logo(draw, lx, cy, logo_s, ac, bg)
        rec.add(9, "__LOGO__", lbbox)
        cy += logo_s + max(12, H//40)

    accent_line(draw, W//5, cy, W*4//5, cy+max(2,H//200), ac)
    cy += max(10, H//50)

    # 회사명
    bbox = put(draw, content[1], cx(content[1],f_co), cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//80)
    if 11 in content:
        bbox = put(draw, content[11], cx(content[11],fnt(fb,9)), cy, fnt(fb,9), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,9)) + max(2, H//90)

    cy += max(8, H//50)
    accent_line(draw, W//4, cy, W*3//4, cy+max(1,H//220), st)
    cy += max(10, H//50)

    # 이름
    bbox = put(draw, content[0], cx(content[0],f_nm), cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(5, H//70)
    bbox = put(draw, content[2], cx(content[2],f_ti), cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(5, H//70)
    if 12 in content:
        bbox = put(draw, content[12], cx(content[12],fnt(fb,8)), cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(5, H//70)

    cy += max(10, H//50)
    accent_line(draw, W//4, cy, W*3//4, cy+max(1,H//220), st)
    cy += max(10, H//50)

    # 연락처
    for fid in [3,6,7,4,8,5]:
        if fid not in content: continue
        val  = content[fid]
        font = f_reg if fid != 5 else f_sml
        col  = pt if fid in {3,6,4} else st
        bbox = put(draw, val, cx(val,font), cy, font, col)
        rec.add(fid, val, bbox)
        cy += th(draw, val, font) + max(4, H//75)

    if 10 in content:
        qr_s = max(70, W//3)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx = (W - qr_s) // 2
        qy = H - qr_s - max(20, H//30)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L08: 세로형 상단강조 + 하단흰배경 ──────────────────────────
def render_L08(content, palette, ftheme, bg_pattern, company_en):
    W, H = PT_W, PT_H
    img  = Image.new("RGB", (W,H))
    bg = palette["bg"]
    img.paste(bg, [0,0,W,H])
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    fh, fb = ftheme

    header_h = H * 2 // 5
    draw.rectangle([0,0,W,header_h], fill=ac)
    head_tc = (255,255,255) if sum(ac)/3 < 128 else (15,15,15)

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 20)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)
    pad   = max(18, W//18)

    def cx(text, font): return (W - tw(draw,text,font)) // 2

    # 헤더: 로고 + 이름
    cy = max(20, header_h//8)
    if 9 in content:
        logo_s = max(50, W//5)
        lx = (W - logo_s) // 2
        lbbox = draw_logo(draw, lx, cy, logo_s, head_tc, ac)
        rec.add(9, "__LOGO__", lbbox)
        cy += logo_s + max(10, header_h//10)

    bbox = put(draw, content[0], cx(content[0],f_nm), cy, f_nm, head_tc)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(4, H//70)
    bbox = put(draw, content[2], cx(content[2],f_ti), cy, f_ti, head_tc)
    rec.add(2, content[2], bbox)

    # 하단 섹션
    cy = header_h + max(18, H//25)
    bbox = put(draw, content[1], cx(content[1],f_co), cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//80)
    if 11 in content:
        bbox = put(draw, content[11], cx(content[11],fnt(fb,8)), cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//80)
    if 12 in content:
        bbox = put(draw, content[12], cx(content[12],fnt(fb,8)), cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(3, H//80)

    cy += max(8, H//55)
    accent_line(draw, pad, cy, W-pad, cy+max(1,H//200), ac)
    cy += max(10, H//50)

    for fid in [3,6,7,4,8,5]:
        if fid not in content: continue
        val  = content[fid]
        font = f_reg if fid != 5 else f_sml
        col  = pt if fid in {3,6,4} else st
        bbox = put(draw, val, cx(val,font), cy, font, col)
        rec.add(fid, val, bbox)
        cy += th(draw, val, font) + max(4, H//75)

    if 10 in content:
        qr_s = max(70, W//3)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx = (W - qr_s) // 2
        qy = H - qr_s - max(20, H//30)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L09: 세로형 좌측정렬 ─────────────────────────────────────
def render_L09(content, palette, ftheme, bg_pattern, company_en):
    W, H = PT_W, PT_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    bar_w = max(6, W//60)
    accent_line(draw, 0, 0, bar_w, H, ac)
    pad = bar_w + max(16, W//20)
    cy  = max(22, H//22)

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 20)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    if 9 in content:
        logo_s = max(55, W//4)
        lbbox = draw_logo(draw, pad, cy, logo_s, ac, bg)
        rec.add(9, "__LOGO__", lbbox)
        cy += logo_s + max(10, H//45)

    bbox = put(draw, content[1], pad, cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//80)
    if 11 in content:
        bbox = put(draw, content[11], pad, cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//80)

    cy += max(8, H//55)
    accent_line(draw, pad, cy, W - max(16,W//20), cy+max(1,H//220), ac)
    cy += max(10, H//50)

    bbox = put(draw, content[0], pad, cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(5, H//70)
    bbox = put(draw, content[2], pad, cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(5, H//70)
    if 12 in content:
        bbox = put(draw, content[12], pad, cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(5, H//70)

    cy += max(8, H//55)
    accent_line(draw, pad, cy, W - max(16,W//20), cy+max(1,H//220), st)
    cy += max(10, H//50)

    _contact_block(draw, rec, content, pad, cy, f_reg, f_sml, pt, st, W)

    if 10 in content:
        qr_s = max(65, W//3)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx = W - qr_s - max(14, W//22)
        qy = H - qr_s - max(16, H//35)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L10: 세로형 하단강조 바 + 상단정보 ──────────────────────────
def render_L10(content, palette, ftheme, bg_pattern, company_en):
    W, H = PT_W, PT_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    footer_h = H // 3
    # 하단 강조 배경
    draw.rectangle([0, H-footer_h, W, H], fill=ac)
    foot_tc = (255,255,255) if sum(ac)/3 < 128 else (15,15,15)

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 20)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)
    pad   = max(18, W//18)

    def cx(text, font): return (W - tw(draw,text,font)) // 2

    cy = max(22, H//22)
    if 9 in content:
        logo_s = max(55, W//4)
        lx = (W - logo_s) // 2
        lbbox = draw_logo(draw, lx, cy, logo_s, ac, bg)
        rec.add(9, "__LOGO__", lbbox)
        cy += logo_s + max(10, H//45)

    bbox = put(draw, content[0], cx(content[0],f_nm), cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(5, H//70)
    bbox = put(draw, content[2], cx(content[2],f_ti), cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(5, H//70)
    if 11 in content:
        bbox = put(draw, content[11], cx(content[11],fnt(fb,8)), cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(4, H//75)

    accent_line(draw, pad, cy, W-pad, cy+max(1,H//200), st)
    cy += max(8, H//55)

    for fid in [3,6,4,8]:
        if fid not in content: continue
        val = content[fid]
        bbox = put(draw, val, cx(val,f_reg), cy, f_reg, pt)
        rec.add(fid, val, bbox)
        cy += th(draw, val, f_reg) + max(4, H//75)

    # 하단 강조 영역: 회사명 + 주소 + QR
    fcy = H - footer_h + max(16, footer_h//6)
    bbox = put(draw, content[1], cx(content[1],f_co), fcy, f_co, foot_tc)
    rec.add(1, content[1], bbox)
    fcy += th(draw, content[1], f_co) + max(4, H//75)
    if 5 in content:
        bbox = put(draw, content[5], cx(content[5],f_sml), fcy, f_sml, foot_tc)
        rec.add(5, content[5], bbox)
        fcy += th(draw, content[5], f_sml) + max(4, H//75)
    if 12 in content:
        bbox = put(draw, content[12], cx(content[12],fnt(fb,8)), fcy, fnt(fb,8), foot_tc)
        rec.add(12, content[12], bbox)

    if 10 in content:
        qr_s = max(55, footer_h - max(16,footer_h//6)*2 - max(20,H//25))
        qr_img = make_qr(content[4], qr_s, foot_tc, ac)
        qx = W - qr_s - pad
        qy = H - footer_h + (footer_h - qr_s) // 2
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L11: 가로형 2컬럼 그리드 ─────────────────────────────────
def render_L11(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    pad  = max(20, W//30)
    mid  = W // 2

    f_co  = fnt(fh, 11)
    f_nm  = fnt(fh, 21)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    # 상단 풀폭 헤더
    cy = max(18, H//20)
    bbox = put(draw, content[1], pad, cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//70)
    if 11 in content:
        bbox = put(draw, content[11], pad, cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//70)
    cy += max(4, H//60)
    accent_line(draw, pad, cy, W-pad, cy+max(2,H//130), ac)
    cy += max(6, H//55)

    # 좌: 이름/직함
    lcy = cy
    bbox = put(draw, content[0], pad, lcy, f_nm, pt)
    rec.add(0, content[0], bbox)
    lcy += th(draw, content[0], f_nm) + max(4, H//60)
    bbox = put(draw, content[2], pad, lcy, f_ti, ac)
    rec.add(2, content[2], bbox)
    lcy += th(draw, content[2], f_ti) + max(3, H//70)
    if 12 in content:
        bbox = put(draw, content[12], pad, lcy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        lcy += th(draw, content[12], fnt(fb,8)) + max(3, H//70)

    # 수직 구분선
    accent_line(draw, mid, cy, mid+max(1,W//250), H-max(18,H//20), st)

    # 우: 연락처
    rcy = cy
    for fid in [3,6,7,4,8,5]:
        if fid not in content: continue
        val  = content[fid]
        font = f_reg if fid != 5 else f_sml
        col  = pt if fid in {3,6,4} else st
        bbox = put(draw, val, mid+pad, rcy, font, col)
        rec.add(fid, val, bbox)
        rcy += th(draw, val, font) + max(3, H//80)

    # QR + 로고
    if 9 in content:
        logo_s = max(40, H//5)
        lx = W - logo_s - pad
        ly = max(18, H//20)
        lbbox = draw_logo(draw, lx, ly, logo_s, ac, bg)
        rec.add(9, "__LOGO__", lbbox)

    if 10 in content:
        qr_s = max(50, H//4)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx = W - qr_s - pad
        qy = H - qr_s - max(15, H//25)
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ── L12: 가로형 박스형 레이아웃 (외곽 테두리) ──────────────────
def render_L12(content, palette, ftheme, bg_pattern, company_en):
    W, H = LS_W, LS_H
    img  = Image.new("RGB", (W,H))
    make_background(img, palette, bg_pattern)
    draw = ImageDraw.Draw(img)
    rec  = AnnotationRecorder()
    pt, st, ac = palette["pt"], palette["st"], palette["ac"]
    bg = palette["bg"]
    fh, fb = ftheme

    bw   = max(5, W//80)      # 테두리 두께
    ipad = max(22, W//28)     # 내부 패딩

    # 외곽 테두리
    draw.rectangle([bw//2, bw//2, W-bw//2, H-bw//2], outline=ac, width=bw)

    # 모서리 장식
    corner = max(20, W//30)
    for cx_, cy_ in [(0,0),(W,0),(0,H),(W,H)]:
        sx = min(cx_+corner, W-bw) if cx_==0 else max(cx_-corner, bw)
        ex = bw if cx_==0 else W-bw
        sy = min(cy_+corner, H-bw) if cy_==0 else max(cy_-corner, bw)
        ey = bw if cy_==0 else H-bw
        # 수평
        draw.rectangle([min(ex,sx), min(ey,sy)-bw, max(ex,sx), min(ey,sy)], fill=ac)
        # 수직
        draw.rectangle([min(ex,sx)-bw, min(ey,sy), min(ex,sx), max(ey,sy)], fill=ac)

    f_co  = fnt(fh, 12)
    f_nm  = fnt(fh, 21)
    f_ti  = fnt(fb, 10)
    f_reg = fnt(fb, 9)
    f_sml = fnt(fb, 8)

    ix = bw + ipad
    cy = bw + ipad

    # 로고 우측 상단
    if 9 in content:
        logo_s = max(45, H//5)
        lx = W - logo_s - bw - ipad
        lbbox = draw_logo(draw, lx, cy, logo_s, ac, bg)
        rec.add(9, "__LOGO__", lbbox)

    bbox = put(draw, content[1], ix, cy, f_co, ac)
    rec.add(1, content[1], bbox)
    cy += th(draw, content[1], f_co) + max(3, H//70)
    if 11 in content:
        bbox = put(draw, content[11], ix, cy, fnt(fb,8), st)
        rec.add(11, content[11], bbox)
        cy += th(draw, content[11], fnt(fb,8)) + max(3, H//70)
    if 12 in content:
        bbox = put(draw, content[12], ix, cy, fnt(fb,8), st)
        rec.add(12, content[12], bbox)
        cy += th(draw, content[12], fnt(fb,8)) + max(3, H//70)

    cy += max(5, H//60)
    accent_line(draw, ix, cy, W-ix, cy+max(1,H//180), ac)
    cy += max(8, H//50)

    bbox = put(draw, content[0], ix, cy, f_nm, pt)
    rec.add(0, content[0], bbox)
    cy += th(draw, content[0], f_nm) + max(4, H//60)
    bbox = put(draw, content[2], ix, cy, f_ti, ac)
    rec.add(2, content[2], bbox)
    cy += th(draw, content[2], f_ti) + max(10, H//35)

    _contact_block(draw, rec, content, ix, cy, f_reg, f_sml, pt, st, W)

    if 10 in content:
        qr_s = max(55, H//4)
        qr_img = make_qr(content[4], qr_s, ac, bg)
        qx = W - qr_s - bw - ipad
        qy = H - qr_s - bw - ipad
        img.paste(qr_img, (qx,qy))
        rec.add(10, "__QR__", [qx,qy,qx+qr_s,qy+qr_s])

    return img, rec


# ══════════════════════════════════════════════════════════════
#  10. 레이아웃 레지스트리
# ══════════════════════════════════════════════════════════════

LAYOUTS = {
    "L01_landscape_left":        render_L01,
    "L02_landscape_center":      render_L02,
    "L03_landscape_right":       render_L03,
    "L04_landscape_split":       render_L04,
    "L05_landscape_header":      render_L05,
    "L06_landscape_logo_left":   render_L06,
    "L07_portrait_center":       render_L07,
    "L08_portrait_top_accent":   render_L08,
    "L09_portrait_left":         render_L09,
    "L10_portrait_bottom_accent":render_L10,
    "L11_landscape_2col":        render_L11,
    "L12_landscape_border_box":  render_L12,
}

BG_PATTERNS = ["plain", "dots", "stripes", "grid", "waves"]

# ══════════════════════════════════════════════════════════════
#  11. 메인 생성 루프
# ══════════════════════════════════════════════════════════════

def main():
    os.makedirs(f"{OUTPUT_DIR}/images",      exist_ok=True)
    os.makedirs(f"{OUTPUT_DIR}/annotations", exist_ok=True)

    all_index = []
    card_idx  = 0

    for layout_name, render_fn in LAYOUTS.items():
        print(f"\n▶ 레이아웃: {layout_name}")
        for i in range(CARDS_PER_LAYOUT):
            palette     = random.choice(PALETTES)
            ftheme      = random.choice(FONT_THEMES)
            bg_pattern  = random.choice(BG_PATTERNS)
            content, co_en = gen_content()

            try:
                img, rec = render_fn(content, palette, ftheme, bg_pattern, co_en)
            except Exception as e:
                print(f"  ✗ [{card_idx:04d}] 오류: {e}")
                continue

            # 파일명
            img_fname  = f"card_{card_idx:04d}_{layout_name}.jpg"
            ann_fname  = f"card_{card_idx:04d}_{layout_name}.json"

            # 이미지 저장 (300 DPI JPEG)
            img.save(
                f"{OUTPUT_DIR}/images/{img_fname}",
                "JPEG", quality=95, dpi=(DPI, DPI),
            )

            # 어노테이션 저장
            W, H = img.size
            annotation = {
                "image_file":    img_fname,
                "width_px":      W,
                "height_px":     H,
                "dpi":           DPI,
                "orientation":   "portrait" if H > W else "landscape",
                "layout":        layout_name,
                "font_theme":    list(ftheme),
                "bg_pattern":    bg_pattern,
                "palette_bg":    list(palette["bg"]),
                "palette_ac":    list(palette["ac"]),
                "fields":        rec.fields,
            }
            with open(f"{OUTPUT_DIR}/annotations/{ann_fname}", "w", encoding="utf-8") as f:
                json.dump(annotation, f, ensure_ascii=False, indent=2)

            all_index.append({
                "id":          card_idx,
                "image_file":  img_fname,
                "layout":      layout_name,
                "orientation": annotation["orientation"],
                "num_fields":  len(rec.fields),
            })

            print(f"  ✓ [{card_idx:04d}] {img_fname}  fields={len(rec.fields)}")
            card_idx += 1

    # 전체 인덱스
    index_data = {
        "total_cards":   card_idx,
        "layouts":       list(LAYOUTS.keys()),
        "cards_per_layout": CARDS_PER_LAYOUT,
        "dpi":           DPI,
        "field_schema":  FIELD_NAMES,
        "bbox_format":   "xyxy (x1,y1,x2,y2) pixel coordinates",
        "cards":         all_index,
    }
    with open(f"{OUTPUT_DIR}/index.json", "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료! 총 {card_idx}장 생성")
    print(f"   이미지:      {OUTPUT_DIR}/images/")
    print(f"   어노테이션:  {OUTPUT_DIR}/annotations/")
    print(f"   인덱스:      {OUTPUT_DIR}/index.json")


if __name__ == "__main__":
    main()
