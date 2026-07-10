package com.example.hjp

import android.content.Context
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.example.hjp.agent.LiteRtLmChatEngine
import com.example.hjp.search.CardSearchResponse
import com.example.hjp.search.CardSearchService
import com.example.hjp.ui.theme.HJPTheme
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val searchService = CardSearchService(applicationContext)

        setContent {
            HJPTheme {
                HjpApp(
                    searchService = searchService,
                    initialLlmStatus = LiteRtLmChatEngine.modelStatus(applicationContext),
                )
            }
        }
    }
}

private enum class AppTab(
    val label: String,
) {
    Cards("명함"),
    Chat("채팅"),
    Models("모델"),
}

@Composable
fun HjpApp(
    searchService: CardSearchService,
    initialLlmStatus: String,
) {
    var selectedTab by remember { mutableStateOf(AppTab.Cards) }
    var llmStatus by remember { mutableStateOf(initialLlmStatus) }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        bottomBar = {
            NavigationBar {
                AppTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        label = { Text(tab.label) },
                        icon = { Text(tab.label.take(1)) },
                    )
                }
            }
        },
    ) { innerPadding ->
        when (selectedTab) {
            AppTab.Cards -> CardsScreen(
                searchService = searchService,
                modifier = Modifier.padding(innerPadding),
            )

            AppTab.Chat -> ChatScreen(
                searchService = searchService,
                modifier = Modifier.padding(innerPadding),
            )

            AppTab.Models -> ModelsScreen(
                searchService = searchService,
                llmStatus = llmStatus,
                onLlmStatusChanged = { llmStatus = it },
                modifier = Modifier.padding(innerPadding),
            )
        }
    }
}

@Composable
private fun CardsScreen(
    searchService: CardSearchService,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("단어를 입력하면 Room FTS 키워드 검색만 실행됩니다.") }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("명함 목록", style = MaterialTheme.typography.titleLarge)
        Text("키워드 검색: Room FTS", style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("이름, 회사, 직무, 지역") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 1,
        )
        Button(
            onClick = {
                scope.launch {
                    result = withContext(Dispatchers.IO) {
                        try {
                            formatCardList(searchService.searchKeywordOnly(query, 20))
                        } catch (e: Throwable) {
                            "검색 실패: ${e.message ?: e.javaClass.simpleName}"
                        }
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("검색")
        }
        Text(result, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ChatScreen(
    searchService: CardSearchService,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var question by remember { mutableStateOf("판교에 있는 AI 개발자 찾아줘") }
    var answer by remember { mutableStateOf("문장으로 질문하면 하이브리드 검색 후 LLM에 RAG 컨텍스트를 전달합니다.") }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("LLM 채팅", style = MaterialTheme.typography.titleLarge)
        Text("문장 질문: Room FTS + EmbeddingGemma + FunctionGemma", style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(
            value = question,
            onValueChange = { question = it },
            label = { Text("질문") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 3,
        )
        Button(
            onClick = {
                scope.launch {
                    answer = withContext(Dispatchers.IO) {
                        runChat(context, searchService, question)
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("질문하기")
        }
        Text(answer, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ModelsScreen(
    searchService: CardSearchService,
    llmStatus: String,
    onLlmStatusChanged: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var result by remember { mutableStateOf("모델 파일은 앱에 포함하지 않고 이 화면에서 가져옵니다.") }
    var pendingModelFileName by remember { mutableStateOf("embeddinggemma_quant.tflite") }

    val modelPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            result = withContext(Dispatchers.IO) {
                try {
                    val copied = copyModelToAppStorage(context, uri, pendingModelFileName)
                    onLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context))
                    JSONObject()
                        .put("status", "success")
                        .put("copied_to", copied.absolutePath)
                        .put("bytes", copied.length())
                        .put("next", "EmbeddingGemma를 방금 가져왔다면 앱을 한 번 완전히 종료 후 다시 실행하세요.")
                        .toString(2)
                } catch (e: Throwable) {
                    JSONObject()
                        .put("status", "error")
                        .put("message", e.message ?: e.javaClass.simpleName)
                        .toString(2)
                }
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("모델", style = MaterialTheme.typography.titleLarge)
        Text("LLM: $llmStatus", style = MaterialTheme.typography.bodySmall)
        Text("Search: ${searchService.engineStatus}", style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                pendingModelFileName = "embeddinggemma_quant.tflite"
                modelPicker.launch(arrayOf("application/octet-stream", "*/*"))
            }) {
                Text("임베딩 가져오기")
            }
            Button(onClick = {
                pendingModelFileName = "functiongemma_270m.litertlm"
                modelPicker.launch(arrayOf("application/octet-stream", "*/*"))
            }) {
                Text("LLM 가져오기")
            }
        }
        Button(
            onClick = {
                scope.launch {
                    result = withContext(Dispatchers.IO) {
                        searchService.diagnostics().toString(2)
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("진단")
        }
        Text(result, style = MaterialTheme.typography.bodySmall)
    }
}

private fun runChat(
    context: Context,
    searchService: CardSearchService,
    question: String,
): String {
    if (question.isBlank()) return "질문을 입력하세요."
    return try {
        val search = searchService.searchHybrid(question, 5)
        val prompt = """
            You are an on-device assistant for a business card app.
            Answer in Korean using only the provided business card context.

            Question:
            $question

            Business card context:
            ${search.ragContext()}
        """.trimIndent()
        val llmAnswer = LiteRtLmChatEngine.open(context).use { engine ->
            engine.generate(prompt)
        }
        JSONObject()
            .put("answer", llmAnswer)
            .put("retrieval", search.retrieval)
            .put("keyword_query", search.keywordQuery)
            .put("semantic_query", search.semanticQuery)
            .put("cards", search.toJson().getJSONArray("cards"))
            .toString(2)
    } catch (e: Throwable) {
        JSONObject()
            .put("status", "error")
            .put("message", e.message ?: e.javaClass.simpleName)
            .put("hint", "채팅은 EmbeddingGemma와 FunctionGemma 모델이 모두 필요합니다.")
            .toString(2)
    }
}

private fun formatCardList(response: CardSearchResponse): String {
    if (response.results.isEmpty()) return "검색 결과가 없습니다."
    return buildString {
        appendLine("retrieval: ${response.retrieval}")
        appendLine("keyword_query: ${response.keywordQuery.ifBlank { "(all)" }}")
        appendLine()
        response.results.forEachIndexed { index, hit ->
            appendLine("${index + 1}. ${hit.card.name} / ${hit.card.company}")
            appendLine("   ${hit.card.title} · ${hit.card.department} · ${hit.card.location}")
            appendLine("   ${hit.card.phone} · ${hit.card.email}")
        }
    }
}

private fun copyModelToAppStorage(context: Context, uri: Uri, fileName: String): File {
    val dir = context.getExternalFilesDir("models") ?: File(context.filesDir, "models")
    dir.mkdirs()
    val out = File(dir, fileName)
    context.contentResolver.openInputStream(uri).use { input ->
        requireNotNull(input) { "Could not open selected file." }
        out.outputStream().use { output -> input.copyTo(output) }
    }
    return out
}
