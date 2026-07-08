# HJP Agent Search Demo

Android 온디바이스 기준으로 **DB 기반 keyword retrieval + EmbeddingGemma ONNX semantic retrieval + Reciprocal Rank Fusion hybrid retrieval + RAG context 생성** 경계를 제공하는 모듈입니다. Android UI나 LLM 답변 생성/Gemma LLM 연결은 포함하지 않습니다.

## 달라진 점

- 기존 LocalEmbeddingEngine/하드코딩 샘플 중심 구조에서 `RetrievalService.retrieve(query, topK)` API를 추가했습니다.
- production 경로는 `OnDeviceEmbeddingEngine`이며, 모델이 없으면 명확한 메시지와 `fallbackUsed`로 fallback 여부를 노출합니다.
- keyword 검색의 name/company/title별 수동 가중치(50/35/25 등)를 제거하고 `searchableText` token match로 단순화했습니다.
- keyword 점수와 cosine similarity를 직접 더하지 않고 RRF rank fusion을 사용합니다.

## 참고 Room DB

`imported/sojung_room_data/`에 sojung android-app 브랜치에서 가져온 Room 참고 파일이 있습니다. 현재 Java core에는 `BusinessCardRepository`, `InMemoryBusinessCardRepository`, `CardEmbedding`을 두었고 Android Room에서는 같은 필드를 Entity/DAO로 옮기면 됩니다.

### business_cards / card_embeddings

`business_cards`는 명함 원본입니다. `card_embeddings` 권장 필드는 다음과 같습니다.

- `cardId`
- `modelName`
- `dim`
- `vector` (`BLOB`, little-endian float32; `FloatVectorCodec` 사용)
- `sourceTextHash`
- `createdAt`
- `updatedAt`

BLOB를 선택한 이유는 JSON보다 작고 Room/SQLite에서 안정적으로 저장 가능하기 때문입니다.

## searchableText 기준

`BusinessCard.searchableText()`는 `name`, `nameEn`, `company`, `title`, `department`, `industry`, `location`, `memo`, `tags`를 포함합니다. 기본 검색/RAG에는 `phone`, `email`, `address`를 넣지 않습니다. 상세 정보는 `getCard(cardId)`에서만 조회합니다.

## EmbeddingGemma ONNX assets

모델은 git에 올리지 않습니다. 실제 배치 위치:

```text
app/src/main/assets/models/embeddinggemma.onnx
app/src/main/assets/tokenizer/
```

추적되는 파일은 `.gitkeep`뿐입니다. `*.onnx`, `*.safetensors`, `tokenizer.json`, `tokenizer.model`, `tokenizer_config.json` 등은 ignore됩니다.

ONNX 변환은 사용자가 검증한 `google/embeddinggemma-300m` export 결과를 사용합니다. 확인된 출력 dimension은 768입니다. Android에서는 `ai.onnxruntime:onnxruntime-android` dependency를 추가했고, 실제 `OrtSession` input/output signature와 tokenizer id 매핑은 모델 파일 기준 최종 확인이 필요합니다.

## Tokenizer 한계

`TextTokenizer` 아래에 `HuggingFaceTokenizer` placeholder와 `LightweightTokenizer` fallback 계층을 분리했습니다. Android에서 `tokenizer.json` 또는 `tokenizer.model`을 처리하려면 Hugging Face tokenizers 호환 라이브러리 또는 SentencePiece Android 라이브러리를 붙여야 합니다. Python ONNX 테스트 중 tokenizer regex warning이 있었으므로 Android 통합 시 동일 문장으로 token id, attention mask, embedding cosine 결과를 반드시 재검증해야 합니다.

## RetrievalService 사용법

```java
RetrievalService retrievalService = new SearchLookupService(repository, OnDeviceEmbeddingEngine.production());
RetrievalResponse response = retrievalService.retrieve(userQuery, 5);
String ragContext = response.ragContext;
// LLM prompt에 ragContext를 넣어서 답변 생성
BusinessCard detail = retrievalService.getCard(response.cardIds.get(0)); // phone/email/address 포함 가능
```

`RetrievalResponse`는 query, top results, cardIds, ragContext, retrievalMode, embeddingModelName, keywordResultCount, semanticResultCount, fallbackUsed를 포함합니다.

## RAG context 예시

```text
[cardId=C002]
name: 오성령
company: 코어AI
title: AI 엔지니어
department: AI 개발팀
industry: it
location: 판교
memo: EmbeddingGemma와 로컬 벡터 검색을 실험 중
tags: AI, 개발자, 임베딩, 검색
```

## Rank fusion

Hybrid는 `1 / (60 + keywordRank) + 1 / (60 + semanticRank)` 형태의 Reciprocal Rank Fusion을 사용합니다. keyword token score와 semantic cosine similarity는 스케일이 달라 직접 가중합하지 않습니다.

## 저장/수정 시 embedding 갱신

`EmbeddingUpdater.upsertCardAndRefreshEmbedding(card)` 흐름:

1. BusinessCard 저장/수정
2. searchableText 생성
3. SHA-256 sourceTextHash 계산
4. 기존 hash와 다르면 embedding 재생성
5. `card_embeddings` upsert

## Demo / evaluator

```bash
javac -d /tmp/hjp-classes $(find src/main/java -name '*.java')
java -cp /tmp/hjp-classes com.hjp.searchlookup.SearchExample
```

`SearchExample`은 keyword only, semantic only, hybrid, `RetrievalResponse.ragContext`, `getCard(cardId)` 상세 조회, evaluator 결과를 출력합니다. `eval/rag_eval_dataset.jsonl`에는 20개 query가 있고 evaluator는 LLM 답변 품질이 아닌 retrieval 품질(Top1 Accuracy, Recall@5, MRR@5)만 측정합니다.

## 현재 한계

1. 실제 `embeddinggemma.onnx` 파일은 repo에 포함하지 않습니다.
2. Android에서 tokenizer와 ONNX input/output signature는 실제 모델 파일 기준으로 최종 확인이 필요합니다.
3. 실기기 성능 검증이 필요합니다.
4. ONNX 테스트 중 tokenizer regex warning이 있었으므로 tokenizer 동작은 Android 통합 시 추가 검증이 필요합니다.
