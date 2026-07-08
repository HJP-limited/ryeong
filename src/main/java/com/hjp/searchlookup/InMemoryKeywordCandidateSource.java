package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public final class InMemoryKeywordCandidateSource implements KeywordCandidateSource {
    private final List<BusinessCard> cards;
    private final LightweightTokenizer tokenizer;

    public InMemoryKeywordCandidateSource(List<BusinessCard> cards) {
        this(cards, new LightweightTokenizer());
    }

    public InMemoryKeywordCandidateSource(List<BusinessCard> cards, LightweightTokenizer tokenizer) {
        this.cards = Collections.unmodifiableList(new ArrayList<>(cards == null ? Collections.emptyList() : cards));
        this.tokenizer = tokenizer == null ? new LightweightTokenizer() : tokenizer;
    }

    @Override
    public List<SearchResult> searchKeyword(String query, int limit) {
        List<String> tokens = tokenizer.tokenize(query);
        List<SearchResult> results = new ArrayList<>();
        for (BusinessCard card : cards) {
            double score = 0.0;
            Set<String> fields = new LinkedHashSet<>();
            String searchableText = card.searchableText();
            for (String token : tokens) {
                if (token.length() < 2) continue;
                if (contains(searchableText, token)) {
                    score += 1.0;
                    fields.add("keyword");
                }
            }
            if (score > 0.0 || tokens.isEmpty()) {
                double finalScore = tokens.isEmpty() ? 1.0 : score / Math.max(1, tokens.size());
                results.add(new SearchResult(card, finalScore, ScoreBreakdown.keywordOnly(finalScore), new ArrayList<>(fields)));
            }
        }
        results.sort(Comparator.comparingDouble((SearchResult result) -> result.score).reversed());
        int size = limit <= 0 ? results.size() : Math.min(limit, results.size());
        return Collections.unmodifiableList(new ArrayList<>(results.subList(0, size)));
    }

    private boolean contains(String value, String token) {
        if (value == null || token == null) return false;
        return value.toLowerCase(Locale.KOREAN).contains(token.toLowerCase(Locale.KOREAN));
    }

}
