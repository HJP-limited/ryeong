package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class RetrievalResponse {
    public final String query;
    public final List<SearchResult> results;
    public final String ragContext;
    public final String engineName;
    public final String rerankerName;

    public RetrievalResponse(String query, List<SearchResult> results, String ragContext,
            String engineName, String rerankerName) {
        this.query = query == null ? "" : query;
        this.results = Collections.unmodifiableList(new ArrayList<>(results == null ? Collections.emptyList() : results));
        this.ragContext = ragContext == null ? "" : ragContext;
        this.engineName = engineName == null ? "" : engineName;
        this.rerankerName = rerankerName == null ? "" : rerankerName;
    }
}
