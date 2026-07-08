package com.hjp.searchlookup;
import java.util.*;
public final class RetrievalResponse {
 public final String query, ragContext, retrievalMode, embeddingModelName, engineName, rerankerName; public final List<SearchResult> results; public final List<String> cardIds; public final int keywordResultCount, semanticResultCount; public final boolean fallbackUsed;
 public RetrievalResponse(String query,List<SearchResult> results,String ragContext,String retrievalMode,String embeddingModelName,int keywordResultCount,int semanticResultCount,boolean fallbackUsed){ this.query=query==null?"":query; this.results=Collections.unmodifiableList(new ArrayList<>(results==null?Collections.emptyList():results)); List<String> ids=new ArrayList<>(); for(SearchResult r:this.results) ids.add(r.cardId); this.cardIds=Collections.unmodifiableList(ids); this.ragContext=ragContext==null?"":ragContext; this.retrievalMode=retrievalMode; this.embeddingModelName=embeddingModelName; this.engineName=embeddingModelName; this.rerankerName="rank-fusion"; this.keywordResultCount=keywordResultCount; this.semanticResultCount=semanticResultCount; this.fallbackUsed=fallbackUsed; }
 public RetrievalResponse(String query,List<SearchResult> results,String ragContext,String engineName,String rerankerName){ this(query,results,ragContext,RetrievalMode.HYBRID.name(),engineName,0,0,false); }
}
