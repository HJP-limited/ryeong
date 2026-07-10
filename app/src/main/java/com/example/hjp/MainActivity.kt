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
import com.example.hjp.agent.LiteRtLmChatEngine
import com.example.hjp.agent.tools.CreateCalendarEventTool
import com.example.hjp.agent.tools.OpenComposeTool
import com.example.hjp.agent.tools.SearchBusinessCardsTool
import com.example.hjp.agent.tools.ToolRegistry
import com.example.hjp.search.CardSearchService
import com.example.hjp.ui.theme.HJPTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val searchService = CardSearchService(applicationContext)
        val registry = ToolRegistry(
            SearchBusinessCardsTool(searchService),
            CreateCalendarEventTool(applicationContext),
            OpenComposeTool(applicationContext),
        )

        setContent {
            HJPTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    AgentTestScreen(
                        searchService = searchService,
                        registry = registry,
                        llmStatus = LiteRtLmChatEngine.modelStatus(applicationContext),
                        modifier = Modifier.padding(innerPadding)
                    )
                }
            }
        }
    }
}

@Composable
fun AgentTestScreen(
    searchService: CardSearchService,
    registry: ToolRegistry,
    llmStatus: String,
    modifier: Modifier = Modifier,
) {
    var query by remember { mutableStateOf("AI 개발팀 사람 찾아줘") }
    var result by remember { mutableStateOf("Ready") }
    var toolCall by remember {
        mutableStateOf(
            """
            {
              "name": "search_business_cards",
              "args": {
                "query": "AI 개발팀 사람 찾아줘",
                "limit": 5
              }
            }
            """.trimIndent()
        )
    }
    val scope = rememberCoroutineScope()

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("HJP On-device Agent", style = MaterialTheme.typography.titleLarge)
        Text("LLM: $llmStatus", style = MaterialTheme.typography.bodySmall)
        Text("Search: ${searchService.engineStatus}", style = MaterialTheme.typography.bodySmall)

        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("Search query") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 1
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                scope.launch {
                    result = withContext(Dispatchers.IO) {
                        searchService.search(query, 5).toJson().toString(2)
                    }
                }
            }) {
                Text("Search")
            }
            Button(onClick = {
                toolCall = JSONObject()
                    .put("name", "search_business_cards")
                    .put("args", JSONObject().put("query", query).put("limit", 5))
                    .toString(2)
            }) {
                Text("Make tool call")
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
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Diagnostics")
        }

        OutlinedTextField(
            value = toolCall,
            onValueChange = { toolCall = it },
            label = { Text("Tool call JSON") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 7
        )

        Button(
            onClick = {
                scope.launch {
                    result = registry.dispatch(toolCall)
                }
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Run tool")
        }

        Text("Result", style = MaterialTheme.typography.titleMedium)
        Text(result, style = MaterialTheme.typography.bodySmall)

        Text("Available tools", style = MaterialTheme.typography.titleMedium)
        Text(registry.declarationsJson(), style = MaterialTheme.typography.bodySmall)
    }
}
