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
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.example.hjp.agent.LiteRtLmChatEngine
import com.example.hjp.search.CardSearchHit
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

private enum class AppTab(val label: String) {
    Cards("명함"),
    Chat("채팅"),
    Models("모델"),
}

private data class ChatResult(
    val answer: String,
    val search: CardSearchResponse?,
    val error: String? = null,
)

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
    var response by remember { mutableStateOf<CardSearchResponse?>(null) }
    var message by remember { mutableStateOf("이름, 회사, 직무, 지역, 전화번호로 검색해 보세요.") }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("명함 목록", style = MaterialTheme.typography.titleLarge)
        Text("단어 검색 전용 화면입니다. LLM이나 임베딩 모델 없이도 동작합니다.", style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("검색어") },
            placeholder = { Text("예: 김지원, 비전, AI 개발자, 1234") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 1,
        )
        Button(
            onClick = {
                scope.launch {
                    val result = withContext(Dispatchers.IO) {
                        runCatching { searchService.searchKeywordOnly(query, 20) }
                    }
                    result.onSuccess {
                        response = it
                        message = if (it.results.isEmpty()) "검색 결과가 없습니다." else "${it.results.size}개 결과를 찾았습니다."
                    }.onFailure {
                        response = null
                        message = "검색 중 문제가 생겼습니다: ${it.message ?: it.javaClass.simpleName}"
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("검색")
        }
        Text(message, style = MaterialTheme.typography.bodyMedium)
        response?.let {
            SearchSummary(it)
            it.results.forEach { hit -> BusinessCardResultCard(hit) }
        }
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
    var result by remember {
        mutableStateOf(ChatResult("문장으로 질문하면 하이브리드 검색 후 LLM에 명함 정보를 전달합니다.", null))
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("LLM 채팅", style = MaterialTheme.typography.titleLarge)
        Text("자연어 질문 화면입니다. EmbeddingGemma와 FunctionGemma가 모두 필요합니다.", style = MaterialTheme.typography.bodyMedium)
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
                    result = withContext(Dispatchers.IO) {
                        runChat(context, searchService, question)
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("질문하기")
        }
        result.error?.let {
            StatusCard("문제가 있습니다", it, false)
        }
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("답변", style = MaterialTheme.typography.titleMedium)
                Text(result.answer, style = MaterialTheme.typography.bodyMedium)
            }
        }
        result.search?.let {
            SearchSummary(it)
            it.results.take(5).forEach { hit -> BusinessCardResultCard(hit) }
        }
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
    var diagnostics by remember { mutableStateOf<JSONObject?>(null) }
    var importMessage by remember { mutableStateOf("모델 파일을 선택하면 앱 전용 폴더로 복사합니다.") }
    var llmTestMessage by remember { mutableStateOf("아직 LLM 실행 테스트를 하지 않았습니다.") }
    var pendingModelFileName by remember { mutableStateOf("embeddinggemma_quant.tflite") }

    val modelPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { copyModelToAppStorage(context, uri, pendingModelFileName) }
            }
            result.onSuccess { copied ->
                onLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context))
                importMessage = "${pendingModelFileName} 복사 완료 (${formatBytes(copied.length())}). 앱을 완전히 종료했다가 다시 열면 가장 확실합니다."
                diagnostics = withContext(Dispatchers.IO) { searchService.diagnostics() }
            }.onFailure {
                importMessage = "복사 실패: ${it.message ?: it.javaClass.simpleName}"
            }
        }
    }

    LaunchedEffect(Unit) {
        diagnostics = withContext(Dispatchers.IO) { searchService.diagnostics() }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("모델 관리", style = MaterialTheme.typography.titleLarge)
        Text("초록색이면 실제로 사용할 준비가 된 상태입니다. 회색은 파일 없음, 빨간색은 파일은 있지만 로드 실패입니다.", style = MaterialTheme.typography.bodyMedium)

        ModelStatusPanel(
            title = "임베딩 모델",
            ready = diagnostics?.optBoolean("active_embedding_model_backed") == true,
            missing = diagnostics == null || diagnostics?.optString("active_embedding_status").orEmpty().startsWith("missing:"),
            primary = embeddingPrimaryText(diagnostics),
            detail = diagnostics?.optString("active_embedding_status").orEmpty(),
        )

        ModelStatusPanel(
            title = "LLM 모델",
            ready = !llmStatus.startsWith("missing:"),
            missing = llmStatus.startsWith("missing:"),
            primary = if (llmStatus.startsWith("missing:")) "파일을 아직 찾지 못했습니다." else "파일을 찾았습니다.",
            detail = llmStatus,
        )

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

        OutlinedButton(
            onClick = {
                scope.launch {
                    diagnostics = withContext(Dispatchers.IO) { searchService.diagnostics() }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("모델 상태 다시 확인")
        }

        OutlinedButton(
            onClick = {
                scope.launch {
                    llmTestMessage = withContext(Dispatchers.IO) { runLlmSmokeTest(context) }
                    onLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context))
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("LLM 실행 테스트")
        }

        StatusCard("최근 작업", importMessage, true)
        StatusCard("LLM 테스트", llmTestMessage, !llmTestMessage.startsWith("실패"))
    }
}

@Composable
private fun SearchSummary(response: CardSearchResponse) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        AssistChip(onClick = {}, label = { Text("키워드: ${response.keywordQuery.ifBlank { "전체" }}") })
        AssistChip(onClick = {}, label = { Text(response.retrieval) })
    }
}

@Composable
private fun BusinessCardResultCard(hit: CardSearchHit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(hit.card.name.ifBlank { "(이름 없음)" }, style = MaterialTheme.typography.titleMedium)
            Text("${hit.card.company} · ${hit.card.title}", style = MaterialTheme.typography.bodyMedium)
            Text("${hit.card.department} · ${hit.card.location}", style = MaterialTheme.typography.bodySmall)
            Text("${hit.card.phone}  ${hit.card.email}", style = MaterialTheme.typography.bodySmall)
            Text("검색 점수 ${"%.1f".format(hit.score)}", style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun ModelStatusPanel(
    title: String,
    ready: Boolean,
    missing: Boolean,
    primary: String,
    detail: String,
) {
    val status = when {
        ready -> "정상"
        missing -> "파일 없음"
        else -> "로드 실패"
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                AssistChip(onClick = {}, label = { Text(status) })
            }
            Text(primary, style = MaterialTheme.typography.bodyMedium)
            if (detail.isNotBlank()) {
                Text(detail, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun StatusCard(
    title: String,
    message: String,
    ok: Boolean,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(if (ok) message else "실패: $message", style = MaterialTheme.typography.bodyMedium)
        }
    }
}

private fun runChat(
    context: Context,
    searchService: CardSearchService,
    question: String,
): ChatResult {
    if (question.isBlank()) return ChatResult("질문을 입력하세요.", null)
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
        ChatResult(llmAnswer, search)
    } catch (e: Throwable) {
        ChatResult(
            answer = "모델 상태를 먼저 확인해 주세요.",
            search = null,
            error = e.message ?: e.javaClass.simpleName,
        )
    }
}

private fun runLlmSmokeTest(context: Context): String =
    try {
        val answer = LiteRtLmChatEngine.open(context).use { engine ->
            engine.generate("Reply with one short Korean sentence.")
        }
        "성공: ${answer.take(160)}"
    } catch (e: Throwable) {
        "실패: ${e.message ?: e.javaClass.simpleName}"
    }

private fun embeddingPrimaryText(diagnostics: JSONObject?): String {
    if (diagnostics == null) return "아직 상태 확인을 하지 않았습니다."
    return when {
        diagnostics.optBoolean("active_embedding_model_backed") -> {
            val dimensions = diagnostics.optInt("embedding_dimensions")
            val elapsed = diagnostics.optLong("sample_embedding_ms")
            "로드와 샘플 임베딩 테스트가 성공했습니다. 차원 $dimensions, ${elapsed}ms"
        }
        diagnostics.optString("active_embedding_status").startsWith("missing:") -> "파일을 아직 찾지 못했습니다."
        else -> "파일은 찾았지만 앱이 모델을 열지 못했습니다."
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

private fun formatBytes(bytes: Long): String {
    val mb = bytes / 1024.0 / 1024.0
    return "%.1fMB".format(mb)
}
