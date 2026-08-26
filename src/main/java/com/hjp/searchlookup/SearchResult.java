package com.hjp.searchlookup;

import java.util.*;

public final class SearchResult {
 public final BusinessCard card; public final double score; public final String cardId,name,company,title; public final int rank; public final List<String> retrievalSources; public final double similarity, rankFusionScore; public final ScoreBreakdown breakdown; public final List<String> matchedFields;
 public SearchResult(BusinessCard card,double score){ this(card,score,new ScoreBreakdown(score,0,0,0,score),Collections.emptyList(),0,0.0,score); }
 public SearchResult(BusinessCard card,double score,ScoreBreakdown breakdown,List<String> sources){ this(card,score,breakdown,sources,0,breakdown==null?0:breakdown.semanticScore,score); }
 public SearchResult(BusinessCard card,double score,ScoreBreakdown breakdown,List<String> sources,int rank,double similarity,double rankFusionScore){ this.card=card; this.score=score; this.cardId=card==null?"":card.id; this.name=card==null?"":card.name; this.company=card==null?"":card.company; this.title=card==null?"":card.title; this.rank=rank; this.retrievalSources=Collections.unmodifiableList(new ArrayList<>(sources==null?Collections.emptyList():sources)); this.matchedFields=this.retrievalSources; this.similarity=similarity; this.rankFusionScore=rankFusionScore; this.breakdown=breakdown==null?new ScoreBreakdown(0,similarity,0,0,score):breakdown; }
 public SearchResult withRank(int newRank){ return new SearchResult(card,score,breakdown,retrievalSources,newRank,similarity,rankFusionScore); }
}
