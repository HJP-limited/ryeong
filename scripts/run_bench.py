"""
동결된 통합 벤치를 채점한다.

`scripts/build_bench.py` 가 찍은 동결본(`bench/hjp_multiturn_v1.json`)만 읽는다 —
여기서 시나리오를 만들지 않는다. **시험지와 채점기를 분리**해야 시험지를 안 건드린
채로 채점 기준만 고칠 수 있고, 반대로 채점기를 안 건드린 채로 시험지를 갱신할 수 있다.

채점 규칙(외부 고정셋에서 계승):
  · 시나리오마다 **채점 대상 턴은 하나**다. 앞 턴들은 설정·방해이므로 주 지표에 안 넣는다.
    섞어서 평균 내면 쉬운 설정 턴이 분모를 채워 천장에 붙는다 — 옛 자체 시험지가
    라우팅 1.000 · JGA 1.000 에 붙어 있던 이유가 정확히 그것이었다.
  · 설정·방해 턴은 **진단용으로만** 따로 보고한다("방해 턴에서 이미 틀렸나").

  python scripts/run_bench.py                          # 공개셋만
  python scripts/run_bench.py --split holdout          # 홀드아웃(릴리스 직전에만)
  python scripts/run_bench.py --dump run.jsonl         # 턴별 기록
  python scripts/run_bench.py --rescore run.jsonl      # 생성 없이 재채점
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import card_fingerprint as cfp                      # noqa: E402
import eval_multiturn as ev                         # noqa: E402  (채점기를 재사용한다)

CARDS_PATH = ROOT / "data" / "cards_eval1000.json"
DEPTH_ORDER = ["A_1턴째", "B_2턴째", "C_3~5턴째", "D_6턴째+"]
LEVELS = ["L1", "L2", "L3", "L4"]


def pct(ok, n):
    return f"{ok / n:.3f}" if n else "  -  "


def power(n, need=20):
    """표본이 얇으면 항상 같이 찍는다 — 실제로 n=10 짜리 값 하나로 판단했다가 되돌린 적이 있다."""
    return f" [표본 {n} — 1건이 {100 / n:.0f}%p]" if n and n < need else ""


def verify(bench, cards):
    """동결본이 지금 데이터·생성기와 맞는지 먼저 본다. 안 맞으면 정답이 낡았을 수 있다."""
    fp = cfp.answer_fingerprint(cards)
    if fp != bench["cards"]["answer_fingerprint"]:
        print(f"  [경고] 카드 지문 불일치 — 동결 {bench['cards']['answer_fingerprint'][:12]}… "
              f"/ 현재 {fp[:12]}…")
        print("         정답이 낡았을 수 있다. build_bench.py 로 다시 찍고 버전을 올릴 것.")
    gen = ROOT / bench["generator"]["path"]
    if gen.exists():
        got = hashlib.sha256(gen.read_bytes()).hexdigest()
        if got != bench["generator"]["sha256"]:
            print(f"  [알림] 생성기가 동결 이후 바뀌었다 ({got[:12]}… != "
                  f"{bench['generator']['sha256'][:12]}…).")
            print("         **동결본은 그대로이므로 이 채점은 유효하다.** 다음 버전에 반영된다.")


def score_target(turn_spec, res, cards_ctx, value_index, contacts):
    """채점 대상 턴 하나를 본다. 세 층이 서로 다른 것을 잰다."""
    answer = res.get("answer") or ""
    out = {}
    ok, why = ev.check_answer(
        {"must": turn_spec.get("must") or [], "must_not": turn_spec.get("must_not") or []},
        answer)
    out["checklist"] = (1 if ok else 0, 1, "" if ok else why)

    gold = turn_spec.get("gold") or []
    top = (res.get("card_ids") or [])[:5]
    if gold:
        out["hit3"] = (1 if set(gold) & set(top[:3]) else 0, 1)
        out["hit5"] = (1 if set(gold) & set(top) else 0, 1)

    generated = res.get("route") in ev.GENERATING_ROUTES and not res.get("abstained")
    if generated and answer:
        ctx = res.get("context_cards") or res.get("cards") or []
        # 관련성은 **답이 있는 문제에서만** 정의된다. '없다' 가 정답인 턴에서는 답변에
        # 필드 값이 없는 게 맞는데, v1 기준선에서 그걸 0 으로 찍어 0.479 가 나왔다.
        # (그 턴이 맞았는지는 체크리스트가 본다.)
        if turn_spec.get("answerable", True):
            rel = ev.answer_relevancy(turn_spec["user"], answer, ctx, gold, value_index,
                                      None, turn_spec.get("must"))
            if rel is not None:
                out["rel"] = rel
        f_ok, f_n, f_bad = ev.faithfulness(answer, ctx, value_index)
        if f_n:
            out["faith"] = (f_ok, f_n, f_bad)
        if ev.unregistered_contacts(answer, contacts[0], contacts[1]):
            out["unreg"] = True
    return out


def run(bench, cards, split, dump_fh):
    value_index = ev.build_value_index(cards)
    contacts = ev.build_contact_index(cards)
    scenarios = [s for s in bench["scenarios"]
                 if split == "all" or s["split"] == split]

    cell = collections.defaultdict(lambda: {"chk_ok": 0, "chk_n": 0, "rel_ok": 0, "rel_n": 0,
                                            "faith_ok": 0, "faith_n": 0,
                                            "hit3": 0, "hit5": 0, "hit_n": 0, "unreg": 0})
    setup = {"route_ok": 0, "route_n": 0, "hit5": 0, "hit_n": 0}
    fails, gen_ms = [], []

    for idx, sc in enumerate(scenarios, 1):
        history, focus, prev_ids, memory = [], None, None, None
        for t in sc["turns"]:
            try:
                res = ev.ask(t["user"], history, focus, prev_ids, memory, False)
            except Exception as e:                       # noqa: BLE001
                fails.append((sc, t, f"요청 실패: {type(e).__name__}"))
                break
            if res.get("gen_ms"):
                gen_ms.append(res["gen_ms"])

            if t.get("target"):
                s = score_target({**t, "answerable": sc["answerable"]}, res, cards,
                                 value_index, contacts)
                c = cell[(sc["depth_tier"], sc["difficulty"])]
                c["chk_ok"] += s["checklist"][0]
                c["chk_n"] += 1
                if not s["checklist"][0]:
                    fails.append((sc, t, f"{s['checklist'][2]} / 답변={(res.get('answer') or '')[:60]!r}"))
                for key, dst in (("rel", "rel"), ("faith", "faith")):
                    if key in s:
                        c[dst + "_ok"] += s[key][0]
                        c[dst + "_n"] += s[key][1]
                if "hit5" in s:
                    c["hit3"] += s["hit3"][0]
                    c["hit5"] += s["hit5"][0]
                    c["hit_n"] += 1
                if s.get("unreg"):
                    c["unreg"] += 1
            else:
                # 설정·방해 턴 — 진단용. 주 지표 분모에 넣지 않는다.
                setup["route_n"] += 1
                if setup_route_ok(t.get("kind"), res.get("route")):
                    setup["route_ok"] += 1

            if dump_fh is not None:
                dump_fh.write(json.dumps({
                    "sid": sc["id"], "depth_tier": sc["depth_tier"],
                    "difficulty": sc["difficulty"], "split": sc["split"],
                    "reference": sc["reference"], "answerable": sc["answerable"],
                    "target": bool(t.get("target")), "kind": t.get("kind"),
                    "q": t["user"],
                    "must": t.get("must"), "must_not": t.get("must_not"),
                    "gold": t.get("gold"), "answer": res.get("answer"),
                    "route": res.get("route"), "abstained": bool(res.get("abstained")),
                    "card_ids": res.get("card_ids"), "gen_ms": res.get("gen_ms"),
                    "repaired": bool(res.get("repaired")),
                    "context_cards": res.get("context_cards"),
                }, ensure_ascii=False) + "\n")

            history = res.get("history") or history
            focus = res.get("focus")
            prev_ids = res.get("card_ids")
            memory = res.get("conversation_memory")

        if idx % 10 == 0:
            print(f"  … {idx}/{len(scenarios)} 시나리오", flush=True)

    return cell, setup, fails, gen_ms, scenarios


def report(cell, setup, fails, gen_ms, scenarios, split):
    n_turns = sum(len(s["turns"]) for s in scenarios)
    print(f"\n=== 통합 벤치 채점 ({split}) ===")
    if n_turns:
        print(f"시나리오 {len(scenarios)}개 / 턴 {n_turns}개 "
              f"— 채점 대상 {len(scenarios)}턴, 설정·방해 {n_turns - len(scenarios)}턴")
    else:
        # 재채점 경로 — 덤프에는 시나리오 정의가 없어 턴 수를 셀 수 없다.
        print(f"시나리오 {len(scenarios)}개 (덤프 재채점)")

    tot = collections.Counter()
    for c in cell.values():
        for k, v in c.items():
            tot[k] += v
    print(f"\n[전체 — 채점 대상 턴만]")
    print(f"  체크리스트   {pct(tot['chk_ok'], tot['chk_n'])}  ({tot['chk_ok']}/{tot['chk_n']})")
    print(f"  Relevancy    {pct(tot['rel_ok'], tot['rel_n'])}  ({tot['rel_ok']}/{tot['rel_n']} 요청 필드)")
    print(f"  Faithfulness {pct(tot['faith_ok'], tot['faith_n'])}  ({tot['faith_ok']}/{tot['faith_n']} 주장)")
    print(f"  Hit@3 / Hit@5 {pct(tot['hit3'], tot['hit_n'])} / {pct(tot['hit5'], tot['hit_n'])}"
          f"  ({tot['hit_n']}턴)")
    print(f"  미등록 연락처 없음 {pct(tot['chk_n'] - tot['unreg'], tot['chk_n'])}")

    print(f"\n[깊이 x 난이도 — 체크리스트]  * 빈 칸은 그 조합이 구조적으로 없다는 뜻")
    print(f"  {'':<12}" + "".join(f"{lv:>14}" for lv in LEVELS) + f"{'행 합계':>14}")
    for tier in DEPTH_ORDER:
        row, ok, n = "", 0, 0
        for lv in LEVELS:
            c = cell.get((tier, lv))
            if not c or not c["chk_n"]:
                row += f"{'-':>14}"
                continue
            ok += c["chk_ok"]
            n += c["chk_n"]
            cellv = pct(c["chk_ok"], c["chk_n"]) + " n=" + str(c["chk_n"])
            row += f"{cellv:>14}"
        rowv = pct(ok, n) + " n=" + str(n)
        print(f"  {tier:<12}{row}{rowv:>14}")

    print(f"\n[난이도별 — 열 합계]")
    for lv in LEVELS:
        ok = sum(c["chk_ok"] for (t, l), c in cell.items() if l == lv)
        n = sum(c["chk_n"] for (t, l), c in cell.items() if l == lv)
        if n:
            print(f"  {lv}  {pct(ok, n)}  ({ok}/{n}){power(n)}")

    print(f"\n[설정·방해 턴 — 진단용, 주 지표 아님]")
    print(f"  갈래에 맞는 경로로 갔나  {pct(setup['route_ok'], setup['route_n'])}  "
          f"({setup['route_ok']}/{setup['route_n']})")
    print("  * 방해 턴에서 이미 틀리면 채점 턴의 실패가 문맥 탓인지 검색 탓인지 못 가린다.")
    print("  * 갈래별 기대 경로: 조회·목록 -> 생성, 개수 -> 카운트, 잡담 -> 무엇이든.")

    if gen_ms:
        g = sorted(gen_ms)
        print(f"\n  [개발환경 전용 · 실기기 아님] 생성 시간 중앙/P95/최대  "
              f"{g[len(g) // 2] / 1000:.1f} / {g[int(len(g) * .95) - 1] / 1000:.1f} / "
              f"{g[-1] / 1000:.1f}초")

    print(f"\n[실패 {len(fails)}건]")
    for sc, t, why in fails[:30]:
        print(f"  [{sc['id']}] {sc['depth_tier']}/{sc['difficulty']} "
              f"참조={sc['reference']} 답가능={sc['answerable']}")
        print(f"      Q {t['user']}")
        print(f"      {why}")
    if len(fails) > 30:
        print(f"  … 외 {len(fails) - 30}건")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=str(ROOT / "bench" / "hjp_multiturn_v1.json"))
    ap.add_argument("--split", default="public", choices=["public", "holdout", "all"],
                    help="홀드아웃은 릴리스 직전에만 돌린다 — 자주 보면 거기에도 맞추게 된다")
    ap.add_argument("--dump", default=None)
    ap.add_argument("--rescore", default=None, help="덤프만 읽어 다시 채점한다(생성 불필요)")
    args = ap.parse_args()

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    bench = json.loads(Path(args.bench).read_text(encoding="utf-8"))
    print(f"{bench['dataset_version']}  (동결 {bench.get('built_at') or '시각 없음'}, "
          f"시드 {bench['seed']})")
    verify(bench, cards)

    if args.rescore:
        rescore(args.rescore, cards)
        return 0

    dump_fh = open(args.dump, "w", encoding="utf-8", buffering=1) if args.dump else None
    t0 = time.time()
    try:
        cell, setup, fails, gen_ms, scenarios = run(bench, cards, args.split, dump_fh)
    finally:
        if dump_fh:
            dump_fh.close()
    report(cell, setup, fails, gen_ms, scenarios, args.split)
    print(f"\n실행 시간 {time.time() - t0:.0f}초")
    return 0


def rescore(path, cards):
    """생성(1시간)과 채점(초)을 분리한다 — 채점 기준을 고쳐도 답변을 다시 만들지 않는다."""
    value_index = ev.build_value_index(cards)
    contacts = ev.build_contact_index(cards)
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    cell = collections.defaultdict(lambda: {"chk_ok": 0, "chk_n": 0, "rel_ok": 0, "rel_n": 0,
                                            "faith_ok": 0, "faith_n": 0,
                                            "hit3": 0, "hit5": 0, "hit_n": 0, "unreg": 0})
    setup = {"route_ok": 0, "route_n": 0, "hit5": 0, "hit_n": 0}
    fails, gen_ms, sids = [], [], set()
    for r in rows:
        sids.add(r["sid"])
        if r.get("gen_ms"):
            gen_ms.append(r["gen_ms"])
        if not r["target"]:
            setup["route_n"] += 1
            if setup_route_ok(r.get("kind"), r.get("route")):
                setup["route_ok"] += 1
            continue
        res = {"answer": r.get("answer"), "route": r.get("route"),
               "abstained": r.get("abstained"), "card_ids": r.get("card_ids"),
               "context_cards": r.get("context_cards")}
        spec = {"user": r["q"], "must": r.get("must"), "must_not": r.get("must_not"),
                "gold": r.get("gold"), "answerable": r.get("answerable", True)}
        s = score_target(spec, res, cards, value_index, contacts)
        c = cell[(r["depth_tier"], r["difficulty"])]
        c["chk_ok"] += s["checklist"][0]
        c["chk_n"] += 1
        if not s["checklist"][0]:
            fake = {"id": r["sid"], "depth_tier": r["depth_tier"], "difficulty": r["difficulty"],
                    "reference": r["reference"], "answerable": r["answerable"]}
            fails.append((fake, spec, f"{s['checklist'][2]} / 답변={(r.get('answer') or '')[:60]!r}"))
        for key in ("rel", "faith"):
            if key in s:
                c[key + "_ok"] += s[key][0]
                c[key + "_n"] += s[key][1]
        if "hit5" in s:
            c["hit3"] += s["hit3"][0]
            c["hit5"] += s["hit5"][0]
            c["hit_n"] += 1
        if s.get("unreg"):
            c["unreg"] += 1
    scenarios = [{"id": s, "turns": []} for s in sids]
    print(f"\n재채점 — {path} (생성 없음)")
    report(cell, setup, fails, gen_ms, scenarios, "dump")


if __name__ == "__main__":
    raise SystemExit(main())
