package com.hjp.searchlookup;

import java.util.*;

public final class SqliteFts5KeywordRetriever implements KeywordRetriever {
    @Override public List<SearchResult> retrieve(QueryAnalysis analysis, int topK) {
        // TODO(raw SQLite): evaluate CREATE VIRTUAL TABLE card_fts USING fts5(searchableText, tokenize='trigram').
        // Keep this behind an adapter because Android/Room support varies by SQLite version and build options.
        return Collections.emptyList();
    }
}
