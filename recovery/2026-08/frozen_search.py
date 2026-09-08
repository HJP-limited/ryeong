import ast
import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "scripts/eval_search.py"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, n=1):
    global s
    assert s.count(old) == n, f"{s.count(old)}건(기대 {n}) -> {old[:60]!r}"
    s = s.replace(old, new)


rep("""def main():
    rng = random.Random(42)
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))""",
"""DEFAULT_BENCH = "bench/hjp_search_v1.json"


def load_frozen_queries(path, cards):
    \"\"\"
    동결본을 읽는다. **여기서 질의를 만들지 않는다** — 시험지와 채점기를 분리해야
    시험지를 안 건드린 채로 채점 기준만 고칠 수 있고, 반대도 된다.

    카드 지문을 대조한다. 카드가 바뀐 뒤 옛 동결본을 돌리면 정답 id 가 다른 사람을
    가리킬 수 있는데, id 는 그대로라 다른 검사로는 안 잡힌다.
    \"\"\"
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    print(f"{payload['dataset_version']}  (동결 {payload.get('built_at') or '시각 없음'}, "
          f"시드 {payload['seed']})")
    now = _cfp.answer_fingerprint(cards)
    if payload.get("cards_fingerprint") and payload["cards_fingerprint"] != now:
        print(f"  [중단] 카드가 동결 시점과 다르다 — 동결본 {payload['cards_fingerprint'][:16]}… "
              f"vs 지금 {now[:16]}…")
        print("         정답 id 가 다른 사람을 가리킬 수 있다. 시험지를 다시 찍을 것"
              "(scripts/build_search_bench.py).")
        raise SystemExit(2)
    return [(q["kind"], q["query"], q["relevant"]) for q in payload["queries"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=DEFAULT_BENCH,
                    help="동결된 질의셋. 이걸 읽고 여기서 질의를 만들지 않는다")
    ap.add_argument("--regenerate", action="store_true",
                    help="동결본을 무시하고 즉석 생성한다. **동결본을 새로 찍기 전에 "
                         "미리 보는 용도**이지 평가용이 아니다 — 이걸로 낸 숫자는 "
                         "다른 실행과 비교할 수 없다")
    args = ap.parse_args()

    rng = random.Random(42)
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))""")

rep("""    queries = build_eval_queries(cards, rng)""",
"""    if args.regenerate:
        print("  [주의] 즉석 생성 — 이 숫자는 다른 실행과 비교하지 말 것")
        queries = build_eval_queries(cards, rng)
    else:
        queries = load_frozen_queries(args.bench, cards)""")

rep("""import json
import math
import os""",
"""import argparse
import json
import math
import os""")

io.open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("검색 동결본 읽기 OK")
