package com.hjp.searchlookup;

import java.util.Arrays;
import java.util.List;

public final class SearchExample {
    private SearchExample() {
    }

    public static void main(String[] args) {
        List<BusinessCard> cards = Arrays.asList(
                new BusinessCard(
                        "C001",
                        "김지원",
                        "Jiwon Kim",
                        "비전글로벌",
                        "대표이사",
                        "전략팀",
                        "business",
                        "서울",
                        "010-0000-0001",
                        "jiwon@example.com",
                        "서울특별시 강남구",
                        "스타트업 투자와 파트너십 미팅에서 만난 대표",
                        Arrays.asList("대표", "투자", "파트너십")
                ),
                new BusinessCard(
                        "C002",
                        "오성령",
                        "Sungryung Oh",
                        "코어AI",
                        "AI 엔지니어",
                        "플랫폼팀",
                        "it",
                        "판교",
                        "010-0000-0002",
                        "ai@example.com",
                        "경기도 성남시",
                        "EmbeddingGemma와 로컬 벡터 검색을 실험 중",
                        Arrays.asList("AI", "개발자", "임베딩", "검색")
                )
        );

        SearchLookupService service = new SearchLookupService(cards, new LocalEmbeddingEngine());
        for (SearchResult result : service.search("AI 개발팀 사람", 5)) {
            System.out.printf("%s %s %.2f%n", result.card.id, result.card.name, result.score);
        }
    }
}
