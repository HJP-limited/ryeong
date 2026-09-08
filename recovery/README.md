# company-followup-feature.patch

"그 회사 다니는 사람" 같은 회사-엔티티 후속질문 처리 기능. 원래
`ymj-hybrid-search-rag-db-aligned`(포크 클론, origin `HJP-limited/ryeong`)의
커밋 `6b54215`에서 코드 부분만 추려냈다(벤치 결과 파일은 뺐다).

## 내용
- `app/src/main/java/com/example/hjp/MainActivity.kt` — `focusCompany` 추적,
  "그 회사"가 속성이 아니라 엔티티(다니다/근무/재직/일하다/사람/직원/동료)를
  가리킬 때만 회사명으로 치환. 대명사 치환 순서를 길이순으로 정렬.
- `app/src/main/java/com/example/hjp/agent/AgentSession.kt` — `KEY_FOCUS_COMPANY` 키 추가
- `app/src/test/java/com/example/hjp/MainActivityTest.kt`, `AgentSessionTest.kt` — 대응 테스트
- `scripts/hybrid_server.py` — 같은 로직 파이썬 쪽 포팅(`COMPANY_ENTITY_FOLLOWUP_RE`)
- `bench/manual_ui/index.html` — 수동 점검용 채팅 UI

## 검증 상태 (2026-09-07)
- 자동 회귀 벤치(`eval_search.py`, `eval_multiturn.py --generate`): 회귀 없음,
  기존 지표 오차범위 내 유지
- 수동 스모크 테스트: "사여름씨 회사가 어디야?" → "그 회사 다니는 다른 사람 있어?"
  → 질의가 "(주) 다이나믹스튜디오 다니는 다른 사람 있어?"로 정확히 치환되고
  같은 회사 동료를 찾아냄

## 적용 방법
실제 앱 코드베이스에서:
```
git apply company-followup-feature.patch
```
(경로가 다르면 `git apply -p1 --directory=<대상경로>` 등으로 조정)

## 원본
원본 클론(`ymj-hybrid-search-rag-db-aligned`)은 사용자 소유가 아닌 포크라
2026-09-07 디스크 정리 중 삭제했다. `origin/llm-integration-work`까지의
이력은 GitHub(`HJP-limited/ryeong`)에 그대로 남아있다.

## 함께 보기 — `recovered-2026-08/`

삭제된 클론에는 원격보다 앞선 **31개 커밋(2026-08-26~08-29)** 이 있었고, 그것도 함께 유실됐다.
그 작업을 세션 기록에서 복원한 것이 `recovered-2026-08/` 폴더다:

- **`FIXES.md`** — 유실된 제품 코드 수정 4건이 무엇이었고 왜·어떻게 고쳤는지. **먼저 읽을 문서**
- `fix_correction*.py`, `company*.py`, `twin.py`, `kt_*.py` — 당시 실제로 사용한 패치 스크립트 전문
- `build_search_bench.py`, `frozen_search.py` — 검색 동결셋(317문항) 생성기
- `partial-apply-on-3cdc150.patch` — 위 스크립트를 8/26 원격본에 적용해 실제로 붙은 401줄
  (⚠️ 부분 적용본 · Kotlin 컴파일 미검증)
