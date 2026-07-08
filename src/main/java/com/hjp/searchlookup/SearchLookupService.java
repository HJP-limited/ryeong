package com.hjp.searchlookup;

import java.util.*;

public final class SearchLookupService implements RetrievalService {
    private static final int RAG_CARD_LIMIT = 5;
    private final BusinessCardRepository repository;
    private final EmbeddingEngine embeddingEngine;
    private final QueryAnalyzer queryAnalyzer = new QueryAnalyzer();
    private final KeywordRetriever cardTabKeywordRetriever;
    private final KeywordRetriever agentKeywordRetriever;
    private final SemanticRetriever semanticRetriever;
    private final ReciprocalRankFusion rankFusion = new ReciprocalRankFusion();
    private final RagContextBuilder ragContextBuilder = new RagContextBuilder();

    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine) { this(new InMemoryBusinessCardRepository(cards), embeddingEngine); }
    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine, Map<String,float[]> vectors, RerankerEngine unused) { this(cards, embeddingEngine); if(vectors!=null) for(BusinessCard c:cards) { float[] v=vectors.get(c.id); if(v!=null) repository.upsertEmbedding(new CardEmbedding(c.id,this.embeddingEngine.name(),v.length,FloatVectorCodec.toBlob(v),EmbeddingUpdater.sha256(c.searchableText()),System.currentTimeMillis(),System.currentTimeMillis())); } }
    public SearchLookupService(BusinessCardRepository repository, EmbeddingEngine embeddingEngine) {
        this.repository=repository; this.embeddingEngine=embeddingEngine==null?OnDeviceEmbeddingEngine.production():embeddingEngine;
        this.cardTabKeywordRetriever = new LikeFallbackKeywordRetriever(repository);
        this.agentKeywordRetriever = new LikeFallbackKeywordRetriever(repository);
        this.semanticRetriever = new SemanticRetriever(repository, this.embeddingEngine);
        EmbeddingUpdater updater=new EmbeddingUpdater(repository,this.embeddingEngine); for(BusinessCard c:repository.getAllCards()) updater.refreshIfNeeded(c);
    }

    public List<SearchResult> search(String rawQuery, int limit) { return searchCardTab(rawQuery, SortOption.RELEVANCE, limit); }
    public List<SearchResult> searchCardTab(String rawQuery, SortOption sortOption, int limit) { return cardTabKeywordRetriever.retrieve(queryAnalyzer.analyze(rawQuery), limit); }
    public RetrievalResponse retrieveForAgent(String rawQuery, AgentSessionState session, int limit) { RetrievalResponse r=retrieve(rawQuery,limit); (session==null?new AgentSessionState():session).updateLastSearch(r.query,r.results); return r; }
    @Override public RetrievalResponse retrieve(String rawQuery, int topK) { return retrieve(rawQuery, topK, RetrievalMode.HYBRID); }
    public RetrievalResponse retrieve(String rawQuery, int topK, RetrievalMode mode) {
        int safe=Math.max(1,topK); RetrievalMode actual=mode==null?RetrievalMode.HYBRID:mode; QueryAnalysis analysis=queryAnalyzer.analyze(rawQuery);
        List<SearchResult> keyword = actual==RetrievalMode.SEMANTIC_ONLY ? Collections.emptyList() : agentKeywordRetriever.retrieve(analysis, Integer.MAX_VALUE);
        List<SearchResult> semantic = actual==RetrievalMode.KEYWORD_ONLY ? Collections.emptyList() : semanticRetriever.retrieve(analysis, Integer.MAX_VALUE);
        List<SearchResult> results = actual==RetrievalMode.KEYWORD_ONLY ? limit(keyword,safe) : actual==RetrievalMode.SEMANTIC_ONLY ? limit(semantic,safe) : rankFusion.fuse(keyword, semantic, safe);
        String rag= actual==RetrievalMode.KEYWORD_ONLY ? "" : ragContextBuilder.build(analysis.normalizedQuery,results,Math.min(RAG_CARD_LIMIT,safe));
        boolean fb=embeddingEngine instanceof OnDeviceEmbeddingEngine && ((OnDeviceEmbeddingEngine)embeddingEngine).isFallbackUsed();
        return new RetrievalResponse(analysis.normalizedQuery,results,rag,actual,embeddingEngine.name(),keyword.size(),semantic.size(),fb,analysis);
    }
    @Override public BusinessCard getCard(String cardId){ return repository.getCard(cardId==null?null:cardId.trim()); }
    public String engineName(){ return embeddingEngine.name(); }
    public QueryAnalysis analyzeQuery(String rawQuery){ return queryAnalyzer.analyze(rawQuery); }
    public List<SearchResult> retrieveKeywordCandidates(String rawQuery, int topK){ return agentKeywordRetriever.retrieve(queryAnalyzer.analyze(rawQuery), topK); }
    public List<SearchResult> retrieveSemanticCandidates(String rawQuery, int topK){ return semanticRetriever.retrieve(queryAnalyzer.analyze(rawQuery), topK); }
    private List<SearchResult> limit(List<SearchResult> r,int l){ if(r==null||l<=0)return Collections.emptyList(); return Collections.unmodifiableList(new ArrayList<>(r.subList(0,Math.min(l,r.size())))); }
}
