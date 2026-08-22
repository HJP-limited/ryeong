from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "business_card_multiturn_benchmark_final50_v3.json"
DEFAULT_CARDS = HERE.parent / "data" / "cards_eval1000.json"
DEFAULT_ENDPOINT = "http://127.0.0.1:8100/chat"

EXPECTED_CATEGORIES = {
    "long_range_reactivation": 10,
    "local_state_carryover": 10,
    "explicit_target_correction": 10,
    "discourse_coreference": 10,
    "unanswerable": 10,
}


def canonical_fingerprint(cards):
    fields = ["id", "name", "company", "title", "department", "location", "phone", "email", "address"]
    rows = [{f: c.get(f, "") for f in fields} for c in sorted(cards, key=lambda x: x["id"])]
    raw = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compact(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", s)


def normalize_answer(s):
    """
    Exact Match용 정규화.
    NFKC -> lowercase -> 한글/영문/숫자 이외 제거.
    전화번호/이메일의 하이픈·공백·기호 차이는 무시한다.
    """
    return compact(s)


def value_hit(answer, value):
    if not value:
        return False

    value = str(value)
    answer = answer or ""

    # phone-like values: formatting differences are ignored.
    vd = re.sub(r"\D", "", value)
    if len(vd) >= 8:
        answer_digits = re.sub(r"\D", "", answer)
        if vd in answer_digits:
            return True

    # email: ignore whitespace/case only, preserving the address string itself.
    if "@" in value:
        return value.lower().replace(" ", "") in answer.lower().replace(" ", "")

    return compact(value) in compact(answer)


def tokens(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^0-9a-z가-힣]+", " ", s).split()


def answer_f1(answer, gold_text):
    """
    CoQA/SQuAD 계열에서 널리 쓰이는 token-overlap F1 형태.
    이 benchmark에는 자유서술형 정답 reference가 없으므로,
    target field value들을 requested_fields 순서대로 이어 붙인
    canonical gold text와 비교한다.
    """
    gold_tokens = tokens(gold_text)
    pred_tokens = tokens(answer)

    if not gold_tokens and not pred_tokens:
        return 1.0
    if not gold_tokens or not pred_tokens:
        return 0.0

    gold_counter = collections.Counter(gold_tokens)
    pred_counter = collections.Counter(pred_tokens)
    overlap = sum((gold_counter & pred_counter).values())

    if overlap == 0:
        return 0.0

    precision = overlap / sum(pred_counter.values())
    recall = overlap / sum(gold_counter.values())
    return 2 * precision * recall / (precision + recall)


def exact_match(answer, gold_text):
    return float(normalize_answer(answer) == normalize_answer(gold_text))


def percentile(xs, q):
    if not xs:
        return None
    ys = sorted(xs)
    return ys[min(len(ys) - 1, max(0, math.ceil(q * len(ys)) - 1))]


def gold_values_in_order(turn):
    raw = turn.get("gold_answer_values")

    if isinstance(raw, dict):
        requested = turn.get("requested_fields") or []
        if requested:
            values = [raw.get(field) for field in requested]
        else:
            values = list(raw.values())
    elif isinstance(raw, list):
        values = raw
    elif raw is None:
        values = []
    else:
        values = [raw]

    return [str(v).strip() for v in values if str(v or "").strip()]


def canonical_gold_text(turn):
    return " ".join(gold_values_in_order(turn))


def preflight(ds, cards):
    errors = []
    by_id = {c["id"]: c for c in cards}

    fp = canonical_fingerprint(cards)
    expected_fp = ds.get("reference_cards", {}).get("canonical_sha256")
    if fp != expected_fp:
        errors.append(
            f"cards_eval1000 fingerprint mismatch: dataset={expected_fp}, actual={fp}"
        )

    scenarios = ds.get("scenarios") or []
    if len(scenarios) != 50:
        errors.append(f"scenario count != 50: {len(scenarios)}")

    counts = collections.Counter(s.get("category") for s in scenarios)
    if counts != collections.Counter(EXPECTED_CATEGORIES):
        errors.append(f"category counts mismatch: {dict(counts)}")

    seen_ids = set()

    for s in scenarios:
        sid = s.get("id")
        if sid in seen_ids:
            errors.append(f"{sid}: duplicate scenario id")
        seen_ids.add(sid)

        target_id = s.get("target_card_id")
        target = by_id.get(target_id)
        if not target:
            errors.append(f"{sid}: target card missing: {target_id}")
            continue

        source_ids = s.get("source_card_ids") or []
        if target_id not in source_ids:
            errors.append(f"{sid}: target_card_id not included in source_card_ids")
        for cid in source_ids:
            if cid not in by_id:
                errors.append(f"{sid}: source card missing: {cid}")

        eval_turns = [t for t in (s.get("turns") or []) if t.get("evaluate")]
        if len(eval_turns) != 1:
            errors.append(f"{sid}: eval turn count != 1: {len(eval_turns)}")
            continue

        turn = eval_turns[0]
        is_unanswerable = s.get("category") == "unanswerable"

        if is_unanswerable:
            missing_field = s.get("missing_field")
            if not missing_field:
                errors.append(f"{sid}: unanswerable scenario missing missing_field")
            elif (target.get(missing_field) or "").strip():
                errors.append(
                    f"{sid}: field {missing_field} is not actually missing on target card"
                )

            if not (turn.get("expected_contains_any") or []):
                errors.append(f"{sid}: unanswerable eval turn has no expected_contains_any")
        else:
            gold_values = gold_values_in_order(turn)
            if not gold_values:
                errors.append(f"{sid}: answerable eval turn has no gold_answer_values")

            target_fields = s.get("target_fields") or []
            grounded_values = {
                str(target.get(field) or "").strip()
                for field in target_fields
                if str(target.get(field) or "").strip()
            }

            for value in gold_values:
                if value not in grounded_values:
                    errors.append(
                        f"{sid}: gold value not grounded in target fields: {value!r}"
                    )

            for value in turn.get("expected_contains") or []:
                if str(value).strip() not in grounded_values:
                    errors.append(
                        f"{sid}: expected_contains not grounded in target fields: {value!r}"
                    )

        if any(
            "기억해 주세요" in (t.get("user") or "")
            or "기억해줘" in (t.get("user") or "")
            for t in (s.get("turns") or [])
        ):
            errors.append(f"{sid}: unsupported third-party fact injection")

    if errors:
        print("[PREFLIGHT FAIL]")
        for e in errors:
            print(" -", e)
        raise SystemExit(2)

    print(
        f"[PREFLIGHT OK] cards={len(cards)}, scenarios=50, "
        f"categories=5x10, fingerprint={fp[:12]}..."
    )


def ask(endpoint, question, history, focus, prev_ids, memory):
    body = json.dumps(
        {
            "question": question,
            "history": history,
            "focus": focus,
            "prev_card_ids": prev_ids,
            "conversation_memory": memory,
            "dry_run": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))


def score(scenario, turn, answer):
    expected = turn.get("expected_contains") or []
    expected_any = turn.get("expected_contains_any") or []
    forbidden = turn.get("forbidden_contains") or []
    forbidden_patterns = turn.get("forbidden_patterns") or []

    required_values_ok = all(value_hit(answer, v) for v in expected)
    forbidden_values_ok = not any(value_hit(answer, v) for v in forbidden)

    for pattern in forbidden_patterns:
        if re.search(pattern, answer or "", re.I):
            forbidden_values_ok = False

    if scenario["category"] == "unanswerable":
        abstention_ok = any(value_hit(answer, v) for v in expected_any)

        return {
            "answer_f1": None,
            "exact_match": None,
            "unanswerable_accuracy": float(abstention_ok and forbidden_values_ok),
            # diagnostics only; not aggregated as headline metrics
            "required_values_ok": None,
            "forbidden_values_ok": forbidden_values_ok,
            "canonical_gold_text": "",
        }

    gold_text = canonical_gold_text(turn)

    return {
        "answer_f1": answer_f1(answer, gold_text),
        "exact_match": exact_match(answer, gold_text),
        "unanswerable_accuracy": None,
        # diagnostics only; not aggregated as headline metrics
        "required_values_ok": required_values_ok,
        "forbidden_values_ok": forbidden_values_ok,
        "canonical_gold_text": gold_text,
    }


def mean(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return sum(values) / len(values) if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--cards", default=str(DEFAULT_CARDS))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--ids",
        default="",
        help="쉼표로 scenario id 지정. 예: lr_01,sc_01,cu_01,er_01,ua_01",
    )
    parser.add_argument("--outdir", default="results_final50_v3")
    args = parser.parse_args()

    ds = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    cards = json.loads(Path(args.cards).read_text(encoding="utf-8"))
    preflight(ds, cards)

    scenarios = ds["scenarios"]

    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        scenarios = [s for s in scenarios if s["id"] in wanted]
    elif args.limit:
        scenarios = scenarios[: args.limit]

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    detail_path = out / "final50_v3_turn_results.jsonl"
    summary_path = out / "final50_v3_summary.json"

    scored = []
    latencies = []
    eval_latencies = []
    errors = 0
    empty = 0
    total = 0

    print(f"시나리오 {len(scenarios)}개 평가 시작")
    started = time.time()

    with open(detail_path, "w", encoding="utf-8", buffering=1) as detail_file:
        for scenario_index, scenario in enumerate(scenarios, start=1):
            history = []
            focus = None
            prev = []
            memory = None

            print(
                f"[{scenario_index}/{len(scenarios)}] "
                f"{scenario['id']} ({scenario['category']})"
            )

            for turn_index, turn in enumerate(scenario["turns"], start=1):
                total += 1
                turn_started = time.perf_counter()
                err = None

                try:
                    result = ask(
                        args.endpoint,
                        turn["user"],
                        history,
                        focus,
                        prev,
                        memory,
                    )
                except Exception as exc:
                    result = {}
                    err = f"{type(exc).__name__}: {exc}"
                    errors += 1

                latency_ms = (time.perf_counter() - turn_started) * 1000
                latencies.append(latency_ms)

                answer = result.get("answer") or ""
                if not answer.strip():
                    empty += 1

                record = {
                    "scenario_id": scenario["id"],
                    "category": scenario["category"],
                    "turn_index": turn_index,
                    "evaluate": bool(turn.get("evaluate")),
                    "question": turn["user"],
                    "answer": answer,
                    "route": result.get("route"),
                    "card_ids": result.get("card_ids") or [],
                    "latency_ms": round(latency_ms, 1),
                    "gen_ms": result.get("gen_ms"),
                    "error": err or result.get("error"),
                }

                if turn.get("evaluate"):
                    record.update(score(scenario, turn, answer))
                    scored.append(record.copy())
                    eval_latencies.append(latency_ms)

                detail_file.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )

                field_filters = result.get("field_filters") or {}
                terms = " ".join(
                    value
                    for key in ("name", "location", "title")
                    for value in (field_filters.get(key) or [])
                )

                history = history + [
                    {
                        "q": turn["user"],
                        "a": answer
                        or ", ".join(result.get("hybrid_top") or []),
                        "filter_terms": terms or None,
                    }
                ]

                focus = result.get("focus") or focus
                prev = result.get("card_ids") or prev
                memory = result.get("conversation_memory") or memory

    metrics = {
        "answer_f1": mean(scored, "answer_f1"),
        "exact_match": mean(scored, "exact_match"),
        "unanswerable_accuracy": mean(scored, "unanswerable_accuracy"),
    }

    by_category = {}
    for category in sorted({r["category"] for r in scored}):
        rows = [r for r in scored if r["category"] == category]
        by_category[category] = {
            "n": len(rows),
            "answer_f1": mean(rows, "answer_f1"),
            "exact_match": mean(rows, "exact_match"),
            "unanswerable_accuracy": mean(rows, "unanswerable_accuracy"),
        }

    answerable_n = sum(r.get("answer_f1") is not None for r in scored)
    unanswerable_n = sum(
        r.get("unanswerable_accuracy") is not None for r in scored
    )

    summary = {
        "dataset_version": ds["dataset_version"],
        "scenario_count": len(scenarios),
        "total_user_turns_executed": total,
        "evaluated_turns": len(scored),
        "answerable_evaluated_turns": answerable_n,
        "unanswerable_evaluated_turns": unanswerable_n,
        "metrics": metrics,
        "metric_notes": {
            "answer_f1": (
                "Token-overlap F1 on answerable evaluated turns only. "
                "Gold text is the requested target-card field values joined "
                "in requested_fields order."
            ),
            "exact_match": (
                "Normalized exact match on answerable evaluated turns only. "
                "Normalization uses NFKC, lowercase, and removes non "
                "Korean/Latin/digit characters."
            ),
            "unanswerable_accuracy": (
                "Accuracy on unanswerable evaluated turns only, using the "
                "dataset's expected abstention expressions and forbidden-value checks."
            ),
        },
        "by_category": by_category,
        "latency_seconds": {
            "mean": (
                sum(latencies) / len(latencies) / 1000
                if latencies
                else None
            ),
            "p95": (
                percentile(latencies, 0.95) / 1000
                if latencies
                else None
            ),
            "eval_mean": (
                sum(eval_latencies) / len(eval_latencies) / 1000
                if eval_latencies
                else None
            ),
            "eval_p95": (
                percentile(eval_latencies, 0.95) / 1000
                if eval_latencies
                else None
            ),
        },
        "error_rate": errors / total if total else 0,
        "empty_response_rate": empty / total if total else 0,
        "elapsed_seconds": round(time.time() - started, 1),
    }

    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n========== FINAL50 v3 SUMMARY ==========")
    print(
        f"시나리오: {len(scenarios)} / 실행 user turn: {total} / "
        f"채점 turn: {len(scored)}"
    )
    print(
        f"answerable: {answerable_n} / "
        f"unanswerable: {unanswerable_n}"
    )

    for key, value in metrics.items():
        if value is not None:
            print(f"{key}: {value:.3f}")

    if latencies:
        print(
            "latency mean/P95: "
            f"{summary['latency_seconds']['mean']:.1f}s / "
            f"{summary['latency_seconds']['p95']:.1f}s"
        )

    print(f"error rate: {summary['error_rate']:.3f}")
    print(f"empty response rate: {summary['empty_response_rate']:.3f}")
    print(f"실행 시간: {summary['elapsed_seconds']:.1f}s")
    print("상세:", detail_path)
    print("요약:", summary_path)


if __name__ == "__main__":
    main()
