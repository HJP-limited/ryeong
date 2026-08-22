# 명함 에이전트 멀티턴 Challenge Set — Final50 v3

## 1. 목적

Final50 v3는 명함 검색 에이전트의 멀티턴 대화 성능을 고정된 조건에서 재현 가능하게 평가하기 위한
프로젝트 전용 challenge set이다.

이 데이터셋은 공개 벤치마크를 그대로 복제한 것이 아니다. 다음 공개 연구의 평가 관점을 참고해
명함 검색 도메인에 맞게 재구성했다.

- CoQA (Reddy et al., TACL 2019): 대화형 QA의 F1 기반 응답 평가 관점
- LoCoMo (Maharana et al., ACL 2024): 장기 대화 문맥 및 장거리 기억 평가 관점
- MultiWOZ / Dialogue State Tracking 연구: JGA 및 Slot Accuracy 기반 상태 추적 평가 관점
- Schema-Guided Dialogue (SGD): active intent / requested slots / slot values 형태의 구조화된 대화 상태 표현 관점

Final50 v3의 고정 challenge set과 동적 regression suite는 서로 목적이 다르므로
하나의 overall score로 합치지 않는다.

---

## 2. 데이터셋 구성

- 시나리오 수: 50개
- 총 user turn: 244개
- 최종 평가 turn: 50개
- 범주 수: 5개
- 각 범주: 10개
- 기준 명함 데이터: `cards_eval1000.json` 1,000장
- 각 시나리오당 evaluated target turn: 정확히 1개
- 임의의 제3자 명함 사실 주입: 사용하지 않음
- 모든 정답 개인정보: 실제 `cards_eval1000.json`의 target card 값으로부터 생성

### 범주

#### 1) `long_range_reactivation`
과거에 등장한 target 인물 뒤에 여러 실제 인물의 distractor turn을 배치한 뒤,
최근 대화의 최신 인물이 아닌 과거 target을 다시 참조하는 능력을 평가한다.

현재 서버는 최근 4턴(8개 메시지)을 원문으로 유지하고,
그보다 오래된 대화는 `history_digest`로 이동한다.

따라서 10개 시나리오를 다음 길이로 단계화했다.

- 6턴 × 2
- 8턴 × 2
- 10턴 × 3
- 12턴 × 3

각 evaluated turn의 `context_distance`는 각각 5 / 7 / 9 / 11 수준으로 구성되어
최근 원문 window 밖의 정보 회수까지 포함한다.

#### 2) `local_state_carryover`
하나의 실제 명함 인물을 중심으로 회사, 주소, 이메일 등의 정보를 연속해서 질의한 뒤
동일한 활성 대상을 유지하는지 평가한다.

#### 3) `explicit_target_correction`
사용자가 명시적으로
`A가 아니라 B`, `정정할게` 등의 표현으로 검색 대상을 수정한 뒤,
후속 대명사 표현이 수정된 target을 가리키는지 평가한다.

`correction`은 데이터셋 범주이며 별도의 프로젝트 전용 headline metric 이름으로 사용하지 않는다.

#### 4) `discourse_coreference`
둘 이상의 실제 인물이 등장한 뒤
`첫 번째 사람`, `처음에 물어본 사람` 등 담화상 지시 표현을 사용하여
최신 인물이 아닌 이전 target을 다시 참조하는 능력을 평가한다.

`coreference` 역시 데이터셋 범주이며 별도의 프로젝트 전용 headline metric 이름으로 사용하지 않는다.

#### 5) `unanswerable`
실제 target card에서 값이 비어 있는 필드를 질문한다.
존재하지 않는 정보를 생성하지 않고 답변 불가/정보 없음으로 처리하는지 평가한다.

---

## 3. Final50 v3 주 평가 지표

Final50 v3는 최종 evaluated turn의 응답 텍스트를 평가한다.

### Answer F1

- 적용 대상: answerable 40개 evaluated turn
- target card의 `gold_answer_values`를 `requested_fields` 순서로 이어 붙인 canonical gold text와
  모델 응답의 token overlap F1을 계산한다.
- CoQA 등 대화형 QA에서 널리 사용하는 F1 평가 방식을 참고했다.
- 단, 본 프로젝트는 자유서술 reference 답변 대신 실제 명함 필드값을 canonical gold text로 사용하므로
  CoQA 공식 평가 코드를 그대로 재현한 것은 아니다.

### Exact Match (EM)

- 적용 대상: answerable 40개 evaluated turn
- NFKC 정규화, 소문자화, 한글/영문/숫자 이외 문자 제거 후
  모델 응답과 canonical gold text가 완전히 동일한지 평가한다.
- 전화번호의 하이픈, 공백 등 표기 차이를 완화하기 위한 프로젝트 적응형 정규화가 포함된다.

### Unanswerable Accuracy

- 적용 대상: unanswerable 10개 evaluated turn
- 데이터셋에 정의된 답변 불가 표현(`expected_contains_any`) 중 하나를 포함하고,
  금지된 실제 값이나 금지 패턴을 생성하지 않았을 때 정답으로 처리한다.

### 보고 원칙

- Answer F1 / EM은 answerable turn만 평균한다.
- Unanswerable Accuracy는 unanswerable turn만 평균한다.
- 세 지표를 임의 가중 평균해 하나의 overall score로 합치지 않는다.
- 범주별 성능은 동일한 표준 지표를 category별로 나누어 보고한다.

---

## 4. 별도 dynamic regression suite 지표

`handoff-multiturn/scripts/eval_multiturn.py`는 Final50과 별개의 동적 regression suite다.
이 suite는 내부 상태와 검색 결과를 진단한다.

### 주 상태/검색 지표

- Joint Goal Accuracy (JGA)
- Slot Accuracy
- Slot Precision
- Slot Recall
- Slot F1
- Recall@5
- Mean Reciprocal Rank (MRR)

### 보조/운영 지표

- Hit@5
- Routing Accuracy
- checklist 통과율
- pass^k
- latency
- error rate

기존 코드에서 `R@5`로 계산되던
`gold 중 하나라도 top-5에 있으면 성공` 방식은 실제 Recall@5가 아니라 Hit@5이므로
v3 작업에서 명칭을 바로잡았다.

True Recall@5는 다음과 같이 계산한다.

`Recall@5 = |Gold ∩ Top5| / |Gold|`

MRR은 첫 번째 relevant result의 reciprocal rank를 scenario/turn에 대해 평균한다.

---

## 5. Fixed Final50과 dynamic regression suite의 역할 분리

### Final50 v3
- 고정 데이터셋
- 50개 scenario
- 50개 evaluated target turn
- 재현 가능한 최종 응답 비교
- 주지표: Answer F1 / Exact Match / Unanswerable Accuracy

### Dynamic regression suite
- 실행 시 실제 카드에서 scenario를 동적으로 구성
- 내부 상태 추적과 retrieval 회귀 진단
- 주지표: JGA / Slot Accuracy / Slot P-R-F1 / Recall@5 / MRR

두 평가 결과를 하나의 점수로 합치지 않는다.

---

## 6. 데이터 무결성

builder는 다음을 검증한다.

- scenario 수 = 50
- category별 10개
- evaluated turn 수 = 50
- scenario id 중복 없음
- 모든 source/target card id 존재
- target card가 source card 목록에 포함
- answerable gold가 실제 target card 필드값과 일치
- unanswerable target field가 실제로 비어 있음
- 임의의 제3자 사실 주입 없음

현재 canonical card fingerprint:

`760e980afda23a30a83b333861fb0b0eab74b704208a0bf75ab674259dd47e05`

fingerprint는 `id, name, company, title, department, location, phone, email, address`
선택 필드를 card id 순으로 정렬한 뒤 canonical JSON으로 직렬화하여 SHA-256을 계산한다.

---

## 7. 주요 파일

- `business_card_multiturn_benchmark_final50_v3.json`
- `business_card_multiturn_benchmark_final50_v3_annotations.json`
- `eval_benchmark_final50_v3.py`
- `../scripts/build_final50_v3.py`
- `../scripts/eval_multiturn.py`

---

## 8. 참고 자료

- Reddy, S., Chen, D., & Manning, C. D. (2019).
  *CoQA: A Conversational Question Answering Challenge.*
  Transactions of the Association for Computational Linguistics, 7, 249–266.
  https://aclanthology.org/Q19-1016/

- Maharana, A., Lee, D.-H., Tulyakov, S., Bansal, M., Barbieri, F., & Fang, Y. (2024).
  *Evaluating Very Long-Term Conversational Memory of LLM Agents.*
  ACL 2024.
  https://aclanthology.org/2024.acl-long.747/

- Kim, T., Yoon, H., Lee, Y., Kang, P., & Kim, M. (2022).
  *Mismatch between Multi-turn Dialogue and its Evaluation Metric in Dialogue State Tracking.*
  ACL 2022.
  https://aclanthology.org/2022.acl-short.33/

- Schema-Guided Dialogue Dataset.
  https://github.com/google-research-datasets/dstc8-schema-guided-dialogue

---

## 9. 해석 시 주의사항

Final50 v3는 공개 benchmark를 그대로 재현한 것이 아니라,
공개 benchmark의 평가 관점을 명함 검색 에이전트에 맞게 적용한 프로젝트 전용 challenge set이다.

따라서 다음 표현을 사용하지 않는다.

- "LoCoMo 공식 long recall metric"
- "MultiWOZ 공식 correction accuracy"
- "공식 entity resolution accuracy"
- "Final50 overall benchmark score"

대신 공개 연구에서 널리 쓰이는 평가 단위와 지표를 참고했다고 명시하고,
프로젝트에서 추가한 category 설계와 정규화 방식은 별도로 구분해 설명한다.
