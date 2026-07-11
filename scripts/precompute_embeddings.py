# data/cards_5000.json의 각 명함을 EmbeddingGemma로 미리 임베딩해서 앱에 번들한다.
# 폰에서 라이브 모델을 못 띄워도 시맨틱 검색이 바로 동작하도록 하기 위함 (OCR 붙기 전 임시 조치).
# 사용법: python scripts/precompute_embeddings.py
import json
import struct
from pathlib import Path

from sentence_transformers import SentenceTransformer

REPO = Path(__file__).resolve().parent.parent
CARDS_PATH = REPO / "data" / "cards_5000.json"
MODEL_PATH = REPO / "models" / "embeddinggemma-300m"
OUT_DIR = REPO / "app" / "src" / "main" / "assets" / "cards"
IDS_PATH = OUT_DIR / "cards_embeddings_ids.json"
VECTORS_PATH = OUT_DIR / "cards_embeddings.bin"

# CardSearchService.cardEmbeddingInput()과 반드시 동일한 필드 순서/구분자를 써야
# 나중에 온디바이스에서 재계산될 때(OCR 카드 등) 같은 입력 형식이 된다.
FIELDS = ["name", "nameEn", "company", "title", "department", "industry", "location", "memo", "tags"]


def card_text(card: dict) -> str:
    parts = [card.get(f, "") for f in FIELDS]
    return ", ".join(p for p in parts if p)


def main() -> None:
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    model = SentenceTransformer(str(MODEL_PATH))

    texts = [card_text(c) for c in cards]
    print(f"encoding {len(texts)} cards...")
    vectors = model.encode_document(texts, batch_size=64, show_progress_bar=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ids = [c["id"] for c in cards]
    IDS_PATH.write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")

    with open(VECTORS_PATH, "wb") as f:
        for vec in vectors:
            f.write(struct.pack(f"<{len(vec)}f", *vec.tolist()))

    print(f"wrote {len(ids)} ids -> {IDS_PATH}")
    print(f"wrote {VECTORS_PATH} ({VECTORS_PATH.stat().st_size / 1024 / 1024:.1f} MB, dim={vectors.shape[1]})")


if __name__ == "__main__":
    main()
