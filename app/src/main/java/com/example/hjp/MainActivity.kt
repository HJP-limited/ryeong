package com.example.hjp

import com.example.hjp.agent.tools.OpenComposeTool
import com.example.hjp.agent.tools.CreateCalendarEventTool
import com.example.hjp.agent.tools.ToolRegistry
import android.content.Context
import android.content.Intent
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
import androidx.compose.material3.TextButton
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
import com.example.hjp.agent.AgentSession
import com.example.hjp.agent.ConversationalFollowup
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
        intent?.getStringExtra("q")?.let { q ->
            android.util.Log.i(DIAG_TAG, "onCreate q=$q")
            DebugQuestion.offer(q)
            intent.removeExtra("q")
        }

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

    /**
     * 이미 떠 있는 액티비티에 질문을 더 밀어 넣는다. launchMode=singleTop 이라 액티비티가
     * 다시 만들어지지 않으므로 **멀티턴 세션이 유지된다** — 이게 없으면 질문마다 세션이
     * 초기화돼서 후속 발화("그 사람 부서는?")를 시험할 수가 없다.
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val q = intent.getStringExtra("q")
        android.util.Log.i(DIAG_TAG, "onNewIntent q=$q")
        DebugQuestion.offer(q)
    }

    /**
     * onNewIntent 가 안 오는 경우(런처 플래그·태스크 상태에 따라 다르다)를 대비한 폴백.
     * 같은 인텐트를 두 번 처리하지 않도록 소비한 extra 는 지운다.
     */
    override fun onResume() {
        super.onResume()
        intent?.getStringExtra("q")?.let { q ->
            android.util.Log.i(DIAG_TAG, "onResume q=$q")
            intent.removeExtra("q")
            DebugQuestion.offer(q)
        }
    }
}

private enum class AppTab(val label: String) {
    Cards("명함"),
    Chat("채팅"),
    Models("모델"),
}

/** 실기기 진단 로그 태그. `adb logcat -s HJP` 로 본다. */
private const val DIAG_TAG = "HJP"

/**
 * 디버그용 질문 주입구.
 *
 * `adb shell input text` 가 한글을 못 쳐서(NullPointerException) 실기기에서 시나리오를
 * 자동으로 태울 방법이 없었다. 인텐트로 질문을 받아 여기로 흘려보내면 화면의 전송
 * 버튼과 똑같은 경로를 타고, **세션이 유지되므로 멀티턴도 그대로 된다**:
 *
 *     adb shell am start -n com.example.hjp/.MainActivity --es q "대전에 있는 변호사 찾아줘"
 *     adb shell am start -n com.example.hjp/.MainActivity --es q "두 번째 사람 연락처"
 *
 * 결과는 DIAG_TAG 로그로 나온다. 운영 동작에는 영향이 없다(인텐트가 없으면 아무 일도
 * 안 한다). replay=0 이라 화면 회전 등으로 다시 구독해도 옛 질문이 재실행되지 않는다.
 */
internal object DebugQuestion {
    /**
     * 대기 중인 질문. **SharedFlow 가 아니라 상태로 들고 있는다** — 흘려보내는 방식은
     * 채팅 화면이 아직 안 떠 있으면 구독자가 없어 그냥 버려졌다(실측: 명함 탭에 있을 때
     * 인텐트가 조용히 무시됨). 상태로 두면 탭 전환 -> 화면 구성 -> 처리 순서가 보장된다.
     */
    var pending by mutableStateOf<String?>(null)
        private set

    fun offer(question: String?) {
        if (!question.isNullOrBlank()) pending = question.trim()
    }

    fun consume() {
        pending = null
    }
}

private data class ChatResult(
    val answer: String,
    val search: CardSearchResponse?,
    /**
     * 어느 처리 경로로 갔는지 — 진단 로그와 실기기/노트북 대조에 쓴다.
     * hybrid_server.py 의 "route" 필드와 같은 이름을 쓴다(양쪽 비교가 목적).
     */
    val route: String? = null,
    val error: String? = null,
    val modelLabel: String? = null,
    /** 재검색 없이 직전 결과를 근거로 답한 턴인가(정정/확인/복수지시 발화). */
    val conversationalFollowup: Boolean = false,
    /** LLM 이 무관하다고 판단해 카드 목록에서 뺀 사람들. */
    val filteredOut: List<String> = emptyList(),
)

private data class ChatMessage(
    val isUser: Boolean,
    val text: String,
    val modelLabel: String? = null,
    val search: CardSearchResponse? = null,
    val error: String? = null,
    val conversationalFollowup: Boolean = false,
    val filteredOut: List<String> = emptyList(),
)

@Composable
fun HjpApp(
    searchService: CardSearchService,
    initialToolLlmStatus: String,
    initialChatLlmStatus: String,
) {
    var selectedTab by remember { mutableStateOf(AppTab.Cards) }
    // 디버그 인텐트로 질문이 들어오면 채팅 화면으로 옮긴다 — 그 화면이 떠 있어야
    // 질문이 처리된다(adb 로 탭을 누르는 건 기기에서 잘 안 먹혔다).
    LaunchedEffect(DebugQuestion.pending) {
        if (DebugQuestion.pending != null) selectedTab = AppTab.Chat
    }
    var toolLlmStatus by remember { mutableStateOf(initialToolLlmStatus) }
    var chatLlmStatus by remember { mutableStateOf(initialChatLlmStatus) }

    Scaffold(
        // imePadding 은 **Scaffold 에** 건다. 화면 쪽 Column 에 걸면 Scaffold 가 이미 준
        // 하단 탭바 높이 패딩 위에 키보드 높이가 또 더해져서, 입력창이 키보드보다
        // 탭바 높이만큼 위로 떠 채팅 내용이 가려진다(실기기에서 확인).
        // 여기에 걸면 탭바까지 함께 올라가고 입력창이 키보드에 붙는다.
        modifier = Modifier
            .fillMaxSize()
            .imePadding(),
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
    // 멀티턴 세션 — 앱 프로세스가 살아있는 동안 하나를 유지한다(운영 아키텍처 규격).
    // 지칭 대상 인물과 직전 결과 카드는 tool_session_context 에 저장된다.
    val session = remember { AgentSession() }
    val messages = remember {
        mutableStateListOf(
            ChatMessage(isUser = false, text = "명함에 대해 문장으로 물어보세요.\n예) \"판교에 있는 AI 개발자 찾아줘\"")
        )
    }
    val listState = rememberLazyListState()

    // 질문 하나를 처리한다. 화면의 전송 버튼과 **디버그 인텐트**가 같이 쓴다.
    //
    // 인텐트 진입점을 둔 이유: `adb shell input text` 가 한글을 못 친다
    // (NullPointerException). 그래서 실기기에서 무엇이 일어나는지 확인하려면 사람이
    // 손으로 타이핑하는 수밖에 없었다. 아래 DebugQuestion 으로 밀어 넣으면
    // 노트북에서 시나리오를 그대로 태울 수 있고, 세션이 유지되므로 멀티턴도 된다.
    fun send(question: String) {
        if (question.isBlank()) return
            messages.add(ChatMessage(isUser = true, text = question))
            // 턴 시작을 구조화 메모리에 걸어둔다 — 이 턴이 끝까지 완료되지 못해도
            // (예외 등) 다음 턴에서 "아직 처리 못한 요청"으로 남는다.
            val turnId = java.util.UUID.randomUUID().toString()
            session.beginTurn(turnId, question)
            scope.launch {
                asking = true
                val startedAt = System.currentTimeMillis()
                val result = withContext(Dispatchers.IO) {
                    runChat(context, searchService, question, session)
                }
                asking = false
                // 실기기 진단 로그. `adb logcat -s HJP` 로 본다.
                //
                // 이게 없을 때는 폰에서 무슨 일이 일어나는지 전혀 볼 수 없었다 —
                // 크래시만 보이고 어느 경로로 갔는지, 어떤 조건이 잡혔는지, 얼마나
                // 걸렸는지가 안 보여서 화면을 눈으로 읽는 수밖에 없었다.
                // 노트북 서버(hybrid_server.py)가 내는 항목과 **같은 이름**을 쓴다 —
                // 양자화 임베딩 때문에 폰과 노트북의 검색 순위가 갈릴 수 있어서
                // 둘을 나란히 놓고 대조하는 게 목적이다.
                android.util.Log.i(
                    DIAG_TAG,
                    buildString {
                        append("q=").append(question)
                        append(" | route=").append(result.route ?: "-")
                        append(" | ms=").append(System.currentTimeMillis() - startedAt)
                        result.search?.let { s ->
                            append(" | filters=").append(s.fieldFilters)
                            append(" | abstained=").append(s.abstained)
                            append(" | cards=")
                                .append(s.results.joinToString(",") { it.card.name })
                        }
                        if (result.filteredOut.isNotEmpty()) {
                            append(" | dropped=").append(result.filteredOut.joinToString(","))
                        }
                        append(" | answer=").append(result.answer.replace('\n', ' ').take(120))
                        result.error?.let { append(" | error=").append(it) }
                    },
                )
                // 대화 내역은 세션이 관리한다(최근 8개 window + 구조화 메모리).
                // 후속 발화 재사용 턴은 새로 검색하지 않았으니 도구 실행 기록도 없다.
                val executedTools = if (result.conversationalFollowup) {
                    emptyList()
                } else {
                    listOf("search_business_cards")
                }
                session.recordTurn(turnId, question, result.answer, executedTools)
                // 질문이 실제로 이름을 지목했으면 그 이름을 지칭 대상으로 삼는다(우선).
                // 그런 이름이 없으면(대명사/생략형 후속) 검색 1등 카드로 대체 — 새 개념
                // 검색("판교 AI개발자 찾아줘")에서도 focus가 정상적으로 잡히게.
                // "검색 1등이면 무조건 focus"였던 예전 방식은 유사 이름 오매칭 시
                // focus가 엉뚱한 사람으로 튀는 문제가 있었다(실기기에서 발견).
                val resultNames = result.search?.results?.map { it.card.name }?.distinct().orEmpty()
                val namedInQuestion = resultNames.firstOrNull { name -> question.contains(name) }
                (namedInQuestion ?: resultNames.firstOrNull())?.let {
                    session.putToolContext(AgentSession.KEY_FOCUS_PERSON, it)
                    // 담화 순서 지시("처음에 물어본 사람")를 풀려면 최근 창 밖의 인물도
                    // 알아야 한다. focus 는 매 턴 그 턴의 주인공이므로 그대로 쌓으면
                    // '대화에 등장한 순서'가 된다.
                    session.putToolContext(
                        AgentSession.KEY_SUBJECT_HISTORY,
                        appendSubject(session.toolContextValue(AgentSession.KEY_SUBJECT_HISTORY), it),
                    )
                }
                // 정정/확인 발화가 아니었을 때만 근거 카드를 갱신한다
                // (정정 턴은 직전 근거를 그대로 유지해야 대화가 이어진다).
                if (!result.conversationalFollowup) {
                    val ids = result.search?.results?.map { it.card.id }.orEmpty()
                    session.putToolContext(
                        AgentSession.KEY_LAST_CARD_IDS,
                        ids.joinToString(",").ifBlank { null },
                    )
                    session.putToolContext(AgentSession.KEY_LAST_QUERY, question)
                }
                // 이번 턴이 물어본 속성을 남겨 둔다 — 다음 턴이 "○○씨는?" 처럼
                // 속성을 생략하면 여기서 이어받는다. 속성이 없는 질문이면
                // 이전 값을 그대로 둬서 대화 흐름을 유지한다.
                attributeOf(question)?.let {
                    session.putToolContext(AgentSession.KEY_LAST_ATTRIBUTE, it)
                }
                // 이번 턴에 걸린 필드 조건어를 남긴다 — 다음 턴이 "그중에 …" 로
                // 좁히면 여기서 이어받는다. 조건이 없었으면 이전 값을 유지한다.
                result.search?.fieldFilters?.let { f ->
                    val terms = (f.names + f.locations + f.titles).joinToString(" ")
                    if (terms.isNotBlank()) {
                        session.putToolContext(AgentSession.KEY_LAST_FILTER_TERMS, terms)
                    }
                }
                messages.add(
                    ChatMessage(
                        isUser = false,
                        text = result.answer,
                        modelLabel = result.modelLabel,
                        search = result.search,
                        error = result.error,
                        conversationalFollowup = result.conversationalFollowup,
                        filteredOut = result.filteredOut,
                    )
                )
            }
    }

    // 디버그 인텐트로 들어온 질문을 태운다(앱을 껐다 켜지 않으므로 세션이 유지된다).
    LaunchedEffect(DebugQuestion.pending, asking) {
        val q = DebugQuestion.pending
        if (q != null && !asking) {
            DebugQuestion.consume()
            send(q)
        }
    }

    LaunchedEffect(messages.size, asking) {
        listState.animateScrollToItem((messages.size - 1).coerceAtLeast(0))
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("채팅", style = MaterialTheme.typography.titleLarge)
            // 멀티턴 기억을 초기화하고 대화를 처음부터 다시 시작한다.
            TextButton(
                enabled = !asking,
                onClick = {
                    messages.clear()
                    messages.add(
                        ChatMessage(isUser = false, text = "명함에 대해 문장으로 물어보세요.\n예) \"판교에 있는 AI 개발자 찾아줘\"")
                    )
                    // 세션 초기화 시 대화 내역과 모델 conversation 을 모두 폐기한다.
                    session.reset()
                    scope.launch(Dispatchers.IO) { LiteRtLmChatEngine.resetSharedChat() }
                },
            ) {
                Text("새 대화")
            }
        }

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
                    val q = input.trim()
                    input = ""
                    send(q)
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
            SearchSummary(search, message.conversationalFollowup, message.filteredOut)
            search.results.take(5).forEach { hit ->
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
            subtitle = "Gemma 4 E2B IT · gemma-4-E2B-it.litertlm",
            role = "채팅 탭에서 검색된 명함 내용을 바탕으로 답변 문장을 만드는 모델입니다.",
            state = if (chatLlmStatus.startsWith("missing:")) ModelState.Missing else ModelState.Ready,
            stateLabel = if (chatLlmStatus.startsWith("missing:")) "모델 파일 없음 — 파일을 가져와 주세요" else "파일 있음 — 동작 확인으로 실행을 검사하세요",
            detail = "",
            onImport = {
                pendingModelFileName = "gemma-4-E2B-it.litertlm"
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
private fun SearchSummary(
    response: CardSearchResponse,
    conversationalFollowup: Boolean = false,
    filteredOut: List<String> = emptyList(),
) {
    // 검색이 왜 이렇게 동작했는지 화면에서 바로 보이게 한다 — 라우팅/필터/기권이 조용히
    // 결과를 바꾸면 "검색이 이상하다"와 "규칙이 걸렸다"를 구분할 수 없다.
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AssistChip(onClick = {}, label = { Text("키워드: ${response.keywordQuery.ifBlank { "전체" }}") })
            AssistChip(onClick = {}, label = { Text(response.retrieval) })
        }
        val notes = buildList {
            if (conversationalFollowup) add("정정/확인 발화 → 재검색 없이 직전 결과 사용")
            if (response.identifierRouted) add("식별자 질의 → 시맨틱 제외")
            if (!response.fieldFilters.isEmpty) add("필드 필터 ${response.fieldFilters}")
            if (response.abstained) add("기권 — 없는 이름/지역/번호")
            if (filteredOut.isNotEmpty()) add("무관 판정 제외 ${filteredOut.size}명: ${filteredOut.joinToString(", ")}")
        }
        notes.forEach {
            Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
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

/** 조건에 맞는 사람이 하나도 없을 때 쓰는 고정 문구. LLM 도 이 문구로 답하도록 지시한다. */
private const val NO_MATCH_PHRASE = "조건에 해당하는 명함을 찾지 못했습니다."

/**
 * 위 고정 문구 외에, LLM이 다른 말투로 "못 찾았다"고 답하는 경우도 거절로 인정한다.
 * 실측(스트레스 테스트): "김철수 전화번호 알려줘"에 "김철수 전화번호는 찾지 못했습니다."
 * 라고 답했는데 NO_MATCH_PHRASE 와 정확히 안 겹쳐서 거절로 인식을 못 했고, 그 결과
 * "못 찾았다"는 답변 밑에 관계없는 카드가 그대로 남아있었다.
 * "없습니다"는 넣지 않는다 — "안정우는 나이가 없습니다"처럼 '그 사람은 있는데 그
 * 필드가 없다'는 정상 답변까지 거절로 오인해서 존재하는 카드를 지워버리기 때문이다.
 */
internal val REJECTION_MARKERS = listOf(NO_MATCH_PHRASE, "찾지 못했", "찾을 수 없", "찾지못했", "찾을수없")

/**
 * 명함 검색과 무관한 자기참조 질문("너는 누구야?") — 결정적으로 우회한다.
 * 실측: 프롬프트 규칙에만 맡기면 "너"를 명함 속 인물로 오인해서 관계없는 사람 이름을
 * 그대로 답했다(예: "너는 누구야?" -> "유유진").
 */
private val SELF_REFERENCE_PATTERNS = listOf(
    "너는 누구", "너 누구", "너는 뭐", "너 뭐야", "너 뭐하는", "너 몇 살", "너는 몇 살",
    "너는 ai", "너 ai", "너는 사람이야", "너는 로봇", "당신은 누구", "니 정체", "네 정체",
)
private const val SELF_REFERENCE_ANSWER = "저는 명함 검색을 도와드리는 온디바이스 AI 어시스턴트입니다."

internal fun isSelfReferenceQuestion(question: String): Boolean {
    val q = question.trim().lowercase()
    if (q.isEmpty()) return false
    return SELF_REFERENCE_PATTERNS.any { it in q }
}
/**
 * "너 뭐 할 줄 알아?" 같은 기능 질문 — 자기참조와 같은 이유로 결정적으로 우회한다.
 * 실측(전량 채점): 검색에 태우면 컨텍스트의 1등을 답으로 뱉었다("너 뭐 할 줄 알아?" -> "이현",
 * 카드 1장). 무관 요청 카드 억제 실패 1건이 이 계열이었다.
 *
 * **자기참조보다 먼저 판정해야 한다** — "너는 뭐 할 줄 알아?" 는 SELF_REFERENCE_PATTERNS 의
 * "너는 뭐" 에도 걸리는데, 그쪽이 먼저 잡으면 정체만 답하고 기능은 말하지 않는다.
 */
private val CAPABILITY_PATTERNS = listOf(
    "뭐 할 줄", "뭘 할 줄", "무엇을 할 줄", "뭐할 줄", "뭘할 줄",
    "뭐 할 수", "뭘 할 수", "무엇을 할 수", "할 수 있는 게", "할 수 있는게",
    "어떤 기능", "기능이 뭐", "기능 뭐", "뭐 도와", "뭘 도와", "어떻게 쓰는",
)

internal fun isCapabilityQuestion(question: String): Boolean {
    val q = question.trim().lowercase()
    if (q.isEmpty()) return false
    return CAPABILITY_PATTERNS.any { it in q }
}

/**
 * 기능 안내 문구. 검색은 이 화면 자체의 기능이라 항상 맨 앞에 두고, 나머지는 등록된
 * 도구에서 파생한다([ToolRegistry.capabilityLabels]). 도구가 늘면 여기를 고칠 필요가 없다.
 */
internal fun buildCapabilityAnswer(toolLabels: List<String>): String {
    val lines = mutableListOf("이름·회사·지역·직함으로 명함을 찾습니다.")
    lines += toolLabels
    return "저는 명함 검색을 도와드리는 온디바이스 AI 어시스턴트입니다. 이런 걸 할 수 있어요:\n" +
        lines.joinToString("\n") { "- $it" }
}


/**
 * "전체 몇 장/명" 같이 조건 없이 전체를 묻는 질문 — 결정적으로 우회한다. 검색은 항상
 * top-N(5명)까지만 후보를 채우므로, 이런 질문을 그냥 검색에 태우면 "총 5명"이라고
 * 답해버린다(실측: 60장인데 5명이라고 답함) — top-5를 전체로 착각하게 만드는 잘못된
 * 답이라 아예 검색 전에 걸러서 진짜 전체 개수로 답한다.
 *
 * 긴 신호 단어부터 원문에서 직접 걷어내고, 아무것도 안 남으면 "전체를 요구하는 것"으로
 * 판정한다. 토큰화(KeywordSearchRanker.analyze) 기반으로 먼저 시도했다가 실측으로
 * 버그를 발견해서 원문 문자열 직접 치환 방식으로 바꿨다: 조사 제거 로직이 "명함"을
 * 조사 뗀 형태에서만 걸러내고 원본 "명함이"는 안 걸러내는 불일치가 있었다.
 *
 * "등록된 사람 총 몇 명이야?"처럼 "전체/모두/전부" 없이 "총"+"몇"만으로 전체를 묻는
 * 문구도 신호에 추가했다(실측: 이 문구가 우회를 못 타서 "총 5명"으로 잘못 답함 —
 * top-5를 전체로 착각하는 원래 버그가 그대로 재현됨). "총"만으로는 안 걸고 "몇"과
 * 같이 나올 때만 건다 — "판교에 총 몇명이야?"처럼 조건이 있는 질의는 strip 단계에서
 * "판교"가 안 걷어지고 남으므로 어차피 여기서 걸러진다(회귀 없음).
 */
private val GENERIC_LIST_STRIP_WORDS = listOf(
    // 긴 것부터 — "내가 가진"이 "내"보다 먼저 걷혀야 한다.
    "가지고 있어", "가지고 있는", "가지고있는", "내가 가진", "가진", "가지고",
    "저장된", "등록된", "있는", "있어", "있나", "있지",
    "보여줘", "알려줘", "찾아줘", "리스트", "목록", "전체", "명함", "이름",
    "카드", "사람", "모두", "전부", "얼마나", "몇", "장수", "개수", "장", "명", "총", "개",
    "내", "제", "다", "이", "야", "어", "지", "나",
    "은", "는", "이야", "인가", "될까",
    "?", "!", ".", ",", " ",
)

internal fun isUnfilteredListAllQuestion(question: String): Boolean {
    // 개수/목록을 묻는 말이 있어야 한다. 없으면 그냥 검색 질의다.
    //
    // 예전에는 "전체/모두/전부/총" 신호가 있어야만 통과시켰는데, 가장 자연스러운
    // 표현들이 그 신호를 안 쓴다 — "내가 가진 명함 개수 몇개야?", "명함 몇 개 있어?"
    // 가 전부 검색으로 빠져서 top-5 를 보고 "총 5명"이라 답했다(실기기 실측, 실제 1000).
    // 신호 게이트를 없애고 **일반 단어를 다 걷어냈을 때 아무것도 안 남으면 전체**로 본다.
    // 조건이 있으면("판교에 몇 명") 그 말이 안 걷혀서 남으므로 여기서 걸러진다.
    if (!Regex("몇|목록|리스트|다 보여|얼마나|개수|장수|전체|전부|모두").containsMatchIn(question)) return false
    var stripped = question
    for (w in GENERIC_LIST_STRIP_WORDS) stripped = stripped.replace(w, "")
    return stripped.trim().isEmpty()
}

private val FILTERED_COUNT_SIGNAL_RE = Regex("몇\\s*(명|장|개)")

/**
 * 조건이 있는 카운트 질문("판교에 몇 명 있어?", "이사 직급 몇 명이야?")인지 본다.
 * 조건 없는 전체질문(isUnfilteredListAllQuestion)은 이미 다른 우회가 처리하므로
 * 거기서 걸리면 여기서는 제외한다.
 */
internal fun isFilteredCountQuestion(question: String): Boolean {
    if (isUnfilteredListAllQuestion(question)) return false
    return FILTERED_COUNT_SIGNAL_RE.containsMatchIn(question)
}

/**
 * 멀티턴 RAG 채팅.
 *
 * 대화 상태는 AgentSession 이 갖는다(최근 메시지 8개 window + rolling summary +
 * tool_session_context). 그 위에 두 가지 결정적 처리가 얹혀 있다.
 *
 *  1) 지칭 치환: 후속 질문("그 사람 직급이 뭐야?")의 대명사를 직전 대상 인물로 치환한다.
 *     소형 모델의 LLM 재작성은 의도를 왜곡해(예: "어디 살아"→"회사") 불안정했고(실기기 확인),
 *     대화 기록에서 이름을 재추출하면 "전화번호는" 같은 명사를 인물로 오인했다.
 *     그래서 직전 검색 결과의 '실제 명함 이름'만 지칭 대상으로 쓴다.
 *  2) 정정/확인 발화 처리: "5명인데?" 같이 검색할 내용이 없는 발화는 재검색하지 않고
 *     직전 카드를 그대로 근거로 쓴다. 이게 없으면 엉뚱한 카드가 근거가 돼 대화가 끊긴다.
 */
private fun runChat(
    context: Context,
    searchService: CardSearchService,
    question: String,
    session: AgentSession,
): ChatResult {
    if (question.isBlank()) return ChatResult("질문을 입력하세요.", null, route = "blank")

    // 검색/LLM 엔진 로드보다 먼저 결정적으로 우회할 질문인지 본다 — 불필요한 엔진 로드를
    // 막기도 하고, 프롬프트 규칙에만 맡기면 신뢰할 수 없는 질문 유형이기도 하다.
    // conversationalFollowup=true로 반환한다 — 검색을 안 했으니 도구 실행 기록을 남기지
    // 않고, focus/직전 카드 id도 건드리지 않는 게 이 플래그의 기존 의미와 정확히 같다.
    // 기능 질문은 자기참조보다 먼저 본다("너는 뭐 할 줄 알아?" 가 양쪽에 걸린다).
    if (isCapabilityQuestion(question)) {
        val registry = ToolRegistry(CreateCalendarEventTool(context), OpenComposeTool(context))
        return ChatResult(
            buildCapabilityAnswer(registry.capabilityLabels()),
            null,
            route = "capability",
            conversationalFollowup = true,
        )
    }
    if (isSelfReferenceQuestion(question)) {
        return ChatResult(SELF_REFERENCE_ANSWER, null, route = "self_reference", conversationalFollowup = true)
    }
    if (isUnfilteredListAllQuestion(question)) {
        val total = searchService.totalCardCount()
        return ChatResult(
            "현재 총 ${total}명의 명함이 등록되어 있습니다. 이름·회사·지역 등 구체적인 조건으로 검색해 보세요.",
            null,
            route = "total_count",
            conversationalFollowup = true,
        )
    }
    // 조건이 있는 카운트 질문은 검색(top-5 컷)을 안 태우고 전체 카드를 직접 세서 정확한
    // 개수로 답한다(실측: "AI 다루는 사람 몇 명이야?" 가 실제 42명인데 검색은 5명까지만
    // 봐서 캡됨). 가제티어가 모르는 조건(개념형 질의)이면 null이 와서 기존 검색+LLM
    // 경로로 그대로 떨어진다.
    if (isFilteredCountQuestion(question)) {
        val matched = searchService.countByCondition(question)
        if (matched != null) {
            val sample = matched.take(5).map { card ->
                CardSearchHit(card = card, score = 0.0, keywordRank = null, vectorRank = null, similarity = 0f)
            }
            val response = CardSearchResponse(
                query = question,
                engine = "count",
                retrieval = "gazetteer-count",
                keywordQuery = question,
                semanticQuery = question,
                results = sample,
            )
            return ChatResult(
                "총 ${matched.size}명",
                response,
                route = "filtered_count",
                conversationalFollowup = true,
            )
        }
    }

    val focusPerson = session.toolContextValue(AgentSession.KEY_FOCUS_PERSON)
    val prevCardIds = session.toolContextValue(AgentSession.KEY_LAST_CARD_IDS)
        ?.split(",")?.filter { it.isNotBlank() }.orEmpty()

    // 속성을 생략한 후속("음가영씨는?")이면 직전 턴이 물어본 속성을 이어 붙인다.
    // 아래 로직은 전부 이 보충된 질문을 쓴다 — 검색어와 LLM 에 넘기는 질문이 갈리면
    // 카드는 맞는데 답변만 엉뚱해진다.
    @Suppress("NAME_SHADOWING")
    val question = applyNarrowing(
        carryOverAttribute(
            // 담화 순서 지시는 **가장 먼저** 푼다. 뒤로 밀면 "첫 번째 사람"이 아래
            // ordinalIdx 블록으로 새서 직전 카드 목록의 1번을 고른다.
            // 대상 정정은 대명사 치환(resolveSearchQuery)보다 **먼저** 푼다 —
            // 뒤에 두면 '그분'이 이미 옛 focus 로 바뀐 뒤라 정정이 무시된다.
            resolveCorrection(
                resolveDiscourseReference(
                    question,
                    session.toolContextValue(AgentSession.KEY_SUBJECT_HISTORY),
                    prevCardIds.size,
                ),
                runCatching { searchService.knownNamesIn(question) }.getOrNull().orEmpty(),
            ),
            session.toolContextValue(AgentSession.KEY_LAST_ATTRIBUTE),
        ),
        session.toolContextValue(AgentSession.KEY_LAST_FILTER_TERMS),
    )

    // Chat 모델(Gemma 4 E2B 등)이 없거나 메모리가 부족한 폰에서는 FunctionGemma로 대신 답변한다.
    val role = when {
        !LiteRtLmChatEngine.modelStatus(context, LlmRole.Chat).startsWith("missing:") -> LlmRole.Chat
        !LiteRtLmChatEngine.modelStatus(context, LlmRole.ToolCalling).startsWith("missing:") -> LlmRole.ToolCalling
        else -> null
    }

    // LLM이 아예 없으면 재작성도 불가 — 원문 질문으로 검색만 해서 결과를 보여준다.
    if (role == null) {
        val search = runCatching { searchService.searchHybrid(question, 5) }.getOrNull()
        return ChatResult(
            answer = if (search?.abstained == true) NO_MATCH_PHRASE
            else "LLM 모델이 없어 검색 결과만 보여드려요. 모델 탭에서 LLM 파일을 가져오면 답변도 생성됩니다.",
            search = search,
        )
    }

    val engine = try {
        LiteRtLmChatEngine.openShared(context, role) // 공유 엔진 — 닫지 않는다(반복 로드 스파이크 방지)
    } catch (e: Throwable) {
        val search = runCatching { searchService.searchHybrid(question, 5) }.getOrNull()
        return ChatResult("LLM 로드에 실패했어요. 검색 결과만 보여드려요.", search, error = e.message ?: e.javaClass.simpleName)
    }
    val loadedModel = engine.loadedFileName.removeSuffix(".litertlm")
    val modelLabel = if (role == LlmRole.ToolCalling) "$loadedModel (임시 대체 — 품질 낮음)" else loadedModel

    // 순서 지시("두 번째 사람")면 직전 집합에서 그 하나만 남긴다. 새 검색이 아니라
    // 앞 결과를 가리키는 발화이므로 아래 후속 경로로 보낸다.
    val ordinalIdx = ConversationalFollowup.ordinalIndex(question)
    val selectedIds = if (ordinalIdx != null && prevCardIds.isNotEmpty()) {
        val i = if (ordinalIdx < 0) prevCardIds.size - 1 else ordinalIdx
        prevCardIds.getOrNull(i)?.let { listOf(it) } ?: prevCardIds
    } else {
        prevCardIds
    }

    // 정정/확인/복수지시 발화 — 새로 검색하지 않고 직전 턴의 카드를 그대로 근거로 쓴다.
    if ((ConversationalFollowup.isFollowup(question) || ordinalIdx != null) &&
        selectedIds.isNotEmpty()
    ) {
        val search = runCatching { searchService.searchByIds(selectedIds) }.getOrNull()
        val answer = fieldListAnswer(question, search?.results?.map { it.card }.orEmpty())
            ?: emptyFieldAnswer(question, search?.results?.map { it.card }.orEmpty())
            ?: runCatching {
                engine.generate(
                    buildAnswerPrompt(session, question, search?.ragContext(5).orEmpty(), followup = true)
                )
            }.getOrNull().orEmpty()
        val finalAnswer = answer.ifBlank { "직전 결과 기준으로 답변을 만들지 못했어요." }
        // 후속 발화에서도 LLM이 "못 찾았다"고 답할 수 있다 — 메인 경로와 동일하게 그
        // 경우 카드를 비운다(일관성 문제였다. 메인 경로는 이미 narrowByAnswer로 처리함).
        var narrowedSearch = search
        var dropped: List<String> = emptyList()
        if (search != null) {
            val (n, d) = narrowByAnswer(search, finalAnswer)
            narrowedSearch = n
            dropped = d
        }
        return ChatResult(
            answer = finalAnswer,
            search = narrowedSearch,
            route = "followup",
            modelLabel = modelLabel,
            conversationalFollowup = true,
            filteredOut = dropped,
        )
    }

    // 문맥 참조 발화("아까 말한 …")인데 새로 검색하라는 말이 없으면, 검색도 LLM 호출도
    // 없이 이미 아는 것으로 답한다(sojung contextAnswerForSearch).
    //
    // **대화형 후속 검사보다 뒤에 둔다.** 앞에 두었더니 "그 사람들 회사 알려줘"가
    // CONTEXT_REFERENCES 의 "그 사람"에 걸려서 직전 답변을 그대로 재생했다 — 사용자는
    // 회사를 물었는데 이름 목록만 다시 받는다(멀티턴 평가에서 21건 잡힘).
    // 직전 결과 집합에 대해 **새로 묻는** 발화는 그 카드로 다시 답을 만들어야 하고,
    // context_answer 는 "아까 뭐였지"처럼 **되짚는** 발화에만 쓴다.
    ConversationalFollowup.contextAnswer(session, question)?.let { contextual ->
        val prior = if (prevCardIds.isNotEmpty()) {
            runCatching { searchService.searchByIds(prevCardIds) }.getOrNull()
        } else {
            null
        }
        return ChatResult(
            answer = contextual,
            search = prior,
            route = "context_answer",
            modelLabel = modelLabel,
            conversationalFollowup = true,
        )
    }

    val searchQuery = resolveSearchQuery(question, focusPerson)

    val search = try {
        searchService.searchHybrid(searchQuery, 5)
    } catch (e: Throwable) {
        return ChatResult("검색 중 문제가 있었습니다.", null, error = e.message ?: e.javaClass.simpleName)
    }

    // 근거가 없으면 LLM 을 호출하지 않는다 — 부르면 무관한 카드로 답을 지어낸다
    // (실측: 없는 사람 "정하은"에 대해 "채용설명회에서 만났습니다"라고 답했다).
    //
    // 기권뿐 아니라 **후보가 0장인 경우**도 포함한다. "부산에 있는 디자인"처럼 지역·직함이
    // 둘 다 데이터에 있는데 교집합만 비는 경우인데, 빈 컨텍스트를 넣었더니 2B 모델이
    // 컨텍스트 문자열("검색 후보 없음")을 그대로 답변으로 뱉었다(pass^3 3회 모두 재현).
    if (search.abstained || search.results.isEmpty()) {
        return ChatResult(
            answer = NO_MATCH_PHRASE,
            search = search,
            route = if (search.abstained) "abstain" else "empty_result",
            modelLabel = modelLabel,
        )
    }

    // 조건이 명확해서 전체를 셀 수 있으면 그 진짜 수를 컨텍스트에 넣는다. 못 세는
    // 개념형 질의면 null 이라 헤더에 숫자가 안 들어간다 — 모델이 후보 개수를 답으로
    // 옮겨 적는 것을 막기 위해서다(실측: "디자인하는 사람" -> 이름 대신 "총 3명").
    val totalMatches = runCatching { searchService.countByCondition(question)?.size }.getOrNull()

    return try {
        val llmAnswer = fieldListAnswer(question, search.results.map { it.card })
            ?: emptyFieldAnswer(question, search.results.map { it.card })
            ?: engine.generate(
                buildAnswerPrompt(session, question, search.ragContext(5, totalMatches)))
        if (llmAnswer == LiteRtLmChatEngine.EMPTY_RESPONSE) {
            ChatResult(
                answer = "LLM이 유효한 답변을 만들지 못했어요. 검색 결과를 참고해 주세요." +
                    if (role == LlmRole.ToolCalling) "\n(FunctionGemma는 대화용 모델이 아니라 자주 이렇습니다)" else "",
                search = search,
                modelLabel = loadedModel,
            )
        } else {
            // LLM 판정을 카드 목록에도 반영한다. 검색은 top-N 을 채우느라 무관한 후보를 함께
            // 담는데(점수 컷오프로는 못 자른다는 것을 오프라인 측정으로 확인), LLM 은 그중
            // 관련 있는 사람만 골라 답한다. 그 판단을 화면 카드에도 적용해 답변과 카드가
            // 어긋나지 않게 한다.
            val (narrowed, dropped) = narrowByAnswer(search, llmAnswer)
            ChatResult(
                answer = llmAnswer,
                search = narrowed,
                route = "search",
                modelLabel = modelLabel,
                filteredOut = dropped,
            )
        }
    } catch (e: Throwable) {
        ChatResult(
            answer = "LLM 답변 생성에 실패했어요. 검색 결과는 아래에서 확인할 수 있습니다.",
            search = search,
            error = e.message ?: e.javaClass.simpleName,
        )
    }
}

// buildAnswerPrompt 규칙 3번("맨 위 '총 N명'을 그대로 쓰고")이 요구하는 집계형 답변
// 형식과 정확히 맞춘 패턴. 답변에 후보 이름도 없고 이 패턴도 없으면 명함과 무관한
// 답변이라는 뜻이다(실측: "오늘 날씨 어때?" -> "날씨 정보는 명함 컨텍스트에 포함되어
// 있지 않습니다." 인데 top-5 후보가 그대로 카드로 남음. "홍길동 명함 삭제해 줘"
// (존재 안 하는 이름) -> 의도 확인 답변인데 엉뚱한 홍씨 5명이 카드로 남음).
private val AGGREGATE_COUNT_RE = Regex("총\\s*(\\d+)\\s*명")

/**
 * 답변이 이 카드를 근거로 삼았는가.
 *
 * 이름만 보면 안 된다(실측 회귀): "문선영씨 회사가 어디야?" -> "주식회사 노블어패럴입니다."
 * 처럼 필드 값으로만 답하는 게 정상인 질문이 많은데, 이름이 없다는 이유로 카드를 통째로
 * 지워버렸다. 회사/주소/이메일/전화 같은 '그 카드에서 온 값'도 근거로 인정한다.
 * 직함은 쓰지 않는다 — 여러 사람이 공유해서 변별력이 없다.
 */
private fun cardReferencedIn(card: BusinessCardEntity, answer: String): Boolean {
    if (answer.isBlank()) return false
    val name = card.name.orEmpty().trim()
    if (name.isNotBlank() && name in answer) return true
    for (raw in listOf(card.company, card.address, card.email)) {
        // 라벨 접두어("A.  ", "E.  ")를 떼고 비교한다.
        val v = raw.orEmpty().trim().substringAfterLast("  ").trim()
        if (v.length < 4) continue
        if (v in answer) return true
        // LLM 이 값의 일부만 말하는 경우도 인정한다 — 주소가 대표적이다.
        // 실측: 카드가 "강원도 당진시 반포대2로 67 (승현이김리)" 인데 답변은 괄호를 뺀
        // "강원도 당진시 반포대2로 67" 이라 v in answer 가 False 였고 카드가 지워졌다.
        val head = v.substringBefore(" (").trim()
        if (head.length >= 6 && head in answer) return true
    }
    val digits = card.phone.orEmpty().filter { it.isDigit() }
    val answerDigits = answer.filter { it.isDigit() }
    if (digits.length >= 4 && answerDigits.length >= 4 && digits.takeLast(4) in answerDigits) return true
    return false
}

/**
 * LLM 답변에 언급된 사람만 카드로 남긴다.
 *
 * 답변이 전원 거절(NO_MATCH_PHRASE)이면 카드도 전부 비운다 — 안 그러면 "없습니다" 라는
 * 답변 밑에 명함이 그대로 뜬다. 아무 이름도 언급되지 않은 집계형 답변("총 5명")이면
 * 원본을 유지한다(이름이 없다고 해서 후보가 무관한 건 아니므로). 이름도 없고 집계형
 * 형식도 아니면 명함과 무관한 답변이므로 카드를 비운다.
 */
internal fun narrowByAnswer(
    search: CardSearchResponse,
    answer: String,
): Pair<CardSearchResponse, List<String>> {
    if (REJECTION_MARKERS.any { it in answer }) {
        return search.copy(results = emptyList()) to search.results.map { it.card.name }
    }
    val agg = AGGREGATE_COUNT_RE.find(answer)
    // "총 0명" — 숫자로 표현된 거절이다. 집계형이라고 카드를 살려두면 "총 0명"이라
    // 답하면서 명함 5장이 뜨는 모순이 된다(실측: "울릉도 근무자" -> '총 0명', 카드 5장).
    if (agg != null && agg.groupValues[1].toIntOrNull() == 0) {
        return search.copy(results = emptyList()) to search.results.map { it.card.name }
    }
    // **하드 필터를 통과한 카드는 답변이 뭐라 하든 지우지 않는다.**
    //
    // 필드 조건(이름/직함/지역)이 걸렸다는 건 검색이 이미 '조건을 만족하는 사람'만
    // 남겼다는 뜻이라, 그 카드들은 정의상 답이다. LLM 이 그중 일부만 말했다고 나머지를
    // 지우면 사용자가 답의 일부만 보게 된다.
    // 실기기 실측: "대전에 있는 변호사 찾아줘" -> 검색은 탁예린·방우성 2명을 맞게 찾았는데
    // 답변이 "탁예린" 한 명만 말해서 방우성이 잘렸다. 그 상태로 "두 번째 사람 연락처"를
    // 물으면 두 번째가 아예 없다. 같은 질문에도 매번 달라져서 재현이 들쭉날쭉했다.
    //
    // 이 함수의 원래 목적(무관한 카드가 답변과 어긋나게 뜨는 것 방지)은 **조건이 없는**
    // 질의에서만 필요하다 — "오늘 날씨 어때?" 는 필드 조건이 안 잡히므로 아래로 내려가
    // 예전처럼 비워진다. 거절 답변은 위 두 분기에서 이미 걸러진다.
    if (!search.fieldFilters.isEmpty) {
        return search to emptyList()
    }
    val mentioned = search.results.filter { cardReferencedIn(it.card, answer) }
    if (mentioned.isNotEmpty()) {
        val dropped = search.results.filterNot { it in mentioned }.map { it.card.name }
        return search.copy(results = mentioned) to dropped
    }
    if (agg == null) {
        return search.copy(results = emptyList()) to search.results.map { it.card.name }
    }
    // 집계형인데 답변이 말한 수가 후보 수보다 적으면 그 수만큼만 보여준다.
    // 안 그러면 "총 2명"이라 답하고 카드는 5장 뜨는 모순이 된다
    // (실측: "AI 개발하는 사람 찾아줘" -> '총 2명' + 카드 5장. 뒤 3장은 AI개발팀이지만
    //  직함이 대표이사·디자인 디렉터라 실제 답이 아니었다).
    // 정렬이 정확 일치를 앞에 두므로 상위 N개가 그 N명이다.
    val want = agg.groupValues[1].toIntOrNull() ?: return search to emptyList()
    if (want in 1 until search.results.size) {
        val kept = search.results.take(want)
        return search.copy(results = kept) to search.results.drop(want).map { it.card.name }
    }
    return search to emptyList()
}

// 후속 질문임을 나타내는 대명사/지시 표현들. 이게 있을 때 직전 인물로 치환한다.
private val FOLLOWUP_PRONOUNS = listOf(
    "그 사람", "그사람", "그 분", "그분", "이 사람", "이사람", "저 사람", "저사람",
    "그 사람의", "걔", "그 회사", "그회사", "방금 그", "그 명함", "이 분", "이분",
)

// 속성 명사로 시작하는 생략형 후속("메일은?", "직급은?")도 직전 인물에 대한 질문으로 본다.
// 반대로 새 이름으로 시작하면("옹현은…", "홍길동은…") 새 인물로 보고 focus를 붙이지 않는다.
private val ATTRIBUTE_NOUNS = listOf(
    "전화번호", "전화", "번호", "연락처", "핸드폰", "휴대폰", "메일", "이메일",
    "직급", "직함", "직책", "회사", "소속", "주소", "위치", "지역", "부서", "이름",
)

/**
 * 후속 질문의 검색 쿼리를 만든다. 대명사가 있고 직전 대화의 대상 인물(focusPerson)이 있으면
 * 그 이름으로 치환한다. focusPerson은 직전 검색 결과 최상위 카드의 '실제 명함 이름'이라,
 * 기록 텍스트에서 정규식으로 이름을 재추출할 때 생기던 오인("전화번호는"→인물)이 없다.
 * 이름이 이미 있는 질문(대명사 없음)은 그대로 둔다 — 의도 왜곡 없이 정확히 검색되게.
 */
/**
 * 생략된 **속성**을 직전 턴에서 이어받는다.
 *
 * 생략형 후속은 두 방향이 있는데 그동안 한쪽만 처리하고 있었다:
 *   "주소는?"      주어 생략 + 속성 명시  -> focus 인물을 앞에 붙임 (resolveSearchQuery)
 *   "음가영씨는?"  주어 명시 + 속성 생략  -> **처리 없음**
 * 뒤엣것은 검색은 맞게 되는데(그 사람 카드를 찾음) 답변이 "음가영"처럼 이름만 되돌아왔다.
 * 앞 턴이 "회사가 어디야?"였으면 이번에도 회사를 묻는 것이므로 그 속성을 붙여 준다.
 *
 * 별도 규칙을 더한 게 아니라 이미 있던 생략 처리의 나머지 절반이다.
 */

/**
 * 담화 순서 지시("처음에 물어본 사람 전화번호는?")를 그 사람 이름으로 바꿔 다시 쓴다.
 *
 * [ConversationalFollowup.ordinalIndex] 와 **다른 것**이다. 저쪽은 직전 결과 목록의
 * N번째 카드를 고르고, 이쪽은 **대화에서 N번째로 화제가 된 사람**을 가리킨다. 지시 대상이
 * 카드 목록이 아니라 지난 발화라 focus 치환으로도 닿지 않는다(그 인물은 이미 최근 창 밖이다).
 *
 * 실측(HJP-limited/ymj Final50 v3): 이 처리가 없으면 "처음에 물어본 사람 전화번호는?" 이
 * 새 검색으로 빠지고 "처음/물어본/사람"이 검색어가 돼 대화에 없던 사람을 데려왔다
 * (long_range_reactivation 0/10, discourse_coreference 0/10).
 *
 * 이름을 앞에 붙여 **질의를 다시 쓰는** 방식이라(resolveSearchQuery·applyNarrowing 과 동일)
 * 그 뒤 검색·필터·focus 는 평소 경로를 그대로 탄다.
 */
private val DISCOURSE_VERBS = listOf(
    "물어본", "물어봤", "질문한", "질문했", "언급한", "언급했",
    "확인한", "확인했", "말한", "말했", "등장한", "나온",
)
private val DISCOURSE_FIRST = listOf("맨 처음", "처음에", "처음", "가장 먼저", "먼저")
private val DISCOURSE_HINTS = DISCOURSE_VERBS + DISCOURSE_FIRST + listOf("대화")

/** 이름을 앞에 붙인 뒤 남으면 검색어를 오염시키는 말들. 긴 것부터 지운다. */
private val DISCOURSE_STRIP = (DISCOURSE_HINTS + listOf(
    // 시간 부사를 남기면 contextAnswer 가 "아까"를 보고 되짚기로 오인해 직전 답변을
    // 재생한다(실측: "아까 처음에 물어본 분 전화번호는?" -> 엉뚱한 번호).
    "아까", "방금", "앞서",
    "그분", "그 분", "사람", "분", "대화에서", "두 사람", "중", "맨", "가장",
    "첫 번째로", "첫 번째", "첫번째", "번째로", "번째", "그", "했던", "던",
)).sortedByDescending { it.length }

/** 쉼표로 이어 둔 화제 인물 목록에 새 인물을 더한다(이미 있으면 순서를 유지한다). */
internal fun appendSubject(previous: String?, name: String): String {
    val list = previous?.split(",")?.filter { it.isNotBlank() }.orEmpty()
    return if (name in list) list.joinToString(",") else (list + name).joinToString(",")
}

/**
 * @param subjectHistory 대화에 등장한 인물(처음 나온 순서). [AgentSession.KEY_SUBJECT_HISTORY].
 * @param prevCardCount  직전 턴이 남긴 카드 수. 담화 단서 없는 순서 지시를 가를 때 쓴다.
 */
internal fun resolveDiscourseReference(
    question: String,
    subjectHistory: String?,
    prevCardCount: Int,
): String {
    val subjects = subjectHistory?.split(",")?.filter { it.isNotBlank() }.orEmpty()
    if (subjects.isEmpty()) return question
    // 질문이 이미 사람을 지목하고 있으면 지시가 아니다.
    if (subjects.any { it in question }) return question

    val idx = when {
        DISCOURSE_HINTS.any { it in question } ->
            if (DISCOURSE_FIRST.any { it in question }) 0
            else ConversationalFollowup.ordinalIndex(question)
        // "첫 번째 사람" 처럼 담화 단서가 없는 순서 지시. 직전 결과가 0~1장이면 거기서
        // 고를 게 없으므로 대화 순서를 가리키는 말로 읽는다(narrowByAnswer 4단계와 같은 원리).
        prevCardCount < 2 -> ConversationalFollowup.ordinalIndex(question)
        else -> null
    } ?: return question

    val name = (if (idx < 0) subjects.lastOrNull() else subjects.getOrNull(idx)) ?: return question
    var rest = question
    for (w in DISCOURSE_STRIP) rest = rest.replace(w, " ")
    rest = rest.replace(Regex("\\s+"), " ").trim()
    return "$name $rest".trim()
}


/** 대상 정정("A가 아니라 B야") 표지. */
private val CORRECTION_MARKERS = listOf("아니라", "말고", "정정", "아니고")

/**
 * "손서윤씨가 아니라 남다은씨야. 그분 회사는?" 처럼 **대상을 바꾸는** 발화를
 * 정정된 사람에 대한 질의로 다시 쓴다.
 *
 * 실측(Final50 v3): 이게 없으면 두 이름이 **둘 다** 이름 조건으로 잡히고, 대명사('그분')는
 * [resolveSearchQuery] 가 **옛 focus** 로 치환해 버린다("… 남다은씨야. 손서윤 회사는 어디야?").
 * 그러면 focus 가 옛 대상에 머물러 **그 뒤 모든 턴이 틀린 사람**을 답한다(4턴 시나리오가 통째로
 * 무너진다). 그래서 대명사 치환보다 **먼저** 돌아야 한다. 실측 4/10 -> 7/10.
 *
 * 정정 표지가 있고 아는 이름이 **둘 이상**일 때만 건다 — 마지막에 말한 이름이 정정된 대상이다.
 *
 * @param knownNames 이 발화에서 뽑힌, 데이터에 실재하는 이름들.
 */
internal fun resolveCorrection(question: String, knownNames: List<String>): String {
    if (CORRECTION_MARKERS.none { it in question }) return question
    if (knownNames.size < 2) return question
    // 추출 순서가 아니라 **발화에 나타난 위치** 순으로 본다.
    val ordered = knownNames.sortedBy { question.indexOf(it) }
    val target = ordered.last()
    // 정정 뒤의 실제 요청만 남긴다 — 마지막 문장이 그 요청이다.
    var tail = question
    for (sep in listOf(".", "!", "?")) {
        val parts = tail.split(sep).filter { it.isNotBlank() }
        if (parts.size > 1) tail = parts.last()
    }
    // 옛 이름과 대명사를 지운다 — 남으면 다시 이름 조건으로 잡히거나 focus 로 치환된다.
    for (n in ordered.dropLast(1)) tail = tail.replace("${n}씨", " ").replace(n, " ")
    for (p in FOLLOWUP_PRONOUNS) tail = tail.replace(p, " ")
    tail = tail.replace(Regex("\\s+"), " ").trim()
    return "$target $tail".trim()
}

internal fun carryOverAttribute(question: String, lastAttribute: String?): String {
    if (lastAttribute.isNullOrBlank()) return question
    val q = question.trim()
    // "이름 + 조사 + ?" 형태만 대상으로 한다("음가영씨는?", "그 사람은?").
    // 이미 속성 명사가 들어 있으면 손대지 않는다.
    if (ATTRIBUTE_NOUNS.any { it in q }) return question
    val m = Regex("^(.{2,10}?)(씨|님)?(는|은|이|가)\\s*\\??$").find(q) ?: return question
    val subject = m.groupValues[1] + m.groupValues[2]
    return "$subject $lastAttribute"
}

/** 질문에서 어떤 속성을 물었는지 뽑아 둔다(다음 턴이 속성을 생략했을 때 이어받으려고). */
internal fun attributeOf(question: String): String? =
    ATTRIBUTE_NOUNS.firstOrNull { it in question }
/**
 * 속성 명사 -> 카드 필드. 물어본 칸이 실제로 비어 있는지 보려고 둔다.
 * ('이름'은 비는 일이 없어 뺀다.)
 */
private val ATTRIBUTE_FIELD = mapOf(
    // 복합어를 **먼저** 등록한다. "메일 주소는?" 은 이메일 하나를 묻는 말이지
    // 이메일과 주소를 함께 묻는 말이 아니다(실측: 두 칸으로 읽혀 주소까지 답했다).
    "이메일 주소" to "email", "메일 주소" to "email",
    "이메일주소" to "email", "메일주소" to "email",
    "회사 주소" to "address", "회사주소" to "address",
    "전화번호" to "phone", "전화" to "phone", "번호" to "phone", "연락처" to "phone",
    "핸드폰" to "phone", "휴대폰" to "phone",
    "메일" to "email", "이메일" to "email",
    "직급" to "title", "직함" to "title", "직책" to "title",
    "회사" to "company", "소속" to "company",
    "주소" to "address", "위치" to "address", "지역" to "location",
    "부서" to "department",
)

/**
 * 대상이 하나로 정해졌는데 물어본 칸이 비어 있으면 결정적으로 '없다'고 답한다.
 *
 * 실측(Final50 v3 unanswerable): 빈 칸을 그냥 물으면 2B 모델이 **옆 칸 값으로 대체**했다 —
 * 회사를 물었는데 "국내영업팀입니다"(부서), "제주특별자치도 제주시"(주소), 직급을 물었는데
 * "생산관리팀입니다"(부서). 컨텍스트에 그 칸만 없을 뿐 나머지 값이 다 들어 있으니 모델이
 * 가장 그럴듯한 걸 골라 채운다. **값이 없다는 건 코드가 이미 아는 사실**이라 모델에
 * 맡길 이유가 없다(프롬프트 규칙 추가는 4전 4패다).
 *
 * 후보가 정확히 1장일 때만 건다 — 여러 명이면 '그중 누구의 칸'인지 정해지지 않는다
 * (narrowByAnswer 4단계와 같은 원리).
 */

/**
 * 지시 관형사 뒤의 속성 명사는 **요청이 아니라 가리키는 말**이다.
 * "그 회사 주소는?" 은 주소 하나만 묻는 것이지 회사를 함께 묻는 게 아니다
 * (실측: 이 구분이 없으면 우리 시나리오 '대명사 체인' 7턴이 통째로 오탐된다).
 */
private val DEMONSTRATIVES = listOf("그", "이", "저")

/** 질의에서 그 명사가 **요청으로** 쓰인 첫 위치. 없으면 -1. */
private fun requestedPos(question: String, noun: String): Int {
    var start = 0
    while (true) {
        val pos = question.indexOf(noun, start)
        if (pos < 0) return -1
        val before = question.substring(0, pos).trimEnd()
        if (DEMONSTRATIVES.none { before.endsWith(it) }) return pos
        start = pos + 1
    }
}

/**
 * 질의가 물은 속성들을 **말한 순서대로**, 필드 기준 중복 없이 돌려준다.
 * '전화번호'가 '전화'·'번호'를 품는 식으로 명사가 겹치므로 **긴 명사부터** 본다 —
 * 짧은 쪽이 먼저 잡히면 라벨이 잘려 나온다("메일: …").
 */
internal fun requestedFields(question: String): List<Pair<String, String>> {
    val found = mutableListOf<Triple<Int, String, String>>()
    val taken = mutableListOf<IntRange>()   // 이미 어떤 명사가 차지한 글자 구간
    for (noun in ATTRIBUTE_FIELD.keys.sortedByDescending { it.length }) {
        val field = ATTRIBUTE_FIELD.getValue(noun)
        if (found.any { it.second == field }) continue
        val pos = requestedPos(question, noun)
        if (pos < 0) continue
        // 앞서 잡힌 명사 안에 들어 있으면 같은 말을 두 번 세는 것이다.
        if (taken.any { pos in it }) continue
        taken.add(pos until pos + noun.length)
        found.add(Triple(pos, field, noun))
    }
    return found.sortedBy { it.first }.map { it.second to it.third }
}

/**
 * 한 사람에게 **여러 칸**을 물으면 코드가 직접 조합해 답한다.
 *
 * 실측(Final50 v3): "회사와 이메일도 알려줘" 에 2B 모델이 이메일만 답했다(4건).
 * 값은 컨텍스트에 다 있는데 모델이 하나를 빠뜨리는 것이라 **검색·문맥 문제가 아니다.**
 * 어느 칸을 물었는지도, 그 값이 무엇인지도 코드가 이미 안다
 * (프롬프트 규칙 추가는 4전 4패다). 담화 지시 6/10 -> 10/10.
 *
 * 두 칸 이상일 때만 건다 — 한 칸짜리는 LLM 이 문장으로 답하게 둔다(자연스러움 유지).
 * 후보가 정확히 1장일 때만 건다 — 여러 명이면 '누구의 칸'인지 안 정해진다.
 */
internal fun fieldListAnswer(question: String, cards: List<BusinessCardEntity>): String? {
    if (cards.size != 1) return null
    val fields = requestedFields(question)
    if (fields.size < 2) return null
    val card = cards[0]
    return fields.joinToString(", ") { (field, noun) ->
        val value = cardField(card, field)
        if (value.isNullOrBlank()) "$noun: 정보 없음" else "$noun: $value"
    }
}

private fun cardField(card: BusinessCardEntity, field: String): String? = when (field) {
    "phone" -> card.phone
    "email" -> card.email
    "title" -> card.title
    "company" -> card.company
    "address" -> card.address
    "location" -> card.location
    "department" -> card.department
    else -> null
}

internal fun emptyFieldAnswer(question: String, cards: List<BusinessCardEntity>): String? {
    if (cards.size != 1) return null
    val attr = attributeOf(question) ?: return null
    val field = ATTRIBUTE_FIELD[attr] ?: return null
    val card = cards[0]
    val value = cardField(card, field)
    if (!value.isNullOrBlank()) return null
    return "$attr 정보가 없습니다."
}


/** "그중에", "거기서" — 앞 턴 결과 안에서 더 좁히자는 표현. */
private val NARROWING_MARKERS = listOf("그중", "그 중", "거기서", "그 안에서", "그것들 중")

/**
 * 점진적 좁히기 — 앞 턴의 조건을 이어받는다.
 *
 * "대전에 있는 사람 찾아줘" -> "그중에 변호사만" 에서 앞 턴의 지역 조건이 사라져
 * **전국 변호사**가 나왔다. 매 턴 질문에서 조건을 새로 뽑기 때문이다.
 *
 * 조건을 따로 병합하지 않고 **앞 턴의 조건어를 질의 앞에 붙인다** — focus 인물을 앞에
 * 붙이는 resolveSearchQuery 와 같은 방식이다. 그러면 필터 추출이 알아서 둘을 합치고,
 * 검색어에도 그 말이 들어가서 후보 풀에 해당 지역 사람이 실제로 담긴다
 * (필터만 합치면 풀에 대전 사람이 없어 걸러낼 대상 자체가 없을 수 있다).
 */
internal fun applyNarrowing(question: String, previousTerms: String?): String {
    if (previousTerms.isNullOrBlank()) return question
    if (NARROWING_MARKERS.none { it in question }) return question
    return "$previousTerms $question"
}

/**
 * 속성 명사 앞에 흔히 붙는 군말. 이걸 떼고도 속성으로 시작하면 생략형 후속이다
 * ("어느 부서야?", "그럼 주소는?"). 지시 관형사(그/이/저)는 넣지 않는다 —
 * 그건 [FOLLOWUP_PRONOUNS] 가 이미 담당하므로 중복이다.
 */
private val ELLIPSIS_LEAD_FILLERS =
    listOf("어느", "어떤", "그럼", "그러면", "근데", "그리고", "혹시", "이제", "또")

internal fun resolveSearchQuery(question: String, focusPerson: String?): String {
    if (focusPerson == null) return question
    val hasPronoun = FOLLOWUP_PRONOUNS.any { question.contains(it) }
    // 질문에 '새 검색값'(전화번호 뒷자리 등)이 있으면 생략형 후속으로 보지 않는다 —
    // "번호 뒷자리 4312인 분"처럼 새 값을 주는 질문을 이전 focus에 억지로 묶으면 안 됨.
    //
    // 숫자가 하나라도 있으면 새 값으로 봤더니 실측으로 버그가 났다: "전화번호 뒤 4자리는
    // 뭐야"의 '4'가 새 값으로 잡혀서 직전 인물이 안 붙고 엉뚱한 검색이 됐다(답변은
    // '조건에 해당하는 명함을 찾지 못했습니다', focus 도 딴 사람으로 튐).
    // '4자리' 같은 자릿수 표현과 '4312' 같은 검색값은 자릿수 길이로 가른다.
    val hasNewValue = Regex("\\d{3,}").containsMatchIn(question)
    // 속성 명사 **앞에 붙는 군말**을 떼고도 본다. startsWith 만 보면 "부서는?"은 되는데
    // "어느 부서야?"는 새 검색으로 빠져 focus 가 엉뚱한 사람으로 튄다 — 그 한 턴이
    // 오염시키면 **뒤 턴이 연쇄로 무너진다**(실측: 평가 발화를 다양화하자 실패 2건 -> 32건,
    // 대부분이 이 한 가지 말투에서 시작된 연쇄였다. 고친 뒤 다시 2건).
    val trimmed = question.trimStart()
    val withoutFiller = ELLIPSIS_LEAD_FILLERS
        .firstOrNull { trimmed.startsWith(it) }
        ?.let { trimmed.removePrefix(it).trimStart() }
        ?: trimmed
    val isElliptical = !hasNewValue &&
        ATTRIBUTE_NOUNS.any { trimmed.startsWith(it) || withoutFiller.startsWith(it) }
    // 대명사도 없고 속성 명사로 시작하지도 않으면 새 인물/독립 질문 — 그대로 둔다.
    if (!hasPronoun && !isElliptical) return question
    var q = question
    for (p in FOLLOWUP_PRONOUNS) q = q.replace(p, focusPerson)
    // 대명사 치환이 없었으면(생략형 후속) 이름을 앞에 붙여 focus 인물로 검색되게 한다.
    return if (q != question) q else "$focusPerson $question"
}

/**
 * 검색 컨텍스트 + 세션 컨텍스트로 최종 답변 프롬프트를 만든다.
 *
 * 규칙 수를 늘릴수록 2B 모델의 준수율이 떨어진다(실측: 규칙 6개일 때 "판교에 있는 디자이너"에
 * 이름 대신 "총 2명"이라고 답했다). 꼭 필요한 것만 두고, 실제로 결과를 좌우하는 규칙을
 * 뒤에 배치한다 — 최근 규칙일수록 더 잘 따른다.
 */
private fun buildAnswerPrompt(
    session: AgentSession,
    question: String,
    ragContext: String,
    followup: Boolean = false,
): String {
    val rules = buildString {
        append("You are an on-device assistant for a business card app.\n")
        append("Answer in Korean using only the business card context below.\n")
        append("- \"그 사람\" 같은 표현은 이전 대화에서 다룬 인물을 가리킨다. 그 인물 기준으로 답하라.\n")
        append("- 되묻지 말고 바로 답하라. 이름을 물으면 이름을 답하라.\n")
        // 2B 모델은 목록을 세다 틀린다(실측: 판교 5명을 맞게 검색했는데 "4명입니다").
        // 그래서 셀 일이 없게 컨텍스트 맨 위에 개수를 박아 두고 그대로 쓰게 한다.
        append("- 인원수를 물었을 때만 숫자를 써라. 후보 전원이 조건에 맞으면 맨 위 '총 N명'을\n")
        append("  그대로 쓰고 직접 세지 마라.\n")
        // 이 규칙이 무관 카드를 실제로 잘라낸다. '전원 거절'은 같은 판단의 극단이라 붙여 둔다 —
        // 따로 떼면 모델이 후보 중 하나를 억지로 고른다(실측: "우주비행사 찾아줘" -> '장우주').
        append("- 가장 중요: 컨텍스트에 있다고 질문과 관련 있는 건 아니다. 직함·부서·업무로 판단해\n")
        append("  질문 조건에 맞는 사람만 답하고, 무관한 사람은 이름조차 언급하지 마라.\n")
        append("  이름 글자가 우연히 겹치는 것은 근거가 아니다.\n")
        append("  맞는 사람이 하나도 없으면 다른 말 없이 '$NO_MATCH_PHRASE' 라고만 답하라.\n")
        if (followup) {
            append("- 지금 사용자 발화는 새 검색이 아니라 직전 답변에 대한 정정/확인/추가질문이다.\n")
            append("  아래 컨텍스트는 '직전 검색 결과'다. 이 사람들만 대상으로 짧게 답하라.\n")
            append("  사용자가 숫자나 사실을 정정했고 컨텍스트가 사용자 말과 맞으면 정정을 인정하라.\n")
            // 무엇을 물었는지 **코드로 뽑아서** 알려준다. 규칙을 하나 더 얹는 게 아니라
            // 이미 해석해 둔 의도를 전달하는 것이다 — 이게 없으면 "두 번째 사람 연락처"
            // 처럼 속성을 명시해도 모델이 이름만 돌려줬다(실기기 실측). followup 분기가
            // "짧게 답하라"로만 유도해서 무엇을 답할지가 비어 있었다.
            attributeOf(question)?.let {
                append("- 사용자가 물은 것은 '$it' 다. 그 값을 답하라(이름만 답하지 마라).\n")
            }
        }
    }
    return "$rules\n${session.buildContextBlocks(question)}\n\n명함 컨텍스트:\n$ragContext"
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
