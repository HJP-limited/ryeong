package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public final class SearchLookupService {
    private static final float SEMANTIC_THRESHOLD = 0.04f;
    private static final double SEMANTIC_WEIGHT = 45.0;

    private final List<BusinessCard> cards;
    private final EmbeddingEngine embeddingEngine;
    private final Map<String, BusinessCard> cardsById = new LinkedHashMap<>();
    private final Map<String, float[]> cardVectors = new HashMap<>();
    private final Map<String, List<String>> synonyms = new HashMap<>();
    private final SearchState state = new SearchState();

    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine) {
        this.cards = Collections.unmodifiableList(new ArrayList<>(cards));
        this.embeddingEngine = embeddingEngine;
        installSynonyms();

        for (BusinessCard card : cards) {
            cardsById.put(card.id, card);
            cardVectors.put(card.id, embeddingEngine.embedCard(card));
        }
    }

    public List<SearchResult> search(String rawQuery, int limit) {
        String query = normalize(rawQuery);
        if (query.isEmpty()) {
            state.clear();
        } else if (!query.contains("그중") && !query.contains("이전") && !query.contains("거기서")) {
            state.clear();
        }

        updateState(query);

        List<String> tokens = expandTokens(query);
        float[] queryVector = embeddingEngine.embed(query + " " + join(tokens, " "));
        List<SearchResult> results = new ArrayList<>();

        for (BusinessCard card : cards) {
            if (!passesState(card)) continue;
            double score = score(card, tokens, queryVector);
            if (query.isEmpty()) score = 10;
            if (score > 0) results.add(new SearchResult(card, score));
        }

        results.sort(Comparator.comparingDouble((SearchResult result) -> result.score).reversed());
        return results.subList(0, Math.min(Math.max(limit, 1), results.size()));
    }

    public BusinessCard getCard(String cardId) {
        if (cardId == null) return null;
        return cardsById.get(cardId.trim());
    }

    public String engineName() {
        return embeddingEngine.name();
    }

    private double score(BusinessCard card, List<String> tokens, float[] queryVector) {
        String searchableText = card.searchableText();
        double total = 0;

        for (String token : tokens) {
            if (token.length() < 2) continue;
            if (card.name.toLowerCase(Locale.KOREAN).contains(token)) total += 50;
            else if (card.company.toLowerCase(Locale.KOREAN).contains(token)) total += 35;
            else if (card.title.toLowerCase(Locale.KOREAN).contains(token)) total += 25;
            else if (card.industry.toLowerCase(Locale.KOREAN).contains(token)) total += 20;
            else if (searchableText.contains(token)) total += 12;
        }

        for (String tag : state.semanticTags) {
            List<String> related = synonyms.get(tag);
            if (related == null) continue;
            for (String keyword : related) {
                if (searchableText.contains(keyword.toLowerCase(Locale.KOREAN))) {
                    total += 8;
                }
            }
        }

        Float semanticScore = embeddingEngine.cosine(queryVector, cardVectors.get(card.id));
        if (semanticScore != null && semanticScore > SEMANTIC_THRESHOLD) {
            total += semanticScore * SEMANTIC_WEIGHT;
        }

        return total;
    }

    private void updateState(String query) {
        for (String location : Arrays.asList("서울", "부산", "대전", "대구", "광주", "성남", "판교", "제주")) {
            if (query.contains(location.toLowerCase(Locale.KOREAN))) {
                state.location = location;
            }
        }

        if (query.contains("제조")) state.industry = "manufacturing";
        if (query.contains("투자") || query.contains("금융")) state.industry = "finance";
        if (query.contains("개발") || query.contains("it") || query.contains("ai")) state.industry = "it";
        if (query.contains("광고") || query.contains("마케팅")) state.industry = "advertising";
        if (query.contains("교육")) state.industry = "education";
        if (query.contains("운송") || query.contains("물류")) state.industry = "transport";

        if (query.contains("대표") || query.contains("ceo") || query.contains("창업")) state.title = "대표";
        if (query.contains("이사")) state.title = "이사";
        if (query.contains("팀장")) state.title = "팀장";
        if (query.contains("매니저")) state.title = "매니저";

        for (String key : synonyms.keySet()) {
            if (query.contains(key.toLowerCase(Locale.KOREAN))) {
                state.semanticTags.add(key);
            }
        }
    }

    private boolean passesState(BusinessCard card) {
        if (!state.location.isEmpty() && !card.location.contains(state.location)) return false;
        if (!state.industry.isEmpty() && !card.industry.equals(state.industry)) return false;
        if (!state.title.isEmpty() && !card.title.contains(state.title)) return false;
        return true;
    }

    private List<String> expandTokens(String query) {
        Set<String> tokens = new HashSet<>();
        if (!query.isEmpty()) {
            tokens.addAll(Arrays.asList(query.split("\\s+")));
        }

        for (Map.Entry<String, List<String>> entry : synonyms.entrySet()) {
            if (query.contains(entry.getKey().toLowerCase(Locale.KOREAN))) {
                for (String value : entry.getValue()) {
                    tokens.add(value.toLowerCase(Locale.KOREAN));
                }
            }
        }

        return new ArrayList<>(tokens);
    }

    private void installSynonyms() {
        synonyms.put("투자", Arrays.asList("투자", "vc", "스타트업", "IR", "핀테크", "finance"));
        synonyms.put("제조", Arrays.asList("제조", "공장", "생산", "품질", "manufacturing"));
        synonyms.put("세미나", Arrays.asList("세미나", "컨퍼런스", "행사", "AI", "네트워킹"));
        synonyms.put("개발자", Arrays.asList("개발", "엔지니어", "백엔드", "AI", "it"));
        synonyms.put("대표", Arrays.asList("대표", "CEO", "Founder", "창업자"));
        synonyms.put("영업", Arrays.asList("영업", "세일즈", "파트너십", "BD"));
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.KOREAN);
    }

    private String join(List<String> values, String separator) {
        StringBuilder builder = new StringBuilder();
        for (String value : values) {
            if (builder.length() > 0) builder.append(separator);
            builder.append(value);
        }
        return builder.toString();
    }

    private static final class SearchState {
        String location = "";
        String industry = "";
        String title = "";
        final Set<String> semanticTags = new HashSet<>();

        void clear() {
            location = "";
            industry = "";
            title = "";
            semanticTags.clear();
        }
    }
}
