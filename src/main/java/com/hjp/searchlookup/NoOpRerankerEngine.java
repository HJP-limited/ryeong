package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class NoOpRerankerEngine implements RerankerEngine {
    @Override
    public List<SearchResult> rerank(String query, List<SearchResult> candidates, int limit) {
        if (candidates == null || candidates.isEmpty() || limit <= 0) return Collections.emptyList();
        int size = Math.min(limit, candidates.size());
        return Collections.unmodifiableList(new ArrayList<>(candidates.subList(0, size)));
    }

    @Override
    public String name() {
        return "NoOpRerankerEngine";
    }

    @Override
    public boolean isModelBacked() {
        return false;
    }
}
