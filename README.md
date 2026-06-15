# HJP 검색/조회 정리

이 브랜치는 최종 구현 기준인 `card-agent-android`의 검색/조회 정책을 따로 정리한 저장소입니다.

기존 브랜치에 있던 파일은 제거했고, 현재는 명함 검색 정책과 조회 흐름을 설명하는 README와 검색/조회 핵심 Java 코드만 남겨두었습니다.

## 범위

- 명함 필드 기반 키워드 검색
- 임베딩 인터페이스 기반 의미 검색
- 키워드 점수와 의미 점수를 합치는 하이브리드 랭킹
- `cardId` 기반 명함 상세 조회
- 데모/오프라인 실행용 로컬 fallback 임베딩

이 저장소는 완성된 Android 앱이 아닙니다. Android UI, RoomDB, assets, 온디바이스 임베딩 모델에 연결할 수 있도록 검색/조회 핵심 로직만 정리한 코드입니다.

## 최종 앱 기준 데이터 저장 방식

현재 최종 앱인 `card-agent-android`는 5000개 명함 데이터를 APK assets에 저장합니다.

```text
assets/cards/business_cards.json
assets/cards/card_vector_ids.txt
assets/cards/card_vectors_f32.bin
assets/cards/images/*.jpg
```

앱 실행 시에는 다음처럼 동작합니다.

```text
business_cards.json -> List<BusinessCard>로 메모리에 로딩
card_vectors_f32.bin -> Map<cardId, float[]>로 메모리에 로딩
검색 시 전체 명함 리스트를 순회하며 점수 계산
```

현재 최종 앱에서는 RoomDB, SQLite FTS, VectorDB를 사용하지 않습니다.

## 전체 검색 흐름

```text
사용자 query
  -> 정규화
  -> 필터/의미 태그 상태 갱신
  -> query token 확장
  -> query + 확장 token 임베딩
  -> 모든 명함 점수 계산
  -> 최종 점수 내림차순 정렬
  -> 상위 결과 반환
```

## 키워드 기반 검색

키워드 검색은 query token을 각 명함 필드에 대해 `contains()`로 비교하는 방식입니다.

토큰 길이가 2 미만이면 무시합니다. 각 토큰은 아래 순서로 비교하며, `if / else if` 구조라서 한 토큰은 한 카드 안에서 가장 먼저 매칭된 필드 하나에 대해서만 점수를 줍니다.

| 매칭 위치 | 점수 |
| --- | ---: |
| 이름 `name` | 50 |
| 회사 `company` | 35 |
| 직책 `title` | 25 |
| 업종 `industry` | 20 |
| 전체 검색 텍스트 `searchableText` | 12 |

`searchableText`에는 다음 필드가 들어갑니다.

```text
name, nameEn, company, title, department, industry, location,
phone, email, address, memo, tags
```

예시:

```text
query: "김지원 대표"

card:
  name: 김지원
  title: 대표이사

keyword score:
  김지원 -> name match  +50
  대표   -> title match +25

total keyword score = 75
```

중요한 점은 query만 보고 `"김지원"`이 이름이라고 먼저 추론하지 않는다는 것입니다. 각 토큰을 이름, 회사, 직책, 업종, 전체 텍스트 순서로 모두 비교하고, 먼저 걸린 필드의 가중치를 적용합니다.

## 의미기반 검색

의미기반 검색은 필드별 유사도를 따로 계산하지 않습니다.

현재 방식은 query 전체를 하나의 벡터로 만들고, 명함 전체 검색 텍스트도 하나의 벡터로 만든 뒤 cosine similarity를 한 번 계산합니다.

```text
query_vector = embed(query + expandedTokens)
card_vector  = embed(card.searchableText())
semantic_score = cosine(query_vector, card_vector)
```

벡터는 L2 normalize되어 있으므로 cosine 계산은 dot product와 같습니다.

의미 점수는 threshold를 넘을 때만 최종 점수에 반영합니다.

```text
if semantic_score > 0.04:
    semantic contribution = semantic_score * 45
```

예시:

```text
query: "AI 개발팀 사람"

semantic_score = 0.70
semantic contribution = 0.70 * 45 = 31.5
```

즉 의미기반은 다음 구조입니다.

```text
필드별 의미 유사도 계산 X
필드별 의미 유사도 합산 X
명함 전체 문서 벡터와 query 벡터 비교 O
```

## 하이브리드 검색

최종 앱의 `search_cards`는 키워드와 의미기반을 항상 같은 검색 흐름 안에서 계산합니다.

최종 점수는 단순 가중합입니다.

```text
final_score =
    keyword_field_score
  + synonym_tag_score
  + semantic_score * 45
```

단, 의미 점수는 `semantic_score > 0.04`일 때만 더합니다.

예시:

```text
query: "AI 개발팀 대표"

card A:
  department: AI개발팀
  industry: it

keyword:
  AI     -> searchableText match +12
  개발팀 -> searchableText match +12

semantic:
  cosine = 0.70
  0.70 * 45 = 31.5

final:
  12 + 12 + 31.5 = 55.5
```

현재 최종 구현에서는 키워드 검색과 의미 검색이 분리된 도구가 아닙니다.

```text
search_cards 실행
  -> 키워드 점수 계산
  -> 의미 점수 계산
  -> 둘을 합산
```

다만 임베딩 벡터가 비어 있거나 의미 점수가 threshold 이하이면, 사실상 키워드/동의어 점수만 랭킹에 영향을 줍니다.

## 조회 흐름

검색 결과는 후보를 식별할 수 있는 `cardId`를 반환합니다. 상세 정보 조회는 별도 단계입니다.

```text
search(query) -> cardId 후보 목록
getCard(cardId) -> 특정 명함 상세 정보
```

이렇게 분리하면 검색 결과 응답을 작게 유지할 수 있고, 전화번호/이메일/주소 같은 상세 정보를 사용자가 특정 명함을 선택했을 때만 보여주는 구조로 만들 수 있습니다.

## 코드 파일

```text
src/main/java/com/hjp/searchlookup/BusinessCard.java
src/main/java/com/hjp/searchlookup/SearchResult.java
src/main/java/com/hjp/searchlookup/EmbeddingEngine.java
src/main/java/com/hjp/searchlookup/LocalEmbeddingEngine.java
src/main/java/com/hjp/searchlookup/SearchLookupService.java
src/main/java/com/hjp/searchlookup/SearchExample.java
```

## 각 파일 역할

`BusinessCard.java`

명함 데이터 모델입니다. 이름, 회사, 직책, 부서, 업종, 연락처, 메모, 태그를 가지고 있고 `searchableText()`로 검색 대상 문자열을 만듭니다.

`SearchResult.java`

검색 결과 모델입니다. 명함 객체와 최종 점수를 담습니다.

`EmbeddingEngine.java`

임베딩 엔진 인터페이스입니다. 실제 EmbeddingGemma, ONNX Runtime, TFLite, fallback 엔진을 같은 방식으로 연결할 수 있게 분리했습니다.

`LocalEmbeddingEngine.java`

모델이 없을 때 쓰는 fallback 임베딩입니다. 단어 feature, 2~3글자 n-gram, concept map을 해시 벡터에 넣고 normalize합니다. 실제 AI 임베딩 모델은 아닙니다.

`SearchLookupService.java`

검색/조회 핵심 서비스입니다. 키워드 점수, 의미 점수, 동의어 boost, 필터 상태, 상세 조회를 담당합니다.

`SearchExample.java`

간단한 실행 예시입니다.

## 실제 제품화 방향

현재 `card-agent-android`는 발표/데모 안정성을 위해 assets 기반으로 구현되어 있습니다.

제품화 단계에서는 아래 구조가 더 적합합니다.

```text
RoomDB
  - business_cards
  - card_tags
  - card_embeddings

SQLite FTS5
  - 키워드 후보 검색

Embedding model
  - query embedding 생성

In-memory cosine
  - 후보군 rerank
```

5000개 규모에서는 메모리에 벡터를 올리고 brute-force cosine을 계산해도 충분히 현실적입니다. 데이터가 더 커지면 on-device vector index 또는 ANN 라이브러리를 붙이는 방향이 좋습니다.
