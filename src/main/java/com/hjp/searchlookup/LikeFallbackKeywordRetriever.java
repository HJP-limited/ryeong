package com.hjp.searchlookup;

import java.util.*;

public final class LikeFallbackKeywordRetriever implements KeywordRetriever {
    private final BusinessCardRepository repository;

    public LikeFallbackKeywordRetriever(BusinessCardRepository repository) { this.repository = repository; }

    @Override public List<SearchResult> retrieve(QueryAnalysis analysis, int topK) {
        List<String> tokens = analysis == null ? Collections.emptyList() : analysis.tokens;
        List<SearchResult> results = new ArrayList<>();
        for (BusinessCard card : repository.getAllCards()) {
            String text = card.searchableText();
            int matches = 0;
            for (String token : tokens) if (token.length() >= 2 && text.contains(token.toLowerCase(Locale.ROOT))) matches++;
            if (tokens.isEmpty() || matches > 0) {
                double score = tokens.isEmpty() ? 1.0 : (double) matches / Math.max(1, tokens.size());
                // Weak UX tie-breaker only; hybrid ranking uses list rank via RRF, not this score scale.
                if (card.verified) score += 0.001;
                results.add(new SearchResult(card, score, ScoreBreakdown.keywordOnly(score), Arrays.asList("keyword-like")));
            }
        }
        results.sort(Comparator.comparingDouble((SearchResult r) -> r.score).reversed().thenComparing(r -> r.card.name));
        return limit(rank(results), topK);
    }
    private List<SearchResult> rank(List<SearchResult> in){ List<SearchResult> out=new ArrayList<>(); for(int i=0;i<in.size();i++) out.add(in.get(i).withRank(i+1)); return out; }
    private List<SearchResult> limit(List<SearchResult> r,int l){ if(l<=0)return Collections.unmodifiableList(r); return Collections.unmodifiableList(new ArrayList<>(r.subList(0,Math.min(l,r.size())))); }
}
