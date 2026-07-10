package com.example.hjp.search

import android.content.Context
import android.os.Build
import com.example.hjp.data.BusinessCardEntity
import com.example.hjp.data.CardEmbeddingEntity
import com.example.hjp.data.HjpDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.system.measureTimeMillis

data class CardSearchHit(
    val card: BusinessCardEntity,
    val score: Double,
    val keywordRank: Int?,
    val vectorRank: Int?,
    val similarity: Float,
)

data class CardSearchResponse(
    val query: String,
    val engine: String,
    val results: List<CardSearchHit>,
) {
    fun ragContext(limit: Int = 5): String =
        results.take(limit).joinToString("\n\n") { it.card.ragContext() }

    fun toJson(): JSONObject {
        val cards = JSONArray()
        results.forEach { hit ->
            cards.put(
                JSONObject()
                    .put("card_id", hit.card.id)
                    .put("name", hit.card.name)
                    .put("company", hit.card.company)
                    .put("title", hit.card.title)
                    .put("department", hit.card.department)
                    .put("industry", hit.card.industry)
                    .put("location", hit.card.location)
                    .put("score", hit.score)
                    .put("keyword_rank", hit.keywordRank ?: JSONObject.NULL)
                    .put("vector_rank", hit.vectorRank ?: JSONObject.NULL)
                    .put("similarity", hit.similarity.toDouble())
                    .put("context", hit.card.ragContext())
            )
        }
        return JSONObject()
            .put("query", query)
            .put("engine", engine)
            .put("retrieval", "room_fts_plus_embeddinggemma_rrf")
            .put("cards", cards)
            .put("rag_context", ragContext())
    }
}

class CardSearchService(
    context: Context,
) {
    private val appContext = context.applicationContext
    private val mediaPipeProvider = MediaPipeEmbeddingGemmaProvider(context)
    private val embeddingProvider: TextEmbeddingProvider = mediaPipeProvider
    private val dao = HjpDatabase.getInstance(context).businessCardDao()

    val engineStatus: String
        get() = "${embeddingProvider.name} / Room FTS"

    fun diagnostics(): JSONObject {
        seedIfEmpty()
        var dimensions = 0
        var elapsedMs = 0L
        val error = try {
            if (embeddingProvider.isModelBacked) {
                elapsedMs = measureTimeMillis {
                    dimensions = embeddingProvider.embed("AI developer in Pangyo").size
                }
            }
            ""
        } catch (e: Throwable) {
            e.javaClass.simpleName + ": " + e.message.orEmpty()
        }
        return JSONObject()
            .put("active_embedding_provider", embeddingProvider.name)
            .put("active_embedding_model_backed", embeddingProvider.isModelBacked)
            .put("active_embedding_status", embeddingProvider.diagnosticStatus)
            .put("mediapipe_attempt", mediaPipeProvider.name)
            .put("mediapipe_model_backed", mediaPipeProvider.isModelBacked)
            .put("mediapipe_status", mediaPipeProvider.diagnosticStatus)
            .put("embedding_dimensions", dimensions)
            .put("sample_embedding_ms", elapsedMs)
            .put("room_card_count", dao.countCards())
            .put("device_abis", JSONArray(Build.SUPPORTED_ABIS.toList()))
            .put("internal_models_dir", java.io.File(appContext.filesDir, "models").absolutePath)
            .put("external_models_dir", appContext.getExternalFilesDir("models")?.absolutePath ?: "")
            .put("error", error)
    }

    fun seedIfEmpty() {
        if (dao.countCards() > 0) return
        dao.clearFts()
        dao.upsertCards(sampleCards())
    }

    fun indexEmbeddings() {
        seedIfEmpty()
        requireEmbeddingModel()
        dao.allCards().forEach { card ->
            val text = card.searchableText()
            val hash = sha256(text)
            val existing = dao.findEmbedding(card.id, embeddingProvider.name, hash)
            if (existing == null) {
                val vector = embeddingProvider.embed(text)
                if (vector.isNotEmpty()) {
                    dao.upsertEmbedding(
                        CardEmbeddingEntity(
                            card.id,
                            embeddingProvider.name,
                            vector.toBlob(),
                            vector.size,
                            hash,
                            System.currentTimeMillis()
                        )
                    )
                }
            }
        }
    }

    fun search(rawQuery: String, limit: Int = 5): CardSearchResponse {
        seedIfEmpty()
        requireEmbeddingModel()
        indexEmbeddings()
        val query = rawQuery.trim().lowercase(Locale.KOREAN)
        val safeLimit = limit.coerceIn(1, 20)
        val keywordIds = keywordIds(query, 40)
        val queryVector = embeddingProvider.embed(query)
        val vectorScores = if (queryVector.isNotEmpty()) vectorScores(queryVector, 40) else emptyList()

        val keywordRank = keywordIds.mapIndexed { index, id -> id to index + 1 }.toMap()
        val vectorRank = vectorScores.mapIndexed { index, hit -> hit.first to index + 1 }.toMap()
        val similarityById = vectorScores.toMap()
        val candidateIds = LinkedHashSet<String>().apply {
            addAll(keywordIds)
            addAll(vectorScores.map { it.first })
        }
        if (candidateIds.isEmpty()) candidateIds.addAll(dao.allCards().map { it.id })

        val hits = candidateIds.mapNotNull { id ->
            val card = dao.findCard(id) ?: return@mapNotNull null
            val score = rrf(keywordRank[id]) + rrf(vectorRank[id])
            CardSearchHit(card, score, keywordRank[id], vectorRank[id], similarityById[id] ?: 0f)
        }.sortedWith(
            compareByDescending<CardSearchHit> { it.score }
                .thenByDescending { it.similarity }
                .thenBy { it.card.name }
        ).take(safeLimit)

        return CardSearchResponse(query, engineStatus, hits)
    }

    private fun keywordIds(query: String, limit: Int): List<String> {
        if (query.isBlank()) return dao.allCards().take(limit).map { it.id }
        val match = query.split(Regex("\\s+"))
            .map { it.trim().replace("\"", "\"\"") }
            .filter { it.length >= 2 }
            .joinToString(" OR ") { "\"$it\"" }
        val ids = try {
            if (match.isBlank()) emptyList() else dao.searchFtsIds(match, limit)
        } catch (_: Throwable) {
            emptyList()
        }
        if (ids.isNotEmpty()) return ids
        return query.split(Regex("\\s+"))
            .flatMap { token -> if (token.length >= 2) dao.searchLikeIds("%$token%", limit) else emptyList() }
            .distinct()
            .take(limit)
    }

    private fun vectorScores(queryVector: FloatArray, limit: Int): List<Pair<String, Float>> =
        dao.embeddingsForModel(embeddingProvider.name)
            .mapNotNull { embedding ->
                val vector = embedding.vector.toFloatArray(embedding.dimensions)
                embedding.cardId to cosine(queryVector, vector)
            }
            .sortedByDescending { it.second }
            .take(limit)

    private fun rrf(rank: Int?): Double = if (rank == null) 0.0 else 1.0 / (60.0 + rank)

    private fun requireEmbeddingModel() {
        if (!embeddingProvider.isModelBacked) {
            throw IllegalStateException(
                "EmbeddingGemma is required but not loaded: ${embeddingProvider.diagnosticStatus}"
            )
        }
    }

    private fun sampleCards(): List<BusinessCardEntity> = listOf(
        BusinessCardEntity(
            "C001", "김지원", "Jiwon Kim", "비전글로벌", "대표이사", "전략팀",
            "business", "서울", "010-0000-0001", "jiwon@example.com", "서울 강남구",
            "스타트업 투자와 파트너십 미팅에서 만난 대표", "대표, 투자, 파트너십",
            System.currentTimeMillis()
        ),
        BusinessCardEntity(
            "C002", "오성령", "Sungryung Oh", "코어AI", "AI 엔지니어", "AI 개발팀",
            "it", "판교", "010-0000-0002", "ai@example.com", "경기도 성남시",
            "EmbeddingGemma와 로컬 벡터 검색을 실험 중", "AI, 개발자, 임베딩, 검색",
            System.currentTimeMillis()
        ),
        BusinessCardEntity(
            "C003", "박민수", "Minsu Park", "네오팩토리", "품질 팀장", "제조혁신팀",
            "manufacturing", "부산", "010-0000-0003", "factory@example.com", "부산 해운대구",
            "스마트공장 품질 검사 프로젝트 담당", "제조, 품질, 스마트공장",
            System.currentTimeMillis()
        )
    )
}
