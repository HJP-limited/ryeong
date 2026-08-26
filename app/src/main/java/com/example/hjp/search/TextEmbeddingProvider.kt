package com.example.hjp.search

import android.content.Context
import com.google.ai.edge.localagents.rag.models.EmbedData
import com.google.ai.edge.localagents.rag.models.EmbeddingRequest
import com.google.ai.edge.localagents.rag.models.GemmaEmbeddingModel
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.sqrt

interface TextEmbeddingProvider {
    val name: String
    val isModelBacked: Boolean
    val diagnosticStatus: String

    /** 검색 질의를 임베딩한다. EmbeddingGemma의 query 프롬프트 형식이 자동 적용된다. */
    fun embedQuery(text: String): FloatArray

    /** 저장할 문서(명함)를 임베딩한다. document 프롬프트 형식이 자동 적용된다. */
    fun embedDocument(text: String): FloatArray

    fun close() {}
}

/**
 * EmbeddingGemma 300M을 AI Edge RAG SDK(GemmaEmbeddingModel)로 실행한다.
 *
 * 필요한 파일 2개 (files/models 또는 외부 앱 폴더 models/):
 * - embeddinggemma-300m.tflite  (litert-community 양자화 모델)
 * - sentencepiece.model         (같은 저장소의 토크나이저)
 *
 * MediaPipe TextEmbedder는 이 모델에 필요한 메타데이터가 없어 로드하지 못한다
 * ("could not build model from the provided pre-loaded flatbuffer").
 */
class GemmaEmbeddingProvider(context: Context) : TextEmbeddingProvider {
    private val appContext = context.applicationContext
    private var model: GemmaEmbeddingModel? = null
    private var status = "not initialized"

    private val modelFile = findFile(MODEL_FILE_NAME)
    private val tokenizerFile = findFile(TOKENIZER_FILE_NAME)

    override val name: String
        get() = "EmbeddingGemma RAG (${modelFile?.name ?: "no model"})"

    override val isModelBacked: Boolean
        get() = model != null

    override val diagnosticStatus: String
        get() = status

    init {
        when {
            modelFile == null -> status = "missing: $MODEL_FILE_NAME — ${expectedLocations(MODEL_FILE_NAME).joinToString(" | ")}"
            tokenizerFile == null -> status = "missing: $TOKENIZER_FILE_NAME — ${expectedLocations(TOKENIZER_FILE_NAME).joinToString(" | ")}"
            else -> try {
                // GPU 초기화는 기기별 편차가 커서 CPU로 고정. seq256 문장 하나는 CPU로도 수십 ms 수준.
                model = GemmaEmbeddingModel(modelFile.absolutePath, tokenizerFile.absolutePath, false)
                status = "loaded from ${modelFile.absolutePath}"
            } catch (e: Throwable) {
                model = null
                status = "load failed: ${describeThrowable(e)}"
            }
        }
    }

    override fun embedQuery(text: String): FloatArray =
        run(EmbedData.create(text, EmbedData.TaskType.RETRIEVAL_QUERY, true))

    override fun embedDocument(text: String): FloatArray =
        run(EmbedData.create(text, EmbedData.TaskType.RETRIEVAL_DOCUMENT, false))

    private fun run(data: EmbedData<String>): FloatArray {
        val embedder = model ?: throw IllegalStateException("EmbeddingGemma is not loaded: $status")
        return try {
            val values = embedder.getEmbeddings(EmbeddingRequest.create(listOf(data))).get()
            normalize(FloatArray(values.size) { values[it] })
        } catch (e: Throwable) {
            status = "embed failed: ${describeThrowable(e)}"
            throw IllegalStateException(status, e)
        }
    }

    private fun findFile(fileName: String): File? =
        expectedFiles(fileName).firstOrNull { it.exists() && it.length() > 0L }

    private fun expectedFiles(fileName: String): List<File> {
        val external = appContext.getExternalFilesDir("models")
        return listOfNotNull(
            File(File(appContext.filesDir, "models"), fileName),
            external?.let { File(it, fileName) },
        )
    }

    private fun expectedLocations(fileName: String): List<String> =
        expectedFiles(fileName).map { it.absolutePath }

    private fun describeThrowable(error: Throwable): String {
        val chain = generateSequence(error) { it.cause }.take(4).toList()
        return chain.joinToString(" -> ") { item ->
            item.javaClass.simpleName + item.message?.let { ": $it" }.orEmpty()
        }
    }

    companion object {
        const val MODEL_FILE_NAME = "embeddinggemma-300m.tflite"
        const val TOKENIZER_FILE_NAME = "sentencepiece.model"
    }
}

fun normalize(source: FloatArray): FloatArray {
    var sum = 0f
    for (value in source) sum += value * value
    if (sum == 0f) return source
    val norm = sqrt(sum)
    for (i in source.indices) source[i] /= norm
    return source
}

fun cosine(a: FloatArray, b: FloatArray): Float {
    if (a.isEmpty() || a.size != b.size) return 0f
    var dot = 0f
    for (i in a.indices) dot += a[i] * b[i]
    return dot
}

fun FloatArray.toBlob(): ByteArray {
    val buffer = ByteBuffer.allocate(size * 4).order(ByteOrder.LITTLE_ENDIAN)
    forEach { buffer.putFloat(it) }
    return buffer.array()
}

fun ByteArray.toFloatArray(dimensions: Int): FloatArray {
    val buffer = ByteBuffer.wrap(this).order(ByteOrder.LITTLE_ENDIAN)
    return FloatArray(dimensions) { buffer.float }
}

fun sha256(text: String): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
    return digest.joinToString("") { "%02x".format(it) }
}
