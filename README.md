# HJP Agent Search Demo

Android 온디바이스 기준으로 **명함 탭 빠른 키워드 검색**과 **에이전트 하이브리드 검색/RAG retrieval**을 분리한 검색 모듈입니다. 기존 ONNX Runtime 기반 `OnDeviceEmbeddingEngine` 구조와 `LocalEmbeddingEngine` fallback은 유지합니다.

## 전체 구조

- `BusinessCardRepository`: 명함 원본 데이터와 `CardEmbedding` 저장소 경계입니다.
- `QueryAnalyzer`: 사용자 query를 `rawQuery`, `normalizedQuery`, `keywordQuery`, `semanticQuery`, `tokens`로 분석합니다.
- `KeywordRetriever`: DB 구현이 Room FTS4, raw SQLite FTS5, LIKE fallback으로 바뀌어도 `RetrievalService` 영향이 작도록 만든 keyword retrieval 인터페이스입니다.
- `SemanticRetriever`: `QueryAnalysis.semanticQuery`를 embedding으로 변환하고 저장된 card embedding과 cosine similarity로 semantic ranking을 만듭니다.
- `ReciprocalRankFusion`: keyword ranking과 semantic ranking을 `1 / (60 + rank)` 공식으로 결합합니다. keyword score와 semantic score를 직접 더하지 않습니다.
- `RagContextBuilder`: LLM prompt에 넣을 최소 명함 context를 만듭니다.

## 명함 탭 검색 vs 에이전트 하이브리드 검색

### 명함 탭 검색

짧은 키워드 입력을 대상으로 하는 빠른 검색입니다. 이름, 회사명, 직책, 부서, 산업/태그, 메모 등 `searchableText` 기반으로 찾으며 embedding, RRF, RAG context를 사용하지 않습니다.

```java
List<SearchResult> results = service.searchCardTab("코어AI 개발", SortOption.RELEVANCE, 20);
```

### 에이전트 하이브리드 검색

자연어 query를 대상으로 합니다.

```text
사용자 자연어 query
→ QueryAnalyzer
→ KeywordRetriever keyword retrieval
→ SemanticRetriever query embedding + vector retrieval
→ ReciprocalRankFusion RRF 결합
→ RagContextBuilder
→ RetrievalResponse
```

LLM 담당자는 아래 API를 호출하면 top 명함 결과와 ragContext를 받을 수 있습니다.

```java
RetrievalResponse response = retrievalService.retrieve(userQuery, 5);
RetrievalResponse responseWithMode = service.retrieve(userQuery, 5, RetrievalMode.HYBRID);
```

`RetrievalResponse`는 `results`, `ragContext`, `queryAnalysis`, `mode`, `cardIds`, `keywordResultCount`, `semanticResultCount`, `fallbackUsed`를 포함합니다.

## QueryAnalyzer 역할

기본 정규화는 `trim`, lower-case 가능한 언어의 lower-case, 연속 공백 정리, 검색에 불필요한 특수문자 정리를 포함합니다. 한글/영문/숫자와 이메일/전화번호에 자주 쓰이는 `@`, `.`, `_`, `+`, `-` 등은 최대한 보존합니다.

## KeywordRetriever 구현 전략

현재 포함된 구현/adapter는 다음과 같습니다.

- `LikeFallbackKeywordRetriever`: 현재 in-memory/일반 테이블 기반에서도 동작하는 fallback입니다. 명함 탭 검색과 agent keyword 후보 생성에 바로 사용할 수 있습니다.
- `RoomFtsKeywordRetriever`: Room DB 담당자가 연결할 FTS4 adapter placeholder입니다.
- `SqliteFts5KeywordRetriever`: raw SQLite FTS5 + trigram tokenizer 검토용 adapter placeholder입니다.

### Room DB / SQLite FTS 전략

- Room 일반 테이블(`business_cards`)은 명함 원본 데이터를 저장합니다.
- FTS 테이블은 검색용 `searchableText` 인덱스를 저장합니다.
- Room 사용 시 우선 `FTS4 + unicode61 tokenizer + prefix index`를 고려합니다.
- Room FTS4에서 짧은 token/부분 문자열 매칭이 부족하면 `LIKE` fallback을 병행합니다.
- FTS5를 직접 사용할 수 있는 raw SQLite 경로에서는 `trigram tokenizer`를 검토합니다.
- FTS 미사용 또는 미지원 환경에서는 `LikeFallbackKeywordRetriever`를 사용합니다.
- 최종 Room FTS 적용 방식은 DB 담당자와 협의가 필요합니다.

## searchableText 기준과 개인정보 최소화

`BusinessCard.searchableText()`는 `name`, `nameEn`, `company`, `title`, `department`, `industry`, `location`, `memo`, `tags`를 포함합니다. 기본 RAG context는 이름, 회사, 직책, 부서, 산업/태그, 메모, 검색에 필요한 설명 중심이며 전화번호, 이메일, 상세 주소를 과도하게 넣지 않습니다. 상세 정보는 `getCard(cardId)`로 별도 조회합니다.

## EmbeddingGemma ONNX assets

대용량 모델 파일은 Git에 올리지 않습니다. 실제 배치 위치는 아래입니다.

```text
app/src/main/assets/models/embeddinggemma.onnx
app/src/main/assets/tokenizer/
```

추적되는 파일은 `.gitkeep`뿐입니다. `*.onnx`, `*.safetensors`, `*.tflite`, `*.task`, `tokenizer.json`, `tokenizer.model`, `tokenizer_config.json` 등은 ignore 상태로 유지합니다.

`app/build.gradle.kts`의 `androidResources { noCompress += "onnx" }` 설정은 Android asset에 포함된 ONNX 파일을 압축하지 않아 ONNX Runtime이 효율적으로 읽게 하기 위한 설정입니다.

## 현재 확인된 것

1. ONNX 모델 변환 완료.
2. 로컬 assets에 모델 포함 시 `assembleDebug` 성공.
3. 실제 기기 ONNX Runtime 추론은 추가 테스트가 필요합니다.

`OnDeviceEmbeddingEngine.production()`은 production 경로이며, 실제 모델/토크나이저가 준비되지 않은 JVM demo 환경에서는 fallback 사용 여부를 `RetrievalResponse.fallbackUsed`로 노출합니다.

## Demo / evaluator

```bash
javac -d /tmp/hjp-classes $(find src/main/java -name '*.java')
java -cp /tmp/hjp-classes com.hjp.searchlookup.SearchExample
```

`SearchExample`은 명함 탭 단순 키워드 검색, 에이전트 하이브리드 검색, QueryAnalyzer 결과, keyword retrieval 후보, semantic retrieval 후보, RRF 최종 결과, ragContext, `getCard(cardId)` 상세 조회, evaluator 결과를 출력합니다.
