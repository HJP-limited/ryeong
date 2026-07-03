package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class SearchResult {
    public final BusinessCard card;
    public final double score;
    public final String cardId;
    public final ScoreBreakdown breakdown;
    public final List<String> matchedFields;

    public SearchResult(BusinessCard card, double score) {
        this(card, score, new ScoreBreakdown(score, 0.0, 0.0, 0.0, score), Collections.emptyList());
    }

    public SearchResult(BusinessCard card, double score, ScoreBreakdown breakdown, List<String> matchedFields) {
        this.card = card;
        this.score = score;
        this.cardId = card == null ? "" : card.id;
        this.breakdown = breakdown == null ? new ScoreBreakdown(0.0, 0.0, 0.0, 0.0, score) : breakdown;
        this.matchedFields = Collections.unmodifiableList(new ArrayList<>(matchedFields == null ? Collections.emptyList() : matchedFields));
    }
}
