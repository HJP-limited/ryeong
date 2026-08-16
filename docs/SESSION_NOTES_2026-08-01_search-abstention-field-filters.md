# 세션 정리 — 검색 가제티어 기권, 필드 하드 필터, 검색 탭 신설 (2026-08-01)

브랜치: `llm-integration-work` (origin: `HJP-limited/ryeong`, main 아님)

이 문서는 이 저장소(내 것) 안에서 이번 세션에 실제로 끝난 작업만 정리한다. 다른 세션이나
다른 LLM이 이어받았을 때 "왜 이렇게 했는지"를 다시 설명 안 해도 되게 하는 게 목적이다.
이전 세션 정리는 `docs/SESSION_NOTES_2026-07-24_gemma4-hybrid-search.md` — 그 문서의 연속.

멀티턴은 이번 세션에 아직 제대로 손 못 댔다 — 자세한 건 4절 참고.

## 1. Python (`scripts/hybrid_server.py`, `scripts/eval_search.py`) — 커밋 안 됨

`scripts/hybrid_server.py`:
- **대화형 후속 발화 처리**: `"5명인데?"`, `"그 사람들 이름 알려줘"` 같이 재검색할 내용이 없는
  발화를 감지해서, 새로 검색하지 않고 **직전 턴의 카드 id(`prev_card_ids`)를 그대로 근거로
  재사용**한다.
  - 왜 필요했나: 이 발화를 검색어로 그대로 쓰면 하이브리드 검색이 엉뚱한 카드를 물어와서
    대화가 끊겼다(실측: "판교에서 일하는 사람 몇명이지?" → "5명인데?"에 충청북도 무관 인물이
    튀어나옴).
  - `run_turn(question, history, focus, prev_card_ids)`가 이 분기를 처리하고
    `conversational_followup: true`, `card_ids`를 응답에 포함.
- **LLM 전원 거절 권한 명시**: 검색 결과가 있어도 "조건에 맞는 사람이 하나도 없다"고 LLM이
  답할 수 있게 프롬프트에 명시적으로 허용. 이게 없으면 이름이 우연히 비슷한 사람을 억지로
  답으로 골랐다(실측: "우주비행사 찾아줘" → 이름에 '우주'가 든 '장우주'를 답).
  - `NO_MATCH_PHRASE = "조건에 해당하는 명함을 찾지 못했습니다."`가 답변에 포함되면 백엔드가
    카드 목록도 함께 비운다(`llm_rejected` 플래그).
  - **주의**: 프롬프트 규칙 수를 늘릴수록 2B 모델 준수율이 떨어지는 걸 반복 실측했다. 지금
    버전(4개 규칙, 무관 판정 규칙을 맨 뒤에 배치)이 8개 수동 시나리오 중 7개를 통과하는 현재
    최선이다. `"AI 다루는 사람 있나"`에 이름 대신 "총 2명"이라 답하는 문제 하나가 남아있고,
    규칙을 더 만지면 다른 게 깨지는 게 반복 확인됐다 — **더 손대지 말고 이 상태를 유지할 것**.
- `rag_context()`가 `"검색 후보: 총 N명"` 헤더 + `[N번]` 번호를 붙인다 — 2B 모델이 카드
  개수를 직접 세다가 틀리는 문제(실측: 5장인데 "4명입니다") 대응.
- `/search` 엔드포인트 신설 — LLM 호출 없이 키워드/시맨틱/하이브리드 3축을 그대로 비교(검증용).

`scripts/eval_search.py`의 `Gazetteer.looks_like_person_name()`:
- 호칭 없는 맨 이름("정하은")도 기권 대상으로 잡되, **"데이터에 있는 성 + 데이터에 있는 이름
  조합인데 명단엔 없는 경우"**로만 좁게 잡는다.
- 처음엔 "아는 성으로 시작하는 3자 한글"로 넓게 잡았더니 기권 정확도는 0.158→0.421로 올랐지만,
  서커스·공무원·임원급·조련사·조종사가 전부 이름으로 오탐되어 개념형 R@5가 0.660→0.630으로
  떨어지는 걸 실측으로 확인하고 **폐기**했다. 지금 최종 조건(성+이름 둘 다 알려진 값)은 오탐
  0건에 R@5 0.918을 유지하는 대신, 기권 정확도는 **0.158로 되돌아갔다**(트레이드오프를 개념형
  recall 쪽으로 결정한 것 — 아래 최종 지표 참고). 실제 채팅에서는 이거 하나로 다 못 잡는
  케이스(존재하지 않는 "직업")를 `hybrid_server.py`의 LLM 전원거절 경로가 별도로 보완한다.

### 최종 오프라인 평가 지표 (204개 질의, `scripts/eval_search.py` 실행 결과, 이 세션 마지막
실행분 — 위 폐기된 중간 버전이 아니라 이 수치가 현재 코드 상태다)

랭킹 평가 185개(기권 대상 제외) / 기권 평가 19개. 4개 시스템 비교:

| 지표 | 키워드 전용 | 시맨틱 전용 | 하이브리드(RRF, 기존) | **하이브리드(라우팅+기권, 개선)** |
|---|---|---|---|---|
| Recall@1 | 0.870 | 0.600 | 0.724 | **0.886** |
| Recall@5 | 0.891 | 0.644 | 0.916 | **0.918** |
| Recall@20 | 0.899 | 0.715 | 0.942 | **0.941** |
| Precision@5 | 0.526 | 0.356 | 0.439 | **0.682** |
| nDCG@5 | 0.882 | 0.619 | 0.846 | **0.906** |
| MRR | 0.887 | 0.658 | 0.848 | **0.928** |
| 개념형(easy) R@5 | 0.733 | 0.853 | 0.867 | 0.867 |
| 개념형(hard) R@5 | 0.300 | 0.650 | 0.660 | 0.660 |
| 이름 P@5 | 0.477 | 0.450 | 0.455 | **1.000** |
| 전화 P@5 | 1.000 | 0.000 | 0.233 | **1.000** |
| 기권 정확도(no-result) | 0.684 | 0.000 | 0.000 | 0.158 |

원본 출력 전문: 세션 스크래치패드 `eval_v9.txt`(휘발성 디렉터리 — 보존하려면 저장소로 복사할
것. 이 표가 그 파일의 최종본을 옮겨 적은 것).

읽는 법:
- 이름/전화(정답 보통 1개)는 MRR·R@1이 핵심 — 개선판이 이름 P@5 0.455→1.000, 전화 P@5
  0.233→1.000으로 개선(필드 하드 필터 + 식별자 라우팅 효과).
- 개념형(정답 다수, LLM에 후보 넘기는 용도)은 R@5+P@5 — hard 개념형은 0.660에서 안 움직임
  (이번 세션 변경이 이 축엔 영향 없었다는 뜻).
- 기권 정확도 0.158은 가제티어 단독 판정 기준. 위 문단에서 설명한 대로, 이걸 0.421까지 올리는
  방법은 있지만 개념형 R@5를 깎아먹어서 **의도적으로 선택하지 않았다.**

**이 표가 이 프로젝트의 공식 벤치마크 기준이다.** 진짜 EmbeddingGemma 300M(온디바이스와 동일
모델/프롬프트)로 뽑은 수치이므로, 앞으로 검색 품질을 얘기하거나 회귀를 확인할 땐 이 표를
기준으로 비교할 것.

`gemma-chat.html` (세션 스크래치패드, `localchat/gemma-chat.html`, :8000에서 서빙):
- 탭 2개 추가: "채팅 (검색+Gemma)" / "검색만 (LLM 제외)". 검색만 탭은 `/search`를 호출해
  3축을 나란히 보여준다.
- `prev_card_ids` 왕복, `conversational_followup`/`llm_rejected` 배지 표시.

**검증 방법**: 로컬 3개 서버(:8000 페이지, :8100 하이브리드 백엔드, :9379 Gemma 서버)를 계속
띄워두고 `verify_*.py` 스크립트로 curl 대신 실제 HTTP 왕복을 찍어서 확인했다. 서버 재시작
절차: `HJP_TEST_CARDS=data/cards_test.json python scripts/hybrid_server.py`.

## 2. Kotlin (`app/src/main/java/com/example/hjp/`) — 커밋 안 됨

Python에서 검증한 규칙을 같은 저장소의 Kotlin 앱에도 이식했다.

신규 파일:
- `search/CardGazetteer.kt` — Python `Gazetteer`/`should_abstain`/`extract_field_filters`의
  Kotlin 대응. `FieldFilters` data class, `shouldAbstain()`, `extractFieldFilters()`,
  `applyFieldFilters()` 최상위 함수 포함.
- `agent/AgentSession.kt` — **잠정 구현.** README에 적힌 규격(`[conversation_summary]`/
  `[recent_conversation]`/`[current_user]`/`[tool_session_context]`, 8개 메시지 윈도우, 3000자
  summary)을 보고 재구현한 것으로, 아직 검증된 최종 버전이 아니다. 멀티턴은 4절 참고.
- `agent/ConversationalFollowup.kt` — Python `is_conversational_followup()`의 Kotlin 대응.
- `app/src/test/java/com/example/hjp/search/CardGazetteerTest.kt` — Python과 같은 테스트
  데이터(`data/cards_test.json`)로 같은 기대값을 검증하는 JVM 단위 테스트 17개. 전부 통과.

수정 파일:
- `search/CardSearchService.kt` — `searchHybrid()`/`searchKeywordOnly()`에 식별자 라우팅,
  필드 필터, 기권 적용. `RRF_K=60`, `FUSION_POOL=40`을 Python 상수와 동일하게 맞춤(주석에
  "동기화 유지 필요" 명시). 가제티어는 카드 5000장 기준 비용이 커서 `CardGazetteer` 인스턴스를
  캐시하고 카드가 바뀔 때만 무효화.
- `MainActivity.kt` — `runChat()`이 세션 기반으로 재작성됨, 기권 시 LLM 미호출, LLM
  전원거절 시 카드 비우기(`narrowByAnswer()`), `SearchSummary` composable에 기권/필터/
  후속발화 배지 추가.
- `agent/tools/SearchBusinessCardsTool.kt` — 기권을 "검색 실패"가 아니라 "그런 사람 없음"으로
  에이전트 도구 응답에 명시(안 그러면 LLM이 재시도하거나 비슷한 이름으로 답을 지어낸다).

**빌드 이슈**: OneDrive 동기화 폴더 안에서 빌드하면 `app/build/intermediates/merged_native_libs`
가 OneDrive에 의해 읽기전용 placeholder가 되어 `AccessDeniedException`이 난다. 해결: 해당
폴더의 속성을 `Normal`로 바꾼 뒤 삭제하고 재빌드.
```powershell
Get-ChildItem $path -Recurse -Force | % { $_.Attributes = 'Normal' }; Remove-Item -Recurse -Force $path
```

**검증**: `:app:testDebugUnitTest` 24개(`CardGazetteerTest` 17 + 기존
`KeywordSearchRankerTest` 6 + `ExampleUnitTest` 1) 전부 통과, `:app:assembleDebug` 성공.

## 3. 남겨둔 채팅 품질 이슈 (Python, 손대지 말 것 — 반복 실측으로 확인된 트레이드오프)

- `"AI 다루는 사람 있나"`에 이름 나열 대신 "총 2명"이라 답하는 문제 — 프롬프트 규칙을
  조정해봤지만 다른 케이스가 깨져서 롤백함. 2B 모델의 한계로 판단, 추가 프롬프트 튜닝보다 더
  나은 방법(예: 답변에 이름이 없으면 후처리로 카드 목록을 그대로 보여주는 것으로 이미 부분
  완화됨)이 필요하면 논의.

## 4. 아직 안 한 것

- **멀티턴이 아직 제대로 구현되지 않았다.** `agent/AgentSession.kt`는 README 설명만 보고 만든
  잠정 구현이고, 검증된 최종 버전이 아니다. 어떤 방향으로 완성할지는 다음 세션에서 다시 논의
  필요 — 세부 사항은 저장소 밖(별도 소스) 검토가 필요한 부분이라 이 문서엔 적지 않는다.
- **커밋/푸시 안 됨**: 사용자가 "test 좀 해보고 개선하다가 마무리 되면 커밋할게 그때 되면
  말해줘"라고 한 바 있음 — 사용자가 명시적으로 말할 때까지 커밋하지 말 것.

## 5. 참고 — 검증에 쓴 도구/경로

- 세션 스크래치패드: `verify_*.py`, `eval_v*.txt`, `localchat/gemma-chat.html` 등이 있는
  임시 디렉터리. **세션이 끝나면 사라질 수 있으므로** 보존해야 할 게 있으면 저장소로 옮길 것.
- 로컬 3서버: :8000(페이지), :8100(hybrid_server.py), :9379(Gemma litert-lm serve). 재시작
  시 `HJP_TEST_CARDS=data/cards_test.json python scripts/hybrid_server.py`.
