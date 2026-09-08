import ast
import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = "scripts/hybrid_server.py"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, n=1):
    global s
    assert s.count(old) == n, f"{s.count(old)}건(기대 {n}) -> {old[:70]!r}"
    s = s.replace(old, new)


# ── 1) 메모리에 '이 대화가 정한 사람' 칸을 만든다 ───────────────────────────
rep('''        "subject_history": [],
    }''',
'''        "subject_history": [],
        # 이름 -> 카드 id. **동명이인을 이 대화가 어느 쪽으로 정했는지** 기억한다.
        #
        # subject_history 는 이름만 담아서 "백다인이 나왔다" 까지만 안다. 그런데 카드에
        # 백다인은 두 장이다. 회사로 한 명을 특정한 뒤 몇 턴 지나서 이름만으로 다시
        # 부르면, focus 도 prev_card_ids 도 그새 방해 인물로 덮여서 어느 백다인인지
        # 알 길이 없다 — v1.3 실패 3건이 전부 이것이고, 되묻지도 않고 틀린 번호를 줬다.
        # 이름이 한 장으로 좁혀진 턴에서만 기록하므로, 애매한 채로 지나간 턴은 안 남는다.
        "subject_cards": {},
    }''')

# ── 2) 한 장으로 좁혀졌으면 기억한다 ────────────────────────────────────────
rep('''def finalize_turn(memory, turn_id, now_ms, question, answer, executed_tools, history):''',
'''def finalize_turn(memory, turn_id, now_ms, question, answer, executed_tools, history,
                  card_ids=None):''')

rep('''    if turn_names:
        memory = dict(memory)
        seen = list(memory.get("subject_history") or [])
        for n in turn_names:
            if n not in seen:
                seen.append(n)
        memory["subject_history"] = seen''',
'''    if turn_names:
        memory = dict(memory)
        seen = list(memory.get("subject_history") or [])
        for n in turn_names:
            if n not in seen:
                seen.append(n)
        memory["subject_history"] = seen

    # 이번 턴이 어떤 이름을 **한 장으로** 좁혔으면 그 짝을 기억한다. 회사로 특정한
    # 턴("샤인기계 백다인씨")이 여기 해당한다. 여러 장이 남았으면 기록하지 않는다 —
    # 애매한 채로 지나간 턴을 기억하면 나중에 그 애매함을 확신으로 둔갑시킨다.
    pinned = [cid for cid in (card_ids or []) if cid in CARDS_BY_ID]
    if turn_names and len(pinned) == 1:
        name = CARDS_BY_ID[pinned[0]]["name"]
        if name in turn_names:
            memory = dict(memory)
            memory["subject_cards"] = {**(memory.get("subject_cards") or {}),
                                       name: pinned[0]}''')

# 검색 경로의 호출부에 결과 카드를 넘긴다(다른 경로는 검색을 안 했으니 그대로 둔다).
rep('''    memory, recent = finalize_turn(memory, turn_id, now_ms, question, answer, ["search_business_cards"], history)''',
'''    memory, recent = finalize_turn(memory, turn_id, now_ms, question, answer,
                                   ["search_business_cards"], history, card_ids=top_ids)''')

# ── 3) 이름이 모호하면 이 대화가 정한 쪽을 고른다 ───────────────────────────
rep('''    top_ids = hy[:TOP_N]
    # faithfulness 채점용 — LLM 이 **실제로 본** 카드. narrow_by_answer 가 top_ids 를''',
'''    # **동명이인 되부르기.** 이름 조건이 하나인데 그 이름 카드가 여럿 남았고, 이 대화가
    # 앞에서 한 명으로 정해 둔 적이 있으면 그쪽만 남긴다. 사람은 한 번 정하면 다음부터
    # 이름만 댄다("샤인기계 백다인씨 직급" ... 세 턴 뒤 "백다인씨 전화번호는?").
    #
    # 규칙을 프롬프트에 적지 않고 여기서 결정적으로 거른다 — 프롬프트 규칙 추가는
    # 이 저장소에서 4전 4패고, 결정적 우회는 9전 9승이다.
    pinned = (memory.get("subject_cards") or {}).get(
        (field_filters.get("name") or [None])[0])
    if pinned and len(field_filters.get("name") or []) == 1:
        same_name = [cid for cid in hy
                     if CARDS_BY_ID[cid]["name"] == CARDS_BY_ID[pinned]["name"]]
        if len(same_name) > 1 and pinned in same_name:
            hy = [cid for cid in hy if cid == pinned or cid not in same_name]

    top_ids = hy[:TOP_N]
    # faithfulness 채점용 — LLM 이 **실제로 본** 카드. narrow_by_answer 가 top_ids 를''')

io.open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("동명이인 되부르기 OK")
