# 세션 정리 — Gemma 4 전환, 멀티턴, 하이브리드 검색 A/B, 앱 반영 (2026-07-23 ~ 07-25)

브랜치: `llm-integration-work` (origin: `HJP-limited/ryeong`, main 아님)

이 문서는 이 기간 동안 한 작업, 발견한 문제, 내린 결정과 근거, 그리고 아직 안 끝난 것을 정리한다.
다른 세션/팀원이 이어서 작업할 때 "왜 이렇게 했는지"를 다시 설명 안 해도 되게 하는 게 목적이다.

---

## 1. 채팅 모델: Gemma 3 1B → Gemma 4 E2B

### 무엇을 왜
- 채팅(RAG 답변) 모델을 `gemma3-1b-it-int4.litertlm`(529MB)에서 `gemma-4-E2B-it.litertlm`(2.5GB)로 교체.
- 이유: "돌아가는 것 중 가장 성능 좋은 모델"이 목표였고, Gemma 4가 Gemma 3보다 전 영역(한국어 품질, 지시 준수, **툴콜링**)에서 세대가 다름.
- 출처: `litert-community/gemma-4-E2B-it-litert-lm`의 **generic 빌드**(칩셋 전용 아님) — 팀이 EmbeddingGemma 선택 때 썼던 것과 같은 기준.
  - 다른 후보였던 `google/gemma-4-E2B-it-qat-mobile-transformers`/`-mobile-ct`는 **HF Transformers/compressed-tensors 포맷**이라 이 앱(LiteRT-LM 엔진)과 호환 안 됨 — 확인 후 배제.
- Gemma 3 1B/270M은 `LlmRole.Chat.fileNames`에 fallback으로 남겨둠.

### 상한선 판단 (E4B는 왜 안 썼나)
- Gemma 4 E4B: 파일 3.66GB, 구글 공식 벤치마크 CPU 백엔드 RAM 3.28GB — S21(가용 RAM ~2~3.7GB)엔 위험 부담이 큼.
- E2B가 이 기기의 실질적 상한선으로 판단.

### 관련 파일
`LiteRtLmChatEngine.kt`, `MainActivity.kt`, `CLAUDE.md`, `MODEL_SETUP_STATUS.md`, `EMBEDDING_MIGRATION_NOTES.md`, `REAL_DEVICE_TEST.md`, `scripts/install_real_device_debug.ps1`

---

## 2. 멀티턴 대화 — 세 번의 반복

### 2-1. 1차: Conversation 재사용 (초기 구현, 폐기)
- 기존 코드는 질문마다 `engine.createConversation()`을 새로 만들어 즉시 닫음 → 이전 대화를 전혀 기억 못 함(사용자가 실기기에서 직접 발견).
- 1차 수정: `generateWithHistory()`를 추가해 **세션 동안 Conversation을 재사용**(KV 캐시로 기억 유지), "새 대화" 버튼으로 리셋. `maxNumTokens` 640→2048.
- **폐기 이유**: 실기기 테스트에서 "그 사람 전화번호는?" 같은 후속 질문마다 **새로 하이브리드 검색**을 하는데, 대명사만으로는 엉뚱한 카드가 검색돼 그게 컨텍스트로 주입되면서 **Conversation의 기억을 덮어버림** (강건우 얘기 중 "그 사람 직급?" → 엉뚱한 "옹현"이 검색되어 옹현 얘기를 함).

### 2-2. 2차: LLM 기반 쿼리 재작성 (history-aware query rewriting, 폐기)
- 후속 질문을 Gemma에게 "독립형 질문으로 재작성"시킨 뒤(예: "그 사람 직급?" → "강건우 직급?") 그걸로 재검색.
- **폐기 이유**: 소형 모델이 재작성 시 **앞 턴 문장 구조를 베낌** — "옹현은 어디 살아?"(직전 턴이 "~ 어느 회사에 다녀?")를 "옹현은 어느 회사에 다녀?"로 잘못 재작성. 사용자가 로그로 직접 지적해서 발견.

### 2-3. 3차: 결정적 focus 치환 (현재 채택)
- LLM 재작성을 버리고, **직전 검색 결과 최상위 카드의 이름(`focusPerson`)을 상태로 추적**해서 문자열 치환.
- 대명사("그 사람", "걔", "그 회사" 등)가 있으면 `focusPerson`으로 치환.
- **생략형 후속**("메일은?", "직급은?" 처럼 대명사 없이 속성 명사로만 시작)도 `ATTRIBUTE_NOUNS` 목록으로 감지해 `focusPerson`을 앞에 붙임.
- 새 이름으로 시작하는 질문은 그대로 둠(새 인물로 전환).
- 구현: `MainActivity.kt`의 `resolveSearchQuery()`, `FOLLOWUP_PRONOUNS`, `ATTRIBUTE_NOUNS`. `focusPerson`은 매 턴 검색 결과 1등 카드 이름으로 갱신.

### 2-4. 3차 구현에서 발견된 미해결 버그 (다음 작업 대상)
사용자가 로컬 채팅으로 여러 턴을 빠르게 쳐보다가 발견. **아직 코드 수정 안 함.**

| # | 증상 | 원인 | 비고 |
|---|---|---|---|
| A | "강서연**씨** 찾아줘"가 검색 실패 | 존칭(씨/님)을 토큰에서 안 뗌 → 키워드가 "강서연씨"로 검색되어 매칭 실패 → 시맨틱만 동작 → 유사 이름(강서영)이 1등으로 잘못 올라옴 | `KeywordSearchRanker.particles`에 씨/님 없음 |
| B | focus가 자꾸 엉뚱한 사람으로 잡힘 | `focusPerson = 검색결과 1등 카드`인데, 이름 검색은 유사 이름이 1등으로 뜨는 경우가 많음(A의 결과로 focus가 "강서영"이 됨) | focus는 "1등 카드"가 아니라 "질문이 실제로 지목한 이름"이어야 함 |
| C | "번호 뒷자리가 4312인 분"처럼 **새 검색값이 있는 질문**도 생략형으로 오인 | `ATTRIBUTE_NOUNS`가 "번호"로 시작하면 무조건 focus를 붙임 → "서은영 번호 뒷자리 4312"로 검색되어 진짜 대상을 못 찾음 | 질문에 숫자/새 고유값이 있으면 생략형 판정을 하지 말아야 함 |

**다음 수정 방향(합의됨, 미구현)**:
1. 존칭(씨/님)·복합조사 보강
2. focus를 "1등 카드"가 아니라 "질문이 명시한 이름 우선, 없으면 유지"로
3. 생략형 판정에 "질문에 숫자/신규값이 있으면 새 검색으로 처리" 예외 추가
4. (근본 해결책으로 검토만 함, 안 채택) LLM 기반 쿼리 이해(self-query) — 매 턴 LLM 호출이 추가돼 폰에서 느려짐. 이 앱은 폐쇄 도메인(이름/지역/직급 값이 유한)이라 **가제티어(사전) 매칭**이 정석이라는 결론.

### 2-5. ragContext 확장
- `BusinessCardEntity.ragContext()`에 phone/email/address 추가 — 원래 없어서 "전화번호는?" 질문에 검색은 맞아도 LLM이 답을 못 내는 문제가 있었음.

---

## 3. 실기기(갤럭시 S21, SM-G991N, Android 15, arm64) 검증

### adb/한글 입력 셋업
- USB 디버깅과 USB 테더링은 다른 기능(사용자가 혼동) — 개발자옵션의 USB 디버깅이 맞음.
- `adb input text`는 한글을 못 보냄(URL-encode 문자 그대로 입력됨) → **ADBKeyboard**(github.com/senzhk/ADBKeyBoard) 설치해서 `ADB_INPUT_B64`(base64) 브로드캐스트로 해결. 공백 있는 문자열은 `ADB_INPUT_TEXT`(plain)로 보내면 공백 기준으로 인자가 쪼개져 실패함 — 항상 base64 경로 사용.

### 메모리
- S21 총 RAM ~7GB, 앱 실행 중 가용 메모리 ~2.1GB로 매우 빠듯.
- Gemma 4 E2B 로드 시 **GPU 백엔드 실패**(`LitertLmJniException`: `libvndksupport.so` 없음, OpenCL 부재) → 코드의 자동 폴백으로 **CPU 백엔드**(~1.7GB) 사용. 이 과정에서 시스템이 다른 앱(카카오톡, 토스 등)을 대량 강제종료 + 스왑 압박 발생.
- 그래도 **크래시 없이 로드+생성 성공** — 결론: 이 기기에서 "느리지만 동작".

### 임베딩 파일 함정 (중요, 재발 방지용 기록)
- 처음 push한 `embeddinggemma_quant.tflite`(191,474,704B)가 사실 **`embeddinggemma-300M_seq256_mixed-precision.google.tensor_g5.tflite`**(구글 Tensor G5 NPU 전용 빌드)였음 — `legacy/` 폴더에 잘못 들어있었던 것으로 추정.
- 증상: `E/tflite: Encountered unresolved custom op: DISPATCH_OP` → 임베더 초기화 실패 → 검색이 키워드 전용으로 폴백.
- 해결: **올바른 generic 빌드** `embeddinggemma-300M_seq256_mixed-precision.tflite`(179,131,736B, MODEL_SETUP_STATUS의 "179MB"와 일치)로 교체.
- 이 파일은 **gated 저장소**(`litert-community/embeddinggemma-300m`)라 `~/.cache/huggingface/token`으로 인증 다운로드 필요했음.
- 앱이 기대하는 파일명: `embeddinggemma-300m.tflite` + `sentencepiece.model`.

### 실기기 확인된 것
- Gemma 4 E2B 로드 + 한국어 생성 성공
- 하이브리드 검색 동작 확인 (`retrieval: room_fts_plus_embeddinggemma_rrf`)
- 멀티턴 1차 수정(대명사 치환) 기본 동작 확인 (단, 2-4절의 버그는 그 이후 로컬 테스트에서 발견됨 — 아직 재검증 안 됨)
- 첫 응답 30~80초, 이후 20~30초(모두 CPU 백엔드 기준)

---

## 4. 데스크톱에서 실기기 없이 검증하는 방법

### litert-lm CLI
- 구글 공식 CLI(`uv tool install litert-lm`)가 Windows CPU/GPU를 네이티브 지원 — 폰 없이 `.litertlm` 모델을 노트북에서 직접 실행 가능.
- `litert-lm run <model> --backend cpu --prompt "..."` — 단발 생성
- `litert-lm serve --host 127.0.0.1 --port 9379 [--cors-origin ...]` — OpenAI 호환 API, `litert-lm import`로 등록한 모델 서빙. **멀티턴 검증엔 이쪽을 써야 함**(interactive `run`은 stdin 파이프 여러 줄 시 "Failed to parse message JSON"으로 실패).
- 콘솔 한글 출력이 cp949로 깨짐 → 파일로 리다이렉트 후 `data.decode('cp949')`로 읽어야 함.
- 데스크톱 CPU 실행 시 모델 옆에 `*.xnnpack_cache_*`(최대 ~1.1GB) 생김 — arm64 기기엔 무의미하니 정리.
- **긴 RAG 프롬프트에서 데스크톱 x86 CLI가 `Failed to invoke the compiled model`로 실패하는 경우 발견** — 짧은 프롬프트/serve 경로는 정상. x86 XNNPack 런타임 엣지케이스로 추정, 안드로이드는 별도 런타임이라 재현 안 될 가능성 높음(실기기에서 긴 RAG 프롬프트 별도 확인 권장).

### 로컬 완전 하이브리드 채팅 (`scripts/hybrid_server.py` + `gemma-chat.html`)
앱 파이프라인(대명사 치환 → 키워드+시맨틱 하이브리드 RRF → Gemma 답변)을 노트북에서 그대로 재현.

- **임베딩**: `sentence-transformers`로 `models/embeddinggemma-300m`(EmbeddingGemma 300M **풀 정밀도 원본**) 로드. 모바일 tflite(양자화)와 **같은 모델, 다른 정밀도** — 모바일 상한선에 해당하는 품질로 봐도 됨.
  - RAG SDK(모바일 앱이 쓰는 것)와 sentence-transformers(이 로컬 도구)는 완전히 다른 런타임. RAG SDK는 "노트북이라 대신 쓴 것"이 아니라 **모바일 앱이 실제로 쓰는 방식**이고, sentence-transformers가 데스크톱 전용 대체재.
- **키워드**: 처음엔 `eval_search.py`의 LIKE+커스텀 점수(내 방식)를 그대로 썼다가, 아래 5절의 A/B 결과로 **FTS4 unicode61 티어드**(검색 담당 브랜치 방식)로 교체.
- **RRF**: `eval_search.py`의 `rrf_fuse` 재사용, k=60(양쪽 동일, 표준값 그대로).
- **Gemma 답변**: `litert-lm serve`(:9379)를 실제로 호출 — 규칙 기반이 아니라 **진짜 모델 출력**.
- **UI**: 답변마다 "검색 비교"(키워드/시맨틱/하이브리드 top-N + 소요시간)를 펼쳐볼 수 있고, 조회된 명함을 필드 기반 카드로 렌더링(실사진 없어서 텍스트 카드로 대체).
- `HJP_TEST_CARDS` 환경변수로 5000장 대신 소규모 테스트셋(7절)을 즉석에서 로드 가능(임베딩은 그 자리에서 계산).

---

## 5. 키워드 검색 A/B: 내 방식 vs 검색 담당 브랜치 방식

5000장 + `eval_search.py`의 자동생성 정답셋(150개 질의: 이름/회사/전화/지역+직함)으로 오프라인 비교.

| 방식 | Recall@1 | Recall@5 | Recall@20 | Precision@5 | MRR |
|---|---|---|---|---|---|
| **A · 내 방식**(LIKE + 커스텀 점수: 완전40/전방25/역전방20/포함12+바이그램) | 0.760 | 0.843 | 0.996 | 0.369 | 0.812 |
| **B · 검색 담당 방식**(FTS4 unicode61, phrase→allTerms→prefix→LIKE 티어드) | **0.940** | **0.969** | 0.986 | **0.396** | **0.964** |

- 유형별로 보면 이름/회사/지역+직함은 둘 다 잘함. **결정적 차이는 전화번호 조회**: A는 R@5 0.367·MRR 0.191(전화 조각을 부분일치 12점으로만 잡아 순위가 밀림), B는 **R@5 1.000·MRR 1.000**.
- **결론: B(검색 담당 FTS4 티어드) 채택.**

### 하이브리드(키워드+임베딩 RRF)까지 포함한 비교

| 시스템 | R@1 | R@5 | R@20 | P@5 | MRR |
|---|---|---|---|---|---|
| 키워드 A | 0.760 | 0.843 | 0.996 | 0.369 | 0.812 |
| 키워드 B | 0.940 | 0.969 | 0.986 | 0.396 | 0.964 |
| 시맨틱 단독 | 0.607 | 0.620 | 0.713 | 0.280 | 0.648 |
| 하이브리드 A(내 키워드+임베딩) | 0.747 | 0.764 | 0.951 | 0.357 | 0.784 |
| 하이브리드 B(검색 담당 키워드+임베딩) | 0.767 | 0.967 | 0.989 | **0.403** | 0.879 |

**중요한 발견(반직관적)**: 하이브리드가 **키워드 단독보다 오히려 나쁨**(B 키워드 MRR 0.964 → 하이브리드 B는 0.879). 이유: 이 평가셋(자동생성)이 전부 **정확 조회형**(이름/회사/전화/지역+직함) 질의라 시맨틱이 약하고(전화 R@5=0.00), RRF로 섞으면 좋은 키워드 결과가 희석됨. **"하이브리드가 항상 좋다"는 이 데이터에서는 틀렸다** — 조회형엔 키워드, 개념형("AI 개발하는 사람" 같은 의미 매칭)엔 시맨틱이 강할 걸로 예상되나, 평가셋에 개념형 질의가 없어 실측 못함(7절 데이터셋으로 보완 가능).

**시사점**: RRF에 키워드 가중을 더 주거나(가중 RRF: `w_kw·rrf(k_kw) + w_sem·rrf(k_sem)`), 평가셋에 개념형 질의를 추가해 시맨틱의 실제 기여를 다시 측정할 필요.

### RRF 상수 k=60 관련 논의(참고)
- k=60은 RRF 원 논문(Cormack et al., SIGIR 2009)의 관례적 기본값. k가 작을수록 각 축의 1등을 강하게 신뢰, k가 클수록 순위차를 뭉개 "양쪽에 고루 등장"을 우대.
- k와 가중치 w는 **독립적으로, 축마다 다르게** 조절 가능(현재는 양쪽 다 60·1:1 대칭).

---

## 6. 다른 팀원 브랜치와의 비교

### 6-1. `HJP-limited/ryeong` — main vs 이 브랜치
- 이번 세션 커밋(`0bfd236`)은 **`llm-integration-work`에만** push됨. main(`e3dd67f`)은 안 건드림.

### 6-2. `HJP-limited/ymj` `ymj/embedding-search-android-eval` (검색+검증 담당) 비교
분기점: `b79f293`(에이전트 도구 초기 구현). 이후 각자 독자적으로 검색/임베딩을 발전시킴 — **합칠 필요는 없음**(역할이 다름: 저쪽은 검색 전용, 이쪽은 LLM 채팅까지 포함).

| 구성요소 | 검색 담당 브랜치 | 이 브랜치(원래) |
|---|---|---|
| 구조 | 21개 모듈로 분리(Repository/Retriever/Embedder/Fusion/Codec 등) | 3개 통합(CardSearchService/KeywordSearchRanker/TextEmbeddingProvider) |
| 임베딩 런타임 | **raw TFLite `Interpreter`** 직접 호출 | **AI Edge RAG SDK**(`GemmaEmbeddingModel`, 고수준) |
| 토크나이저 | **직접 구현 BPE**(`SimpleBpeTokenizer`) + **패리티 검증**(`TokenizerParityVerifier`: 기준 토크나이저와 일치하는지 대조) | SDK 내장 sentencepiece(검증 코드 없음 — SDK가 정답을 담당하므로 불필요) |
| FTS | `@Fts4(tokenizer=unicode61)` + **티어드 MATCH**(phrase→allTerms→prefix→LIKE) | 원래 `@Fts4`(기본 토크나이저) + LIKE+커스텀 점수 → **이번에 검색 담당 방식으로 교체(8절)** |
| RRF | `DEFAULT_K = 60` | `1/(60+rank)` — **동일** |
| 평가 | **Kotlin 온디바이스** `SearchEvaluator`(recall@3/5, MRR@3/5) + 계측 테스트(androidTest) | **Python** `eval_search.py`(recall@1/5/20, MRR) — 실행 환경 다름, 지표는 둘 다 recall+MRR뿐(precision/nDCG 없음) |
| 채팅 LLM | 없음(검색 전용) | Gemma 4 E2B 멀티턴 채팅 |

**BPE·패리티 검증이 뭔지(참고 — 팀 내 용어 정리용)**:
- BPE(Byte Pair Encoding) = 텍스트를 모델이 학습된 서브워드 단위로 쪼개는 토큰화 방식.
- 패리티 검증 = "직접 구현한 토크나이저가 기준(정답) 토크나이저와 똑같이 쪼개는가"를 대조하는 것. raw TFLite처럼 토크나이저를 손수 구현할 때만 필요 — SDK가 정답 토크나이저를 내장해서 쓰는 이 브랜치엔 해당 없음.

**결론(팀 논의로 확정)**: 임베딩 런타임은 이 브랜치 방식(RAG SDK) 유지, **키워드는 검색 담당 방식 채택**(A/B로 확정), 평가는 온디바이스(저쪽)가 더 프로덕션에 충실하나 Python(이쪽)이 반복실험엔 더 빠름 — 상호보완적으로 병행 권장.

---

## 7. 새 테스트 데이터셋 (`data/cards_test50.json`)

### 배경
- 기존 5000장 합성 데이터가 근사 중복 이름이 너무 많음(강서연/강서영/서서연/강건우/권건우/김건우 등) → 멀티턴·키워드 정성 테스트에 노이즈가 심해 실제 버그(2-4절)와 데이터 노이즈를 구분하기 어려웠음.

### 스펙(생성 스크립트: `scripts/generate_test50.py`)
- **인물 50명**, **회사 45종**(5개 회사는 동료 2명씩, 40개는 1명씩)
- **동명이인 정확히 2쌍**(`김민준`, `이서연` — 각자 회사/직무/연락처 전부 다름), 나머지 46명은 **서로 근사 중복도 없는** 이름으로 선정
- 전 필드(name/nameEn/company/title/department/industry/location/phone/email/address/memo/tags) **빈칸 없음**, 전화·이메일·id 전부 고유
- 테스트 목적으로 **의도적으로 심어둔 조합**: "판교+AI 개발자"(이서연·스타테크), "판교+디자이너"(박도윤·한빛소프트웨어) — 실제로 검색되는 정답이 있는 케이스를 확보(기존 5000장엔 이런 조합이 실제로 0건이라 "노이즈인지 버그인지" 구분이 안 됐음)
- 생성 스크립트에 assert로 스펙 검증(50명/45사/동명이인 2종/필드 비어있지 않음/전화·이메일·id 유일) 포함 — 재생성해도 항상 스펙 보장.

### 사용법
```bash
python scripts/generate_test50.py           # data/cards_test50.json 생성
HJP_TEST_CARDS=data/cards_test50.json python scripts/hybrid_server.py   # 로컬 채팅에서 이 데이터셋 사용
```
앱에서 쓰려면 "명함 데이터 가져오기 (JSON)" 버튼으로 이 파일을 그대로 import 가능(스키마 동일).

### 실사용 확인
"판교에 있는 AI 개발자 찾아줘" → 하이브리드 1위 **이서연(계획된 정답)** 정확히 검색됨. 단 Gemma 답변이 판교 디자이너 박도윤도 같이 언급 — top-5 컨텍스트에 같이 들어가면 LLM이 지역만 보고 과포함하는 경향 관찰(프롬프트 개선 여지, 별도 이슈로 기록).

---

## 8. 앱(Kotlin/Java) 코드 반영 — FTS4 티어드 키워드 검색

5절 A/B 결과("검색 담당 방식이 확실히 낫다")를 **실제 안드로이드 앱**에 이식. 컴파일 성공, **아직 실기기 미검증·미push**.

| 파일 | 변경 |
|---|---|
| `data/BusinessCardFtsEntity.java` | `@Fts4` 토크나이저를 기본값 → `unicode61` + `prefix={2,3,4}` |
| `data/HjpDatabase.java` | FTS 스키마 변경으로 DB `version` 1→2, `fallbackToDestructiveMigration()` 추가. **데이터 유실 아님** — 카드/임베딩은 `seedIfEmpty()`가 번들 asset(`cards_seed.json`)에서 자동 재시딩하는 기존 로직을 그대로 씀 |
| `search/CardSearchService.kt` | `keywordHits()`를 **티어드 FTS**(정확구문→전체단어AND→접두어AND→LIKE폴백)로 교체. **티어 등장 순서를 그대로 랭킹으로 사용**(재점수화 안 함) — eval에서 검증한 것과 동일 방식. `KeywordSearchRanker.score()`는 그대로 남겨둠(다른 곳에서 안 씀, 기존 유닛테스트가 이 함수를 직접 테스트해서 영향 없음) |

- **명함 탭·채팅 탭 둘 다** 같은 `keywordHits()`를 쓰므로 이번 변경으로 **동시에 개선**됨.
- 컴파일 확인: `gradlew :app:compileDebugKotlin :app:compileDebugJavaWithJavac` → BUILD SUCCESSFUL.

---

## 9. 남은 일 (다음 세션 시작점)

1. **멀티턴 버그 3개 수정** (2-4절 표) — 존칭/복합조사 보강, focus를 "질문이 지목한 이름" 기준으로, 생략형 판정에 신규값 예외 추가. 로컬 채팅(`gemma-chat.html`)과 앱 코드(`MainActivity.kt`) 양쪽 다 반영 필요.
2. **8절 앱 변경사항 실기기 검증 후 push** — 특히 DB destructive migration이 실제로 재시딩되는지 실기기에서 확인 필요(로컬에서는 확인 불가).
3. **평가 지표 보강** — `eval_search.py`(Python)와 검색 담당의 `SearchEvaluator`(Kotlin) 둘 다 recall+MRR뿐, **Precision@k·nDCG@k 없음**. "판교 디자이너"처럼 노이즈만 반환하는 문제는 recall만으론 안 잡히고 precision으로 잡힘.
4. **개념형 질의를 평가셋에 추가** — 현재 자동생성 질의는 전부 정확조회형이라 시맨틱/하이브리드의 실제 가치를 못 재고 있음(5절 하이브리드 역전 현상 참고).
5. **필드 인식 no-match 게이트**(제안만 함, 미구현) — "판교"=지역/"디자이너"=직급으로 인식해 AND 필터링, 해당자 없으면 "없습니다" 응답. 방식은 가제티어(가장 가벼움, 폐쇄도메인에 적합) 채택 권장, LLM 파싱(self-query)은 매 턴 추가 호출로 무겁다고 판단해 보류.
6. **RRF 가중치 튜닝 검토** — 조회형/개념형 질의 비율에 따라 `w_kw`/`w_sem` 또는 `k_kw`/`k_sem`을 분리해 eval로 확정.

---

## 10. 관련 메모리 파일 (`.claude/.../memory/`)
- `hjp-target-architecture.md` — 최종 추천 파이프라인(OCR→Embed→검색→Gemma 4 E2B)
- `hjp-chat-model-gemma4.md` — 채팅 모델 교체·멀티턴·S21 검증 결과
- `validate-litertlm-on-desktop.md` — 실기기 없이 `.litertlm` 모델을 노트북에서 검증하는 방법(litert-lm CLI 사용법)
