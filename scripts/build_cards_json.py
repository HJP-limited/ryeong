# 합성 명함 라벨(out/final/labels/*.json) 5000장을 앱 임포트용 cards JSON 하나로 변환한다.
# 사용법: python scripts/build_cards_json.py
# 출력: data/cards_5000.json (앱의 "명함 데이터 가져오기(JSON)" 버튼으로 임포트)
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LABELS_DIR = REPO.parent / "HJP_limitededition-main" / "out" / "final" / "labels"
OUT_PATH = REPO / "data" / "cards_5000.json"

# 라벨 field -> 앱 BusinessCardEntity 필드 매핑에 쓰지 않는 것들
IGNORED_FIELDS = {"logo_text", "logo_area", "website"}

# 명함 렌더링용 라벨 텍스트가 값 앞에 붙어 있는 경우 제거 ("Mobile. 010-..." -> "010-...")
LABEL_PREFIXES = ("Mobile.", "Tel.", "TEL.", "E-mail.", "Email.", "Address.", "Fax.", "H.P.")


def strip_label_prefix(text: str) -> str:
    stripped = text.strip()
    for prefix in LABEL_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def region_texts(label: dict) -> dict:
    out = {}
    for region in label.get("regions", []):
        field = region.get("field", "")
        if field in IGNORED_FIELDS or field in out:
            continue
        out[field] = strip_label_prefix(region.get("text") or "")
    return out


def location_from_address(address: str) -> str:
    # "충청북도 제천시 ..." -> "충청북도" 수준의 대략적 지역 필드
    return address.split()[0] if address.strip() else ""


def main() -> None:
    if not LABELS_DIR.is_dir():
        sys.exit(f"labels dir not found: {LABELS_DIR}")
    cards = []
    for i, path in enumerate(sorted(LABELS_DIR.glob("*.json"))):
        with open(path, encoding="utf-8") as f:
            label = json.load(f)
        fields = region_texts(label)
        address = fields.get("address_ko", "")
        cards.append(
            {
                "id": f"S{i:05d}",
                "name": fields.get("name_ko", ""),
                "nameEn": fields.get("name_en", ""),
                "company": fields.get("company_ko", ""),
                "title": fields.get("title", ""),
                "department": fields.get("department", ""),
                "industry": "",
                "location": location_from_address(address),
                "phone": fields.get("mobile", "") or fields.get("tel_office", ""),
                "email": fields.get("email", ""),
                "address": address,
                "memo": "",
                "tags": "",
            }
        )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(cards)} cards -> {OUT_PATH}")


if __name__ == "__main__":
    main()
