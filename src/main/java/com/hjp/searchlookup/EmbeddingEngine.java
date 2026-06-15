package com.hjp.searchlookup;

public interface EmbeddingEngine {
    float[] embed(String input);

    default float[] embedCard(BusinessCard card) {
        return embed(card.searchableText());
    }

    default Float cosine(float[] a, float[] b) {
        if (a == null || b == null || a.length == 0 || a.length != b.length) return null;
        float dot = 0f;
        for (int i = 0; i < a.length; i++) {
            dot += a[i] * b[i];
        }
        return dot;
    }

    String name();

    boolean isModelBacked();
}
