package com.hjp.searchlookup;

import java.util.*;

public final class SearchLookupService implements RetrievalService {
    private static final int RRF_K = 60;
    private static final int RAG_CARD_LIMIT = 5;
    private final BusinessCardRepository repository;
    private final EmbeddingEngine embeddingEngine;
    private final KeywordCandidateSource keywordCandidateSource;
    private final RagContextBuilder ragContextBuilder = new RagContextBuilder();
    private final LightweightTokenizer tokenizer = new LightweightTokenizer();

    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine) { this(new InMemoryBusinessCardRepository(cards), embeddingEngine); }
    public SearchLookupService(List<BusinessCard> cards, EmbeddingEngine embeddingEngine, Map<String,float[]> vectors, RerankerEngine unused) { this(cards, embeddingEngine); if(vectors!=null) for(BusinessCard c:cards) repository.upsertEmbedding(new CardEmbedding(c.id,this.embeddingEngine.name(),vectors.get(c.id).length,FloatVectorCodec.toBlob(vectors.get(c.id)),EmbeddingUpdater.sha256(c.searchableText()),System.currentTimeMillis(),System.currentTimeMillis())); }
    public SearchLookupService(BusinessCardRepository repository, EmbeddingEngine embeddingEngine) { this.repository=repository; this.embeddingEngine=embeddingEngine==null?OnDeviceEmbeddingEngine.production():embeddingEngine; this.keywordCandidateSource=new InMemoryKeywordCandidateSource(repository.getAllCards(), tokenizer); EmbeddingUpdater updater=new EmbeddingUpdater(repository,this.embeddingEngine); for(BusinessCard c:repository.getAllCards()) updater.refreshIfNeeded(c); }

    public List<SearchResult> search(String rawQuery, int limit) { return retrieve(rawQuery, limit).results; }
    public List<SearchResult> searchCardTab(String rawQuery, SortOption sortOption, int limit) { return limit(keywordOnly(rawQuery, Integer.MAX_VALUE), limit); }
    public RetrievalResponse retrieveForAgent(String rawQuery, AgentSessionState session, int limit) { RetrievalResponse r=retrieve(rawQuery,limit); (session==null?new AgentSessionState():session).updateLastSearch(r.query,r.results); return r; }
    @Override public RetrievalResponse retrieve(String rawQuery, int topK) { return retrieve(rawQuery, topK, RetrievalMode.HYBRID); }
    public RetrievalResponse retrieve(String rawQuery, int topK, RetrievalMode mode) {
        String query=tokenizer.normalize(rawQuery); int safe=Math.max(1,topK);
        List<SearchResult> keyword=keywordOnly(query,Integer.MAX_VALUE);
        List<SearchResult> semantic=semanticOnly(query,Integer.MAX_VALUE);
        List<SearchResult> fused = mode==RetrievalMode.KEYWORD_ONLY ? keyword : mode==RetrievalMode.SEMANTIC_ONLY ? semantic : fuse(keyword, semantic);
        fused=rank(limit(fused,safe));
        String rag=ragContextBuilder.build(query,fused,Math.min(RAG_CARD_LIMIT,safe));
        boolean fb=embeddingEngine instanceof OnDeviceEmbeddingEngine && ((OnDeviceEmbeddingEngine)embeddingEngine).isFallbackUsed();
        return new RetrievalResponse(query,fused,rag,mode.name(),embeddingEngine.name(),keyword.size(),semantic.size(),fb);
    }
    @Override public BusinessCard getCard(String cardId){ return repository.getCard(cardId==null?null:cardId.trim()); }
    public String engineName(){ return embeddingEngine.name(); }

    private List<SearchResult> keywordOnly(String query,int limit){ return rank(keywordCandidateSource.searchKeyword(query,limit)); }
    private List<SearchResult> semanticOnly(String query,int limit){ float[] q=embeddingEngine.embed(query); CosineSimilarity.normalizeInPlace(q); List<SearchResult> out=new ArrayList<>(); for(CardEmbedding e:repository.getEmbeddings(embeddingEngine.name())){ BusinessCard c=repository.getCard(e.cardId); Float sim=CosineSimilarity.cosine(q,e.vector()); if(c!=null&&sim!=null) out.add(new SearchResult(c,sim,new ScoreBreakdown(0,sim,0,0,sim),Arrays.asList("semantic"),0,sim,0)); } out.sort(Comparator.comparingDouble((SearchResult r)->r.similarity).reversed()); return rank(limit(out,limit)); }
    private List<SearchResult> fuse(List<SearchResult> keyword,List<SearchResult> semantic){ Map<String,Double> scores=new LinkedHashMap<>(); Map<String,BusinessCard> cards=new HashMap<>(); Map<String,Double> sims=new HashMap<>(); Map<String,Set<String>> src=new HashMap<>(); add(scores,cards,sims,src,keyword,"keyword"); add(scores,cards,sims,src,semantic,"semantic"); List<SearchResult> out=new ArrayList<>(); for(String id:scores.keySet()){ double s=scores.get(id); out.add(new SearchResult(cards.get(id),s,new ScoreBreakdown(0,sims.getOrDefault(id,0.0),0,0,s),new ArrayList<>(src.get(id)),0,sims.getOrDefault(id,0.0),s)); } out.sort(Comparator.comparingDouble((SearchResult r)->r.rankFusionScore).reversed()); return out; }
    private void add(Map<String,Double> scores,Map<String,BusinessCard> cards,Map<String,Double> sims,Map<String,Set<String>> src,List<SearchResult> list,String source){ for(int i=0;i<list.size();i++){ SearchResult r=list.get(i); scores.put(r.cardId,scores.getOrDefault(r.cardId,0.0)+1.0/(RRF_K+i+1)); cards.put(r.cardId,r.card); sims.put(r.cardId,Math.max(sims.getOrDefault(r.cardId,0.0),r.similarity)); src.computeIfAbsent(r.cardId,k->new LinkedHashSet<>()).add(source); } }
    private List<SearchResult> rank(List<SearchResult> in){ List<SearchResult> out=new ArrayList<>(); for(int i=0;i<in.size();i++) out.add(in.get(i).withRank(i+1)); return Collections.unmodifiableList(out); }
    private List<SearchResult> limit(List<SearchResult> r,int l){ if(r==null||l<=0)return Collections.emptyList(); return new ArrayList<>(r.subList(0,Math.min(l,r.size()))); }
}
