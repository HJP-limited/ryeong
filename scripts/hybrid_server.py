# 로컬 완전 하이브리드 채팅 백엔드.
# 앱과 동일한 파이프라인을 노트북에서 재현한다:
#   질문 → 대명사 치환 → [키워드(KeywordSearchRanker 포팅) + 시맨틱(EmbeddingGemma)] → RRF → Gemma(serve) 답변
# eval_search.py의 키워드/벡터/RRF 로직을 그대로 재사용한다(드리프트 방지).
#   실행: (먼저 litert-lm serve 가 9379에 떠 있어야 함) python scripts/hybrid_server.py
import json
import os
import re
import sqlite3
import struct
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_search as ev  # 키워드 랭킹/벡터/RRF 재사용

import numpy as np

GEMMA_URL = "http://127.0.0.1:9379/v1/chat/completions"
GEMMA_MODEL = "gemma4e2b"
TOP_N = 5           # Gemma에 넣을 카드 수(앱 ragContext(3)보다 여유 있게 5)
PORT = 8100
ALLOWED_ORIGINS = {"http://127.0.0.1:8000", "http://localhost:8000"}

RAG_FIELDS = ["name", "company", "title", "department", "industry", "location", "phone", "email", "address", "memo", "tags"]

# 앱 MainActivity.kt 의 대명사/생략형 후속 처리 포팅
PRONOUNS = ["그 사람의", "그 사람", "그사람", "그 분", "그분", "이 사람", "이사람", "저 사람", "저사람",
            "걔", "그 회사", "그회사", "방금 그", "그 명함", "이 분", "이분"]
ATTRIBUTE_NOUNS = ["전화번호", "전화", "번호", "연락처", "핸드폰", "휴대폰", "메일", "이메일",
                   "직급", "직함", "직책", "회사", "소속", "주소", "위치", "지역", "부서", "이름"]


# 대화형 후속 발화 — 새 검색이 아니라 '직전 답변에 대한 반응'인 경우.
#
# 왜 필요한가(실측): "판교에서 일하는 사람 몇명이지" 다음에 "5명인데?" 라고 정정하면,
# 그게 새 검색어로 취급돼 검색이 엉뚱한 카드(충청북도 민대현 등)를 물어오고 그걸 근거로
# 답을 만들어 대화가 끊겼다. 이런 발화는 검색할 내용이 없으므로 직전 결과를 그대로 재사용해야 한다.
#
# 개념형 질의("돈 관리하는 사람")를 잘못 삼키지 않도록, '내용어가 없다'는 식의 느슨한 판정이
# 아니라 정정/확인/메타 발화의 명시적 패턴만 본다.
FOLLOWUP_META_PATTERNS = (
    "인데", "아닌데", "아니야", "아니고", "아냐", "맞아", "맞나", "맞지", "틀렸", "잘못",
    "다시", "왜", "진짜", "정말", "확실", "그래서", "응", "네", "아니",
)
COUNT_UNITS = ("명", "개", "건", "곳", "군데")

# LLM 이 "후보 전원이 조건에 안 맞는다"고 선언할 때 쓰는 고정 문구.
# 가제티어 기권(없는 이름/지역)은 검색 단계에서 잡지만, "우주비행사"처럼 '존재하지 않는
# 직업'은 어휘 목록으로 판정할 수 없다(직함 가제티어로 막으면 "돈 관리하는 사람" 같은
# 개념형 질의까지 죽는다는 걸 오프라인 측정으로 확인). 이건 의미 판단이라 LLM 몫이다.
NO_MATCH_PHRASE = "조건에 해당하는 명함을 찾지 못했습니다."

# 위 고정 문구 외에, LLM이 다른 말투로 "못 찾았다"고 답하는 경우도 거절로 인정한다.
# 실측: "김철수 전화번호 알려줘"에 "김철수 전화번호는 찾지 못했습니다."라고 답했는데
# 이 문자열은 NO_MATCH_PHRASE 와 정확히 안 겹쳐서 llm_rejected 판정을 못 받았고,
# 그 결과 "못 찾았다"는 답변 밑에 관계없는 카드 5장이 그대로 남아있었다.
# "없습니다"는 넣지 않는다 — "안정우는 나이가 없습니다"처럼 '그 사람은 있는데 그
# 필드가 없다'는 정상 답변까지 거절로 오인해서 존재하는 카드를 지워버리기 때문이다.
# "찾지 못했"/"찾을 수 없"은 '검색 자체가 실패했다'는 뜻이라 그 위험이 없다.
REJECTION_MARKERS = (NO_MATCH_PHRASE, "찾지 못했", "찾을 수 없", "찾지못했", "찾을수없")

# 프롬프트 규칙(build_prompt)이 요구하는 집계형 답변 형식("맨 위 '총 N명'을 그대로 쓰고")과
# 정확히 맞춘 패턴. 답변에 후보 이름도 없고 이 패턴도 없으면 명함과 무관한 답변이라는 뜻이다
# (실측: "오늘 날씨 어때?" -> "날씨 정보는 명함 컨텍스트에 포함되어 있지 않습니다." 인데
# top-5 후보가 그대로 카드로 남음. "홍길동 명함 삭제해 줘"(존재 안 하는 이름) -> 의도 확인
# 답변인데 엉뚱한 홍씨 5명이 카드로 남음).
AGGREGATE_COUNT_RE = re.compile(r"총\s*(\d+)\s*명")


def card_referenced_in(card, answer: str) -> bool:
    """
    답변이 이 카드를 근거로 삼았는가.

    이름만 보면 안 된다(실측 회귀): "문선영씨 회사가 어디야?" -> "주식회사 노블어패럴입니다."
    처럼 필드 값으로만 답하는 게 정상인 질문이 많은데, 이름이 없다는 이유로 카드를
    통째로 지워버렸다. 회사/주소/이메일/전화 같은 '그 카드에서 온 값'도 근거로 인정한다.
    직함은 쓰지 않는다 — 여러 사람이 공유해서 변별력이 없다.
    """
    if not answer:
        return False
    name = (card.get("name") or "").strip()
    if name and name in answer:
        return True
    for field in ("company", "address", "email"):
        v = (card.get(field) or "").strip()
        # 라벨 접두어("A.  ", "E.  ")를 떼고 비교한다.
        v = v.split("  ")[-1].strip()
        if len(v) < 4:
            continue
        if v in answer:
            return True
        # LLM 이 값의 일부만 말하는 경우도 인정한다 — 주소가 대표적이다.
        # 실측: 카드가 "강원도 당진시 반포대2로 67 (승현이김리)" 인데 답변은 괄호를 뺀
        # "강원도 당진시 반포대2로 67" 이라 v in answer 가 False 였고 카드가 지워졌다.
        head = v.split(" (")[0].strip()
        if len(head) >= 6 and head in answer:
            return True
    digits = "".join(ch for ch in (card.get("phone") or "") if ch.isdigit())
    ans_digits = "".join(ch for ch in answer if ch.isdigit())
    if len(digits) >= 4 and len(ans_digits) >= 4 and digits[-4:] in ans_digits:
        return True
    return False

# 명함 검색과 무관한 자기참조 질문("너는 누구야?") — 결정적으로 우회한다.
# 프롬프트 규칙에만 맡기면 "너"를 명함 속 인물로 오인해서 관계없는 사람 이름을
# 그대로 답하는 걸 실측으로 확인했다(예: "너는 누구야?" -> "유유진").
SELF_REFERENCE_PATTERNS = (
    "너는 누구", "너 누구", "너는 뭐", "너 뭐야", "너 뭐하는", "너 몇 살", "너는 몇 살",
    "너는 ai", "너 ai", "너는 사람이야", "너는 로봇", "당신은 누구", "니 정체", "네 정체",
)
SELF_REFERENCE_ANSWER = "저는 명함 검색을 도와드리는 온디바이스 AI 어시스턴트입니다."

# "너 뭐 할 줄 알아?" 같은 기능 질문 — 자기참조와 같은 이유로 결정적으로 우회한다.
# 실측(전량 채점): 검색에 태우면 컨텍스트 1등을 답으로 뱉었다("너 뭐 할 줄 알아?" -> "이현",
# 카드 1장). '무관 요청 카드 억제' 실패 1건이 이 계열이었다.
# 자기참조보다 **먼저** 판정해야 한다 — "너는 뭐 할 줄 알아?" 는 "너는 뭐" 에도 걸린다.
CAPABILITY_PATTERNS = (
    "뭐 할 줄", "뭘 할 줄", "무엇을 할 줄", "뭐할 줄", "뭘할 줄",
    "뭐 할 수", "뭘 할 수", "무엇을 할 수", "할 수 있는 게", "할 수 있는게",
    "어떤 기능", "기능이 뭐", "기능 뭐", "뭐 도와", "뭘 도와", "어떻게 쓰는",
)
# Kotlin 은 이 목록을 ToolRegistry.capabilityLabels() 로 도구에서 파생한다.
# 여기(거울)에는 레지스트리가 없어 같은 문장을 적어 둔다. 도구를 추가하면 양쪽을 같이 고칠 것.
CAPABILITY_TOOL_LABELS = (
    "기기의 캘린더 앱에 일정 등록 화면을 엽니다.",
    "메일 또는 문자(SMS) 작성 화면을 초안이 채워진 상태로 엽니다.",
)
CAPABILITY_ANSWER = (
    "저는 명함 검색을 도와드리는 온디바이스 AI 어시스턴트입니다. 이런 걸 할 수 있어요:\n"
    + "\n".join(["- 이름·회사·지역·직함으로 명함을 찾습니다."]
                + ["- " + t for t in CAPABILITY_TOOL_LABELS])
)

# "전체 몇 장/명" 같이 조건 없이 전체를 묻는 질문 — 결정적으로 우회한다.
# 검색은 항상 top-N(5명)까지만 후보를 채우므로, 이런 질문을 그냥 검색에 태우면
# "총 5명"이라고 답해버린다(실측: 60장인데 5명이라고 답함) — top-5를 전체로 착각하게
# 만드는 잘못된 답이라 아예 검색 전에 걸러서 진짜 전체 개수로 답한다.
# 긴 것부터 순서대로 치환해야 짧은 조각("명")이 긴 단어("명함") 안쪽을 망가뜨리지 않는다.
GENERIC_LIST_STRIP_WORDS = (
    # 긴 것부터 — "내가 가진"이 "내"보다 먼저 걷혀야 한다.
    "가지고 있어", "가지고 있는", "가지고있는", "내가 가진", "가진", "가지고",
    "저장된", "등록된", "있는", "있어", "있나", "있지",
    "보여줘", "알려줘", "찾아줘", "리스트", "목록", "전체", "명함", "이름",
    "카드", "사람", "모두", "전부", "얼마나", "몇", "장수", "개수", "장", "명", "총", "개",
    "내", "제", "다", "이", "야", "어", "지", "나",
    "은", "는", "이야", "인가", "될까",
    "?", "!", ".", ",", " ",
)

# 복수 지시어 — "그 사람들 이름 알려줘" 처럼 '직전 결과 집합 전체'를 가리키는 발화.
# focus(단일 인물) 치환으로는 못 잡는다. 지시어가 명시적으로 앞을 가리키므로
# 새로 검색하지 않고 직전 카드 집합을 그대로 근거로 쓰는 게 정의상 맞다.
GROUP_REFERENCES = (
    "그 사람들", "그사람들", "그분들", "그 분들", "이 사람들", "이사람들",
    "저 사람들", "그들", "걔네", "그 명단", "그 목록", "위 사람들", "방금 그",
)


# ---------------------------------------------------------------------------
# 구조화 멀티턴 메모리 — HJP-limited/sojung 저장소의 agent/structured-multiturn-memory
# 브랜치(agent-core/AgentSession.kt, agent-contract/AgentModel.kt)를 그대로 포팅했다.
# app/src/main/java/com/example/hjp/agent/{ConversationMemory,ConversationMemoryReducer,
# AgentSession}.kt 에 이식한 것과 같은 로직이다 — 이 서버는 노트북에서 그 로직이 실제
# 대화에서 어떻게 동작하는지 눈으로 확인하기 위한 확인용이고(진짜는 Kotlin 앱), 그래서
# 마커 단어·상수·병합 알고리즘까지 정확히 맞춘다. 드리프트가 생기면 이 서버로 확인한 게
# 앱 실제 동작과 달라진다.
#
# 서버가 요청마다 무상태(stateless)라서, session 객체를 들고 있는 대신 memory 딕셔너리를
# history/prev_card_ids 처럼 클라이언트가 매 요청에 실어 보내고 갱신된 걸 돌려받는다.
# ---------------------------------------------------------------------------
MEMORY_MAX_TOPIC_CHARS = 240
MEMORY_MAX_ITEM_CHARS = 300
MEMORY_MAX_ITEMS_PER_BUCKET = 8
MEMORY_MAX_HISTORY_DIGEST_CHARS = 1500
MEMORY_MAX_DIGEST_MESSAGE_CHARS = 500
MAX_RECENT_TURNS = 4  # 8개 메시지 = 4턴(질문+답변)

PREFERENCE_MARKERS = ("선호", "좋아", "싫어", "말투", "스타일", "앞으로")
CONSTRAINT_MARKERS = ("하지 마", "하지마", "말아", "반드시", "꼭", "전에 확인", "동의 없이")
EXPLICIT_FACT_MARKERS = ("나는 ", "내 이름", "내 회사", "내 직책", "기억해", "라고 불러")


def default_conversation_memory() -> dict:
    return {
        "schema_version": 1,
        "topic": "",
        "confirmed_facts": [],
        "preferences": [],
        "constraints": [],
        "pending_actions": [],
        "resolved_actions": [],
        "history_digest": "",
    }


def _normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _memory_item(content, turn_id, timestamp_ms, confidence="EXPLICIT", key=""):
    return {
        "content": content[:MEMORY_MAX_ITEM_CHARS],
        "source_turn_id": turn_id,
        "updated_at_epoch_millis": timestamp_ms,
        "confidence": confidence,
        # 같은 종류를 가리키는 식별자("user.company"). 정정을 처리하려고 있다 —
        # "내 회사는 A야" 뒤 "내 회사는 B야"는 content 가 달라 둘 다 남는다.
        "key": key,
    }


# 작업성 발화인지 — 잡담이 작업 메모리를 오염시키지 않게 한다.
ACTION_MARKERS = (
    "찾아", "검색", "조회", "보여", "알려", "작성", "보내", "전송", "수정", "등록",
    "일정", "명함", "연락처", "메일", "이메일", "문자", "sms", "캘린더",
)
MAX_PENDING_AGE_MILLIS = 30 * 60 * 1_000

FACT_PATTERNS = (
    ("user.name", re.compile(r"내 이름은\s*(.+?)(?:이야|야|입니다|이라고|라고|\.)?$")),
    ("user.company", re.compile(r"내 회사는\s*(.+?)(?:이야|야|입니다|라고|\.)?$")),
    ("user.title", re.compile(r"내 직책은\s*(.+?)(?:이야|야|입니다|라고|\.)?$")),
)


def _is_action_like(text: str) -> bool:
    return any(m in text for m in ACTION_MARKERS)


def _extract_preferences(text, turn_id, ts):
    out = []
    if "정중" in text or "존댓말" in text:
        out.append(_memory_item("정중한 말투", turn_id, ts, key="response.tone"))
    if "짧게" in text or "간단하게" in text or "간단히" in text:
        out.append(_memory_item("짧고 간결한 답변", turn_id, ts, key="response.length"))
    if "반말" in text:
        out.append(_memory_item("반말", turn_id, ts, key="response.tone"))
    return out


def _extract_constraints(text, turn_id, ts):
    if any(m in text for m in CONSTRAINT_MARKERS):
        return [_memory_item(text[:MEMORY_MAX_ITEM_CHARS], turn_id, ts, key="action.confirmation")]
    return []


def _extract_facts(text, turn_id, ts):
    out = []
    for key, pattern in FACT_PATTERNS:
        m = pattern.search(text)
        if m:
            value = (m.group(1) or "").strip()
            if value:
                out.append(_memory_item(value, turn_id, ts, key=key))
    return out


def _merge(items, new_items):
    for it in new_items:
        items = _upsert(items, it)
    return items


def _dedup_tail(items):
    """Kotlin distinctBy{content}.takeLast(N) 과 동일: 앞에서부터 첫 등장만 남기고, 뒤에서 N개."""
    seen = set()
    deduped = []
    for it in items:
        if it["content"] in seen:
            continue
        seen.add(it["content"])
        deduped.append(it)
    return deduped[-MEMORY_MAX_ITEMS_PER_BUCKET:]


def _upsert(items, item):
    """같은 key(없으면 같은 content)면 덮어쓴다 — 이게 '정정'을 만든다."""
    key = item.get("key") or ""
    filtered = [
        it for it in items
        if not ((key and it.get("key") == key) or it["content"] == item["content"])
    ]
    return _dedup_tail(filtered + [item])


def memory_begin_turn(memory: dict, turn_id: str, timestamp_ms: int, user_text: str) -> dict:
    """
    턴이 시작될 때 호출한다. 발화를 pending_actions 에 걸어둬서, 이 턴이 끝까지 완료되지
    못해도(생성 실패 등) 다음 턴까지 "아직 처리 못한 요청"으로 남게 한다.
    """
    normalized = _normalize_memory_text(user_text)
    if not normalized or not _is_action_like(normalized):
        return memory
    pending = _memory_item(normalized, turn_id, timestamp_ms, key=f"action:{turn_id}")
    active = [
        p for p in memory.get("pending_actions", [])
        if timestamp_ms - p.get("updated_at_epoch_millis", 0) <= MAX_PENDING_AGE_MILLIS
    ]
    new_memory = dict(memory)
    new_memory["topic"] = normalized[:MEMORY_MAX_TOPIC_CHARS]
    new_memory["pending_actions"] = _upsert(active, pending)
    return new_memory


def memory_reduce_completed_turn(memory: dict, turn_id: str, timestamp_ms: int, user_text: str, executed_tools) -> dict:
    """턴이 정상 완료됐을 때 호출한다. 마커로 선호/제약/사실을 분류하고 pending 을 resolved 로 옮긴다."""
    normalized = _normalize_memory_text(user_text)
    if not normalized:
        return memory
    preferences = _merge(list(memory.get("preferences", [])),
                         _extract_preferences(normalized, turn_id, timestamp_ms))
    constraints = _merge(list(memory.get("constraints", [])),
                         _extract_constraints(normalized, turn_id, timestamp_ms))
    facts = _merge(list(memory.get("confirmed_facts", [])),
                   _extract_facts(normalized, turn_id, timestamp_ms))

    pending = list(memory.get("pending_actions", []))
    # 이 턴에 걸어둔 pending 이 있으면 완료 처리하고, 없으면 작업성 발화일 때만 새로 만든다.
    completed = next((p for p in pending if p.get("source_turn_id") == turn_id), None)
    if completed is None and _is_action_like(normalized):
        completed = _memory_item(normalized, turn_id, timestamp_ms, key=f"action:{turn_id}")
    resolved = list(memory.get("resolved_actions", []))
    if completed is not None:
        resolved = _upsert(resolved, {**completed, "updated_at_epoch_millis": timestamp_ms})
    tool_items = [
        _memory_item(f"도구 실행 완료: {tool}", turn_id, timestamp_ms, "TOOL_VERIFIED")
        for tool in dict.fromkeys(executed_tools or [])  # distinct, 순서 보존
    ]

    new_memory = dict(memory)
    new_memory.update({
        "topic": normalized[:MEMORY_MAX_TOPIC_CHARS] if _is_action_like(normalized)
        else memory.get("topic", ""),
        "confirmed_facts": facts,
        "preferences": preferences,
        "constraints": constraints,
        "pending_actions": [p for p in pending if p.get("source_turn_id") != turn_id],
        "resolved_actions": _dedup_tail(resolved + tool_items),
    })
    return new_memory


def merge_history_digest(previous: str, evicted_pairs, max_chars: int) -> str:
    """
    윈도우에서 밀려난 (질문,답변) 턴들을 한 줄씩(최대 500자)으로 줄여 이어붙인다. 예산을
    넘으면 뒤(최신)를 남기고 앞(오래된 것)부터 버리되, 줄 경계에 맞춰 자른다 — 그냥
    끝에서부터 자르면 문장 중간이 잘려 시작 줄이 의미 없는 조각이 된다.
    """
    if max_chars <= 0 or not evicted_pairs:
        return ""
    lines = []
    for pair in evicted_pairs:
        q = _normalize_memory_text(pair.get("q", ""))[:MEMORY_MAX_DIGEST_MESSAGE_CHARS]
        a = _normalize_memory_text(pair.get("a", ""))[:MEMORY_MAX_DIGEST_MESSAGE_CHARS]
        if q:
            lines.append(f"사용자: {q}")
        if a:
            lines.append(f"어시스턴트: {a}")
    addition = "\n".join(lines)
    merged = "\n".join(x for x in (previous, addition) if x.strip())
    if len(merged) <= max_chars:
        return merged
    tail = merged[-max_chars:]
    return tail.split("\n", 1)[1] if "\n" in tail else tail


def memory_model_view(memory: dict) -> dict:
    """
    모델에 보여줄 뷰. 작업 생명주기 기록(pending/resolved)은 **내부 장부**라 뺀다.

    실측 배경: begin_turn 이 답변 생성 전에 이번 질문을 pending 에 걸어두는데, 그 memory 를
    같은 턴 프롬프트에 그대로 넣으면 사용자 발화 블록과 똑같은 텍스트가 두 번 나와서
    2B 모델이 새로 답하지 않고 그 텍스트를 그대로 에코했다("메일은?" -> "메일은?").
    예전에는 '이번 턴 것만' 걸렀는데, sojung 최신본을 따라 두 버킷을 통째로 뺀다 —
    모델이 답을 만드는 데 쓰는 정보가 아니라 런타임이 미완료 요청을 추적하려는 값이다.
    저장(memory 자체)은 그대로 둔다.
    """
    view = dict(memory)
    view["pending_actions"] = []
    view["resolved_actions"] = []
    return view


def format_conversation_memory(memory: dict, current_turn_id: str = None) -> str:
    memory = memory_model_view(memory)
    if memory == default_conversation_memory():
        return ""
    lines = ["[conversation_memory]", f"schema_version: {memory.get('schema_version', 1)}"]
    if memory.get("topic"):
        lines.append(f"topic: {memory['topic']}")

    def items_block(label, items):
        if not items:
            return []
        return [f"{label}:"] + [f"- {it['content']}" for it in items]

    lines += items_block("confirmed_facts", memory.get("confirmed_facts", []))
    lines += items_block("preferences", memory.get("preferences", []))
    lines += items_block("constraints", memory.get("constraints", []))
    if memory.get("history_digest"):
        lines.append("history_digest:")
        lines.append(memory["history_digest"])
    return "\n".join(lines) + "\n"


def format_recent_conversation(recent_pairs) -> str:
    if not recent_pairs:
        return ""
    lines = ["[recent_conversation]"]
    for pair in recent_pairs:
        q = (pair.get("q") or "").replace("\n", " ")[:1000]
        a = (pair.get("a") or "").replace("\n", " ")[:1000]
        if q:
            lines.append(f"사용자: {q}")
        if a:
            lines.append(f"어시스턴트: {a}")
    return "\n".join(lines) + "\n\n"


def finalize_turn(memory, turn_id, now_ms, question, answer, executed_tools, history):
    """
    턴을 마무리한다. Kotlin AgentSession.recordTurn 과 동일하게, 질문이나 답변이 비어
    있으면(생성 실패 등) 아무것도 갱신하지 않는다 — begin_turn 이 걸어둔 pending 항목이
    그대로 남아 다음 턴까지 "아직 처리 못한 요청"으로 이어진다.
    """
    if not question.strip() or not answer.strip():
        recent = history[-MAX_RECENT_TURNS:] if history else []
        return memory, recent
    memory = memory_reduce_completed_turn(memory, turn_id, now_ms, question, executed_tools)
    full_history = history + [{"q": question, "a": answer}]
    if len(full_history) > MAX_RECENT_TURNS:
        evicted = full_history[:-MAX_RECENT_TURNS]
        recent = full_history[-MAX_RECENT_TURNS:]
        memory = dict(memory)
        memory["history_digest"] = merge_history_digest(
            memory.get("history_digest", ""), evicted, MEMORY_MAX_HISTORY_DIGEST_CHARS,
        )
    else:
        recent = full_history
    return memory, recent


ORDINAL_WORDS = [("첫", 0), ("두", 1), ("세", 2), ("네", 3), ("다섯", 4),
                 ("여섯", 5), ("일곱", 6), ("여덟", 7), ("아홉", 8), ("열", 9)]


def ordinal_index(question: str):
    """
    "두 번째 사람", "3번째", "마지막" — 직전 결과 **집합 안에서** 하나를 고르는 표현.
    0부터 세는 인덱스, "마지막"은 -1. Kotlin ConversationalFollowup.ordinalIndex 와 동일.
    이게 없으면 새 검색으로 빠져 무관한 사람이 나왔다(실측).
    """
    q = question or ""
    if "마지막" in q:
        return -1
    m = re.search(r"(\d+)\s*번째", q)
    if m:
        n = int(m.group(1))
        if n >= 1:
            return n - 1
    for word, idx in ORDINAL_WORDS:
        if re.search(word + r"\s*번째", q):
            return idx
    return None


def is_conversational_followup(question: str) -> bool:
    """
    직전 답변에 대한 정정·확인·되묻기인지 판정한다. True면 새로 검색하지 않고
    직전 턴의 카드를 그대로 근거로 써서 답한다.
    보수적으로 판정한다(짧은 발화 + 메타 패턴). 애매하면 False -> 평소처럼 검색.
    """
    q = (question or "").strip().rstrip("?!.")
    if not q:
        return False
    # 복수 지시어는 길이와 무관하게 직전 집합을 가리킨다 ("그 사람들 이름이랑 회사 알려줘")
    if any(g in q for g in GROUP_REFERENCES):
        return True
    tokens = q.split()
    if len(tokens) > 4:  # 문장이 길면 새 질문일 가능성이 크다
        return False
    has_meta = any(p in q for p in FOLLOWUP_META_PATTERNS)
    # "5명", "3개" 처럼 수량만 말한 정정도 대화형으로 본다
    is_count_only = any(
        u in q for u in COUNT_UNITS
    ) and any(ch.isdigit() for ch in q) and len(tokens) <= 2
    return has_meta or is_count_only


# sojung `feature/runtime-multiturn-summary` 의 AgentKernel.contextAnswerForSearch 이식.
# 원본은 모델이 search_contacts 를 호출하려 할 때 가로채는데, 이 서버는 도구 호출 루프가
# 아니라 검색을 직접 부르므로 검색 직전에 같은 판정을 한다.
# **되짚는 표현만** 넣는다. "그 사람"·"그 회사" 같은 대명사는 빼야 한다 —
# 그건 PRONOUNS(focus 치환)가 담당하는데, 여기 있으면 context_answer 가 먼저 채가서
# "그 사람 부서는?", "그 회사 주소는?" 처럼 **속성을 새로 묻는** 질문에도 직전 답변을
# 그대로 재생했다(실측). 대명사를 빼면 focus 로 치환돼 정상 검색으로 간다.
CONTEXT_REFERENCES = ("아까", "방금", "앞서", "이전", "말한", "찾은", "기억")
EXPLICIT_SEARCH_INTENT = ("검색", "찾아줘", "찾아 줘", "조회", "최신", "새로")


# 사람을 가리키는 지시어. 되짚기("아까 말한 회사 뭐였지")와 가르는 기준이다.
PERSON_DEIXIS = ("그 사람", "그사람", "그 분", "그분", "이 사람", "이사람",
                 "저 사람", "저사람", "이 분", "이분", "걔")


def context_answer(memory: dict, recent_pairs, question: str):
    """
    문맥을 가리키는 발화이고 새로 검색하라는 말이 없으면, 검색을 건너뛰고 이미 아는 것으로
    답한다. 근거가 없으면 None -> 평소대로 검색한다.

    주의: user.* 사실은 **사용자 본인** 것이다("내 회사는 …"라고 직접 말했을 때만 생긴다).
    이 앱에서 "회사"는 보통 명함 속 인물의 회사라, 본인 회사를 말해 둔 상태에서
    "그 사람 회사 어디야?"를 물으면 자기 회사를 답할 수 있다(알려진 한계 — Kotlin 쪽
    AgentSessionTest 에 현재 동작을 고정해 뒀다).
    """
    q = question or ""
    if not any(m in q for m in CONTEXT_REFERENCES):
        return None
    # **사람을 가리키면 되짚기가 아니라 그 사람에 대한 새 질문이다.**
    # "아까 말한 회사 뭐였지"(되짚기)와 "아까 그 사람 회사 알려줘"(새 질문)를 가른다.
    # 대명사를 CONTEXT_REFERENCES 에서 뺐어도 "아까"가 남아 여기로 새고 있었다
    # (실측: Final50 v3 에서 sc_03·sc_08·lr_04·er_04 가 전부 이 경로였다).
    if any(d in q for d in PERSON_DEIXIS):
        return None
    if any(m in q for m in EXPLICIT_SEARCH_INTENT):
        return None
    normalized = q.lower()
    facts = memory.get("confirmed_facts", [])

    def by_key(key):
        return next((f for f in facts if f.get("key") == key), None)

    fact = None
    if "회사" in normalized:
        fact = by_key("user.company")
    elif "직책" in normalized or "직함" in normalized:
        fact = by_key("user.title")
    elif "이름" in normalized:
        fact = by_key("user.name")
    if fact:
        return f"이전 대화에서 확인된 정보입니다: {fact['content']}"
    # history 원소는 {"q": ..., "a": ...} 형태다(format_recent_conversation 과 같은 키).
    for pair in reversed(recent_pairs or []):
        previous = (pair.get("a") or "").strip() if isinstance(pair, dict) else ""
        if previous:
            return f"이전 대화 기준으로 답변합니다.\n{previous}"
    return None


def is_capability_question(question: str) -> bool:
    q = question.strip().lower()
    if not q:
        return False
    return any(p in q for p in CAPABILITY_PATTERNS)


def is_self_reference_question(question: str) -> bool:
    """AI 자신에 대한 질문("너는 누구야?")인지 — 명함 검색과 무관하므로 결정적으로 우회한다."""
    q = (question or "").strip().lower()
    if not q:
        return False
    return any(p in q for p in SELF_REFERENCE_PATTERNS)


def is_unfiltered_list_all_question(question: str) -> bool:
    """
    "전체 명함이 몇 장이야?", "이름 목록 다 보여줘"처럼 구체적인 조건 없이 전체를
    요구하는 질문인지 본다. "전체"/"모두"/"전부" 류 신호가 있고, 거기서 일반 단어·
    조사를 다 걷어냈을 때 아무것도 안 남으면 True.

    토큰화(ev.analyze) 기반으로 먼저 시도했다가 실측으로 버그를 발견해서 원문 문자열
    직접 치환 방식으로 바꿨다: analyze()는 "명함"을 STOPWORDS로 걸러내는데, 원본
    토큰 "명함이"(조사 포함)는 그 필터링을 안 받아서 걸러진 "명함"과 안 걸러진
    "명함이"가 서로 다른 문자열로 남아 있는 그대로 통과해버렸다("전체 명함이 몇
    장이야?"가 안 걸림). 원문에서 바로 걷어내면 이 불일치가 없다.

    "디자이너 전부 알려줘"처럼 구체적 조건("디자이너")이 있으면 False — 이런 질의는
    이미 정상 동작하므로 우회하면 안 된다(회귀 방지, 실측 확인).

    "등록된 사람 총 몇 명이야?"처럼 "전체/모두/전부" 없이 "총"+"몇"만으로 전체를 묻는
    문구도 신호에 추가했다(실측: 이 문구가 우회를 못 타서 "총 5명"으로 잘못 답함 —
    top-5를 전체로 착각하는 원래 버그가 그대로 재현됨). "총"만으로는 안 걸고 "몇"과
    같이 나올 때만 건다 — "판교에 총 몇명이야?"처럼 조건이 있는 질의는 strip 단계에서
    "판교"가 안 걷어지고 남으므로 어차피 여기서 걸러진다(회귀 없음).
    """
    q = question or ""
    # 개수/목록을 묻는 말이 있어야 한다. 이게 없으면 그냥 검색 질의다.
    if not re.search(r"몇|목록|리스트|다 보여|얼마나|개수|장수|전체|전부|모두", q):
        return False
    stripped = q
    for w in GENERIC_LIST_STRIP_WORDS:
        stripped = stripped.replace(w, "")
    return stripped.strip() == ""


FILTERED_COUNT_SIGNAL_RE = re.compile(r"몇\s*(명|장|개)")


def is_filtered_count_question(question: str) -> bool:
    """
    조건이 있는 카운트 질문("판교에 몇 명 있어?", "이사 직급 몇 명이야?")인지 본다.
    조건 없는 전체질문(is_unfiltered_list_all_question)은 이미 다른 우회가 처리하므로
    거기서 걸리면 여기서는 제외한다.
    """
    if is_unfiltered_list_all_question(question):
        return False
    return bool(FILTERED_COUNT_SIGNAL_RE.search(question or ""))


def count_by_known_condition(question: str, gazetteer):
    """
    질문에서 가제티어가 아는 조건(지역/직함/이름)을 뽑아 전체 데이터셋을 직접 세서
    정확한 개수를 낸다. 검색과 달리 top-5(TOP_N)/40(FUSION_POOL) 컷을 전혀 거치지
    않는다 — 그래서 "AI 개발하는 사람 몇 명이야?"류가 42명인데 5명으로 캡되던 문제와
    무관하게 정확하다.

    아는 조건이 하나도 없으면(개념형 질의, 예: "AI 개발자 몇 명이야?" — "AI"는
    가제티어에 없는 개념어라 지역/직함/이름 어디에도 안 걸림) None을 반환한다 —
    호출자가 기존 검색+LLM 경로로 폴백해야 한다는 뜻이다. 이 함수는 검색 파이프라인의
    extract_field_filters/apply_field_filters(eval_search.py)를 건드리지 않는
    별도 경로다 — 그쪽은 204질의 오프라인 평가로 이미 검증된 상태라 카운트 기능
    때문에 건드리는 리스크를 만들고 싶지 않았다.
    """
    tokens, _, _ = ev.analyze(question)
    dept_vocab = getattr(gazetteer, "department_terms", set())
    locs, titles, names, depts = set(), set(), set(), set()
    for tok in tokens:
        if len(tok) >= 2 and not tok.isdigit():
            # 직함을 먼저 본다 — "상무"처럼 직함이면서 주소 조각이기도 한 단어는 직함이
            # 우선이다(검색 쪽 extract_field_filters 와 같은 원칙). 둘 다에 넣으면
            # AND 로 겹쳐서 "주소에 상무가 있고 동시에 직함이 상무" = 0명이 된다.
            if tok in gazetteer.titles or tok in gazetteer.title_terms:
                titles.add(tok)
            elif tok in gazetteer.address_terms:
                locs.add(tok)
            # 부서는 부분 문자열로 맞춘다. 데이터의 부서명이 "AI개발팀"(붙여쓰기)이라
            # 정확 일치로는 질의 토큰 'ai'가 안 걸린다(실측: "AI 개발자 몇 명이야?"가
            # 필터 0건). 실제로 어떤 부서명에 들어있는 조각일 때만 조건으로 인정해서
            # 아무 단어나 부서로 오인하지 않게 한다.
            if any(tok in d for d in dept_vocab):
                depts.add(tok)
        stem = gazetteer.person_name_stem(tok) if gazetteer.looks_like_person_name(tok) else tok
        if len(stem) >= 2 and stem in gazetteer.names:
            names.add(stem)

    if not (locs or titles or names or depts):
        return None

    matched = []
    for cid, c in CARDS_BY_ID.items():
        name_hay = ev.normalize(c.get("name") or "")
        loc_hay = ev.normalize((c.get("location") or "") + " " + (c.get("address") or ""))
        # 직함은 단어 단위로만 맞춘다(부분 문자열이면 "대표이사"가 "이사"에 걸려서 오카운트
        # 된다 — 실측: title=='이사' 정확 매치 78명인데 부분매치로는 161명이 나옴).
        title_words = ev.normalize(c.get("title") or "").split()
        dept_hay = ev.normalize(c.get("department") or "")
        name_ok = not names or name_hay in names
        loc_ok = not locs or any(loc in loc_hay for loc in locs)
        title_ok = not titles or any(t in title_words for t in titles)
        dept_ok = not depts or any(d in dept_hay for d in depts)
        if name_ok and loc_ok and title_ok and dept_ok:
            matched.append(cid)
    return matched


NARROWING_MARKERS = ("그중", "그 중", "거기서", "그 안에서", "그것들 중")


# ---- 담화 순서 지시("처음에 물어본 사람") ----
# 직전 결과의 N번째를 고르는 ordinal_index 와 **다른 것**이다. 이쪽은 '대화에서 N번째로
# 화제가 된 사람'이라, 가리키는 대상이 직전 카드 목록이 아니라 지난 발화들이다.
#
# 실측(HJP-limited/ymj Final50 v3 벤치마크): 이 처리가 없으면 "처음에 물어본 사람
# 전화번호는?" 이 **새 검색**으로 빠지고 "처음/물어본/사람"이 검색어가 돼 시나리오에
# 없는 사람을 데려온다(long_range_reactivation 0/10, discourse_coreference 0/10).
# 최근 창(4턴) 밖으로 밀려난 인물이라 focus 치환으로도 닿지 않는다.
DISCOURSE_VERBS = ("물어본", "물어봤", "질문한", "질문했", "언급한", "언급했",
                   "확인한", "확인했", "말한", "말했", "등장한", "나온")
DISCOURSE_FIRST = ("맨 처음", "처음에", "처음", "가장 먼저", "먼저")
DISCOURSE_HINTS = DISCOURSE_VERBS + DISCOURSE_FIRST + ("대화",)
# 이름을 앞에 붙인 뒤 남으면 검색어를 오염시키는 말들.
DISCOURSE_STRIP = DISCOURSE_HINTS + (
    # 시간 부사를 남기면 아래 context_answer 가 "아까"를 보고 되짚기로 오인해
    # 직전 답변을 재생한다(실측: "아까 처음에 물어본 분 전화번호는?" -> 엉뚱한 번호).
    "아까", "방금", "앞서",
    "그분", "그 분", "사람", "분", "대화에서", "두 사람", "중", "맨", "가장",
    "첫 번째로", "첫 번째", "첫번째", "번째로", "번째", "그", "했던", "던",
)


def discourse_subjects(history, gazetteer):
    """지난 발화에 등장한 인물을 **말한 순서대로** 모은다(중복 제거)."""
    subjects = []
    for h in history or []:
        q = (h or {}).get("q") or ""
        try:
            names = (ev.extract_field_filters(q, gazetteer) or {}).get("name") or []
        except Exception:  # noqa: BLE001
            names = []
        for n in names:
            if n not in subjects:
                subjects.append(n)
    return subjects


# 대상 정정("A가 아니라 B야") 표지.
CORRECTION_MARKERS = ("아니라", "말고", "정정", "아니고")


def resolve_correction(question: str, gazetteer):
    """
    "손서윤씨가 아니라 남다은씨야. 그분 회사는?" 처럼 **대상을 바꾸는** 발화를
    정정된 사람에 대한 질의로 다시 쓴다.

    실측(Final50 v3 explicit_target_correction): 이게 없으면 두 이름이 **둘 다** 이름
    조건으로 잡히고, 대명사('그분')는 resolve_query 가 **옛 focus**로 치환해 버린다
    (resolved='… 남다은씨야. 손서윤 회사는 어디야?'). 그러면 focus 가 옛 대상에 머물러
    **그 뒤 모든 턴이 틀린 사람을 답한다**(4턴짜리 시나리오가 통째로 무너진다).

    정정 표지가 있고 아는 이름이 둘 이상일 때만 건다 — 마지막에 말한 이름이 정정된 대상이다.
    """
    if not any(m in question for m in CORRECTION_MARKERS):
        return question
    try:
        names = (ev.extract_field_filters(question, gazetteer) or {}).get("name") or []
    except Exception:  # noqa: BLE001
        return question
    if len(names) < 2:
        return question
    # 질의에 나타난 **위치** 순으로 본다(추출 순서가 아니라).
    ordered = sorted(names, key=lambda n: question.find(n))
    target = ordered[-1]
    # 정정 뒤의 실제 요청만 남긴다. 마지막 문장이 그 요청이다.
    tail = question
    for sep in (".", "!", "?"):
        parts = [p for p in tail.split(sep) if p.strip()]
        if len(parts) > 1:
            tail = parts[-1]
    # 옛 이름과 대명사를 지운다 — 남으면 다시 이름 조건으로 잡히거나 focus 로 치환된다.
    for n in ordered[:-1]:
        tail = tail.replace(n + "씨", " ").replace(n, " ")
    for p in PRONOUNS:
        tail = tail.replace(p, " ")
    tail = re.sub(r"\s+", " ", tail).strip()
    return f"{target} {tail}".strip()


def resolve_discourse_reference(question: str, history, prev_card_ids, gazetteer):
    """담화 순서로 사람을 가리키면 그 이름을 넣어 질의를 다시 쓴다. 아니면 원문 그대로."""
    if not history:
        return question
    # 이름이 이미 있으면 지시가 아니다.
    try:
        if ((ev.extract_field_filters(question, gazetteer) or {}).get("name") or []):
            return question
    except Exception:  # noqa: BLE001
        pass

    idx = None
    if any(h in question for h in DISCOURSE_HINTS):
        idx = 0 if any(f in question for f in DISCOURSE_FIRST) else ordinal_index(question)
    elif ordinal_index(question) is not None and len([c for c in (prev_card_ids or []) if c in CARDS_BY_ID]) < 2:
        # "첫 번째 사람" 처럼 담화 단서가 없는 순서 지시. 직전 결과가 0~1장이면 거기서
        # 고를 게 없으므로 대화 순서를 가리키는 말로 읽는다(narrow_by_answer 4단계와 같은 원리).
        idx = ordinal_index(question)
    if idx is None:
        return question

    subjects = discourse_subjects(history, gazetteer)
    if not subjects:
        return question
    name = subjects[-1] if idx < 0 else (subjects[idx] if idx < len(subjects) else None)
    if not name:
        return question

    rest = question
    for w in sorted(DISCOURSE_STRIP, key=len, reverse=True):
        rest = rest.replace(w, " ")
    rest = re.sub(r"\s+", " ", rest).strip()
    return f"{name} {rest}".strip()


def apply_narrowing(question: str, previous_terms):
    """
    점진적 좁히기 — 앞 턴의 조건을 이어받는다. Kotlin applyNarrowing 과 같은 규칙.

    "대전에 있는 사람 찾아줘" -> "그중에 변호사만" 에서 앞 턴의 지역 조건이 사라져
    **전국 변호사**가 나왔다(매 턴 질문에서 조건을 새로 뽑기 때문).
    조건을 따로 병합하지 않고 앞 턴 조건어를 질의 앞에 붙인다 — 그러면 필터 추출이
    알아서 합치고, 검색어에도 그 말이 들어가 후보 풀에 해당 지역 사람이 실제로 담긴다.
    """
    if not previous_terms:
        return question
    if not any(m in (question or "") for m in NARROWING_MARKERS):
        return question
    return f"{previous_terms} {question}"


def carry_over_attribute(question: str, last_attribute):
    """
    생략된 **속성**을 직전 턴에서 이어받는다. Kotlin carryOverAttribute 와 같은 규칙.

    생략형 후속은 두 방향인데 그동안 한쪽만 처리했다:
      "주소는?"      주어 생략 + 속성 명시 -> focus 를 앞에 붙임(resolve_query)
      "음가영씨는?"  주어 명시 + 속성 생략 -> **처리 없음**
    뒤엣것은 검색은 맞는데 답변이 "음가영"처럼 이름만 되돌아왔다(pass^3 에서 3회 재현).
    """
    if not last_attribute:
        return question
    q = (question or "").strip()
    if any(n in q for n in ATTRIBUTE_NOUNS):
        return question
    m = re.match(r"^(.{2,10}?)(씨|님)?(는|은|이|가)\s*\??$", q)
    if not m:
        return question
    return f"{m.group(1)}{m.group(2) or ''} {last_attribute}"


def attribute_of(question: str):
    """이번 턴이 물어본 속성을 뽑는다(다음 턴이 생략했을 때 이어받으려고)."""
    return next((n for n in ATTRIBUTE_NOUNS if n in (question or "")), None)


# 속성 명사 -> 카드 필드. 물어본 칸이 실제로 비어 있으면 LLM 을 부르지 않는다.
# ('이름'은 비는 일이 없어 뺀다.)
ATTRIBUTE_FIELD = {
    # 복합어를 **먼저** 등록한다. "메일 주소는?" 은 이메일 하나를 묻는 말이지
    # 이메일과 주소를 함께 묻는 말이 아니다(실측: 두 칸으로 읽혀 주소까지 답했다).
    "이메일 주소": "email", "메일 주소": "email", "이메일주소": "email", "메일주소": "email",
    "회사 주소": "address", "회사주소": "address",
    "전화번호": "phone", "전화": "phone", "번호": "phone", "연락처": "phone",
    "핸드폰": "phone", "휴대폰": "phone",
    "메일": "email", "이메일": "email",
    "직급": "title", "직함": "title", "직책": "title",
    "회사": "company", "소속": "company",
    "주소": "address", "위치": "address", "지역": "location",
    "부서": "department",
}


# 지시 관형사 뒤의 속성 명사는 **요청이 아니라 가리키는 말**이다.
# "그 회사 주소는?" 은 주소 하나만 묻는 것이지 회사를 함께 묻는 게 아니다
# (실측: 이 구분이 없으면 우리 시나리오 '대명사 체인' 7턴이 통째로 오탐된다).
_DEMONSTRATIVES = ("그", "이", "저")


def _requested_pos(question: str, noun: str) -> int:
    """질의에서 그 명사가 **요청으로** 쓰인 첫 위치. 없으면 -1."""
    start = 0
    while True:
        pos = question.find(noun, start)
        if pos < 0:
            return -1
        before = question[:pos].rstrip()
        if not before.endswith(_DEMONSTRATIVES):
            return pos
        start = pos + 1


def requested_fields(question: str):
    """질의가 물은 속성들을 **말한 순서대로**, 필드 기준으로 중복 없이 돌려준다.

    '전화번호'가 '전화'·'번호'를 품는 식으로 명사가 겹치므로 필드로 중복을 없앤다.
    """
    found = []
    taken = []  # 이미 어떤 명사가 차지한 글자 구간
    # **긴 명사부터** 본다 — "이메일" 안의 "메일", "메일 주소" 안의 "주소"가 먼저 잡히면
    # 라벨이 잘리거나 한 요청이 두 칸으로 쪼개진다.
    for noun in sorted(ATTRIBUTE_FIELD, key=len, reverse=True):
        field = ATTRIBUTE_FIELD[noun]
        if any(f == field for _, f, _ in found):
            continue
        pos = _requested_pos(question, noun)
        if pos < 0:
            continue
        # 앞서 잡힌 명사 안에 들어 있으면 같은 말을 두 번 세는 것이다.
        if any(a <= pos < b for a, b in taken):
            continue
        taken.append((pos, pos + len(noun)))
        found.append((pos, field, noun))
    found.sort()
    return [(f, n) for _, f, n in found]


def field_list_answer(question: str, card_ids):
    """
    한 사람에게 **여러 칸**을 물으면 코드가 직접 조합해 답한다.

    실측(Final50 v3): "회사와 이메일도 알려줘" 에 2B 모델이 이메일만 답했다(4건).
    값은 컨텍스트에 다 있는데 모델이 하나를 빠뜨리는 것이라 **검색·문맥 문제가 아니다.**
    프롬프트로 고치는 건 4전 4패라 시도하지 않는다 — 어느 칸을 물었는지도, 그 값이
    무엇인지도 코드가 이미 안다.

    두 칸 이상일 때만 건다. 한 칸짜리는 그대로 LLM 이 문장으로 답하게 둔다(자연스러움 유지).
    후보가 정확히 1장일 때만 건다 — 여러 명이면 '누구의 칸'인지 안 정해진다.
    """
    if len(card_ids) != 1:
        return None
    fields = requested_fields(question)
    if len(fields) < 2:
        return None
    card = CARDS_BY_ID.get(card_ids[0]) or {}
    parts = []
    for field, noun in fields:
        value = str(card.get(field) or "").strip()
        parts.append(f"{noun}: {value}" if value else f"{noun}: 정보 없음")
    return ", ".join(parts)


def empty_field_answer(question: str, card_ids):
    """
    대상이 하나로 정해졌는데 물어본 칸이 비어 있으면 결정적으로 '없다'고 답한다.

    실측(Final50 v3 unanswerable): 빈 칸을 그냥 물으면 2B 모델이 **옆 칸 값으로 대체**했다 —
    회사를 물었는데 "국내영업팀입니다"(부서), "제주특별자치도 제주시"(주소), 직급을 물었는데
    "생산관리팀입니다"(부서). 컨텍스트에 그 칸만 없을 뿐 다른 값이 다 들어 있으니
    모델이 가장 그럴듯한 걸 골라 채운다. 값이 없다는 건 **코드가 이미 아는 사실**이라
    모델에 맡길 이유가 없다(프롬프트 규칙 추가는 4전 4패다).

    후보가 정확히 1장일 때만 건다 — 여러 명이면 '그중 누구의 칸'인지 정해지지 않는다
    (narrow_by_answer 4단계와 같은 원리).
    """
    if len(card_ids) != 1:
        return None
    attr = attribute_of(question)
    field = ATTRIBUTE_FIELD.get(attr) if attr else None
    if not field:
        return None
    card = CARDS_BY_ID.get(card_ids[0]) or {}
    if str(card.get(field) or "").strip():
        return None
    return f"{attr} 정보가 없습니다."


# 속성 명사 앞에 흔히 붙는 군말. 이걸 떼고도 속성으로 시작하면 생략형 후속이다.
# ("어느 부서야?", "그럼 주소는?") 지시 관형사(그/이/저)는 넣지 않는다 —
# 그건 PRONOUNS 가 이미 담당한다.
ELLIPSIS_LEAD_FILLERS = ("어느", "어떤", "그럼", "그러면", "근데", "그리고", "혹시", "이제", "또")


def resolve_query(question: str, focus):
    if not focus:
        return question, False
    trimmed = question.lstrip()
    has_pron = any(p in question for p in PRONOUNS)
    # 질문에 '새 검색값'(전화번호 뒷자리 등)이 있으면 생략형 후속으로 보지 않는다.
    # 숫자가 하나라도 있으면 새 값으로 봤더니 실측으로 버그가 났다:
    # "전화번호 뒤 4자리는 뭐야"의 '4'가 새 값으로 잡혀서 직전 인물이 안 붙고
    # 엉뚱한 검색이 됐다(답변 '조건에 해당하는 명함을 찾지 못했습니다', focus 도 딴 사람으로 튐).
    # '4자리' 같은 자릿수 표현과 '4312' 같은 검색값을 가르려면 자릿수 길이를 봐야 한다.
    has_new_value = bool(re.search(r"\d{3,}", question))
    # 속성 명사 **앞에 붙는 군말**을 떼고 본다. startswith 만 보면 "부서는?"은 되는데
    # "어느 부서야?"는 새 검색으로 빠져 focus 가 엉뚱한 사람으로 튄다 — 그 한 턴이
    # 오염시키면 **뒤 턴이 연쇄로 무너진다**(실측: 표현을 다양화하자 실패 2건 -> 32건,
    # 그중 대부분이 이 한 가지 말투에서 시작된 연쇄였다).
    stripped = trimmed
    for w in ELLIPSIS_LEAD_FILLERS:
        if stripped.startswith(w):
            stripped = stripped[len(w):].lstrip()
            break
    is_ellip = (not has_new_value) and any(
        t.startswith(n) for t in (trimmed, stripped) for n in ATTRIBUTE_NOUNS
    )
    if not has_pron and not is_ellip:
        return question, False
    q = question
    for p in PRONOUNS:
        q = q.replace(p, focus)
    if q == question:
        q = focus + " " + question
    return q, True


# HJP_TEST_CARDS=data/cards_test50.json 처럼 지정하면 5000장 대신 소규모 통제 데이터셋을 쓴다.
# (이름 근사중복이 적어 멀티턴/키워드 테스트 노이즈가 줄어듦 — scripts/generate_test50.py 참고)
TEST_CARDS_PATH = os.environ.get("HJP_TEST_CARDS")

print("[hybrid] 카드/벡터/모델 로딩 중… (EmbeddingGemma 1.2GB — 30초~1분 걸릴 수 있음)")
from sentence_transformers import SentenceTransformer  # noqa: E402
MODEL = SentenceTransformer(str(ev.MODEL_PATH))

if TEST_CARDS_PATH:
    CARDS = json.loads(Path(TEST_CARDS_PATH).read_text(encoding="utf-8"))
    CARDS_BY_ID = {c["id"]: c for c in CARDS}
    PREPARED = []
    for c in CARDS:
        t = ev.card_original_text(c)
        PREPARED.append((t, set(t.split())))
    IDS = [c["id"] for c in CARDS]
    doc_texts = [ev.card_text(c) if hasattr(ev, "card_text") else ", ".join(
        c.get(f, "") for f in ["name", "nameEn", "company", "title", "department", "industry", "location", "memo", "tags"] if c.get(f)
    ) for c in CARDS]
    DOC_MAT = np.asarray(MODEL.encode_document(doc_texts), dtype="<f4")
    print(f"[hybrid] 테스트 데이터셋 사용: {TEST_CARDS_PATH} ({len(CARDS)}명, 임베딩 실시간 계산)")
else:
    CARDS = json.loads(ev.CARDS_PATH.read_text(encoding="utf-8"))
    CARDS_BY_ID = {c["id"]: c for c in CARDS}
    PREPARED = []
    for c in CARDS:
        t = ev.card_original_text(c)
        PREPARED.append((t, set(t.split())))
    IDS = json.loads(ev.IDS_PATH.read_text(encoding="utf-8"))
    _raw = ev.VECTORS_PATH.read_bytes()
    DOC_MAT = np.frombuffer(_raw, dtype="<f4").reshape(len(IDS), ev.DIM).copy()

# 키워드 검색: 저쪽(검색 담당) 방식 = FTS4 unicode61 티어드(phrase→allTerms→prefix→LIKE).
# eval에서 내 LIKE+점수 방식보다 상위 정확도가 높아(특히 전화번호) 이걸 채택.
_FTS = sqlite3.connect(":memory:", check_same_thread=False)
_FTS.execute("CREATE VIRTUAL TABLE fts USING fts4(cardId, text, tokenize=unicode61)")
_FTS.executemany("INSERT INTO fts(cardId, text) VALUES (?,?)",
                 [(CARDS[i]["id"], PREPARED[i][0]) for i in range(len(CARDS))])
_FTS.commit()
_FTS_LOCK = threading.Lock()


def _fts_match(match: str):
    with _FTS_LOCK:
        try:
            return [r[0] for r in _FTS.execute("SELECT cardId FROM fts WHERE text MATCH ?", (match,)).fetchall()]
        except sqlite3.OperationalError:
            return []


def _query_tokens(query: str):
    """
    질의 토큰화 — eval_search.analyze() 와 동일한 결과를 쓴다.
    자체 구현을 쓰다가 '숫자만 추출한 변형'이 누락돼 있었고, 그 때문에
    "번호 뒷자리 2033인 사람"이 "2033인"으로만 검색돼 실제 존재하는 번호를 못 찾았다.
    (analyze() 는 "2033인" 과 "2033" 을 모두 토큰으로 만든다)
    """
    tokens, _, _ = ev.analyze(query)
    return [t for t in tokens if len(t) >= 2]


# 키워드 동의어 확장 — 앱 CardSearchService.kt의 SYNONYMS와 동기화(드리프트 주의).
# LIKE 폴백(가장 느슨한 티어)에만 적용 — 정밀한 ①②③ 티어는 원래 토큰만 쓴다.
SYNONYMS = {
    "ai": ["ai", "인공지능", "머신러닝", "개발", "연구"],
    "인공지능": ["ai", "인공지능", "머신러닝", "개발", "연구"],
    "개발": ["개발", "개발자", "엔지니어", "소프트웨어", "it", "ai"],
    "디자인": ["디자인", "디자이너", "브랜드", "크리에이티브"],
    "투자": ["투자", "벤처", "금융", "vc"],
    "영업": ["영업", "세일즈", "파트너십", "비즈니스"],
    "마케팅": ["마케팅", "브랜드", "광고", "홍보"],
    "의료": ["의료", "헬스케어", "제약", "병원"],
    "대표": ["대표", "ceo", "창업", "창업자"],
    "변호사": ["변호사", "법무", "법률"],
    "회계": ["회계", "회계사", "재무", "감사"],
}


def _expand_synonyms_for_fallback(terms):
    out = []
    for t in terms:
        if t not in out:
            out.append(t)
        for syn in SYNONYMS.get(t.lower(), []):
            if syn not in out:
                out.append(syn)
    return out


def keyword_ranking_fts(query: str):
    toks = _query_tokens(query)
    if not toks:
        return []
    out = []
    def add(ids):
        for i in ids:
            if i not in out:
                out.append(i)
    add(_fts_match('"%s"' % " ".join(toks)))          # 1) 정확 구문(인접)
    add(_fts_match(" ".join(toks)))                    # 2) 전체 단어(AND)
    add(_fts_match(" ".join(t + "*" for t in toks)))   # 3) 접두어(AND)
    # 4) LIKE 폴백 — 동의어까지 확장해서 term-by-term으로 처리(순서=우선순위, 앱과 동일하게).
    for t in _expand_synonyms_for_fallback(toks):
        add([CARDS[i]["id"] for i in range(len(CARDS)) if t in PREPARED[i][0]])
    return out


# 가제티어 — 데이터에 실제 존재하는 지역/직함/회사 값 집합. 기권 판정에 쓴다.
GAZETTEER = ev.Gazetteer(CARDS)

print(
    f"[hybrid] 준비 완료: 카드 {len(CARDS)}장, 벡터 {DOC_MAT.shape}, 키워드=FTS4 티어드, "
    f"가제티어(지역 {len(GAZETTEER.locations)}종/직함 {len(GAZETTEER.titles)}종), 서버 :{PORT}"
)


def names(id_list, n=5):
    return [CARDS_BY_ID[i]["name"] + " · " + (CARDS_BY_ID[i].get("company") or "") for i in id_list[:n]]


def rag_context(id_list, total_matches=None):
    """
    카드 컨텍스트. 맨 앞에 인원수를 명시한다 — 2B 모델은 목록의 개수를 세다가 자주 틀린다
    (실측: 판교 5명을 정확히 검색했는데 답변은 "4명입니다"). 세는 일을 모델에 맡기지 않는다.

    total_matches(셀 수 있는 조건일 때의 진짜 전체 수)를 주면 그 값을 쓴다.
    **없으면 숫자를 아예 안 넣는다.** 예전에는 후보 개수(최대 TOP_N=5)를 헤더에 넣었는데,
    모델이 그 숫자를 **답으로 그대로 옮겨 적었다**:
      "디자인하는 사람 찾아줘" -> 이름 대신 "총 3명" (멀티턴 평가에서 잡힌 실패)
      "변호사 있나?" -> 화면 '총 3명', 실제 변호사 65명
    후보 개수는 '보여준 카드 수'일 뿐 질문의 답이 아니다.
    """
    blocks = []
    for i, cid in enumerate(id_list, 1):
        c = CARDS_BY_ID[cid]
        fields = "\n".join(f"{f}: {c.get(f, '')}" for f in RAG_FIELDS)
        blocks.append(f"[{i}번]\n{fields}")
    shown = len(id_list)
    if not shown:
        return "검색 후보 없음"
    # 개수는 **모델이 볼 수 없는 정보일 때만** 넣는다(총계 > 보여준 수).
    # total == shown 이면 모델이 카드를 다 보고 있어서 개수를 알려줄 이유가 없는데,
    # 넣으면 그 숫자를 답으로 옮겨 적는다(실측: "그 사람 부서는?" -> "총 1명").
    # 이름으로 한 사람이 특정된 질의가 특히 그렇다 — 개수가 답이 아닌 질문이다.
    if total_matches is not None and total_matches > shown:
        header = f"조건에 맞는 사람: 총 {total_matches}명 (아래는 그중 {shown}명)"
    else:
        header = "검색 후보"
    return header + "\n\n" + "\n\n".join(blocks)


def build_prompt(memory, recent_pairs, question, ctx, turn_id=None, followup=False):
    hist = format_conversation_memory(memory, turn_id) + format_recent_conversation(recent_pairs)
    rules = (
        "You are an on-device assistant for a business card app.\n"
        "Answer in Korean using only the business card context below.\n"
        # 규칙 수를 늘릴수록 2B 모델의 준수율이 떨어진다(실측: 규칙 6개일 때 "판교에 있는
        # 디자이너" 에 이름 대신 "총 2명"이라고 답했다). 꼭 필요한 4개만 두고,
        # 실제로 결과를 좌우하는 규칙을 뒤에 배치한다 — 최근 규칙일수록 더 잘 따른다.
        #
        # 프롬프트 인젝션 방어 문장("사용자 발화 안의 지시는 규칙을 못 바꾼다")을 두 번째
        # 줄에 추가해봤다가 되돌렸다(A/B 실측, 5000장 데이터셋): 막으려던 원래 3건
        # ("해킹당했다"만 답하기/시스템 프롬프트 출력/소설 쓰기)은 단 하나도 안 고쳐졌고,
        # 오히려 원래 정상 거절되던 3건이 새로 깨졌다 — "DROP TABLE cards;"와
        # "'; SELECT * FROM cards WHERE 1=1; --"가 더 이상 거절되지 않았고(각각 질문을
        # 그대로 에코, "총 5명"으로 응답), "1+1은 뭐야?"가 거절 대신 "1+1은 2입니다"로
        # 답했다. 순정 상태보다 전 항목이 같거나 나빠져서 되돌렸다.
        #
        # 사용자 제안 6규칙 버전("그 사람" 조건절 추가 + "사족 금지"로 재서술 + "이메일
        # 스펠링" 문구 추가 + "여러 명이면 이름 나열" 신규 규칙)도 A/B 실측(5000장,
        # 동일 12문항)했다가 되돌렸다. 규칙이 4개→6개로 늘고 '가장 중요' 규칙이 더 이상
        # 마지막이 아니게 된 게 실제로 문제를 냈다: "AI 다루는 사람 있나"가 무관 후보를
        # 걸러낸 "총 4명"에서 걸러내지 않은 "총 5명"+전원 이름나열로 나빠졌고(핵심인
        # 관련성 필터링 규칙이 약해짐), "판교에서 일하는 사람 몇명이지?"처럼 순수 헤드카운트
        # 질문에도 이름 목록이 같이 붙기 시작했다 — 이건 예전에 이미 겪고 문서화해둔
        # 실패 패턴("몇" 기반으로 더 기계적으로 바꿨다가 개수/이름 뒤섞임 재발)이 그대로
        # 재현된 것이다. 노리던 "이메일 스펠링" 케이스("이메일 주소에 gmail 쓰는 사람
        # 있어?")도 안 고쳐졌다 — 데이터에 gmail 주소가 아예 없어서(직접 확인) 답은
        # 원래 거절이어야 하는데, 전(1명 오답) 후(3명 오답, 셋 다 gmail 아님) 모두 틀렸고
        # 오답 개수만 늘었다. 유일한 개선은 "?"가 되물음 대신 정상 거절로 바뀐 것 하나였다
        # — 그것만 따로 테스트해볼 가치는 있지만, 나머지 5개 변경과 묶어서 쓰기엔
        # 손해가 더 크다.
        '- "그 사람" 같은 표현은 이전 대화에서 다룬 인물을 가리킨다. 그 인물 기준으로 답하라.\n'
        "- 되묻지 말고 바로 답하라. 이름을 물으면 이름을 답하라.\n"
        # 2B 모델은 목록을 세다 틀린다(실측: 판교 5명을 맞게 검색했는데 "4명입니다").
        # 그래서 셀 일이 없게 컨텍스트 맨 위에 개수를 박아 두고 그대로 쓰게 한다.
        # 규칙을 '몇 이라는 글자가 있으면' 식으로 더 기계적으로 바꿔 봤지만 오히려 나빠졌다
        # (실측: "AI 다루는 사람 있나" 는 고쳐졌지만 "판교에서 일하는 사람 몇명이지?" 가
        # 개수 대신 이름을 나열하고, "우주비행사" 거절도 풀렸다). 규칙을 건드릴 때마다
        # 다른 항목이 깨지므로, 8개 항목 중 7개가 통과하는 이 문장으로 고정한다.
        #
        # "일부만 맞으면 숫자를 새로 만들지 말고 이름을 나열하라"는 문장을 추가해봤다가
        # 되돌렸다: "AI 개발하는 사람 있어?"의 숫자 지어내기(총2명인데 카드5장)는
        # 고쳐졌지만, 그 대신 "1+1은 뭐야?"/"파이썬 코드 짜줘"/"?"/"ㅇㅇ" 같이 원래
        # 정상적으로 거절되던 무관한 질문들이 거절을 멈추고 되묻거나("어떤 정보를
        # 찾으시나요?") 질문을 그대로 에코하기 시작했다(2회 재현, 100% 재현). 이 규칙도
        # 예외가 아니었다 — 손대지 않는 게 낫다.
        "- 인원수를 물었을 때만 숫자를 써라. 후보 전원이 조건에 맞으면 맨 위 '총 N명'을\n"
        "  그대로 쓰고 직접 세지 마라.\n"
        # 이 규칙이 무관 카드를 실제로 잘라낸다. 그리고 '전원 거절'은 같은 판단의 극단이므로
        # 붙여 둔다 — 따로 떼면 모델이 후보 중 하나를 억지로 고른다
        # (실측: "우주비행사 찾아줘" -> 이름에 '우주'가 든 '장우주'를 답).
        "- 가장 중요: 컨텍스트에 있다고 질문과 관련 있는 건 아니다. 직함·부서·업무로 판단해\n"
        "  질문 조건에 맞는 사람만 답하고, 무관한 사람은 이름조차 언급하지 마라.\n"
        "  이름 글자가 우연히 겹치는 것은 근거가 아니다.\n"
        f"  맞는 사람이 하나도 없으면 다른 말 없이 '{NO_MATCH_PHRASE}' 라고만 답하라.\n"
    )
    if followup:
        # 정정/확인 발화에는 새 검색 결과가 없다. 직전 결과를 근거로 짧게 응답하게 유도한다.
        rules += (
            "- 지금 사용자 발화는 새 검색이 아니라 직전 답변에 대한 정정/확인/추가질문이다.\n"
            "  아래 컨텍스트는 '직전 검색 결과'다. 이 사람들만 대상으로 짧게 답하라.\n"
            "  사용자가 숫자나 사실을 정정했고 컨텍스트가 사용자 말과 맞으면 정정을 인정하라.\n"
        )
        # 무엇을 물었는지 **코드로 뽑아서** 알려준다. 규칙을 하나 더 얹는 게 아니라
        # 이미 해석해 둔 의도를 전달하는 것이다 — 이게 없으면 "두 번째 사람 연락처" 처럼
        # 속성을 명시해도 모델이 이름만 돌려줬다(실측). followup 분기가 "짧게 답하라"
        # 로만 유도해서 무엇을 답할지가 비어 있었다.
        asked = attribute_of(question)
        if asked:
            rules += f"- 사용자가 물은 것은 '{asked}' 다. 그 값을 답하라(이름만 답하지 마라).\n"
    return f"{rules}\n{hist}명함 컨텍스트:\n{ctx}\n\n사용자 발화:\n{question}"


def call_gemma(prompt):
    body = json.dumps({
        "model": GEMMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(GEMMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _deterministic_reply(question, focus, memory, turn_id, now_ms, history, answer, card_ids=None,
                         route="deterministic"):
    """
    검색·LLM 호출 없이 결정적으로 턴을 마무리한다(자기참조 질문, 전체 개수 질문 등).
    conversational_followup 경로와 같은 응답 모양을 맞추되, 새로 검색하지 않았으니
    도구 실행 기록은 남기지 않는다.
    """
    top_ids = card_ids or []
    memory, recent = finalize_turn(memory, turn_id, now_ms, question, answer, [], history)
    return {
        "route": route,
        "answer": answer,
        "error": None,
        "resolved_query": question,
        "changed": False,
        "keyword_top": [],
        "semantic_top": [],
        "hybrid_top": names(top_ids),
        "kw_ms": 0.0,
        "sem_ms": 0.0,
        "gen_ms": 0.0,
        "focus": focus,
        "abstained": False,
        "identifier_routed": False,
        "filtered_out": [],
        "field_filters": {},
        "conversational_followup": False,
        "card_ids": top_ids,
        "conversation_memory": memory,
        "history": recent,
        "cards": [
            {k: (CARDS_BY_ID[cid].get(k) or "") for k in ("name", "company", "title", "department", "phone", "email", "address", "location")}
            for cid in top_ids
        ],
    }


def run_turn(question, history, focus, prev_card_ids=None, conversation_memory=None,
             dry_run=False):
    memory = conversation_memory or default_conversation_memory()
    history = history or []

    # 빈 질문은 검색/LLM까지 태우지 않는다(실측: 빈 문자열이 12초 넘게 걸려 전체
    # 파이프라인을 다 돌고 "되묻는" 답까지 만들어냈다 — "되묻지 말라"는 규칙 위반이기도
    # 하고 순수 낭비였다). 세션 상태는 건드리지 않는다 — 아무 턴도 일어나지 않은 것.
    if not question.strip():
        return {
            "route": "blank",
            "answer": "질문을 입력해주세요.", "error": None, "resolved_query": question,
            "changed": False, "keyword_top": [], "semantic_top": [], "hybrid_top": [],
            "kw_ms": 0.0, "sem_ms": 0.0, "gen_ms": 0.0, "focus": focus, "abstained": False,
            "identifier_routed": False, "filtered_out": [], "field_filters": {},
            "conversational_followup": False, "card_ids": [],
            "conversation_memory": memory, "history": history, "cards": [],
        }

    # 속성을 생략한 후속("음가영씨는?")이면 직전 턴이 물어본 속성을 이어 붙인다.
    # 서버는 세션 객체가 없으므로 history 를 거슬러 올라가 마지막 속성을 찾는다
    # (앱에서는 AgentSession.KEY_LAST_ATTRIBUTE 가 같은 역할).
    last_attr = next(
        (a for a in (attribute_of((h or {}).get("q", "")) for h in reversed(history or [])) if a),
        None,
    )
    question = carry_over_attribute(question, last_attr)
    # 앞 턴에 걸렸던 필드 조건어를 history 에서 되짚어 "그중에 …" 질의에 이어 붙인다
    # (앱에서는 AgentSession.KEY_LAST_FILTER_TERMS 가 같은 역할).
    prev_terms = next(
        (t for t in ((h or {}).get("filter_terms") for h in reversed(history or [])) if t),
        None,
    )
    question = apply_narrowing(question, prev_terms)
    # '처음에 물어본 사람' 처럼 대화 순서로 사람을 가리키면 그 이름으로 다시 쓴다.
    # **ordinal_index 블록보다 먼저** 해야 한다 — 뒤에 두면 '첫 번째 사람'이 직전 카드
    # 목록의 1번을 고르는 쪽으로 새서 대화 순서를 못 본다.
    question = resolve_discourse_reference(question, history, prev_card_ids, GAZETTEER)
    # 대상 정정은 대명사 치환(resolve_query)보다 **먼저** 푼다 — 뒤에 두면 '그분'이
    # 이미 옛 focus 로 바뀐 뒤라 정정이 무시된다.
    question = resolve_correction(question, GAZETTEER)

    turn_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    # 턴 시작을 구조화 메모리에 걸어둔다 — Kotlin AgentSession.beginTurn 과 동일.
    memory = memory_begin_turn(memory, turn_id, now_ms, question)
    recent_pairs = history[-MAX_RECENT_TURNS:]

    # 명함 검색과 무관한 자기참조 질문("너는 누구야?")은 결정적으로 우회한다.
    # 실측: 프롬프트 규칙에만 맡기면 "너"를 명함 속 인물로 오인해서 관계없는 사람
    # 이름을 그대로 답했다(예: "너는 누구야?" -> "유유진").
    # 기능 질문은 자기참조보다 먼저 본다("너는 뭐 할 줄 알아?" 가 양쪽에 걸린다).
    if is_capability_question(question):
        return _deterministic_reply(question, focus, memory, turn_id, now_ms, history, CAPABILITY_ANSWER,
                                    route="capability")

    if is_self_reference_question(question):
        return _deterministic_reply(question, focus, memory, turn_id, now_ms, history, SELF_REFERENCE_ANSWER,
                                    route="self_reference")

    # "전체 몇 장이야?" 류는 검색에 태우면 top-5를 전체인 것처럼 답한다(실측:
    # 60장인데 "총 5명"). 검색 전에 걸러서 진짜 전체 개수로 답한다.
    if is_unfiltered_list_all_question(question):
        total_answer = (
            f"현재 총 {len(CARDS)}명의 명함이 등록되어 있습니다. "
            "이름·회사·지역 등 구체적인 조건으로 검색해 보세요."
        )
        return _deterministic_reply(question, focus, memory, turn_id, now_ms, history, total_answer, route="total_count")

    # 조건이 있는 카운트 질문("판교에 몇 명 있어?", "이사 직급 몇 명이야?")은 검색의
    # top-5(TOP_N)/40(FUSION_POOL) 컷을 거치면 실제 개수보다 적게 나온다(실측: AI 관련
    # 42명인데 검색은 5명까지만 봄). 가제티어가 아는 조건(지역/직함/이름)이면 전체
    # 데이터셋을 직접 세서 정확한 개수로 답한다. 모르는 조건(개념형 질의, 예: "AI
    # 개발자 몇 명이야?")이면 None이 와서 기존 검색+LLM 경로로 그대로 폴백한다.
    if is_filtered_count_question(question):
        matched_ids = count_by_known_condition(question, GAZETTEER)
        if matched_ids is not None:
            count_answer = f"총 {len(matched_ids)}명"
            return _deterministic_reply(
                question, focus, memory, turn_id, now_ms, history, count_answer,
                card_ids=matched_ids[:TOP_N], route="filtered_count",
            )

    # 대화형 후속(정정/확인/되묻기)이면 새로 검색하지 않고 직전 턴의 카드를 그대로 근거로 쓴다.
    # 검색할 내용이 없는 발화("5명인데?")를 검색어로 쓰면 엉뚱한 카드가 근거가 되어 대화가 끊긴다.
    # 순서 지시("두 번째 사람")면 직전 집합에서 그 하나만 남기고 후속 경로로 보낸다.
    ordinal_idx = ordinal_index(question)
    _prev = [cid for cid in prev_card_ids if cid in CARDS_BY_ID]
    selected_ids = _prev
    if ordinal_idx is not None and _prev:
        i = len(_prev) - 1 if ordinal_idx < 0 else ordinal_idx
        selected_ids = [_prev[i]] if 0 <= i < len(_prev) else _prev

    if (is_conversational_followup(question) or ordinal_idx is not None) and selected_ids:
        top_ids = selected_ids[:TOP_N]
        prompt_ids = list(top_ids)  # faithfulness 채점용(위 메인 경로와 같은 이유)
        t = time.time()
        try:
            answer = (field_list_answer(question, top_ids)
                      or empty_field_answer(question, top_ids)
                      or call_gemma(build_prompt(memory, recent_pairs, question,
                                                 rag_context(top_ids), turn_id, followup=True)))
            err = None
        except Exception as e:  # noqa: BLE001
            answer, err = "", f"{type(e).__name__}: {e}"
        gen_ms = (time.time() - t) * 1000
        # 후속 재사용 턴은 새로 검색하지 않았으니 도구 실행 기록이 없다.
        memory, recent = finalize_turn(memory, turn_id, now_ms, question, answer, [], history)
        # 후속 발화에서도 LLM이 "못 찾았다"고 답할 수 있다(예: 직전 결과와 무관한 걸
        # 되물었을 때) — 메인 경로와 똑같이 그 경우 카드를 비운다. 일관성 문제였다.
        followup_filtered_out = []
        if answer and any(marker in answer for marker in REJECTION_MARKERS):
            followup_filtered_out = [CARDS_BY_ID[cid]["name"] for cid in top_ids]
            top_ids = []
        return {
            "route": "followup",
            "answer": answer,
            "error": err,
            "resolved_query": question,
            "changed": False,
            "keyword_top": [],
            "semantic_top": [],
            "hybrid_top": names(top_ids),
            "kw_ms": 0.0,
            "sem_ms": 0.0,
            "gen_ms": round(gen_ms, 1),
            "focus": focus,
            "abstained": False,
            "identifier_routed": False,
            "filtered_out": followup_filtered_out,
            "field_filters": {},
            "conversational_followup": True,
            "card_ids": top_ids,
            "conversation_memory": memory,
            "history": recent,
            "context_cards": [
                {k: (CARDS_BY_ID[cid].get(k) or "") for k in ("name", "company", "title", "department", "phone", "email", "address", "location")}
                for cid in prompt_ids
            ],
            "cards": [
                {k: (CARDS_BY_ID[cid].get(k) or "") for k in ("name", "company", "title", "department", "phone", "email", "address", "location")}
                for cid in top_ids
            ],
        }

    # 문맥 참조 발화("아까 말한 …")인데 새로 검색하라는 말이 없으면, 검색도 LLM 호출도 없이
    # 이미 아는 것으로 답한다(sojung contextAnswerForSearch).
    #
    # **대화형 후속 검사보다 뒤에 둔다.** 앞에 두었더니 "그 사람들 회사 알려줘"가
    # CONTEXT_REFERENCES 의 "그 사람"에 걸려서 직전 답변을 그대로 재생했다 — 사용자는
    # 회사를 물었는데 이름 목록만 다시 받는다(멀티턴 평가에서 21건 잡힘).
    # 직전 결과 집합에 대해 **새로 묻는** 발화는 그 카드로 다시 답을 만들어야 하고,
    # context_answer 는 "아까 뭐였지"처럼 **되짚는** 발화에만 쓴다.
    contextual = context_answer(memory, recent_pairs, question)
    if contextual is not None:
        return _deterministic_reply(
            question, focus, memory, turn_id, now_ms, history, contextual,
            card_ids=[cid for cid in prev_card_ids if cid in CARDS_BY_ID][:TOP_N],
            route="context_answer",
        )

    rq, changed = resolve_query(question, focus)

    t0 = time.time()
    kw = keyword_ranking_fts(rq)  # 저쪽(검색 담당) FTS4 티어드 방식
    kw_ms = (time.time() - t0) * 1000

    t1 = time.time()
    qv = np.asarray(MODEL.encode_query([rq])[0], dtype="<f4")
    sims_arr = DOC_MAT @ qv
    order = np.argsort(-sims_arr)
    sims = {IDS[i]: float(sims_arr[i]) for i in range(len(IDS))}
    sem = [IDS[i] for i in order[:ev.TOP_K]]
    sem_ms = (time.time() - t1) * 1000

    # 융합 라우팅: 전화/이메일 같은 식별자 질의는 시맨틱을 섞지 않는다.
    # 근거(오프라인 측정): 식별자 질의에서 시맨틱은 R@5=0.000 인데 대등하게 융합하면
    # 좋은 키워드 결과를 밀어내 Precision@5 가 1.000 -> 0.233 으로 떨어졌다.
    hy = ev.hybrid_search(rq, kw, sims, CARDS_BY_ID)

    # 필드 하드 필터: 질의가 '실제 존재하는' 이름/지역을 지목했으면 그 조건을 만족하는 카드만
    # 남긴다. 이게 없으면 "안정우씨 어디서 만났더라"에 안은정·고우성 같은 무관한 사람이
    # top-5 를 채우느라 함께 딸려온다(오프라인 측정: 이름 질의 Precision@5 0.455 -> 1.000).
    field_filters = ev.extract_field_filters(rq, GAZETTEER)
    hy = ev.apply_field_filters(hy, CARDS_BY_ID, field_filters)

    # 기권(가제티어 기반): 존재하지 않는 지역/이름을 지목했거나, 식별자가 아예 매칭되지 않으면
    # 아무것도 반환하지 않는다. 점수 컷오프 방식은 개념형 질의를 함께 죽여서 폐기했다.
    kw_scored_for_gate = [(cid, 1.0) for cid in kw]  # FTS 티어드는 점수를 안 내므로 존재 여부만 전달
    abstained = ev.should_abstain(rq, kw_scored_for_gate, sims, GAZETTEER)
    if abstained:
        hy = []
    top_ids = hy[:TOP_N]
    # faithfulness 채점용 — LLM 이 **실제로 본** 카드. narrow_by_answer 가 top_ids 를
    # 깎기 전에 잡아 둔다. 답변이 narrow 로 지워진 카드 값을 썼어도 그건 컨텍스트 안이다.
    prompt_ids = list(top_ids)

    # 조건이 명확하면(가제티어가 아는 지역/직함/이름/부서) 전체를 직접 세서 진짜 개수를 준다.
    # 안 그러면 모델이 후보 개수(최대 5)를 전체인 양 답한다.
    # 개념형 질의처럼 셀 수 없는 조건이면 None -> 기존대로 후보 개수를 쓴다.
    total_matches = None
    if not abstained:
        matched_all = count_by_known_condition(rq, GAZETTEER)
        if matched_all is not None:
            total_matches = len(matched_all)

    # dry_run: 생성 직전까지만 돌리고 라우팅·조건·후보를 돌려준다(eval_multiturn.py 전용).
    # 로직을 복사하지 않고 **실제 경로**를 그대로 태우려고 둔 우회로다 — 예전에 평가가
    # 앱과 다른 랭커를 쓰다가 잘못된 결론을 낸 적이 있어서 복제는 피한다.
    if dry_run:
        memory, recent = finalize_turn(
            memory, turn_id, now_ms, question, "", ["search_business_cards"], history)
        # focus 는 아래 메인 경로와 **같은 식**으로 계산해야 한다. 생성 뒤에 정해지는
        # 값이라 그냥 입력 focus 를 돌려줬더니, 평가에서 2턴 이후 focus 가 계속 비어
        # "생략형 후속이 전부 실패"하는 것처럼 보였다(실제로는 잘 동작하는데 측정이 틀림).
        dry_names = list(dict.fromkeys(CARDS_BY_ID[cid]["name"] for cid in hy))
        dry_focus = next((n for n in dry_names if n in question), None) \
            or (dry_names[0] if dry_names else focus)
        return {
            # 기권(가제티어가 없는 값이라고 판정) 과 빈 결과(값은 있는데 조합이 0명)는
            # 원인이 달라 따로 라벨링한다 — "판교에 있는 디자이너"가 후자다.
            "route": "abstain" if abstained else ("empty_result" if not top_ids else "search"),
            "answer": "", "error": None, "resolved_query": rq, "changed": changed,
            "keyword_top": names(kw[:TOP_N]), "semantic_top": names(sem[:TOP_N]),
            "hybrid_top": names(top_ids), "kw_ms": round(kw_ms, 1), "sem_ms": round(sem_ms, 1),
            "gen_ms": 0.0, "focus": dry_focus, "abstained": abstained,
            "identifier_routed": ev.is_identifier_query(rq), "filtered_out": [],
            "field_filters": field_filters, "conversational_followup": False,
            "card_ids": top_ids, "conversation_memory": memory, "history": recent,
            "total_matches": total_matches,
            "cards": [
                {k: (CARDS_BY_ID[cid].get(k) or "") for k in
                 ("name", "company", "title", "department", "phone", "email", "address", "location")}
                for cid in top_ids
            ],
        }

    t2 = time.time()
    if abstained or not top_ids:
        # 근거가 없으면 LLM 을 호출하지 않는다(무관한 카드로 답을 지어내는 것을 방지).
        # 후보가 0장인 경우(abstain 은 아니지만 조건 교집합이 비었을 때)도 마찬가지다 —
        # 빈 컨텍스트를 넣으면 2B 모델이 컨텍스트 문자열("검색 후보 없음")을 그대로
        # 답변으로 뱉었다(pass^3 측정에서 3회 모두 재현).
        answer, err = NO_MATCH_PHRASE, None
    else:
        try:
            answer = (field_list_answer(question, top_ids)
                      or empty_field_answer(question, top_ids)
                      or call_gemma(build_prompt(
                          memory, recent_pairs, question,
                          rag_context(top_ids, total_matches), turn_id)))
            err = None
        except Exception as e:  # noqa: BLE001
            answer, err = "", f"{type(e).__name__}: {e}"
    gen_ms = (time.time() - t2) * 1000
    # 검색은(기권이어도) 실제로 실행됐다 — 후속 재사용 턴만 도구 실행이 없다.
    memory, recent = finalize_turn(memory, turn_id, now_ms, question, answer, ["search_business_cards"], history)

    # LLM 판정을 카드 목록에도 반영한다.
    # 검색은 top-N 을 채우느라 무관한 후보를 함께 담는데(점수 컷오프로는 못 자른다는 것을
    # 오프라인 측정으로 확인), LLM 은 그중 관련 있는 사람만 골라 답한다. 예: "인공지능 다루는
    # 사람" -> AI 개발자 4명만 언급하고 백엔드 개발자는 제외. 그 판단을 화면 카드에도 적용해
    # 답변과 카드가 어긋나지 않게 한다. 답변에 아무 이름도 없어도 '총 N명' 집계형 답변이면
    # 원본을 유지한다(이름을 안 대는 게 정상 형식이므로).
    #
    # 반대로 이름도 없고 '총 N명' 형식도 아니면 — 명함과 아예 무관한 답변인데 카드만
    # 그대로 남아있던 버그였다(실측: "오늘 날씨 어때?" -> 무관한 5명이 그대로 뜸,
    # "홍길동 명함 삭제해 줘"(존재 안 함) -> 의도 확인 답변인데 엉뚱한 홍씨 5명이 뜸).
    # 이럴 땐 거절과 똑같이 카드를 비운다.
    filtered_out = []
    llm_rejected = False
    if not abstained and answer:
        if any(marker in answer for marker in REJECTION_MARKERS):
            # LLM 이 후보 전원을 거절했다(정해진 문구든, "찾지 못했"류 다른 말투든).
            # 검색은 top-N 을 채워 왔지만 의미상 해당자가 없다는 판단이므로 카드도 함께
            # 비운다 — 안 그러면 "못 찾았다"는 답변 밑에 관계없는 명함이 그대로 남는다
            # (실측: "김철수 전화번호는 찾지 못했습니다."에 5명이 안 지워짐).
            llm_rejected = True
            filtered_out = [CARDS_BY_ID[cid]["name"] for cid in top_ids]
            top_ids = []
        else:
            mentioned = [cid for cid in top_ids if card_referenced_in(CARDS_BY_ID[cid], answer)]
            agg = AGGREGATE_COUNT_RE.search(answer)
            if agg and int(agg.group(1)) == 0:
                # "총 0명" — 숫자로 표현된 거절이다. 집계형이라고 카드를 살려두면
                # "총 0명"이라 답하면서 명함 5장이 뜨는 모순이 된다
                # (실측: "울릉도 근무자" -> 답변 '총 0명', 카드 5장).
                llm_rejected = True
                filtered_out = [CARDS_BY_ID[cid]["name"] for cid in top_ids]
                top_ids = []
            elif field_filters:
                # **하드 필터를 통과한 카드는 답변이 뭐라 하든 지우지 않는다.**
                # 필드 조건이 걸렸다는 건 검색이 이미 '조건을 만족하는 사람'만 남겼다는
                # 뜻이라 그 카드들은 정의상 답이다. LLM 이 일부만 말했다고 나머지를 지우면
                # 사용자가 답의 일부만 본다(실기기 실측: "대전에 있는 변호사" 2명을 맞게
                # 찾았는데 답변이 한 명만 말해서 다른 한 명이 잘렸고, 그 상태로
                # "두 번째 사람 연락처"를 물으면 두 번째가 아예 없었다).
                # 원래 목적(무관한 카드 방지)은 조건이 없는 질의에만 필요하다 —
                # "오늘 날씨 어때?"는 필드 조건이 안 잡혀 아래 else 로 내려가 비워진다.
                pass
            elif mentioned:
                filtered_out = [CARDS_BY_ID[cid]["name"] for cid in top_ids if cid not in mentioned]
                top_ids = mentioned
            elif agg:
                # 집계형인데 답변이 말한 수가 후보 수보다 적으면 그 수만큼만 보여준다.
                # 안 그러면 "총 2명"이라 답하고 카드는 5장 뜨는 모순이 된다
                # (실측: "AI 개발하는 사람 찾아줘" -> '총 2명' + 카드 5장. 뒤 3장은
                #  AI개발팀이지만 직함이 대표이사·디자인 디렉터라 실제 답이 아니었다).
                # 정렬이 정확 일치를 앞에 두므로 상위 N개가 그 N명이다.
                want = int(agg.group(1))
                if 0 < want < len(top_ids):
                    filtered_out = [CARDS_BY_ID[cid]["name"] for cid in top_ids[want:]]
                    top_ids = top_ids[:want]
            elif field_filters.get("name") and len(top_ids) == 1:
                # 이름으로 한 사람이 특정된 상태면 답변이 그 카드를 다시 인용하지 않아도
                # 남긴다. 이 단계가 하는 일은 '후보 여럿 중 답변이 가리키는 사람 고르기'인데
                # 후보가 하나면 고를 게 없다. 실측: "직급은?" -> "AI 개발자",
                # "부서는?" -> "데이터사이언스팀" 처럼 필드 값만 짧게 답하면 이름·회사·주소가
                # 답변에 없어서 카드가 사라졌다(멀티턴 내내 사라짐).
                pass
            else:
                filtered_out = [CARDS_BY_ID[cid]["name"] for cid in top_ids]
                top_ids = []

    # 답변의 '총 N명'을 진짜 전체 인원으로 바로잡는다.
    #
    # 모델은 컨텍스트 맨 위 숫자를 옮겨 적는데, 그 숫자는 '모델에게 준 후보 수'(최대 5)라
    # 사용자에게는 '그런 사람이 5명뿐'으로 읽힌다(실측: "변호사 있나?" -> 화면 '총 3명',
    # 실제 변호사 65명). 헤더에 진짜 수를 넣어봤지만 모델이 여전히 카드 수를 셌다.
    # 우리가 정확히 센 값이 있으므로 표시 숫자만 결정적으로 교체한다.
    # 카드 좁히기(위 단계)가 끝난 뒤에 바꾼다 — 모델이 말한 수는 '관련 있는 후보 수'라는
    # 판단 신호로도 쓰이므로, 그 용도를 먼저 소비한 다음 표시용으로만 고친다.
    if total_matches is not None and answer and not llm_rejected:
        agg = AGGREGATE_COUNT_RE.search(answer)
        if agg and int(agg.group(1)) != total_matches:
            answer = AGGREGATE_COUNT_RE.sub(f"총 {total_matches}명", answer, count=1)

    # 질문이 실제로 이름을 지목했으면 그 이름을 우선 지칭 대상으로 삼는다.
    # 없으면(대명사/생략형 후속) 하이브리드 1등으로 대체 — "1등이면 무조건 focus"였던
    # 방식은 유사 이름 오매칭 시 focus가 엉뚱한 사람으로 튀는 문제가 있었음(실측 확인).
    # **narrow 이후** 목록에서 잡아야 한다. hy(융합 원본)를 쓰면 명함과 무관한 질문에도
    # 검색 1등이 focus 가 되어 다음 턴이 엉뚱한 사람으로 이어진다(실측: "오늘 날씨 어때?"
    # 가 카드는 제대로 비웠는데 focus 를 '두여름'으로 바꿔서 다음 "부서는?" 이 그 사람
    # 부서를 답했다). Kotlin 은 narrowByAnswer 결과를 쓰고 있어 이미 맞았다.
    result_names = list(dict.fromkeys(CARDS_BY_ID[cid]["name"] for cid in top_ids))
    named_in_question = next((n for n in result_names if n in question), None)
    focus_new = named_in_question or (result_names[0] if result_names else focus)
    return {
        "route": "abstain" if abstained else ("empty_result" if not top_ids else "search"),
        "answer": answer,
        "error": err,
        "resolved_query": rq,
        "changed": changed,
        "keyword_top": names(kw),
        "semantic_top": names(sem),
        "hybrid_top": names(hy),
        "kw_ms": round(kw_ms, 1),
        "sem_ms": round(sem_ms, 1),
        "gen_ms": round(gen_ms, 1),
        "focus": focus_new,
        "abstained": abstained,
        "llm_rejected": llm_rejected,
        "identifier_routed": ev.is_identifier_query(rq),
        "filtered_out": filtered_out,
        "field_filters": field_filters,
        "context_cards": [
            {k: (CARDS_BY_ID[cid].get(k) or "") for k in ("name", "company", "title", "department", "phone", "email", "address", "location")}
            for cid in prompt_ids
        ],
        # 조건에 맞는 전체 인원(셀 수 있을 때만). 화면에는 top-5 만 뜨므로
        # "전체 N명 중 5명 표시" 로 구분해서 보여주기 위한 값이다.
        "total_matches": total_matches,
        "conversational_followup": False,
        "conversation_memory": memory,
        "history": recent,
        # 프런트가 다음 턴에 되돌려 보내면, 정정/확인 발화에서 이 결과를 근거로 재사용한다.
        "card_ids": top_ids,
        # 조회된 상위 명함(하이브리드 top N)의 필드 — 프런트에서 명함 카드로 렌더링.
        "cards": [
            {k: (CARDS_BY_ID[cid].get(k) or "") for k in ("name", "company", "title", "department", "phone", "email", "address", "location")}
            for cid in top_ids
        ],
    }


def card_view(cid):
    c = CARDS_BY_ID[cid]
    return {k: (c.get(k) or "") for k in
            ("name", "company", "title", "department", "phone", "email", "address", "location")}


def run_search(query):
    """
    LLM 없이 검색 축만 비교한다 — 키워드 단독 / 시맨틱 단독 / 하이브리드(RRF+라우팅+필터+기권).
    챗 탭은 Gemma 답변까지 섞여서 '검색이 틀린 건지 모델이 틀린 건지'가 안 보인다.
    이 엔드포인트는 그 절단면을 없애고 검색 결과만 눈으로 보게 한다.
    """
    q = (query or "").strip()
    if not q:
        return {"query": q, "error": "빈 질의"}

    t0 = time.time()
    kw = keyword_ranking_fts(q)
    kw_ms = (time.time() - t0) * 1000

    t1 = time.time()
    qv = np.asarray(MODEL.encode_query([q])[0], dtype="<f4")
    sims_arr = DOC_MAT @ qv
    sims = {IDS[i]: float(sims_arr[i]) for i in range(len(IDS))}
    sem = [IDS[i] for i in np.argsort(-sims_arr)[:ev.TOP_K]]
    sem_ms = (time.time() - t1) * 1000

    t2 = time.time()
    hy = ev.hybrid_search(q, kw, sims, CARDS_BY_ID)
    field_filters = ev.extract_field_filters(q, GAZETTEER)
    hy = ev.apply_field_filters(hy, CARDS_BY_ID, field_filters)
    abstained = ev.should_abstain(q, [(cid, 1.0) for cid in kw], sims, GAZETTEER)
    if abstained:
        hy = []
    hy_ms = (time.time() - t2) * 1000

    return {
        "query": q,
        "identifier_routed": ev.is_identifier_query(q),
        "field_filters": field_filters,
        "abstained": abstained,
        "tokens": ev.analyze(q),
        "keyword": {"cards": [card_view(c) for c in kw[:TOP_N]], "ms": round(kw_ms, 1),
                    "total": len(kw)},
        "semantic": {"cards": [dict(card_view(c), score=round(sims[c], 3)) for c in sem[:TOP_N]],
                     "ms": round(sem_ms, 1), "total": len(sem)},
        "hybrid": {"cards": [card_view(c) for c in hy[:TOP_N]], "ms": round(hy_ms, 1),
                   "total": len(hy)},
    }


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "")
        allow = origin if origin in ALLOWED_ORIGINS else "http://127.0.0.1:8000"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "cards": len(CARDS)}).encode("utf-8"))
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_POST(self):
        if self.path not in ("/chat", "/search"):
            self.send_response(404); self._cors(); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/search":
            result = run_search(payload.get("query", ""))
        else:
            result = run_turn(
                payload.get("question", ""),
                payload.get("history", []),
                payload.get("focus"),
                payload.get("prev_card_ids") or [],
                payload.get("conversation_memory"),
                bool(payload.get("dry_run")),
            )
        out = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass  # 조용히


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
