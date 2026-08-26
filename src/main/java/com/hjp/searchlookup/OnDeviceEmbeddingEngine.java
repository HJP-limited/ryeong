package com.hjp.searchlookup;

import java.io.File;

public final class OnDeviceEmbeddingEngine implements EmbeddingEngine {
    public static final String MODEL_NAME = "google/embeddinggemma-300m-onnx";
    public static final String DEFAULT_MODEL_PATH = "app/src/main/assets/models/embeddinggemma.onnx";
    public static final int DEFAULT_DIMENSION = 768;
    private final String modelPath;
    private final TextTokenizer tokenizer;
    private final EmbeddingEngine fallback;
    private final boolean fallbackEnabled;
    private boolean fallbackUsed;

    public OnDeviceEmbeddingEngine(String modelPath, TextTokenizer tokenizer, EmbeddingEngine fallback, boolean fallbackEnabled) {
        this.modelPath = modelPath == null || modelPath.trim().isEmpty() ? DEFAULT_MODEL_PATH : modelPath;
        this.tokenizer = tokenizer == null ? new HuggingFaceTokenizer(HuggingFaceTokenizer.DEFAULT_ASSET_DIR) : tokenizer;
        this.fallback = fallback == null ? new LocalEmbeddingEngine() : fallback;
        this.fallbackEnabled = fallbackEnabled;
    }

    public static OnDeviceEmbeddingEngine production() { return new OnDeviceEmbeddingEngine(DEFAULT_MODEL_PATH, new HuggingFaceTokenizer(HuggingFaceTokenizer.DEFAULT_ASSET_DIR), new LocalEmbeddingEngine(), true); }

    @Override public float[] embed(String input) {
        if (!isAvailable()) {
            String message = "EmbeddingGemma ONNX unavailable. Expected model at " + modelPath + "; " + tokenizer.statusMessage();
            if (!fallbackEnabled) throw new IllegalStateException(message);
            fallbackUsed = true;
            System.err.println(message + ". Falling back to " + fallback.name());
            return fallback.embed(input);
        }
        throw new UnsupportedOperationException("ONNX Runtime Android session wiring must run in Android. Add ai.onnxruntime:onnxruntime-android and map tokenizer inputs to model signature before production use.");
    }

    @Override public String name() { return MODEL_NAME + (fallbackUsed ? " (fallback:" + fallback.name() + ")" : ""); }
    @Override public boolean isModelBacked() { return isAvailable() && !fallbackUsed; }
    public boolean isFallbackUsed() { return fallbackUsed || !isAvailable(); }
    public int outputDimension() { return DEFAULT_DIMENSION; }
    public boolean isAvailable() { return new File(modelPath).exists() && tokenizer.isModelBacked(); }
}
