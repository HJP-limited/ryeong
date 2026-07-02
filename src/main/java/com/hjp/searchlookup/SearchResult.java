package com.hjp.searchlookup;

public final class SearchResult {
    public final BusinessCard card;
    public final double score;

    SearchResult(BusinessCard card, double score) {
        this.card = card;
        this.score = score;
    }
}
