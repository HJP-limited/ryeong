package com.example.hjp.search

import android.content.Context
import android.os.Build
import com.example.hjp.data.BusinessCardEntity
import com.example.hjp.data.CardEmbeddingEntity
import com.example.hjp.data.HjpDatabase
import org.json.JSONArray
import org.json.JSONObject
import kotlin.system.measureTimeMillis

// FTS4 MATCH 쿼리 문자열 빌더 — 검색 담당 브랜치의 Fts4QueryBuilder 이식.
private val ftsUnsafeChars = Regex("[^\\p{L}\\p{N}]+")
private val ftsOperators = setOf("AND", "OR", "NOT", "NEAR")

private fun ftsSafeTerms(tokens: List<String>): List<String> =
    tokens.map { it.replace(ftsUnsafeChars, "") }
        .filter { it.isNotBlank() && it.uppercase() !in ftsOperators }

/** 정확 구문 매치(어순·인접 그대로) — 가장 정밀. */
private fun ftsPhraseMatch(terms: List<String>): String? =
    terms.joinToString(" ").takeIf { it.isNotBlank() }?.let { "\"$it\"" }

/** 전체 단어 AND(어순 무관, 인접 불필요). */
private fun ftsAllTermsMatch(terms: List<String>): String? =
    terms.joinToString(" ").takeIf { it.isNotBlank() }

/** 접두어 AND — "강서연씨"처럼 존칭/조사가 붙어도 접두어로 잡힌다(prefix 인덱스 활용). */
private fun ftsPrefixMatch(terms: List<String>): String? =
    terms.filter { it.length >= 2 }
        .joinToString(" ") { "$it*" }
        .takeIf { it.isNotBlank() }

// 키워드 동의어 확장 — sojung 브랜치(ymj/embedding-search-android-eval와 같은 분기점) 참고.
// 키워드는 정확히 그 단어가 있어야만 매치되고 "AI"↔"인공지능" 같은 동의어를 모른다.
// LIKE 폴백(가장 느슨한 티어)에만 적용해서, 정밀한 ①②③ 티어의 정확도는 그대로 두고
// 개념형 질의의 재현율만 싸게 보강한다. 임베딩이 이미 하는 일과 겹치지만, 임베딩이 안 뜨는
// 기기(키워드 전용 폴백)에서도 최소한의 동의어 커버리지를 준다.
private val SYNONYMS: Map<String, List<String>> = mapOf(
    "ai" to listOf("ai", "인공지능", "머신러닝", "개발", "연구"),
    "인공지능" to listOf("ai", "인공지능", "머신러닝", "개발", "연구"),
    "개발" to listOf("개발", "개발자", "엔지니어", "소프트웨어", "it", "ai"),
    "디자인" to listOf("디자인", "디자이너", "브랜드", "크리에이티브"),
    "투자" to listOf("투자", "벤처", "금융", "vc"),
    "영업" to listOf("영업", "세일즈", "파트너십", "비즈니스"),
    "마케팅" to listOf("마케팅", "브랜드", "광고", "홍보"),
    "의료" to listOf("의료", "헬스케어", "제약", "병원"),
    "대표" to listOf("대표", "ceo", "창업", "창업자"),
    "변호사" to listOf("변호사", "법무", "법률"),
    "회계" to listOf("회계", "회계사", "재무", "감사"),
)

/** LIKE 폴백 전용 — 원래 토큰 + 동의어를 합쳐서 돌려준다(중복 제거, 순서 보존). */
private fun expandSynonymsForFallback(terms: List<String>): List<String> {
    val out = LinkedHashSet<String>()
    for (t in terms) {
        out.add(t)
        SYNONYMS[t.lowercase()]?.let { out.addAll(it) }
    }
    return out.toList()
}

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
    val retrieval: String,
    val keywordQuery: String,
    val semanticQuery: String,
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
            .put("retrieval", retrieval)
            .put("keyword_query", keywordQuery)
            .put("semantic_query", semanticQuery)
            .put("cards", cards)
            .put("rag_context", ragContext())
    }
}

class CardSearchService(
    context: Context,
) {
    private val appContext = context.applicationContext
    private var embeddingProvider: TextEmbeddingProvider = GemmaEmbeddingProvider(context)
    private val dao = HjpDatabase.getInstance(context).businessCardDao()
    private var ftsRebuilt = false

    /** 모델 파일을 새로 가져온 뒤 앱 재시작 없이 다시 로드를 시도한다. */
    fun reloadEmbeddingProvider() {
        // 이전 임베더의 네이티브 메모리를 먼저 해제해야 반복 로드 시 메모리가 쌓이지 않는다
        embeddingProvider.close()
        embeddingProvider = GemmaEmbeddingProvider(appContext)
    }

    /** JSON 배열 문자열(명함 목록)로 DB 전체를 교체한다. 기존 임베딩도 함께 지운다. */
    fun importCardsJson(json: String): Int {
        val array = JSONArray(json)
        val now = System.currentTimeMillis()
        val cards = (0 until array.length()).map { i ->
            val o = array.getJSONObject(i)
            BusinessCardEntity(
                o.optString("id").ifBlank { "J%05d".format(i) },
                o.optString("name"),
                o.optString("nameEn"),
                o.optString("company"),
                o.optString("title"),
                o.optString("department"),
                o.optString("industry"),
                o.optString("location"),
                o.optString("phone"),
                o.optString("email"),
                o.optString("address"),
                o.optString("memo"),
                o.optString("tags"),
                now,
            )
        }
        require(cards.isNotEmpty()) { "JSON에 명함이 없습니다." }
        dao.replaceAllCards(cards)
        ftsRebuilt = true
        return cards.size
    }

    val engineStatus: String
        get() = "${embeddingProvider.name} / Room FTS"

    // 어떤 provider 인스턴스가 만들었는지와 무관하게 같은 값을 가리켜야 해서 고정 문자열로 둔다.
    // (provider.name은 로드 상태에 따라 문자열이 바뀌어서 키로 쓰면 안 됨)
    // 임베딩 입력 형식이 바뀌면 버전 접미사를 올려서 기존 벡터가 재계산되게 할 것.
    // query/document 프롬프트 형식은 RAG SDK(GemmaEmbeddingModel)가 자동으로 붙인다.
    private val embeddingModelKey: String = "EmbeddingGemma-300M#doc-v3"

    private fun cardEmbeddingInput(card: BusinessCardEntity): String {
        val parts = listOf(
            card.name, card.nameEn, card.company, card.title, card.department,
            card.industry, card.location, card.memo, card.tags,
        ).filter { it.isNotBlank() }
        return parts.joinToString(", ")
    }

    fun diagnostics(): JSONObject {
        seedIfEmpty()
        var dimensions = 0
        var elapsedMs = 0L
        val error = try {
            if (embeddingProvider.isModelBacked) {
                elapsedMs = measureTimeMillis {
                    dimensions = embeddingProvider.embedQuery("AI developer in Pangyo").size
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
            .put("embedding_dimensions", dimensions)
            .put("sample_embedding_ms", elapsedMs)
            .put("room_card_count", dao.countCards())
            .put("device_abis", JSONArray(Build.SUPPORTED_ABIS.toList()))
            .put("internal_models_dir", java.io.File(appContext.filesDir, "models").absolutePath)
            .put("external_models_dir", appContext.getExternalFilesDir("models")?.absolutePath ?: "")
            .put("error", error)
    }

    fun seedIfEmpty() {
        if (dao.countCards() == 0) {
            dao.clearFts()
            if (seedFromAsset()) {
                seedEmbeddingsFromAsset()
            } else {
                dao.upsertCards(sampleCards())
            }
            ftsRebuilt = true
            return
        }
        if (!ftsRebuilt) {
            dao.rebuildFts()
            ftsRebuilt = true
        }
    }

    /**
     * OCR로 새 카드가 들어오기 전까지는, 라이브 임베딩 모델이 기기에서 안 뜨더라도
     * 검색 기능 자체는 미리 계산해둔 벡터로 동작해야 한다. 그래서 실패해도 조용히 건너뛴다.
     */
    fun indexEmbeddings(onProgress: ((done: Int, total: Int) -> Unit)? = null) {
        seedIfEmpty()
        if (!embeddingProvider.isModelBacked) return
        // 수천 장 규모에서 검색할 때마다 전체 카드를 훑지 않도록, 개수가 맞으면 건너뛴다.
        // (카드 내용이 바뀌면 임포트 시 임베딩을 함께 지우므로 개수 비교로 충분)
        val total = dao.countCards()
        if (onProgress == null && dao.countEmbeddingsForModel(embeddingModelKey) >= total) return
        var done = 0
        dao.allCards().forEach { card ->
            val text = cardEmbeddingInput(card)
            val hash = sha256(text)
            val existing = dao.findEmbedding(card.id, embeddingModelKey, hash)
            if (existing == null) {
                val vector = embeddingProvider.embedDocument(text)
                if (vector.isNotEmpty()) {
                    dao.upsertEmbedding(
                        CardEmbeddingEntity(
                            card.id,
                            embeddingModelKey,
                            vector.toBlob(),
                            vector.size,
                            hash,
                            System.currentTimeMillis()
                        )
                    )
                }
            }
            done++
            onProgress?.invoke(done, total)
        }
    }

    fun search(rawQuery: String, limit: Int = 5): CardSearchResponse = searchHybrid(rawQuery, limit)

    fun searchKeywordOnly(rawQuery: String, limit: Int = 20): CardSearchResponse {
        seedIfEmpty()
        val safeLimit = limit.coerceIn(1, 20)
        val analyzed = KeywordSearchRanker.analyze(rawQuery)
        val hits = keywordHits(analyzed, safeLimit)
        if (hits.isNotEmpty()) {
            return CardSearchResponse(
                query = analyzed.raw,
                engine = "Room FTS keyword",
                retrieval = "room_fts_keyword_only",
                keywordQuery = analyzed.keywordQuery,
                semanticQuery = "",
                results = hits,
            )
        }
        return CardSearchResponse(
            query = analyzed.raw,
            engine = "Room FTS keyword",
            retrieval = "room_fts_keyword_only",
            keywordQuery = analyzed.keywordQuery,
            semanticQuery = "",
            results = emptyList(),
        )
    }

    fun searchHybrid(rawQuery: String, limit: Int = 5): CardSearchResponse {
        seedIfEmpty()
        // 라이브 임베딩 모델이 이 기기에서 안 뜨면 쿼리를 임베딩할 수 없으니 키워드 검색으로 내려간다.
        // 문서(명함) 쪽은 번들된 사전 계산 벡터가 이미 있어도, 쿼리 쪽이 없으면 벡터 검색 자체가 불가능하다.
        val vectorSearchAvailable = embeddingProvider.isModelBacked
        if (vectorSearchAvailable) indexEmbeddings()
        val safeLimit = limit.coerceIn(1, 20)
        val analyzed = KeywordSearchRanker.analyze(rawQuery)
        val keywordHits = keywordHits(analyzed, 40)
        val keywordIds = keywordHits.map { it.card.id }
        val queryVector = if (vectorSearchAvailable) embeddingProvider.embedQuery(analyzed.semanticQuery) else FloatArray(0)
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

        return CardSearchResponse(
            query = analyzed.raw,
            engine = engineStatus,
            retrieval = if (vectorSearchAvailable) "room_fts_plus_embeddinggemma_rrf" else "room_fts_keyword_only (embedding model not loaded)",
            keywordQuery = analyzed.keywordQuery,
            semanticQuery = analyzed.semanticQuery,
            results = hits,
        )
    }

    /**
     * 티어드 FTS 검색(검색 담당 브랜치 ymj/embedding-search-android-eval 이식):
     * 정확 구문(phrase) → 전체 단어 AND(allTerms) → 접두어 AND(prefix) → LIKE 폴백.
     * 순서대로 후보를 채워 나가고, 그 등장 순서를 그대로 랭킹으로 쓴다(재점수화하지 않음).
     * scripts/eval_search.py 오프라인 평가에서 기존 LIKE+커스텀 점수 방식보다
     * Recall@1 0.76→0.94, MRR 0.81→0.96로 뚜렷이 우수했다(특히 전화번호 조회 0.19→1.00).
     */
    private fun keywordHits(query: AnalyzedSearchQuery, limit: Int): List<CardSearchHit> {
        val ids = keywordIdsTiered(query, limit * 4)
        val ranked = if (ids.isEmpty() && query.keywordQuery.isBlank()) {
            dao.allCards().map { it.id }
        } else {
            ids
        }
        return ranked
            .mapNotNull { dao.findCard(it) }
            .take(limit)
            .mapIndexed { index, card ->
                CardSearchHit(
                    card = card,
                    score = (limit - index).toDouble(),
                    keywordRank = index + 1,
                    vectorRank = null,
                    similarity = 0f,
                )
            }
    }

    private fun keywordIdsTiered(query: AnalyzedSearchQuery, limit: Int): List<String> {
        val terms = ftsSafeTerms(query.keywordTokens)
        if (terms.isEmpty()) return emptyList()
        val out = LinkedHashSet<String>()
        ftsPhraseMatch(terms)?.let { out.addAll(safeFtsSearch(it, limit)) }
        if (out.size < limit) ftsAllTermsMatch(terms)?.let { out.addAll(safeFtsSearch(it, limit)) }
        if (out.size < limit) ftsPrefixMatch(terms)?.let { out.addAll(safeFtsSearch(it, limit)) }
        // LIKE 폴백에서만 동의어 확장 — "인공지능" 검색이 "AI" 태그 카드도 잡게.
        if (out.size < limit) expandSynonymsForFallback(terms).forEach { out.addAll(dao.searchLikeIds("%$it%", limit)) }
        return out.take(limit)
    }

    private fun safeFtsSearch(match: String, limit: Int): List<String> =
        try {
            dao.searchFtsIds(match, limit)
        } catch (_: Throwable) {
            emptyList()
        }

    private fun vectorScores(queryVector: FloatArray, limit: Int): List<Pair<String, Float>> =
        dao.embeddingsForModel(embeddingModelKey)
            .mapNotNull { embedding ->
                val vector = embedding.vector.toFloatArray(embedding.dimensions)
                embedding.cardId to cosine(queryVector, vector)
            }
            .sortedByDescending { it.second }
            .take(limit)

    private fun rrf(rank: Int?): Double = if (rank == null) 0.0 else 1.0 / (60.0 + rank)

    /** APK에 번들된 시드 데이터(assets/cards/cards_seed.json)가 있으면 그걸로 채운다. */
    private fun seedFromAsset(): Boolean =
        try {
            appContext.assets.open("cards/cards_seed.json").use { input ->
                importCardsJson(input.readBytes().toString(Charsets.UTF_8)) > 0
            }
        } catch (_: Throwable) {
            false
        }

    /**
     * APK에 번들된 사전 계산 임베딩(assets/cards/cards_embeddings_*)이 있으면 DB에 채운다.
     * 라이브 임베딩 모델을 이 기기에서 못 띄워도 시맨틱 검색이 바로 동작하게 하기 위함 —
     * OCR로 새 카드가 들어오기 전까지 임시로 이 방식을 쓴다.
     */
    private fun seedEmbeddingsFromAsset() {
        try {
            val ids = JSONArray(
                appContext.assets.open("cards/cards_embeddings_ids.json").use {
                    it.readBytes().toString(Charsets.UTF_8)
                }
            )
            val bytes = appContext.assets.open("cards/cards_embeddings.bin").use { it.readBytes() }
            val dimensions = 768
            val vectorBytes = dimensions * 4
            val now = System.currentTimeMillis()
            for (i in 0 until ids.length()) {
                val cardId = ids.getString(i)
                val card = dao.findCard(cardId) ?: continue
                val start = i * vectorBytes
                if (start + vectorBytes > bytes.size) break
                val blob = bytes.copyOfRange(start, start + vectorBytes)
                val hash = sha256(cardEmbeddingInput(card))
                dao.upsertEmbedding(CardEmbeddingEntity(cardId, embeddingModelKey, blob, dimensions, hash, now))
            }
        } catch (_: Throwable) {
            // 번들된 사전 계산 벡터가 없거나 손상된 경우 — 검색은 키워드로, 벡터는 필요할 때 온디바이스로 계산됨
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
