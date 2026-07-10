package com.example.hjp.search

import android.content.Context
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
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
        val embedder = textEmbedder ?: throw IllegalStateException("EmbeddingGemma is not loaded: $status")
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
            throw IllegalStateException(status, e)
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
                ?: throw IllegalStateException("BaseOptions build returned null")
            setupWithBaseOptions(baseOptions, baseOptionsClass)
            status = "loaded from asset $assetName"
        } catch (e: Throwable) {
            textEmbedder = null
            status = "load failed from asset: ${describeThrowable(e)}"
        }
    }

    private fun setup(modelFile: File) {
        try {
            val baseOptionsClass = Class.forName("com.google.mediapipe.tasks.core.BaseOptions")
            val baseOptionsBuilder = baseOptionsClass.getMethod("builder").invoke(null)
            baseOptionsBuilder.javaClass
                .getMethod("setModelAssetBuffer", ByteBuffer::class.java)
                .invoke(baseOptionsBuilder, readDirectBuffer(modelFile))
            val baseOptions = baseOptionsBuilder.javaClass.getMethod("build").invoke(baseOptionsBuilder)
                ?: throw IllegalStateException("BaseOptions build returned null")
            setupWithBaseOptions(baseOptions, baseOptionsClass)
            status = "loaded from ${modelFile.absolutePath}"
        } catch (e: Throwable) {
            textEmbedder = null
            status = "load failed from file: ${describeThrowable(e)}"
        }
    }

    private fun setupWithBaseOptions(baseOptions: Any, baseOptionsClass: Class<*>) {
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

    private fun describeThrowable(error: Throwable): String {
        val chain = generateSequence(error) { it.cause }.take(4).toList()
        return chain.joinToString(" -> ") { item ->
            item.javaClass.simpleName + item.message?.let { ": $it" }.orEmpty()
        }
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
