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

    // 명사 뒤에 자주 붙는 조사. 형태소 분석 없이 꼬리 제거만으로 대부분의 검색 질의를 처리한다.
    // 긴 것부터 검사해야 "에서"가 "에"보다 먼저 떨어진다.
    private val particles = listOf(
        "에서는", "에서", "에게", "한테", "으로", "이랑", "부터", "까지", "처럼", "밖에",
        "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "만", "랑", "로",
        // 존칭 — "강서연씨"가 "강서연"으로 매칭 안 되던 버그의 원인이었음.
        "씨", "님",
    )

    /** "판교에서" -> "판교" 처럼 조사를 뗀 형태를 돌려준다. 뗄 것이 없으면 원문 그대로. */
    fun stripParticle(token: String): String {
        if (!containsHangul(token)) return token
        for (particle in particles) {
            val stem = token.removeSuffix(particle)
            if (stem !== token && stem.length >= 2 && containsHangul(stem)) return stem
        }
        return token
    }

    fun analyze(rawQuery: String): AnalyzedSearchQuery {
        val raw = rawQuery.trim()
        val normalized = normalize(raw)
        val tokens = normalized.split(Regex("\\s+"))
            .map { it.trim() }
            .filter { it.length >= 2 }
            .filterNot { it in stopWords }
            .flatMap { token -> listOf(token, stripParticle(token)) }
            // "010-1234-5678"을 "01012345678"로도 찾을 수 있게 숫자만 남긴 사본을 추가
            .flatMap { token ->
                val digits = token.filter { it.isDigit() }
                if (digits.length >= 3 && digits != token) listOf(token, digits) else listOf(token)
            }
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
        // 점수는 원본 필드 단어 기준으로 매긴다. searchableText()의 바이그램 조각을 쓰면
        // "삼성로"의 조각 '삼성'이 완전 일치(40점)로 둔갑해 진짜 단어 일치와 구분이 안 된다.
        // (바이그램은 FTS 후보 회수에만 쓰인다)
        val originalText = normalize(
            listOf(
                card.name, card.nameEn, card.company, card.title, card.department, card.industry,
                card.location, card.phone, card.phone.filter { it.isDigit() },
                card.email, card.address, card.memo, card.tags,
            ).joinToString(" ")
        )
        val textTokens = originalText.split(Regex("\\s+")).filter { it.isNotBlank() }.toSet()
        // 필드별 가중치는 넣지 않는다 (팀 결정) — 어떤 필드에서 맞았든 매치 강도로만 점수를 매긴다.
        // 필드 중요도 반영은 하이브리드 검색의 임베딩 쪽이 담당한다 (임베딩 입력에 주소는 제외돼 있음).
        var score = 0.0
        query.keywordTokens.forEach { token ->
            score += when {
                token in textTokens -> 40.0
                textTokens.any { it.startsWith(token) } -> 25.0
                // "판교에서의"처럼 조사 목록에 없는 꼬리가 붙어도 명사 부분이 일치하면 인정
                textTokens.any { it.length >= 2 && token.startsWith(it) } -> 20.0
                originalText.contains(token) -> 12.0
                else -> 0.0
            }
        }
        query.ngramTokens.forEach { ngram ->
            if (originalText.contains(ngram)) score += 4.0
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
