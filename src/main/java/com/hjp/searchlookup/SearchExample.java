package com.hjp.searchlookup;

import java.util.Arrays;
import java.util.List;

public final class SearchExample {
    private SearchExample() {
    }

    public static void main(String[] args) {
        List<BusinessCard> cards = Arrays.asList(
                new BusinessCard("C001", "김지원", "Jiwon Kim", "비전글로벌", "대표이사", "전략팀",
                        "business", "서울", "010-0000-0001", "jiwon@example.com", "서울특별시 강남구",
                        "스타트업 투자와 파트너십 미팅에서 만난 대표", Arrays.asList("대표", "투자", "파트너십"),
                        1_700_000_000_000L, 1_700_000_000_000L, "/images/c001.jpg", "scan", true),
                new BusinessCard("C002", "오성령", "Sungryung Oh", "코어AI", "AI 엔지니어", "AI 개발팀",
                        "it", "판교", "010-0000-0002", "ai@example.com", "경기도 성남시",
                        "EmbeddingGemma와 로컬 벡터 검색을 실험 중", Arrays.asList("AI", "개발자", "임베딩", "검색"),
                        1_720_000_000_000L, 1_720_100_000_000L, "/images/c002.jpg", "camera", false),
                new BusinessCard("C003", "박민수", "Minsu Park", "네오팩토리", "품질 팀장", "제조혁신팀",
                        "manufacturing", "부산", "010-0000-0003", "factory@example.com", "부산광역시 해운대구",
                        "스마트공장 품질 검사 프로젝트 담당", Arrays.asList("제조", "품질", "스마트공장"),
                        1_710_000_000_000L, 1_710_050_000_000L, "/images/c003.jpg", "import", true)
        );

        SearchLookupService service = new SearchLookupService(cards, new LocalEmbeddingEngine());

        print("Business card tab keyword search", service.searchCardTab("AI 개발", SortOption.RELEVANCE, 5));
        print("Business card tab latest sort", service.searchCardTab("AI 개발", SortOption.LATEST, 5));
        print("Business card tab name sort", service.searchCardTab("AI 개발", SortOption.NAME, 5));
        print("Business card tab company sort", service.searchCardTab("AI 개발", SortOption.COMPANY, 5));

        AgentSessionState session = new AgentSessionState();
        RetrievalResponse response = service.retrieveForAgent("AI 개발팀 사람 찾아줘", session, 5);
        print("Agent hybrid retrieval", response.results);
        System.out.println("\nRAG context:\n" + response.ragContext);

        String referencedCardId = session.resolveReferencedCardId("첫 번째 사람 자세히 보여줘");
        session.setLastSelectedCardId(referencedCardId);
        BusinessCard detail = service.getCard(referencedCardId);
        System.out.println("\nDetailed lookup through getCard(cardId):");
        if (detail != null) {
            System.out.printf("%s %s %s %s %s%n", detail.id, detail.name, detail.phone, detail.email, detail.address);
        }
    }

    private static void print(String title, List<SearchResult> results) {
        System.out.println("\n== " + title + " ==");
        for (SearchResult result : results) {
            System.out.printf("%s %s %s score=%.2f fields=%s%n",
                    result.cardId, result.card.name, result.card.company, result.score, result.matchedFields);
        }
    }
}
