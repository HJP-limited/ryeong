# HJP Search & Lookup

This branch contains the cleaned search/lookup layer extracted from the final
`card-agent-android` implementation.

The previous branch files were removed so this repository only documents and
implements the card search policy.

## Scope

- Keyword search over card fields
- Semantic search through an embedding interface
- Hybrid ranking by weighted score fusion
- Card detail lookup by `cardId`
- Local fallback embedding for demo/offline execution

This is not a full Android app. It is the organized search/lookup core that can
be connected to Android UI, RoomDB, assets, or an on-device embedding model.

## Current Final App Policy

The final app in `card-agent-android` currently stores 5000 cards in APK assets:

- `assets/cards/business_cards.json`
- `assets/cards/card_vector_ids.txt`
- `assets/cards/card_vectors_f32.bin`
- `assets/cards/images/*.jpg`

At runtime the app loads card metadata into memory and loads/prepares card
vectors into a `Map<cardId, float[]>`. Search then scans the in-memory card list
and ranks results.

No RoomDB, SQLite FTS, or VectorDB is used in the current final app.

## Search Flow

```text
raw query
  -> normalize
  -> update filters / semantic tags
  -> expand query tokens
  -> embed(query + expanded tokens)
  -> score every card
  -> sort by final score desc
  -> return top results
```

## Keyword Scoring

For every query token with length >= 2, the engine checks fields in priority
order. Because this is an `if / else if` policy, one token contributes only one
field score per card.

| Match target | Score |
| --- | ---: |
| name | 50 |
| company | 35 |
| title | 25 |
| industry | 20 |
| searchable text fallback | 12 |

`searchableText` contains:

```text
name, nameEn, company, title, department, industry, location,
phone, email, address, memo, tags
```

Example:

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

## Semantic Scoring

Semantic search does not compare field-by-field. It embeds the whole query once
and the whole card text once.

```text
query_vector = embed(query + expandedTokens)
card_vector  = embed(card.searchableText())
semantic_score = cosine(query_vector, card_vector)
```

Vectors are L2-normalized, so cosine is calculated as dot product.

Semantic score is applied only when it is above the threshold:

```text
if semantic_score > 0.04:
    semantic contribution = semantic_score * 45
```

Example:

```text
query: "AI 개발팀 사람"

semantic_score = 0.70
semantic contribution = 0.70 * 45 = 31.5
```

## Hybrid Ranking

The final score is weighted sum fusion:

```text
final_score =
    keyword_field_score
  + synonym_tag_score
  + semantic_score * 45
```

Example:

```text
query: "AI 개발팀 대표"

card A:
  department: AI개발팀
  industry: it

keyword:
  AI     -> searchable text +12
  개발팀 -> searchable text +12

semantic:
  cosine = 0.70
  0.70 * 45 = 31.5

final:
  12 + 12 + 31.5 = 55.5
```

Keyword and semantic search are always evaluated together in the final
`card-agent-android` `search_cards` flow. If the embedding vector is unavailable
or similarity is below threshold, only the keyword/synonym score affects ranking.

## Lookup Flow

Search results return a `cardId`. Detail lookup is intentionally separate:

```text
search(query) -> cardId candidates
getCard(cardId) -> full card detail
```

This keeps search output small and makes it easy to hide sensitive fields until
the user asks for a specific card.

## Files

```text
src/main/java/com/hjp/searchlookup/BusinessCard.java
src/main/java/com/hjp/searchlookup/SearchResult.java
src/main/java/com/hjp/searchlookup/EmbeddingEngine.java
src/main/java/com/hjp/searchlookup/LocalEmbeddingEngine.java
src/main/java/com/hjp/searchlookup/SearchLookupService.java
src/main/java/com/hjp/searchlookup/SearchExample.java
```

## Production Direction

For a product version, the recommended storage/search structure is:

```text
RoomDB
  - business_cards
  - card_tags
  - card_embeddings
SQLite FTS5
  - keyword candidate retrieval
Embedding model
  - query embedding
In-memory cosine
  - rerank top keyword/vector candidates
```

For 5000 cards, brute-force cosine over in-memory vectors is acceptable. If the
dataset grows significantly, add an on-device vector index or ANN library.
