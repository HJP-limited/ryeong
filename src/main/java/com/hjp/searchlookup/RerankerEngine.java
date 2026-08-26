package com.hjp.searchlookup;

import java.util.List;

public interface RerankerEngine {
    List<SearchResult> rerank(String query, List<SearchResult> candidates, int limit);

    String name();

    boolean isModelBacked();
}
