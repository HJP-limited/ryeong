"""
동결된 벤치가 **스스로 세운 가드레일을 지키는지** 검사한다.

정답이 틀린 벤치는 없느니만 못하다 — 고칠 수 없는 실패를 계속 보고하거나,
반대로 틀린 답을 정답으로 인정한다. 실제로 외부 고정셋에서 결함 6개가 나왔고
전부 이 종류였다. 그래서 시험지를 찍은 뒤 **항상** 이 검사를 통과시킨다.

  python scripts/validate_bench.py bench/hjp_multiturn_v1.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import card_fingerprint as cfp  # noqa: E402

NAME_RE = re.compile(r"([가-힣]{2,4})씨")


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "bench" / "hjp_multiturn_v1.json")
    bench = json.loads(path.read_text(encoding="utf-8"))
    cards = json.loads((ROOT / "data" / "cards_eval1000.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cards}
    names = {c["name"] for c in cards}

    fails = []

    def bad(sid, why):
        fails.append(f"[{sid}] {why}")

    # 카드 지문 — 시험지를 찍을 때의 데이터와 지금 데이터가 같은가.
    fp = cfp.answer_fingerprint(cards)
    if fp != bench["cards"]["answer_fingerprint"]:
        bad("DATASET", f"카드 지문 불일치 — 동결 {bench['cards']['answer_fingerprint'][:12]}… "
                       f"/ 현재 {fp[:12]}…  (정답이 낡았을 수 있다)")

    for sc in bench["scenarios"]:
        sid = sc["id"]
        turns = sc["turns"]

        # 1. 채점 대상 턴은 정확히 하나
        targets = [t for t in turns if t.get("target")]
        if len(targets) != 1:
            bad(sid, f"채점 대상 턴이 {len(targets)}개 (1개여야 함)")
            continue
        tt = targets[0]
        if turns[-1] is not tt:
            bad(sid, "채점 대상 턴이 마지막이 아니다")

        # 2. 등장 인물이 전부 실재하는가 (제3자 사실 금지)
        for t in turns:
            for nm in NAME_RE.findall(t["user"]):
                if nm not in names:
                    bad(sid, f"카드에 없는 인물 등장: {nm}")

        card = by_id.get(sc["target_card_id"])
        if not card:
            bad(sid, f"대상 카드 없음: {sc['target_card_id']}")
            continue
        field = sc["field"]
        value = (card.get(field) or "").strip()

        # 3. 답 가능/불가능이 데이터와 맞는가
        if sc["answerable"] and not value:
            bad(sid, f"answerable 인데 {field} 가 비어 있다")
        if not sc["answerable"] and value:
            bad(sid, f"unanswerable 인데 {field} 에 값이 있다: {value!r}")

        # 4. 정답 문자열이 실제 값에서 나왔는가
        if sc["answerable"]:
            alts = (tt.get("must") or [[]])[0]
            if not alts:
                bad(sid, "정답 대안 목록이 비었다")
            elif not any(a and a in value or (a and value in a) for a in alts):
                bad(sid, f"must {alts} 가 실제 값 {value!r} 과 무관하다")
        else:
            # 없는 칸을 물었는데 **옆 칸 값**을 답하면 실패여야 한다
            if not tt.get("must_not"):
                bad(sid, "unanswerable 인데 옆 칸 값 금지 목록이 없다")

        # 5. 지시어의 뜻과 대상이 맞아야 한다
        #    · 대명사("그 사람") = **직전** 인물. v1 은 반대로 요구했고 기준선 6/6 실패가
        #      전부 그 설계 오류였다 — 모델이 맞고 시험지가 틀렸다.
        #    · 순서 지시("처음 언급한 사람") = **첫** 인물. 직전이면 최근 focus 로 풀려 무의미.
        if sc["reference"] in ("pronoun", "ordinal"):
            prior = [n for t in turns[:-1] for n in NAME_RE.findall(t["user"])]
            if not prior:
                bad(sid, f"{sc['reference']} 인데 앞 턴에 인물이 없다")
            elif sc["reference"] == "pronoun" and prior[-1] != card["name"]:
                bad(sid, f"대명사인데 대상({card['name']})이 직전 인물({prior[-1]})이 아니다 "
                         f"— '그 사람' 은 직전 인물을 뜻한다")
            elif sc["reference"] == "ordinal":
                if prior[0] != card["name"]:
                    bad(sid, f"'처음 언급한 사람' 인데 첫 인물은 {prior[0]}, 대상은 {card['name']}")
                if len(prior) >= 1 and prior[-1] == card["name"]:
                    bad(sid, f"순서 지시인데 대상이 **직전** 인물이다 — 최근 focus 로 풀려 무의미")

        # 6. 정정은 명시적 정정 표현을 포함해야 한다
        if sc["reference"] == "correction":
            if not any(w in tt["user"] for w in ("말고", "아니라", "아니")):
                bad(sid, f"correction 인데 정정 표현이 없다: {tt['user']!r}")
            if card["name"] not in tt["user"]:
                bad(sid, "correction 인데 정정 대상 이름이 질문에 없다")

        # 6b. 대상 이름은 카드 전체에서 고유해야 한다(동명이인은 문제가 모호하다)
        if sum(1 for c in cards if c["name"] == card["name"]) != 1:
            bad(sid, f"대상 {card['name']} 이 동명이인 — 어느 카드를 물었는지 정해지지 않는다")

        # 7. 대상이 방해 인물과 같은 이름이면 채점이 흐려진다
        others = [n for t in turns[:-1] for n in NAME_RE.findall(t["user"])]
        if sc["reference"] == "named" and others.count(card["name"]) > 0:
            bad(sid, f"named 인데 대상({card['name']})이 앞 턴에도 나온다 — 문맥 없이도 풀린다")

        # 8. 깊이·거리가 기록과 실제로 맞는가
        if sc["depth"] != len(turns):
            bad(sid, f"depth 기록 {sc['depth']} != 실제 턴 수 {len(turns)}")

    print(f"\n{path.name} — 시나리오 {len(bench['scenarios'])}개 검사")
    if fails:
        print(f"  실패 {len(fails)}건")
        for f in fails[:40]:
            print("   ", f)
        if len(fails) > 40:
            print(f"    … 외 {len(fails) - 40}건")
        sys.exit(1)
    print("  가드레일 8종 전부 통과")


if __name__ == "__main__":
    main()
