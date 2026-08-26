package com.hjp.searchlookup;

import java.util.*;

public final class SemanticRetriever {
    private final BusinessCardRepository repository;
    private final EmbeddingEngine embeddingEngine;
    public SemanticRetriever(BusinessCardRepository repository, EmbeddingEngine embeddingEngine) { this.repository=repository; this.embeddingEngine=embeddingEngine; }
    public List<SearchResult> retrieve(QueryAnalysis analysis, int topK) {
        String query = analysis == null ? "" : analysis.semanticQuery;
        float[] q=embeddingEngine.embed(query); CosineSimilarity.normalizeInPlace(q);
        List<SearchResult> out=new ArrayList<>();
        for(CardEmbedding e:repository.getEmbeddings(embeddingEngine.name())){ BusinessCard c=repository.getCard(e.cardId); Float sim=CosineSimilarity.cosine(q,e.vector()); if(c!=null&&sim!=null) out.add(new SearchResult(c,sim,new ScoreBreakdown(0,sim,0,0,sim),Arrays.asList("semantic"),0,sim,0)); }
        out.sort(Comparator.comparingDouble((SearchResult r)->r.similarity).reversed());
        List<SearchResult> ranked=new ArrayList<>(); for(int i=0;i<out.size();i++) ranked.add(out.get(i).withRank(i+1));
        if(topK>0 && ranked.size()>topK) ranked = new ArrayList<>(ranked.subList(0, topK));
        return Collections.unmodifiableList(ranked);
    }
}
