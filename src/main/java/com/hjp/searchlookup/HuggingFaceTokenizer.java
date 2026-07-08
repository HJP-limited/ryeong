package com.hjp.searchlookup;

import java.io.File;

public final class HuggingFaceTokenizer implements TextTokenizer {
    public static final String DEFAULT_ASSET_DIR = "app/src/main/assets/tokenizer/";
    private final String tokenizerDir;

    public HuggingFaceTokenizer(String tokenizerDir) {
        this.tokenizerDir = tokenizerDir == null || tokenizerDir.trim().isEmpty() ? DEFAULT_ASSET_DIR : tokenizerDir;
    }

    @Override
    public TokenizedInput tokenizeForModel(String text) {
        throw new IllegalStateException("HuggingFace tokenizer files are not wired to a JVM tokenizer runtime yet. "
                + "Android integration must load tokenizer assets from " + tokenizerDir
                + " and verify token ids against google/embeddinggemma-300m, including the known regex warning.");
    }

    @Override public String name() { return "HuggingFaceTokenizer"; }
    @Override public boolean isModelBacked() { return hasTokenizerFiles(); }
    @Override public String statusMessage() { return hasTokenizerFiles() ? "tokenizer assets present" : "tokenizer assets missing: " + tokenizerDir; }

    private boolean hasTokenizerFiles() {
        File dir = new File(tokenizerDir);
        return new File(dir, "tokenizer.json").exists() || new File(dir, "tokenizer.model").exists();
    }
}
