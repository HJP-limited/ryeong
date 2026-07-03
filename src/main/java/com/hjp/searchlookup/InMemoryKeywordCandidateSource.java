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
            for (String token : tokens) {
                if (token.length() < 2) continue;
                FieldMatch match = firstMatch(card, token);
                if (match != null) {
                    score += match.weight;
                    fields.add(match.name);
                }
            }
            if (score > 0.0 || tokens.isEmpty()) {
                double finalScore = tokens.isEmpty() ? 1.0 : score;
                results.add(new SearchResult(card, finalScore, ScoreBreakdown.keywordOnly(finalScore), new ArrayList<>(fields)));
            }
        }
        results.sort(Comparator.comparingDouble((SearchResult result) -> result.score).reversed());
        int size = limit <= 0 ? results.size() : Math.min(limit, results.size());
        return Collections.unmodifiableList(new ArrayList<>(results.subList(0, size)));
    }

    private FieldMatch firstMatch(BusinessCard card, String token) {
        if (contains(card.name, token)) return new FieldMatch("name", 50.0);
        if (contains(card.company, token)) return new FieldMatch("company", 35.0);
        if (contains(card.title, token)) return new FieldMatch("title", 25.0);
        if (contains(card.industry, token)) return new FieldMatch("industry", 20.0);
        if (contains(card.searchableText(), token)) return new FieldMatch("searchableText", 12.0);
        return null;
    }

    private boolean contains(String value, String token) {
        if (value == null || token == null) return false;
        return value.toLowerCase(Locale.KOREAN).contains(token.toLowerCase(Locale.KOREAN));
    }

    private static final class FieldMatch {
        final String name;
        final double weight;

        FieldMatch(String name, double weight) {
            this.name = name;
            this.weight = weight;
        }
    }
}
