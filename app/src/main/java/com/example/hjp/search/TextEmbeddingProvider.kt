package com.example.hjp.search

import android.content.Context
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.Locale
import kotlin.math.sqrt

interface TextEmbeddingProvider {
    val name: String
    val isModelBacked: Boolean
    val diagnosticStatus: String
    fun embed(text: String): FloatArray
}

class MediaPipeEmbeddingGemmaProvider(context: Context) : TextEmbeddingProvider {
    private val appContext = context.applicationContext
    private var textEmbedder: Any? = null
    private var status = "model asset not found"
    private val modelFile = findModelFile()
    private val modelAssetName = if (modelFile == null) {
        listOf("embeddinggemma_quant.tflite", "embeddinggemma.task").firstOrNull { assetExists(it) }
    } else {
        null
    }

    override val name: String
        get() = "EmbeddingGemma MediaPipe (${modelFile?.name ?: modelAssetName ?: status})"

    override val isModelBacked: Boolean
        get() = textEmbedder != null

    override val diagnosticStatus: String
        get() = status

    init {
        when {
            modelFile != null -> setup(modelFile)
            modelAssetName != null -> setupAsset(modelAssetName)
            else -> status = "missing: ${expectedModelLocations().joinToString(" | ")}"
        }
    }

    override fun embed(text: String): FloatArray {
        val embedder = textEmbedder ?: return FloatArray(0)
        return try {
            val result = embedder.javaClass.getMethod("embed", String::class.java).invoke(embedder, text)
            val embeddingResult = result.javaClass.getMethod("embeddingResult").invoke(result)
            val embeddings = embeddingResult.javaClass.getMethod("embeddings").invoke(embeddingResult) as List<*>
            val first = embeddings.firstOrNull() ?: return FloatArray(0)
            val values = first.javaClass.getMethod("floatEmbedding").invoke(first)
            val vector = when (values) {
                is FloatArray -> values
                is List<*> -> FloatArray(values.size) { (values[it] as Number).toFloat() }
                else -> FloatArray(0)
            }
            normalize(vector)
        } catch (e: Throwable) {
            status = "embed failed: ${e.javaClass.simpleName}"
            FloatArray(0)
        }
    }

    private fun setupAsset(assetName: String) {
        try {
            val baseOptionsClass = Class.forName("com.google.mediapipe.tasks.core.BaseOptions")
            val baseOptionsBuilder = baseOptionsClass.getMethod("builder").invoke(null)
            baseOptionsBuilder.javaClass
                .getMethod("setModelAssetPath", String::class.java)
                .invoke(baseOptionsBuilder, assetName)
            val baseOptions = baseOptionsBuilder.javaClass.getMethod("build").invoke(baseOptionsBuilder)

            val optionsClass = Class.forName(
                "com.google.mediapipe.tasks.text.textembedder.TextEmbedder\$TextEmbedderOptions"
            )
            val optionsBuilder = optionsClass.getMethod("builder").invoke(null)
            optionsBuilder.javaClass
                .getMethod("setBaseOptions", baseOptionsClass)
                .invoke(optionsBuilder, baseOptions)
            val options = optionsBuilder.javaClass.getMethod("build").invoke(optionsBuilder)

            val textEmbedderClass = Class.forName("com.google.mediapipe.tasks.text.textembedder.TextEmbedder")
            textEmbedder = textEmbedderClass
                .getMethod("createFromOptions", Context::class.java, optionsClass)
                .invoke(null, appContext, options)
            status = "loaded"
        } catch (e: Throwable) {
            textEmbedder = null
            status = "load failed: ${e.javaClass.simpleName}"
        }
    }

    private fun setup(modelFile: File) {
        try {
            val baseOptionsClass = Class.forName("com.google.mediapipe.tasks.core.BaseOptions")
            val baseOptionsBuilder = baseOptionsClass.getMethod("builder").invoke(null)
            val buffer = readDirectBuffer(modelFile)
            baseOptionsBuilder.javaClass
                .getMethod("setModelAssetBuffer", ByteBuffer::class.java)
                .invoke(baseOptionsBuilder, buffer)
            val baseOptions = baseOptionsBuilder.javaClass.getMethod("build").invoke(baseOptionsBuilder)

            val optionsClass = Class.forName(
                "com.google.mediapipe.tasks.text.textembedder.TextEmbedder\$TextEmbedderOptions"
            )
            val optionsBuilder = optionsClass.getMethod("builder").invoke(null)
            optionsBuilder.javaClass
                .getMethod("setBaseOptions", baseOptionsClass)
                .invoke(optionsBuilder, baseOptions)
            val options = optionsBuilder.javaClass.getMethod("build").invoke(optionsBuilder)

            val textEmbedderClass = Class.forName("com.google.mediapipe.tasks.text.textembedder.TextEmbedder")
            textEmbedder = textEmbedderClass
                .getMethod("createFromOptions", Context::class.java, optionsClass)
                .invoke(null, appContext, options)
            status = "loaded from ${modelFile.absolutePath}"
        } catch (e: Throwable) {
            textEmbedder = null
            status = "load failed from file: ${e.javaClass.simpleName}"
        }
    }

    private fun assetExists(name: String): Boolean =
        try {
            appContext.assets.open(name).close()
            true
        } catch (_: Throwable) {
            false
        }

    private fun findModelFile(): File? =
        expectedModelFiles().firstOrNull { it.exists() && it.length() > 0L }

    private fun expectedModelFiles(): List<File> {
        val external = appContext.getExternalFilesDir("models")
        return listOfNotNull(
            File(File(appContext.filesDir, "models"), "embeddinggemma_quant.tflite"),
            File(File(appContext.filesDir, "models"), "embeddinggemma.task"),
            external?.let { File(it, "embeddinggemma_quant.tflite") },
            external?.let { File(it, "embeddinggemma.task") },
        )
    }

    private fun expectedModelLocations(): List<String> =
        expectedModelFiles().map { it.absolutePath }

    private fun readDirectBuffer(file: File): ByteBuffer {
        val buffer = ByteBuffer.allocateDirect(file.length().toInt()).order(ByteOrder.nativeOrder())
        FileInputStream(file).use { input ->
            val bytes = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(bytes)
                if (read < 0) break
                buffer.put(bytes, 0, read)
            }
        }
        buffer.rewind()
        return buffer
    }
}

class LocalHashEmbeddingProvider : TextEmbeddingProvider {
    override val name = "LocalHashEmbeddingProvider"
    override val isModelBacked = false
    override val diagnosticStatus = "fallback hash embedding"

    override fun embed(text: String): FloatArray {
        val vector = FloatArray(192)
        val normalized = text.lowercase(Locale.KOREAN)
            .replace(Regex("[^0-9a-zA-Z가-힣\\s]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
        if (normalized.isEmpty()) return vector
        normalized.split(" ").forEach { token ->
            add(vector, "w:$token", 1.0f)
            for (n in 2..3) {
                if (token.length >= n) {
                    for (i in 0..token.length - n) add(vector, "g:${token.substring(i, i + n)}", 0.35f)
                }
            }
        }
        return normalize(vector)
    }

    private fun add(vector: FloatArray, feature: String, weight: Float) {
        val hash = feature.hashCode()
        val index = kotlin.math.abs(hash % vector.size)
        val sign = if ((hash and 1) == 0) 1f else -1f
        vector[index] += sign * weight
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
