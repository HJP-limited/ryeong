package com.example.hjp.search

import com.example.hjp.data.BusinessCardEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KeywordSearchRankerTest {
    private val jiwon = card(
        id = "C001",
        name = "김지원",
        nameEn = "Jiwon Kim",
        company = "비전글로벌",
        title = "AI 개발자",
        department = "플랫폼팀",
        location = "판교",
        phone = "010-1234-5678",
        email = "jiwon@example.com",
        memo = "스타트업 파트너십 미팅",
        tags = "AI, 개발자, 판교",
    )

    private val minsu = card(
        id = "C002",
        name = "박민수",
        nameEn = "Minsu Park",
        company = "오토팩토리",
        title = "품질 관리자",
        department = "제조혁신팀",
        location = "부산",
        phone = "010-9999-1111",
        email = "factory@example.com",
        memo = "스마트공장 프로젝트 담당",
        tags = "제조, 품질",
    )

    @Test
    fun analyze_removes_command_words_but_keeps_search_terms() {
        val query = KeywordSearchRanker.analyze("판교에 있는 AI 개발자 찾아줘")

        assertTrue(query.keywordTokens.contains("판교에"))
        assertTrue(query.keywordTokens.contains("ai"))
        assertTrue(query.keywordTokens.contains("개발자"))
        assertTrue(query.ngramTokens.contains("개발"))
        assertTrue(query.ngramTokens.contains("발자"))
        assertTrue("찾아줘" !in query.keywordTokens)
    }

    @Test
    fun searchable_text_contains_normalized_and_bigram_terms() {
        val text = jiwon.searchableText()

        assertTrue(text.contains("비전글로벌"))
        assertTrue(text.contains("비전"))
        assertTrue(text.contains("전글"))
        assertTrue(text.contains("지원"))
        assertTrue(text.contains("010-1234-5678"))
        assertTrue(text.contains("jiwon@example.com"))
    }

    @Test
    fun partial_korean_query_scores_expected_card_higher() {
        val query = KeywordSearchRanker.analyze("지원")

        assertTrue(KeywordSearchRanker.score(jiwon, query) > 0.0)
        assertEquals(0.0, KeywordSearchRanker.score(minsu, query), 0.0)
    }

    @Test
    fun company_partial_query_uses_bigrams_without_field_weighting() {
        val query = KeywordSearchRanker.analyze("비전")

        assertTrue(KeywordSearchRanker.score(jiwon, query) > KeywordSearchRanker.score(minsu, query))
    }

    @Test
    fun spaced_and_unspaced_job_queries_match() {
        val spaced = KeywordSearchRanker.analyze("AI 개발자")
        val compact = KeywordSearchRanker.analyze("AI개발자")

        assertTrue(KeywordSearchRanker.score(jiwon, spaced) > 0.0)
        assertTrue(KeywordSearchRanker.score(jiwon, compact) > 0.0)
    }

    @Test
    fun phone_and_email_are_searchable() {
        assertTrue(KeywordSearchRanker.score(jiwon, KeywordSearchRanker.analyze("1234")) > 0.0)
        assertTrue(KeywordSearchRanker.score(jiwon, KeywordSearchRanker.analyze("example.com")) > 0.0)
    }

    private fun card(
        id: String,
        name: String,
        nameEn: String,
        company: String,
        title: String,
        department: String,
        location: String,
        phone: String,
        email: String,
        memo: String,
        tags: String,
    ) = BusinessCardEntity(
        id,
        name,
        nameEn,
        company,
        title,
        department,
        "business",
        location,
        phone,
        email,
        "$location 오피스",
        memo,
        tags,
        1L,
    )
}
