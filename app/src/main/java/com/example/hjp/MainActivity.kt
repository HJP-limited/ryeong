package com.example.hjp

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
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
import androidx.compose.ui.unit.dp
import com.example.hjp.agent.tools.CreateCalendarEventTool
import com.example.hjp.agent.tools.OpenComposeTool
import com.example.hjp.agent.tools.ToolRegistry
import com.example.hjp.ui.theme.HJPTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // 실제 앱에서는 에이전트 루프(ViewModel 등)에 주입될 레지스트리.
        // 지금은 LLM 없이 tool call을 직접 넣어 테스트한다.
        val registry = ToolRegistry(
            CreateCalendarEventTool(applicationContext),
            OpenComposeTool(applicationContext),
        )

        setContent {
            HJPTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    ToolTesterScreen(
                        registry = registry,
                        modifier = Modifier.padding(innerPadding)
                    )
                }
            }
        }
    }
}

/**
 * LLM이 출력했다고 가정한 tool call JSON을 직접 실행해 보는 테스트 화면.
 * 에이전트 루프가 완성되면 이 화면은 제거하고 registry만 연결하면 된다.
 */
@Composable
fun ToolTesterScreen(registry: ToolRegistry, modifier: Modifier = Modifier) {
    var toolCallJson by remember { mutableStateOf(SAMPLE_CALENDAR_CALL) }
    var result by remember { mutableStateOf("(아직 실행 안 함)") }
    val scope = rememberCoroutineScope()

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("Tool Call 테스트", style = MaterialTheme.typography.titleLarge)

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { toolCallJson = SAMPLE_CALENDAR_CALL }) { Text("캘린더 예시") }
            Button(onClick = { toolCallJson = SAMPLE_EMAIL_CALL }) { Text("메일 예시") }
            Button(onClick = { toolCallJson = SAMPLE_SMS_CALL }) { Text("문자 예시") }
        }

        OutlinedTextField(
            value = toolCallJson,
            onValueChange = { toolCallJson = it },
            label = { Text("LLM tool call (JSON)") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 8
        )

        Button(
            onClick = {
                scope.launch { result = registry.dispatch(toolCallJson) }
            },
            modifier = Modifier.fillMaxWidth()
        ) { Text("실행") }

        Text("결과 (LLM에게 전달될 문자열):", style = MaterialTheme.typography.titleMedium)
        Text(result, style = MaterialTheme.typography.bodyMedium)

        Text("시스템 프롬프트용 도구 선언:", style = MaterialTheme.typography.titleMedium)
        Text(registry.declarationsJson(), style = MaterialTheme.typography.bodySmall)
    }
}

private val SAMPLE_CALENDAR_CALL = """
{
  "name": "create_calendar_event",
  "args": {
    "title": "김민준 부장 미팅",
    "start_time": "2026-06-10T14:00",
    "end_time": "2026-06-10T15:00",
    "location": "강남역 스타벅스",
    "description": "명함앱 협업 논의\n김민준 / ABC전자 / 010-1234-5678",
    "attendee_emails": ["minjun.kim@example.com"]
  }
}
""".trimIndent()

private val SAMPLE_EMAIL_CALL = """
{
  "name": "open_compose",
  "args": {
    "channel": "email",
    "to": "minjun.kim@example.com",
    "subject": "지난 미팅 후속 자료 전달드립니다",
    "body": "김민준 부장님, 안녕하세요.\n\n지난 미팅에서 논의했던 자료를 정리하여 보내드립니다.\n\n감사합니다."
  }
}
""".trimIndent()

private val SAMPLE_SMS_CALL = """
{
  "name": "open_compose",
  "args": {
    "channel": "sms",
    "to": "010-1234-5678",
    "body": "김민준 부장님, 내일 14시 강남역 스타벅스에서 뵙겠습니다."
  }
}
""".trimIndent()
