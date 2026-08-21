"""카드 데이터 지문(fingerprint) — 임베딩이 카드와 어긋난 걸 잡는다.

**이게 막으려는 사고**: 카드를 다시 만들고 `precompute_embeddings.py` 를 안 돌리면
벡터가 옛날 내용으로 남아 시맨틱 검색이 **조용히** 망가진다. 카드 id 는 그대로라
'ids 순서 일치' 같은 검사로는 안 잡히고, 지표가 조금 나빠질 뿐이라 눈치채기 어렵다
(실제로 놓친 적 있다).

그래서 임베딩을 만들 때 **그때 쓴 카드 내용의 SHA-256 을 같이 적어 두고**, 평가할 때
지금 카드로 다시 계산해 비교한다. 다르면 벡터가 낡은 것이다.

지문 대상 필드는 **임베딩 입력 필드와 같아야 한다**(`EMBEDDING_FIELDS`). 전화번호처럼
임베딩에 안 들어가는 값이 바뀐 걸로 "벡터가 낡았다"고 하면 거짓 경보가 된다.

`HJP-limited/ymj` 의 `eval_benchmark_final50_v3.py` 에서 가져온 방식이다. 다만 거기서는
정답값(phone/email/address 포함)이 바뀌었는지 보려는 것이라 필드 집합이 다르다.
두 목적이 다르므로 함수를 나눠 둔다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# precompute_embeddings.py 의 FIELDS 와 반드시 같아야 한다.
EMBEDDING_FIELDS = [
    "name", "nameEn", "company", "title", "department",
    "industry", "location", "memo", "tags",
]

# 답변으로 나가는 값들. 벤치마크 정답이 아직 유효한지 볼 때 쓴다.
ANSWER_FIELDS = [
    "id", "name", "company", "title", "department",
    "location", "phone", "email", "address",
]

STAMP_NAME = "cards_embeddings_fingerprint.json"


def fingerprint(cards, fields) -> str:
    """카드 목록을 id 순으로 정렬해 지정 필드만 canonical JSON 으로 직렬화한 SHA-256."""
    rows = [{f: c.get(f, "") for f in fields} for c in sorted(cards, key=lambda c: str(c.get("id")))]
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def embedding_fingerprint(cards) -> str:
    return fingerprint(cards, EMBEDDING_FIELDS)


def answer_fingerprint(cards) -> str:
    return fingerprint(cards, ANSWER_FIELDS)


def write_stamp(path: Path, cards, cards_file: str) -> str:
    """임베딩을 만든 직후 호출한다. 그때 쓴 카드의 지문을 남긴다."""
    fp = embedding_fingerprint(cards)
    path.write_text(json.dumps({
        "cards_file": cards_file,
        "count": len(cards),
        "embedding_input_sha256": fp,
        "answer_sha256": answer_fingerprint(cards),
        "fields": EMBEDDING_FIELDS,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


def check_stamp(path: Path, cards):
    """(상태, 메시지) 를 돌려준다. 상태: 'ok' | 'stale' | 'missing'.

    **여기서 예외를 던지지 않는다** — 지문이 없다고 평가를 아예 못 돌리게 하면,
    지문을 붙이기 전에 만든 기존 임베딩으로는 아무것도 못 재게 된다. 대신 부르는 쪽에서
    눈에 띄게 찍는다.
    """
    now = embedding_fingerprint(cards)
    if not path.exists():
        return "missing", (
            f"임베딩 지문 파일이 없다({path.name}). 벡터가 지금 카드와 맞는지 확인할 수 없다.\n"
            f"    python scripts/precompute_embeddings.py --copy-to-assets  로 다시 만들면 생긴다."
        )
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("embedding_input_sha256")
    except (OSError, ValueError) as e:
        return "missing", f"임베딩 지문 파일을 읽지 못했다({path.name}): {e}"
    if saved == now:
        return "ok", ""
    return "stale", (
        "임베딩이 지금 카드 데이터와 다르다 — 시맨틱 검색이 옛날 내용으로 돌고 있다.\n"
        f"    임베딩 생성 당시: {saved}\n"
        f"    지금 카드       : {now}\n"
        "    python scripts/precompute_embeddings.py --copy-to-assets  를 돌린 뒤 다시 측정할 것."
    )


def banner(status: str, message: str) -> str:
    """경고를 출력 중간에 묻히지 않게 감싼다."""
    if status == "ok":
        return ""
    label = "임베딩 불일치" if status == "stale" else "임베딩 지문 없음"
    line = "!" * 78
    return f"\n{line}\n  [{label}] {message}\n{line}\n"
