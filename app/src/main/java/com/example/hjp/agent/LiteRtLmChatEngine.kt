package com.example.hjp.agent

import android.content.Context
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Conversation
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import java.io.File

class LiteRtLmChatEngine private constructor(
    private val engine: Engine,
    private val conversation: Conversation,
    val backendName: String,
) : AutoCloseable {

    @Synchronized
    fun generate(prompt: String): String {
        val response = conversation.sendMessage(prompt)
        return response?.toString()?.trim().orEmpty().ifBlank { "(empty LLM response)" }
    }

    override fun close() {
        try {
            conversation.close()
        } finally {
            engine.close()
        }
    }

    companion object {
        private const val ASSET_MODEL = "gemma/functiongemma_270m.litertlm"
        private const val FILE_MODEL = "functiongemma_270m.litertlm"

        fun modelStatus(context: Context): String =
            locateModel(context)?.absolutePath ?: "missing: ${expectedModelLocations(context).joinToString(" | ")}"

        fun open(context: Context): LiteRtLmChatEngine {
            val model = locateModel(context)
                ?: throw IllegalStateException("FunctionGemma 270M model not found. Put it at app/src/main/assets/$ASSET_MODEL or files/models/$FILE_MODEL.")
            Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
            return try {
                create(context, model.absolutePath, Backend.GPU(), "GPU")
            } catch (gpuError: Throwable) {
                create(context, model.absolutePath, Backend.CPU(), "CPU fallback after ${gpuError.javaClass.simpleName}")
            }
        }

        private fun locateModel(context: Context): File? {
            expectedModelFiles(context).firstOrNull { it.exists() && it.length() > 0L }?.let { return it }
            return if (assetExists(context, ASSET_MODEL)) materializeAsset(context, ASSET_MODEL, FILE_MODEL) else null
        }

        private fun expectedModelFiles(context: Context): List<File> {
            val external = context.getExternalFilesDir("models")
            return listOfNotNull(
                File(File(context.filesDir, "models"), FILE_MODEL),
                File(context.filesDir, FILE_MODEL),
                external?.let { File(it, FILE_MODEL) },
            )
        }

        private fun expectedModelLocations(context: Context): List<String> =
            expectedModelFiles(context).map { it.absolutePath } + "app/src/main/assets/$ASSET_MODEL"

        private fun create(
            context: Context,
            modelPath: String,
            backend: Backend,
            backendName: String,
        ): LiteRtLmChatEngine {
            val config = EngineConfig(
                modelPath = modelPath,
                backend = backend,
                cacheDir = context.cacheDir.absolutePath,
            )
            val engine = Engine(config)
            engine.initialize()
            return LiteRtLmChatEngine(engine, engine.createConversation(), backendName)
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
