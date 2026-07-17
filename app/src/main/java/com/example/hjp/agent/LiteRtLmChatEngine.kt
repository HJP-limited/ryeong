package com.example.hjp.agent

import android.content.Context
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Conversation
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import java.io.File

enum class LlmRole(val fileNames: List<String>, val assetPath: String, val displayName: String) {
    ToolCalling(
        fileNames = listOf("functiongemma_270m.litertlm"),
        assetPath = "gemma/functiongemma_270m.litertlm",
        displayName = "FunctionGemma 270M",
    ),

    // 후보 순서대로 찾는다: 1B(고성능, RAM 8GB+ 기기) -> 270M IT(저사양 기기용 경량)
    Chat(
        fileNames = listOf("gemma3-1b-it-int4.litertlm", "gemma3-270m-it-q8.litertlm"),
        assetPath = "gemma/gemma3-1b-it-int4.litertlm",
        displayName = "Chat Gemma",
    ),
    ;

    val fileName: String get() = fileNames.first()
}

class LiteRtLmChatEngine private constructor(
    private val engine: Engine,
    val backendName: String,
    val loadedFileName: String,
) : AutoCloseable {

    /** 질문마다 새 대화 세션을 만들어 이전 대화의 KV 캐시가 누적되지 않게 한다. */
    @Synchronized
    fun generate(prompt: String): String {
        val conversation = engine.createConversation()
        try {
            val response = conversation.sendMessage(prompt)
            // FunctionGemma처럼 대화용이 아닌 모델은 <pad> 같은 특수 토큰만 뱉기도 한다 — 걸러낸다
            val cleaned = response?.toString().orEmpty()
                .replace(Regex("<pad>|<eos>|<bos>|<end_of_turn>|<start_of_turn>|<unk>"), "")
                .trim()
            // 소형 모델이 같은 문자열을 무한 반복하는 degenerate 출력도 무효 처리한다 ("</h4></h4>..." 등)
            if (Regex("(.{3,40})\\1{4,}").containsMatchIn(cleaned)) return EMPTY_RESPONSE
            return cleaned.ifBlank { EMPTY_RESPONSE }
        } finally {
            conversation.close()
        }
    }

    override fun close() {
        engine.close()
    }

    companion object {
        const val EMPTY_RESPONSE = "(empty LLM response)"

        // 엔진을 열고 닫을 때마다 네이티브 메모리가 조금씩 새서(LiteRT-LM), 질문을 반복하면
        // 저사양 기기에서 앱이 통째로 죽는다. 그래서 엔진 하나를 로드해 두고 계속 재사용한다.
        private var shared: LiteRtLmChatEngine? = null
        private var sharedModelPath: String? = null

        fun modelStatus(context: Context, role: LlmRole): String =
            locateModel(context, role)?.absolutePath ?: "missing: ${expectedModelLocations(context, role).joinToString(" | ")}"

        /**
         * 공유 엔진을 돌려준다. 같은 모델이면 이미 로드된 엔진을 재사용하고,
         * 다른 모델이 요청되면 기존 것을 닫고 새로 연다 (한 번에 LLM 하나만 메모리에 유지).
         * 호출한 쪽에서 close()하지 말 것.
         */
        @Synchronized
        fun openShared(context: Context, role: LlmRole): LiteRtLmChatEngine {
            val model = locateModel(context, role)
                ?: throw IllegalStateException("${role.displayName} model not found. Put it at app/src/main/assets/${role.assetPath} or files/models/${role.fileNames.joinToString(" | ")}.")
            shared?.let { existing ->
                if (sharedModelPath == model.absolutePath) return existing
                existing.close()
                shared = null
                sharedModelPath = null
            }
            val engine = open(context, role)
            shared = engine
            sharedModelPath = model.absolutePath
            return engine
        }

        fun open(context: Context, role: LlmRole): LiteRtLmChatEngine {
            val model = locateModel(context, role)
                ?: throw IllegalStateException("${role.displayName} model not found. Put it at app/src/main/assets/${role.assetPath} or files/models/${role.fileNames.joinToString(" | ")}.")
            Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
            var gpuEngine: LiteRtLmChatEngine? = null
            return try {
                gpuEngine = create(context, model.absolutePath, Backend.GPU(), "GPU", model.name)
                // 일부 기기(특히 삼성)는 OpenCL 라이브러리가 없어도 엔진 초기화는 통과하고
                // 실제 생성(sendMessage) 시점에야 실패한다 — 그래서 초기화 성공만으로는 GPU가
                // 진짜 되는지 알 수 없어 짧은 시험 생성으로 확인한다.
                gpuEngine.generate("Hi")
                gpuEngine
            } catch (gpuError: Throwable) {
                gpuEngine?.close()
                create(context, model.absolutePath, Backend.CPU(), "CPU fallback after ${gpuError.javaClass.simpleName}", model.name)
            }
        }

        private fun locateModel(context: Context, role: LlmRole): File? {
            expectedModelFiles(context, role).firstOrNull { it.exists() && it.length() > 0L }?.let { return it }
            return if (assetExists(context, role.assetPath)) materializeAsset(context, role.assetPath, role.fileName) else null
        }

        private fun expectedModelFiles(context: Context, role: LlmRole): List<File> {
            val external = context.getExternalFilesDir("models")
            return role.fileNames.flatMap { fileName ->
                listOfNotNull(
                    File(File(context.filesDir, "models"), fileName),
                    File(context.filesDir, fileName),
                    external?.let { File(it, fileName) },
                )
            }
        }

        private fun expectedModelLocations(context: Context, role: LlmRole): List<String> =
            expectedModelFiles(context, role).map { it.absolutePath } + "app/src/main/assets/${role.assetPath}"

        private fun create(
            context: Context,
            modelPath: String,
            backend: Backend,
            backendName: String,
            loadedFileName: String,
        ): LiteRtLmChatEngine {
            val config = EngineConfig(
                modelPath = modelPath,
                backend = backend,
                cacheDir = context.cacheDir.absolutePath,
                // KV 캐시 메모리를 미리 크게 잡다가 저사양 기기에서 죽는 것을 막는다.
                // 프롬프트(명함 3장 ~300토큰) + 답변(~300토큰)이면 충분.
                maxNumTokens = 640,
            )
            val engine = Engine(config)
            engine.initialize()
            return LiteRtLmChatEngine(engine, backendName, loadedFileName)
        }

        private fun assetExists(context: Context, assetPath: String): Boolean =
            try {
                context.assets.open(assetPath).close()
                true
            } catch (_: Throwable) {
                false
            }

        private fun materializeAsset(context: Context, assetPath: String, fileName: String): File {
            val dir = File(context.filesDir, "models").apply { mkdirs() }
            val out = File(dir, fileName)
            if (out.exists() && out.length() > 0L) return out
            context.assets.open(assetPath).use { input ->
                out.outputStream().use { output -> input.copyTo(output) }
            }
            return out
        }
    }
}
