package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public final class SearchLookupService {
    private static final float SEMANTIC_THRESHOLD = 0.04f;
    private static final double SEMANTIC_WEIGHT = 45.0;
    private static final int RAG_CARD_LIMIT = 5;

    private final List<BusinessCard> cards;
    private final EmbeddingEngine embeddingEngine;
    private final RerankerEngine rerankerEngine;
    private final KeywordCandidateSource keywordCandidateSource;
    private final RagContextBuilder ragContextBuilder = new RagContextBuilder();
    private final LightweightTokenizer tokenizer = new LightweightTokenizer();
    private final Map<String, BusinessCard> cardsById = new LinkedHashMap<>();
    private final Map<String, float[]> cardVectors = new HashMap<>();
    private final Map<String, List<String>> synonyms = new HashMap<>();

    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine) {
        this(cards, embeddingEngine, null, new NoOpRerankerEngine());
    }

    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine,
            Map<String, float[]> precomputedCardVectors, RerankerEngine rerankerEngine) {
        this.cards = Collections.unmodifiableList(new ArrayList<>(cards == null ? Collections.emptyList() : cards));
        this.embeddingEngine = embeddingEngine == null ? new LocalEmbeddingEngine() : embeddingEngine;
        this.rerankerEngine = rerankerEngine == null ? new NoOpRerankerEngine() : rerankerEngine;
        this.keywordCandidateSource = new InMemoryKeywordCandidateSource(this.cards, tokenizer);
        installSynonyms();
        Map<String, float[]> vectors = precomputedCardVectors == null ? Collections.emptyMap() : precomputedCardVectors;
        for (BusinessCard card : this.cards) {
            cardsById.put(card.id, card);
            float[] vector = vectors.get(card.id);
            cardVectors.put(card.id, vector == null ? this.embeddingEngine.embedCard(card) : vector);
        }
    }

    public List<SearchResult> search(String rawQuery, int limit) {
        return retrieveForAgent(rawQuery, new AgentSessionState(), limit).results;
    }

    public List<SearchResult> searchCardTab(String rawQuery, SortOption sortOption, int limit) {
        SortOption option = sortOption == null ? SortOption.RELEVANCE : sortOption;
        List<SearchResult> results = new ArrayList<>(keywordCandidateSource.searchKeyword(rawQuery, Integer.MAX_VALUE));
        results.sort(comparatorFor(option));
        return limit(results, limit);
    }

    public RetrievalResponse retrieveForAgent(String rawQuery, AgentSessionState session, int limit) {
        String query = tokenizer.normalize(rawQuery);
        int safeLimit = Math.max(1, limit);
        Map<String, SearchResult> keywordById = new LinkedHashMap<>();
        for (SearchResult result : keywordCandidateSource.searchKeyword(query, Integer.MAX_VALUE)) {
            keywordById.put(result.cardId, result);
        }

        List<String> expandedTokens = expandTokens(query);
        float[] queryVector = embeddingEngine.embed(query + " " + join(expandedTokens, " "));
        List<SearchResult> hybrid = new ArrayList<>();

        for (BusinessCard card : cards) {
            SearchResult keywordResult = keywordById.get(card.id);
            double keywordScore = keywordResult == null ? 0.0 : keywordResult.breakdown.keywordScore;
            Set<String> matchedFields = new LinkedHashSet<>(keywordResult == null ? Collections.emptyList() : keywordResult.matchedFields);
            double synonymScore = synonymScore(card, query, expandedTokens);
            if (synonymScore > 0.0) matchedFields.add("synonym");
            double semanticRaw = semanticScore(queryVector, card);
            double semanticContribution = semanticRaw > SEMANTIC_THRESHOLD ? semanticRaw * SEMANTIC_WEIGHT : 0.0;
            if (semanticContribution > 0.0) matchedFields.add("semantic");
            double finalScore = keywordScore + synonymScore + semanticContribution;
            if (query.isEmpty()) finalScore = 1.0;
            if (finalScore > 0.0) {
                ScoreBreakdown breakdown = new ScoreBreakdown(keywordScore, semanticRaw, synonymScore, 0.0, finalScore);
                hybrid.add(new SearchResult(card, finalScore, breakdown, new ArrayList<>(matchedFields)));
            }
        }

        hybrid.sort(Comparator.comparingDouble((SearchResult result) -> result.score).reversed());
        List<SearchResult> reranked = rerankerEngine.rerank(query, hybrid, safeLimit);
        String ragContext = ragContextBuilder.build(query, reranked, Math.min(RAG_CARD_LIMIT, safeLimit));
        AgentSessionState activeSession = session == null ? new AgentSessionState() : session;
        activeSession.updateLastSearch(query, reranked);
        return new RetrievalResponse(query, reranked, ragContext, engineName(), rerankerEngine.name());
    }

    public BusinessCard getCard(String cardId) {
        if (cardId == null) return null;
        return cardsById.get(cardId.trim());
    }

    public String engineName() {
        return embeddingEngine.name();
    }

    private Comparator<SearchResult> comparatorFor(SortOption option) {
        Comparator<SearchResult> relevance = Comparator.comparingDouble((SearchResult result) -> result.score).reversed();
        switch (option) {
            case LATEST:
                return Comparator.comparingLong((SearchResult result) -> result.card.createdAtMillis).reversed().thenComparing(relevance);
            case NAME:
                return Comparator.comparing((SearchResult result) -> safe(result.card.name), String.CASE_INSENSITIVE_ORDER).thenComparing(relevance);
            case COMPANY:
                return Comparator.comparing((SearchResult result) -> safe(result.card.company), String.CASE_INSENSITIVE_ORDER).thenComparing(relevance);
            case RELEVANCE:
            default:
                return relevance;
        }
    }

    private double semanticScore(float[] queryVector, BusinessCard card) {
        Float score = embeddingEngine.cosine(queryVector, cardVectors.get(card.id));
        return score == null ? 0.0 : score;
    }

    private double synonymScore(BusinessCard card, String query, List<String> expandedTokens) {
        String searchableText = card.searchableText();
        double score = 0.0;
        for (Map.Entry<String, List<String>> entry : synonyms.entrySet()) {
            String key = entry.getKey().toLowerCase(Locale.KOREAN);
            if (!query.contains(key) && !expandedTokens.contains(key)) continue;
            for (String keyword : entry.getValue()) {
                if (searchableText.contains(keyword.toLowerCase(Locale.KOREAN))) score += 8.0;
            }
        }
        return score;
    }

    private List<String> expandTokens(String query) {
        Set<String> tokens = new LinkedHashSet<>(tokenizer.tokenize(query));
        for (Map.Entry<String, List<String>> entry : synonyms.entrySet()) {
            if (query.contains(entry.getKey().toLowerCase(Locale.KOREAN))) {
                for (String value : entry.getValue()) tokens.add(value.toLowerCase(Locale.KOREAN));
            }
        }
        return new ArrayList<>(tokens);
    }

    private List<SearchResult> limit(List<SearchResult> results, int limit) {
        if (results == null || results.isEmpty() || limit <= 0) return Collections.emptyList();
        return Collections.unmodifiableList(new ArrayList<>(results.subList(0, Math.min(limit, results.size()))));
    }

    private void installSynonyms() {
        synonyms.put("투자", Arrays.asList("투자", "vc", "스타트업", "ir", "핀테크", "finance"));
        synonyms.put("제조", Arrays.asList("제조", "공장", "생산", "품질", "manufacturing"));
        synonyms.put("세미나", Arrays.asList("세미나", "컨퍼런스", "행사", "ai", "네트워킹"));
        synonyms.put("개발자", Arrays.asList("개발", "엔지니어", "백엔드", "ai", "it"));
        synonyms.put("대표", Arrays.asList("대표", "ceo", "founder", "창업자"));
        synonyms.put("영업", Arrays.asList("영업", "세일즈", "파트너십", "bd"));
    }

    private String join(List<String> values, String separator) {
        StringBuilder builder = new StringBuilder();
        for (String value : values) {
            if (builder.length() > 0) builder.append(separator);
            builder.append(value);
        }
        return builder.toString();
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }
}
