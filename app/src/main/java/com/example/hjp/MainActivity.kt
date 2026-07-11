package com.example.hjp

import android.content.Context
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.example.hjp.agent.LiteRtLmChatEngine
import com.example.hjp.agent.LlmRole
import com.example.hjp.data.BusinessCardEntity
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
                    initialToolLlmStatus = LiteRtLmChatEngine.modelStatus(applicationContext, LlmRole.ToolCalling),
                    initialChatLlmStatus = LiteRtLmChatEngine.modelStatus(applicationContext, LlmRole.Chat),
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
    val modelLabel: String? = null,
)

private data class ChatMessage(
    val isUser: Boolean,
    val text: String,
    val modelLabel: String? = null,
    val search: CardSearchResponse? = null,
    val error: String? = null,
)

@Composable
fun HjpApp(
    searchService: CardSearchService,
    initialToolLlmStatus: String,
    initialChatLlmStatus: String,
) {
    var selectedTab by remember { mutableStateOf(AppTab.Cards) }
    var toolLlmStatus by remember { mutableStateOf(initialToolLlmStatus) }
    var chatLlmStatus by remember { mutableStateOf(initialChatLlmStatus) }

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
                toolLlmStatus = toolLlmStatus,
                chatLlmStatus = chatLlmStatus,
                onToolLlmStatusChanged = { toolLlmStatus = it },
                onChatLlmStatusChanged = { chatLlmStatus = it },
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
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var response by remember { mutableStateOf<CardSearchResponse?>(null) }
    var message by remember { mutableStateOf("이름, 회사, 직무, 지역, 전화번호로 검색해 보세요.") }
    var selectedCard by remember { mutableStateOf<BusinessCardEntity?>(null) }

    val dataPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            message = "명함 데이터를 불러오는 중..."
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val json = context.contentResolver.openInputStream(uri).use { input ->
                        requireNotNull(input) { "파일을 열 수 없습니다." }
                        input.readBytes().toString(Charsets.UTF_8)
                    }
                    searchService.importCardsJson(json)
                }
            }
            result.onSuccess { count ->
                response = null
                message = "명함 ${count}장을 불러왔습니다. 기존 데이터와 임베딩은 교체되었습니다."
            }.onFailure {
                message = "데이터 불러오기 실패: ${it.message ?: it.javaClass.simpleName}"
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
        OutlinedButton(
            onClick = { dataPicker.launch(arrayOf("application/json", "*/*")) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("명함 데이터 가져오기 (JSON)")
        }
        Text(message, style = MaterialTheme.typography.bodyMedium)
        response?.let {
            SearchSummary(it)
            it.results.forEach { hit ->
                BusinessCardResultCard(hit, onClick = { selectedCard = hit.card })
            }
        }
    }
    selectedCard?.let { card ->
        CardDetailDialog(card, onDismiss = { selectedCard = null })
    }
}

@Composable
private fun ChatScreen(
    searchService: CardSearchService,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var input by remember { mutableStateOf("") }
    var asking by remember { mutableStateOf(false) }
    var selectedCard by remember { mutableStateOf<BusinessCardEntity?>(null) }
    val messages = remember {
        mutableStateListOf(
            ChatMessage(isUser = false, text = "명함에 대해 문장으로 물어보세요.\n예) \"판교에 있는 AI 개발자 찾아줘\"")
        )
    }
    val listState = rememberLazyListState()

    LaunchedEffect(messages.size, asking) {
        listState.animateScrollToItem((messages.size - 1).coerceAtLeast(0))
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .imePadding()
            .padding(horizontal = 16.dp),
    ) {
        Text("채팅", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(vertical = 12.dp))

        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(messages) { message ->
                ChatBubble(message, onCardClick = { selectedCard = it })
            }
            if (asking) {
                item { TypingBubble() }
            }
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("질문을 입력하세요") },
                maxLines = 3,
            )
            Button(
                enabled = !asking && input.isNotBlank(),
                onClick = {
                    val question = input.trim()
                    input = ""
                    messages.add(ChatMessage(isUser = true, text = question))
                    scope.launch {
                        asking = true
                        val result = withContext(Dispatchers.IO) {
                            runChat(context, searchService, question)
                        }
                        asking = false
                        messages.add(
                            ChatMessage(
                                isUser = false,
                                text = result.answer,
                                modelLabel = result.modelLabel,
                                search = result.search,
                                error = result.error,
                            )
                        )
                    }
                },
            ) {
                Text("전송")
            }
        }
    }
    selectedCard?.let { card ->
        CardDetailDialog(card, onDismiss = { selectedCard = null })
    }
}

@Composable
private fun ChatBubble(message: ChatMessage, onCardClick: (BusinessCardEntity) -> Unit = {}) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = if (message.isUser) Arrangement.End else Arrangement.Start,
        ) {
            Surface(
                shape = RoundedCornerShape(
                    topStart = 18.dp,
                    topEnd = 18.dp,
                    bottomStart = if (message.isUser) 18.dp else 4.dp,
                    bottomEnd = if (message.isUser) 4.dp else 18.dp,
                ),
                color = if (message.isUser) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.surfaceVariant
                },
                modifier = Modifier.widthIn(max = 320.dp),
            ) {
                Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        message.text,
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (message.isUser) {
                            MaterialTheme.colorScheme.onPrimary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                    message.modelLabel?.let {
                        Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    message.error?.let {
                        Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }
        message.search?.let { search ->
            SearchSummary(search)
            search.results.take(3).forEach { hit ->
                BusinessCardResultCard(hit, onClick = { onCardClick(hit.card) })
            }
        }
    }
}

@Composable
private fun TypingBubble() {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Surface(
            shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = 4.dp, bottomEnd = 18.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
        ) {
            Text(
                "답변 생성 중...",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            )
        }
    }
}

@Composable
private fun ModelsScreen(
    searchService: CardSearchService,
    toolLlmStatus: String,
    chatLlmStatus: String,
    onToolLlmStatusChanged: (String) -> Unit,
    onChatLlmStatusChanged: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var diagnostics by remember { mutableStateOf<JSONObject?>(null) }
    var importMessage by remember { mutableStateOf<String?>(null) }
    var embedCheckMessage by remember { mutableStateOf<String?>(null) }
    var embedChecking by remember { mutableStateOf(false) }
    var toolTestMessage by remember { mutableStateOf<String?>(null) }
    var toolTesting by remember { mutableStateOf(false) }
    var chatTestMessage by remember { mutableStateOf<String?>(null) }
    var chatTesting by remember { mutableStateOf(false) }
    var indexMessage by remember { mutableStateOf<String?>(null) }
    var indexing by remember { mutableStateOf(false) }
    var pendingModelFileName by remember { mutableStateOf("embeddinggemma-300m.tflite") }

    val modelPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            importMessage = "${pendingModelFileName} 복사 중... (파일 크기에 따라 시간이 걸립니다)"
            val result = withContext(Dispatchers.IO) {
                runCatching { copyModelToAppStorage(context, uri, pendingModelFileName) }
            }
            result.onSuccess { copied ->
                onToolLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context, LlmRole.ToolCalling))
                onChatLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context, LlmRole.Chat))
                importMessage = "${pendingModelFileName} 복사 완료 (${formatBytes(copied.length())})"
                diagnostics = withContext(Dispatchers.IO) {
                    searchService.reloadEmbeddingProvider()
                    searchService.diagnostics()
                }
            }.onFailure {
                importMessage = "복사 실패: ${it.message ?: it.javaClass.simpleName}"
            }
        }
    }

    LaunchedEffect(Unit) {
        diagnostics = withContext(Dispatchers.IO) { searchService.diagnostics() }
    }

    val embedStatus = diagnostics?.optString("active_embedding_status").orEmpty()
    val embedState = when {
        diagnostics?.optBoolean("active_embedding_model_backed") == true -> ModelState.Ready
        diagnostics == null || embedStatus.startsWith("missing:") -> ModelState.Missing
        else -> ModelState.Failed
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("모델 관리", style = MaterialTheme.typography.titleLarge)
        Text(
            "모든 AI 기능은 인터넷 없이 기기 안에서 동작합니다. 각 모델 파일을 가져온 뒤 '동작 확인'을 눌러 실제로 실행되는지 검사해 보세요.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        importMessage?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = if (it.startsWith("복사 실패")) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        ModelCard(
            title = "임베딩 모델",
            subtitle = "EmbeddingGemma 300M · 모델(.tflite) + 토크나이저(sentencepiece.model) 2개 파일 필요",
            role = "채팅 탭의 의미 검색에 사용합니다. \"판교에서 만난 AI 하는 분\"처럼 문장 뜻으로 명함을 찾아줍니다.",
            state = embedState,
            stateLabel = when {
                embedState == ModelState.Ready -> "사용 준비됨"
                embedState == ModelState.Missing && embedStatus.contains("sentencepiece") -> "토크나이저 없음 — sentencepiece.model을 가져와 주세요"
                embedState == ModelState.Missing -> "모델 파일 없음 — 파일을 가져와 주세요"
                else -> "파일은 있지만 로드 실패"
            },
            detail = if (embedState == ModelState.Failed) embedStatus else "",
            onImport = {
                pendingModelFileName = "embeddinggemma-300m.tflite"
                modelPicker.launch(arrayOf("application/octet-stream", "*/*"))
            },
            secondaryImportLabel = "토크나이저 가져오기",
            onSecondaryImport = {
                pendingModelFileName = "sentencepiece.model"
                modelPicker.launch(arrayOf("application/octet-stream", "*/*"))
            },
            checking = embedChecking,
            onCheck = {
                scope.launch {
                    embedChecking = true
                    diagnostics = withContext(Dispatchers.IO) {
                        searchService.reloadEmbeddingProvider()
                        searchService.diagnostics()
                    }
                    embedChecking = false
                    embedCheckMessage = diagnostics?.let { d ->
                        if (d.optBoolean("active_embedding_model_backed")) {
                            "정상 동작 · ${d.optInt("embedding_dimensions")}차원 · 문장 1개 ${d.optLong("sample_embedding_ms")}ms"
                        } else {
                            "실행 실패: ${d.optString("active_embedding_status")}"
                        }
                    } ?: "상태를 읽지 못했습니다."
                }
            },
            resultText = embedCheckMessage,
        )

        ModelCard(
            title = "도구 실행 LLM",
            subtitle = "FunctionGemma 270M · functiongemma_270m.litertlm",
            role = "\"김지원한테 문자 보내줘\" 같은 요청을 캘린더·문자 도구 호출로 바꾸는 에이전트용 모델입니다. (에이전트 화면은 아직 연동 전)",
            state = if (toolLlmStatus.startsWith("missing:")) ModelState.Missing else ModelState.Ready,
            stateLabel = if (toolLlmStatus.startsWith("missing:")) "모델 파일 없음 — 파일을 가져와 주세요" else "파일 있음 — 동작 확인으로 실행을 검사하세요",
            detail = "",
            onImport = {
                pendingModelFileName = "functiongemma_270m.litertlm"
                modelPicker.launch(arrayOf("application/octet-stream", "*/*"))
            },
            checking = toolTesting,
            onCheck = {
                scope.launch {
                    toolTesting = true
                    toolTestMessage = withContext(Dispatchers.IO) { runLlmSmokeTest(context, LlmRole.ToolCalling) }
                    toolTesting = false
                    onToolLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context, LlmRole.ToolCalling))
                }
            },
            resultText = toolTestMessage,
        )

        ModelCard(
            title = "채팅 LLM",
            subtitle = "Gemma 3 1B IT · gemma3-1b-it-int4.litertlm",
            role = "채팅 탭에서 검색된 명함 내용을 바탕으로 답변 문장을 만드는 모델입니다.",
            state = if (chatLlmStatus.startsWith("missing:")) ModelState.Missing else ModelState.Ready,
            stateLabel = if (chatLlmStatus.startsWith("missing:")) "모델 파일 없음 — 파일을 가져와 주세요" else "파일 있음 — 동작 확인으로 실행을 검사하세요",
            detail = "",
            onImport = {
                pendingModelFileName = "gemma3-1b-it-int4.litertlm"
                modelPicker.launch(arrayOf("application/octet-stream", "*/*"))
            },
            checking = chatTesting,
            onCheck = {
                scope.launch {
                    chatTesting = true
                    chatTestMessage = withContext(Dispatchers.IO) { runLlmSmokeTest(context, LlmRole.Chat) }
                    chatTesting = false
                    onChatLlmStatusChanged(LiteRtLmChatEngine.modelStatus(context, LlmRole.Chat))
                }
            },
            resultText = chatTestMessage,
        )

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("임베딩 인덱스", style = MaterialTheme.typography.titleMedium)
                Text(
                    "명함 데이터를 새로 넣었다면 여기서 인덱스를 미리 만들어 두세요. 만들지 않으면 첫 채팅 질문이 수 분씩 걸립니다.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Button(
                    enabled = !indexing && embedState == ModelState.Ready,
                    onClick = {
                        scope.launch {
                            indexing = true
                            val result = withContext(Dispatchers.IO) {
                                runCatching {
                                    searchService.indexEmbeddings { done, total ->
                                        if (done % 50 == 0 || done == total) {
                                            scope.launch { indexMessage = "인덱싱 중... $done / $total" }
                                        }
                                    }
                                }
                            }
                            indexing = false
                            indexMessage = result.fold(
                                onSuccess = { "인덱스 구축 완료. 채팅 검색을 바로 쓸 수 있습니다." },
                                onFailure = { "인덱싱 실패: ${it.message ?: it.javaClass.simpleName}" },
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (indexing) "인덱싱 중..." else "인덱스 만들기")
                }
                if (embedState != ModelState.Ready) {
                    Text("임베딩 모델이 준비되면 사용할 수 있습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                indexMessage?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (it.startsWith("인덱싱 실패")) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
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
private fun BusinessCardResultCard(hit: CardSearchHit, onClick: (() -> Unit)? = null) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable { onClick() } else Modifier),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(hit.card.name.ifBlank { "(이름 없음)" }, style = MaterialTheme.typography.titleMedium)
            Text("${hit.card.company} · ${hit.card.title}", style = MaterialTheme.typography.bodyMedium)
            if (hit.card.department.isNotBlank() || hit.card.location.isNotBlank()) {
                Text("${hit.card.department} · ${hit.card.location}", style = MaterialTheme.typography.bodySmall)
            }
            Text("${hit.card.phone}  ${hit.card.email}", style = MaterialTheme.typography.bodySmall)
            if (hit.card.address.isNotBlank()) {
                Text(hit.card.address, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            // 하이브리드(RRF) 점수는 0.03처럼 작아서 소수점 1자리로는 0.0으로 보인다
            val scoreText = if (hit.score < 1.0) "%.3f".format(hit.score) else "%.1f".format(hit.score)
            Text("검색 점수 $scoreText", style = MaterialTheme.typography.labelSmall)
        }
    }
}

/** 명함 상세: 명함 이미지(있으면) + 전체 필드 표 */
@Composable
private fun CardDetailDialog(card: BusinessCardEntity, onDismiss: () -> Unit) {
    val context = LocalContext.current
    // 합성 데이터 카드 id(S00021)는 이미지 파일명(000021.png)과 매핑된다.
    // OCR로 들어올 미래 카드는 "{id}.png" 그대로 찾는다.
    val bitmap = remember(card.id) {
        val dir = context.getExternalFilesDir("card_images")
        val candidates = listOf(
            "${card.id}.png",
            card.id.removePrefix("S").padStart(6, '0') + ".png",
        )
        candidates.firstNotNullOfOrNull { name ->
            dir?.let { d ->
                val f = java.io.File(d, name)
                if (f.exists()) BitmapFactory.decodeFile(f.absolutePath) else null
            }
        }
    }

    Dialog(onDismissRequest = onDismiss) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                Modifier
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(card.name.ifBlank { "(이름 없음)" }, style = MaterialTheme.typography.titleLarge)

                if (bitmap != null) {
                    Image(
                        bitmap = bitmap.asImageBitmap(),
                        contentDescription = "명함 이미지",
                        modifier = Modifier.fillMaxWidth(),
                        contentScale = ContentScale.FillWidth,
                    )
                } else {
                    Surface(
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            "명함 이미지 없음",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 28.dp, horizontal = 16.dp),
                        )
                    }
                }

                listOf(
                    "이름" to card.name,
                    "영문 이름" to card.nameEn,
                    "회사" to card.company,
                    "직함" to card.title,
                    "부서" to card.department,
                    "업종" to card.industry,
                    "지역" to card.location,
                    "전화" to card.phone,
                    "이메일" to card.email,
                    "주소" to card.address,
                    "메모" to card.memo,
                    "태그" to card.tags,
                ).filter { it.second.isNotBlank() }.forEach { (label, value) ->
                    Row(Modifier.fillMaxWidth()) {
                        Text(
                            label,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.widthIn(min = 72.dp),
                        )
                        Text(value, style = MaterialTheme.typography.bodyMedium)
                    }
                }

                Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                    Text("닫기")
                }
            }
        }
    }
}

private enum class ModelState { Ready, Missing, Failed }

@Composable
private fun StatusDot(state: ModelState) {
    val color = when (state) {
        ModelState.Ready -> Color(0xFF2E7D32)
        ModelState.Missing -> MaterialTheme.colorScheme.outline
        ModelState.Failed -> MaterialTheme.colorScheme.error
    }
    Box(
        Modifier
            .size(10.dp)
            .background(color, CircleShape)
    )
}

@Composable
private fun ModelCard(
    title: String,
    subtitle: String,
    role: String,
    state: ModelState,
    stateLabel: String,
    detail: String,
    onImport: () -> Unit,
    checking: Boolean,
    onCheck: () -> Unit,
    resultText: String?,
    secondaryImportLabel: String? = null,
    onSecondaryImport: (() -> Unit)? = null,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                StatusDot(state)
                Text(title, style = MaterialTheme.typography.titleMedium)
            }
            Text(subtitle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(role, style = MaterialTheme.typography.bodyMedium)
            Text(
                stateLabel,
                style = MaterialTheme.typography.bodySmall,
                color = when (state) {
                    ModelState.Ready -> Color(0xFF2E7D32)
                    ModelState.Missing -> MaterialTheme.colorScheme.onSurfaceVariant
                    ModelState.Failed -> MaterialTheme.colorScheme.error
                },
            )
            if (detail.isNotBlank()) {
                Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onImport, modifier = Modifier.weight(1f)) {
                    Text("파일 가져오기")
                }
                OutlinedButton(
                    onClick = onCheck,
                    enabled = !checking && state != ModelState.Missing,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (checking) "확인 중..." else "동작 확인")
                }
            }
            if (secondaryImportLabel != null && onSecondaryImport != null) {
                OutlinedButton(onClick = onSecondaryImport, modifier = Modifier.fillMaxWidth()) {
                    Text(secondaryImportLabel)
                }
            }
            resultText?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (it.startsWith("실행 실패") || it.startsWith("실패")) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
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
    val search = try {
        searchService.searchHybrid(question, 5)
    } catch (e: Throwable) {
        return ChatResult(
            answer = "검색 중 문제가 있었습니다.",
            search = null,
            error = e.message ?: e.javaClass.simpleName,
        )
    }
    // Gemma 3 1B가 없거나 기기 메모리가 부족한 폰(예: RAM 4GB)에서는 FunctionGemma로 대신 답변한다.
    // FunctionGemma는 대화용 모델이 아니라 품질이 낮지만, 전체 흐름을 시연하는 데는 충분하다.
    val role = when {
        !LiteRtLmChatEngine.modelStatus(context, LlmRole.Chat).startsWith("missing:") -> LlmRole.Chat
        !LiteRtLmChatEngine.modelStatus(context, LlmRole.ToolCalling).startsWith("missing:") -> LlmRole.ToolCalling
        else -> return ChatResult(
            answer = "LLM 모델이 없어 검색 결과만 보여드려요. 모델 탭에서 LLM 파일을 가져오면 답변도 생성됩니다.",
            search = search,
        )
    }
    return try {
        val prompt = """
            You are an on-device assistant for a business card app.
            Answer in Korean using only the provided business card context.

            Question:
            $question

            Business card context:
            ${search.ragContext(3)}
        """.trimIndent()
        // 공유 엔진 사용 — 닫지 않는다 (반복 로드로 인한 메모리 스파이크 방지)
        val engine = LiteRtLmChatEngine.openShared(context, role)
        val loadedModel = engine.loadedFileName.removeSuffix(".litertlm")
        val llmAnswer = engine.generate(prompt)
        if (llmAnswer == LiteRtLmChatEngine.EMPTY_RESPONSE) {
            return ChatResult(
                answer = "LLM이 유효한 답변을 만들지 못했어요. 검색 결과를 참고해 주세요." +
                    if (role == LlmRole.ToolCalling) "\n(FunctionGemma는 대화용 모델이 아니라 자주 이렇습니다)" else "",
                search = search,
                modelLabel = loadedModel,
            )
        }
        ChatResult(
            answer = llmAnswer,
            search = search,
            modelLabel = if (role == LlmRole.ToolCalling) "$loadedModel (임시 대체 — 품질 낮음)" else loadedModel,
        )
    } catch (e: Throwable) {
        // 검색은 이미 성공했으니 결과는 보여주고, LLM 답변 생성만 실패했다고 알린다.
        ChatResult(
            answer = "LLM 답변 생성에 실패했어요. 검색 결과는 아래에서 확인할 수 있습니다.",
            search = search,
            error = e.message ?: e.javaClass.simpleName,
        )
    }
}

private fun runLlmSmokeTest(context: Context, role: LlmRole): String =
    try {
        val engine = LiteRtLmChatEngine.openShared(context, role)
        val answer = engine.generate("Reply with one short Korean sentence.")
        "정상 동작 (${engine.backendName}) · 생성 예시: ${answer.take(80)}"
    } catch (e: Throwable) {
        "실행 실패: ${e.message ?: e.javaClass.simpleName}"
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
