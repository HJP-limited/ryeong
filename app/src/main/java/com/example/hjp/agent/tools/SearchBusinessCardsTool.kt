package com.example.hjp.agent.tools

import com.example.hjp.search.CardSearchService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class SearchBusinessCardsTool(
    private val searchService: CardSearchService,
) : AgentTool {
    override val name = "search_business_cards"

    override val declaration = JSONObject(
        """
        {
          "name": "search_business_cards",
          "description": "Search the local on-device business card database with Room FTS plus EmbeddingGemma semantic retrieval. Use this before composing emails, SMS, or calendar events involving a contact.",
          "parameters": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Natural language query such as 'AI developer in Pangyo' or 'manufacturing quality manager'."
              },
              "limit": {
                "type": "integer",
                "description": "Maximum number of cards to return. Default 5."
              }
            },
            "required": ["query"]
          }
        }
        """
    )

    override suspend fun execute(args: JSONObject): String = withContext(Dispatchers.IO) {
        val query = args.optString("query").trim()
        if (query.isBlank()) return@withContext ToolResults.error("query is required.")
        val limit = args.optInt("limit", 5).coerceIn(1, 10)
        val response = searchService.search(query, limit)
        JSONObject()
            .put("status", "success")
            .put("message", "Found ${response.results.size} business cards.")
            .put("query", response.query)
            .put("engine", response.engine)
            .put("retrieval", "room_fts_plus_embeddinggemma_rrf")
            .put("cards", JSONArray(response.results.map { hit ->
                JSONObject()
                    .put("card_id", hit.card.id)
                    .put("name", hit.card.name)
                    .put("company", hit.card.company)
                    .put("title", hit.card.title)
                    .put("department", hit.card.department)
                    .put("location", hit.card.location)
                    .put("phone", hit.card.phone)
                    .put("email", hit.card.email)
                    .put("score", hit.score)
                    .put("similarity", hit.similarity.toDouble())
                    .put("keyword_rank", hit.keywordRank ?: JSONObject.NULL)
                    .put("vector_rank", hit.vectorRank ?: JSONObject.NULL)
            }))
            .put("rag_context", response.ragContext())
            .toString()
    }
}
