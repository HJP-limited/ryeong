"""
검색 평가 질의를 **파일로 동결한다.**

지금까지 `eval_search.py` 는 실행할 때마다 카드에서 질의를 새로 뽑았다. 시드가 42 로
고정이라 같은 카드면 같은 질의가 나오지만, 그건 고정셋이 아니다:

  · 카드 데이터가 바뀌면 질의가 통째로 바뀌어 **이전 숫자와의 비교가 끊긴다**
  · 질의 생성 규칙을 고치면 시험지가 바뀌는데 그게 성능 변화와 **같은 숫자 안에서 섞인다**
    (실측: S2·S3 를 넣자 183 -> 282 질의가 됐고 R@5 0.930 -> 0.951 이 됐다.
     성능이 오른 게 아니라 시험지가 바뀐 것이다)

멀티턴은 `build_bench.py` 로 찍고 `run_bench.py` 가 동결본만 읽는다. 검색도 같게 맞춘다.
시험지를 바꾸려면 **버전을 올려 다시 찍는다** — 그러면 변경이 기록에 남는다.

    python scripts/build_search_bench.py --out bench/hjp_search_v1.json

카드 지문을 함께 박는다. 카드가 바뀐 뒤 옛 동결본을 돌리면 정답 id 가 다른 사람을
가리킬 수 있는데, 그건 실행 시점에 잡아야 하는 사고다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import card_fingerprint as cfp     # noqa: E402
import eval_search as ev           # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bench" / "hjp_search_v1.json"))
    ap.add_argument("--seed", type=int, default=42,
                    help="질의 표집 시드. 기본 42 는 지금까지 쓰던 값이라 동결 직전과 "
                         "직후 숫자가 같아야 한다 — 그게 동결이 제대로 됐다는 증거다")
    ap.add_argument("--built-at", default="", help="동결 시각(문자열). 재현을 위해 밖에서 준다")
    args = ap.parse_args()

    cards = json.loads(ev.CARDS_PATH.read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    queries = ev.build_eval_queries(cards, rng)

    by_id = {c["id"] for c in cards}
    for kind, q, relevant in queries:
        # 정답 id 가 실재하는지 여기서 본다. 동결본이 없는 카드를 가리키면 그 파일은
        # 영영 틀린 채로 재사용된다.
        missing = [r for r in relevant if r not in by_id]
        assert not missing, f"{kind} {q!r} 의 정답에 없는 카드: {missing[:3]}"

    counts = Counter(kind for kind, _, _ in queries)
    ranking = sum(n for k, n in counts.items() if not k.startswith("기권"))
    abstain = sum(n for k, n in counts.items() if k.startswith("기권"))

    payload = {
        "dataset_version": Path(args.out).stem,
        "built_at": args.built_at,
        "seed": args.seed,
        "cards_file": ev.CARDS_PATH.name,
        "cards_fingerprint": cfp.answer_fingerprint(cards),
        "description": (
            "검색 평가 질의 동결본. 카드에서 정답이 자동으로 확정되는 질의만 담는다. "
            "한 번 찍어 동결한다 — 질의 생성 규칙을 고쳐도 이 파일은 안 바뀌므로 "
            "시간에 걸친 비교가 성립한다. 시험지를 바꾸려면 버전을 올려 다시 찍는다."
        ),
        "counts": dict(sorted(counts.items())),
        "queries": [
            {"kind": kind, "query": q, "relevant": relevant}
            for kind, q, relevant in queries
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{out}  —  질의 {len(queries)}개 (랭킹 {ranking} + 기권 {abstain})")
    print(f"  카드 {len(cards)}장 · 지문 {payload['cards_fingerprint'][:16]}…")
    for kind, n in sorted(counts.items()):
        print(f"    {kind:<20} n={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
