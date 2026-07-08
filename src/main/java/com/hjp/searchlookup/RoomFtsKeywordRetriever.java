package com.hjp.searchlookup;

import java.util.*;

public final class RoomFtsKeywordRetriever implements KeywordRetriever {
    @Override public List<SearchResult> retrieve(QueryAnalysis analysis, int topK) {
        // TODO(Room DB): connect a Room @Fts4 entity that stores cardId + searchableText.
        // Suggested: FTS4(contentEntity=BusinessCardEntity, tokenizer="unicode61", prefix={2,3,4}).
        // Query MATCH with QueryAnalysis.keywordQuery, join back to business_cards, and use LIKE fallback for unsupported short tokens.
        return Collections.emptyList();
    }
}
