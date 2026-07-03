# HJP Agent Search Demo

Java core logic for a business card management AI service. This repository is not a complete Android app; it focuses on safe, dependency-light search and lookup logic that can later be wired into Android UI, RoomDB, SQLite FTS5, EmbeddingGemma, a Qwen/BGE-style reranker, and real LLM calls.

## Search split

### Business card tab search

`SearchLookupService.searchCardTab(rawQuery, sortOption, limit)` is keyword-only search for the normal card list tab.

It does **not** use semantic search, embeddings, RAG context, LLM calls, or agent session state. It supports sorting by:

- `RELEVANCE`
- `LATEST`
- `NAME`
- `COMPANY`

The current demo uses `InMemoryKeywordCandidateSource`, which preserves the lightweight field scoring policy. The `KeywordCandidateSource` interface exists so SQLite FTS5 or another card-index source can be connected later without changing the service API.

### Agent search

`SearchLookupService.retrieveForAgent(rawQuery, session, limit)` is hybrid retrieval for the agent flow:

1. keyword candidate scoring
2. semantic scoring with `EmbeddingEngine`
3. optional synonym/tag boost
4. reranking through `RerankerEngine`
5. RAG context creation with essential card fields only

The demo still uses `LocalEmbeddingEngine` as a deterministic fallback. `EmbeddingEngine` remains the integration point for future EmbeddingGemma-based embeddings. `RerankerEngine` was added for a future Qwen/BGE-style reranker, but the current implementation is `NoOpRerankerEngine` and performs no model inference.

## Agent session

`AgentSessionState` is in-memory only. It stores the recent query, recent search results, and last selected card id while the process is running. It is not written to a database or file and disappears when the app closes.

It supports simple multi-turn references such as `첫 번째`, `첫번째`, `두 번째`, `두번째`, `세 번째`, `세번째`, `1번`, `2번`, and `3번`.

## Lookup and RAG privacy boundary

Search returns card-id based candidates. Full details remain separated through `getCard(cardId)`.

Default RAG context includes only essential fields:

- cardId
- name
- company
- title
- department
- industry
- location
- memo
- tags

Phone, email, and address are intentionally excluded from default RAG context. They are still available through explicit detailed lookup with `getCard(cardId)`.

## Run the example

```bash
./gradlew compileJava
java -cp build/classes/java/main com.hjp.searchlookup.SearchExample
```

`SearchExample` demonstrates card-tab keyword search, latest/name/company sorting, agent hybrid retrieval, RAG context generation, and a multi-turn detailed lookup.

## Evaluation sample

`eval/rag_eval_dataset.jsonl` contains a small JSONL sample for future retrieval/RAG evaluation. `RagEvaluator` provides dependency-free Recall@5, MRR@5, and Top1 Accuracy helpers for in-code evaluation.
