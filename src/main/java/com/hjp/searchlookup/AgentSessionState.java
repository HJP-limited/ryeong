package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class AgentSessionState {
    private String lastQuery = "";
    private List<SearchResult> lastSearchResults = Collections.emptyList();
    private String lastSelectedCardId = "";

    public void updateLastSearch(String query, List<SearchResult> results) {
        lastQuery = query == null ? "" : query;
        lastSearchResults = Collections.unmodifiableList(new ArrayList<>(results == null ? Collections.emptyList() : results));
    }

    public List<SearchResult> getLastSearchResults() {
        return lastSearchResults;
    }

    public void setLastSelectedCardId(String cardId) {
        lastSelectedCardId = cardId == null ? "" : cardId.trim();
    }

    public String getLastSelectedCardId() {
        return lastSelectedCardId;
    }

    public String getLastQuery() {
        return lastQuery;
    }

    public void clear() {
        lastQuery = "";
        lastSearchResults = Collections.emptyList();
        lastSelectedCardId = "";
    }

    public String resolveReferencedCardId(String query) {
        String normalized = query == null ? "" : query.replaceAll("\\s+", "");
        int index = -1;
        if (normalized.contains("첫번째") || normalized.contains("1번")) index = 0;
        else if (normalized.contains("두번째") || normalized.contains("2번")) index = 1;
        else if (normalized.contains("세번째") || normalized.contains("3번")) index = 2;

        if (index >= 0 && index < lastSearchResults.size()) {
            SearchResult result = lastSearchResults.get(index);
            if (result != null && result.cardId != null && !result.cardId.isEmpty()) return result.cardId;
        }
        return lastSelectedCardId == null ? "" : lastSelectedCardId;
    }
}
