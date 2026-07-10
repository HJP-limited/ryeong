package com.example.hjp.search

import com.example.hjp.data.BusinessCardEntity
import java.util.Locale

data class AnalyzedSearchQuery(
    val raw: String,
    val normalized: String,
    val keywordTokens: List<String>,
    val ngramTokens: List<String>,
    val ftsTerms: List<String>,
    val keywordQuery: String,
    val semanticQuery: String,
)

object KeywordSearchRanker {
    private val stopWords = setOf(
        "찾아줘", "찾아", "알려줘", "있는", "사람", "명함", "연락처", "누구",
        "please", "find", "show", "me", "who", "is", "are", "the", "a", "an"
    )

    fun analyze(rawQuery: String): AnalyzedSearchQuery {
        val raw = rawQuery.trim()
        val normalized = normalize(raw)
        val tokens = normalized.split(Regex("\\s+"))
            .map { it.trim() }
            .filter { it.length >= 2 }
            .filterNot { it in stopWords }
            .distinct()
        val ngrams = tokens
            .filter { it.length >= 3 && containsHangul(it) }
            .flatMap { token -> token.windowed(2, 1) }
            .distinct()
        val ftsTerms = (tokens + ngrams).distinct()
        return AnalyzedSearchQuery(
            raw = raw,
            normalized = normalized,
            keywordTokens = tokens,
            ngramTokens = ngrams,
            ftsTerms = ftsTerms,
            keywordQuery = tokens.joinToString(" "),
            semanticQuery = normalized.ifBlank { raw },
        )
    }

    fun score(card: BusinessCardEntity, query: AnalyzedSearchQuery): Double {
        if (query.keywordTokens.isEmpty()) return 1.0
        val normalizedText = normalize(card.searchableText())
        val textTokens = normalizedText.split(Regex("\\s+")).filter { it.isNotBlank() }.toSet()
        var score = 0.0
        query.keywordTokens.forEach { token ->
            score += when {
                token in textTokens -> 40.0
                textTokens.any { it.startsWith(token) } -> 25.0
                normalizedText.contains(token) -> 12.0
                else -> 0.0
            }
        }
        query.ngramTokens.forEach { ngram ->
            if (ngram in textTokens || normalizedText.contains(ngram)) score += 4.0
        }
        return score
    }

    fun normalize(raw: String): String =
        raw.lowercase(Locale.KOREAN)
            .replace(Regex("[^\\p{L}\\p{N}\\s@._+-]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()

    fun containsHangul(value: String): Boolean =
        value.any { char -> Character.UnicodeScript.of(char.code) == Character.UnicodeScript.HANGUL }
}
