# 2026-08-26 ~ 08-29 유실 수정 내용

`ymj-hybrid-search-rag-db-aligned` 로컬 클론이 2026-09-07에 삭제되면서, 원격
(`HJP-limited/ryeong`, `3cdc1503` = 2026-08-26)보다 앞서 있던 **31개 커밋이 유실**됐다.
이 폴더는 그 작업을 세션 기록(`689e27cd`)에서 복원한 것이다.

**이 스크립트들은 "그대로 실행하는 패치"가 아니라 "무엇을 어떻게 고쳤는지의 명세"로 읽어야 한다.**
31개 커밋이 사슬로 이어져 있고 중간 단계 일부는 복원 대상에서 빠졌기 때문에, 8/26 기준본에
순서대로 적용하면 앵커 텍스트가 맞지 않아 실패하는 것이 있다(아래 표).

---

## 유실된 제품 코드 수정 4건

### 1. 정정 어순 버그 — 유일하게 측정 효과가 확인된 수정

| | |
|---|---|
| 커밋 | `fc08c03` 수정 · `2e0de8a` 효과 확정 |
| 증상 | **정정 대상이 앞에 오면 버릴 이름 대신 대상을 지웠다.** "X씨 직급 말한 거야. Y씨 말고" → X를 버림 |
| 원인 | 옛 이름 삭제가 **위치 기준**(`ordered[:-1]`)이었다 |
| 수정 | 거절 표지(말고/아니라/정정)에 붙은 이름을 '버릴 이름'으로 잡고, 삭제는 위치가 아니라 **대상 여부**로 판정 |
| 범위 | 앱 `MainActivity.resolveCorrection` + 서버 `resolve_correction` (양쪽 동시) |
| 추가 정제 | 정정 뒤의 요청 문장을 고를 때 **무조건 마지막 문장을 쓰지 않고 '요청이 담긴 문장'을 고른다** (8/26 07:27~07:30) |
| **측정 효과** | **같은 동결본에서 체크리스트 0.950 → 1.000, 실패 6/6 전부 해소** |

관련 파일: `fix_correction.py`, `fix_correction2.py`, `correction-refinements.json`

### 2. 동명이인 유지

| | |
|---|---|
| 커밋 | `d8cafc7` "동명이인을 되부를 때 앞에서 정한 사람에 머문다" |
| 증상 | 동명이인을 다시 부르면 앞 턴에서 정한 사람이 아닌 쪽으로 튄다 |
| 수정 | `AgentSession`에 **"이름=카드id" 목록**을 기억 칸으로 추가 — 이 대화가 동명이인을 어느 쪽으로 정했는지 기억한다. `KEY_SUBJECT_HISTORY` 바로 다음에 삽입 |
| 범위 | `AgentSession.kt` + 서버 미러 |

관련 파일: `kt_twin.py`(Kotlin), `twin.py`(파이썬), `kt_twin_tests.py`(테스트), `probe_twin.py`

### 3. 회사명을 검색 조건으로 사용

| | |
|---|---|
| 커밋 | `fd011ce` "회사명을 검색 조건으로 쓴다 — 가제티어에 회사 핵심어를 넣는다" |
| 증상 | 회사명을 말해도 검색 조건으로 걸리지 않는다 |
| 수정 | 가제티어에 **회사 핵심어**를 넣고, 이름·직함·지역으로 이미 claim된 토큰을 제외한 나머지 중 `gazetteer.company_terms`에 있는 토큰을 회사 조건으로 사용 |
| 범위 | `eval_search.py` / `hybrid_server.py` / `CardGazetteer.kt` |

관련 파일: `company.py`(파이썬 필터), `kt_company.py`(Kotlin), `company_exact.py`(정확 일치 강화)

### 4. 주제 전환 결함 2건 — **유실이 아니었다 (2026-09-08 정정)**

| | |
|---|---|
| 커밋 | `fdcaeba` "턴 깊이별 분해 + 주제 전환 결함 2개 수정(주어 이어받기 · 직전 답 복사)" |
| 증상 | 주제가 바뀔 때 ① 앞 주어를 잘못 이어받고 ② 직전 답을 그대로 복사한다 |
| **실제 상태** | **원격 `3cdc150`(8/26)에 이미 들어 있다.** 복원할 것이 없다 |

처음에는 이 문서에 "미복원"으로 적었으나, 세션 기록을 전수 검색해 정정했다:

- `carryOverAttribute` · `KEY_LAST_ATTRIBUTE` 작업은 **2026-08-14**에 이뤄졌고
  (8/15에 `CLAUDE.md`·`README` 반영까지) 컷(8/26 01:41)보다 12일 앞선다 → 원격에 푸시된 상태
- 확인: 원격본 `MainActivity.kt` 에 `carryOverAttribute` 2곳, `AgentSession.kt` 에
  `KEY_LAST_ATTRIBUTE` 존재
- `fdcaeba` 는 그 제품 수정을 8/26에 커밋 메시지로 정리한 것이거나 시험지 정비였다.
  같은 커밋의 "턴 깊이별 분해" 부분은 `rebalance.py`(eval_multiturn.py 수정)로 복원됐다
- `rebalance.py` 안의 "주제 전환" 언급은 **다른 유형(되돌아오기·무명 지시)을 설명하며
  비교로 적은 주석**이었다 — 이걸 수정 코드로 오독했던 것이다

**결론: 제품 코드에 남은 유실분은 없다.**

---

## 보너스 — 검색 동결셋 생성기가 함께 복원됐다

`build_search_bench.py` + `frozen_search.py` = **동결 검색 시험지(317문항) 생성기**.
유실 목록에 있던 항목이라 별도로 재작성할 필요가 없어졌다.

이 스크립트의 주석에 **지표 해석에 중요한 실측 기록**이 남아 있다:

> 실측: S2·S3 를 넣자 183 → 282 질의가 됐고 R@5 0.930 → 0.951 이 됐다.
> **성능이 오른 게 아니라 시험지가 바뀐 것이다.**

→ `성능지표_2026-09-08.md`의 검색 절에 이 단서를 반영했다. R@5 0.951을 8월 이전 값과
직접 비교하면 안 된다.

---

## 8/26 기준본 적용 검증 결과

원격 `3cdc1503`을 임시 clone해 시간순으로 적용해 본 결과:

| 스크립트 | 결과 | 비고 |
|---|---|---|
| `fix_correction.py` | ❌ | `MainActivityTest.kt` 앵커 없음 — 8/26 이전 선행 커밋 필요 |
| `fix_correction2.py` | ❌ | `fix_correction.py` 적용 결과를 전제 |
| `company.py` | ✅ | 회사 필터 정상 적용 |
| `twin.py` | ❌ | `"subject_history": []` 앵커 없음 |
| `chain.py`, `chain_search.py`, `probe_twin.py` | — | **패처가 아니라 서버로 요청을 보내는 프로브**다. 검증 대상 아님 |
| `kt_company.py` | ❌ | `KeywordSear…` 앵커 없음 |
| `kt_twin.py` | ❌ | `searchService.searchHybrid` 앵커 없음 |
| `kt_tests.py` | ❌ | 앵커 없음 |
| `kt_twin_tests.py` | ✅ | 동명이인 테스트 적용 |
| `company_exact.py` | ❌ | 앵커 없음 |

### 그런데 실제로는 401줄이 적용됐다

패처 스크립트는 파일을 순서대로 고치다가 중간에서 실패하므로, **실패한 스크립트도 앞부분은 이미 적용한다.**
결과적으로 7개 파일이 바뀌었다:

```
 app/src/main/java/com/example/hjp/MainActivity.kt            |  66 ++++++-
 app/src/main/java/com/example/hjp/agent/AgentSession.kt      |  30 ++++
 app/src/main/java/com/example/hjp/search/CardGazetteer.kt    |  64 ++++++-
 app/src/test/java/com/example/hjp/MainActivityTest.kt        | 104 ++++++++++
 app/src/test/java/com/example/hjp/search/CardGazetteerTest.kt|  55 ++++++-
 scripts/eval_search.py                                       |  83 ++++++-
 scripts/hybrid_server.py                                     |  11 ++-
 7 files changed, 401 insertions(+), 12 deletions(-)
```

이 상태를 **`partial-apply-on-3cdc150.patch`** 로 저장해 뒀다(627줄).

⚠️ **이 패치는 부분 적용본이다.**
- 파이썬 2개 파일은 **구문 검증 통과**(`ast.parse`)
- **Kotlin은 컴파일 검증하지 않았다** — Android SDK/모델 에셋이 없는 임시 clone이라 빌드를 돌리지 못했다
- 여러 스크립트가 중간에 끊긴 **혼합 상태**이므로, 그대로 병합하지 말고 `git apply` 후 파일별로 검토할 것

**결론**: 사슬 전체를 자동 복원하는 것은 불가능하다. 대신 위 4건의 **수정 내용(무엇이 왜 틀렸고
어떻게 고쳤는지)** 이 이 문서에 남아 있고, `fix_correction.py` 계열에는 **앵커 텍스트(수정 전 코드)와
교체 텍스트(수정 후 코드)가 그대로 들어 있어** 어느 줄을 어떻게 바꿨는지 읽을 수 있다.
자동 적용이 아니라 **읽고 손으로 옮기는 방식**을 권한다.

---

## 우선순위 권고

1. **정정 어순 수정(1번)** — 측정 효과가 확인된 유일한 수정이다. 8/26본에서 계속 개발하면 이것부터 다시 넣는다
2. **회사명 검색 조건(3번)** — `company.py`가 8/26본에 그대로 적용된다
3. 동명이인(2번) — 표본이 작아(채점 n=6) 효과 측정이 어렵다. 여유 있을 때
   (4번 주제 전환은 유실이 아니었다 — 위 정정 참조)
4. 검색 동결셋 생성기 — 지표를 다시 재려면 필요. 지금 지표는 이미 기록돼 있어 급하지 않다
