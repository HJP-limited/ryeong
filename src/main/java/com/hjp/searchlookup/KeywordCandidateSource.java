package com.hjp.searchlookup;

import java.util.List;

public interface KeywordCandidateSource {
    List<SearchResult> searchKeyword(String query, int limit);
}
