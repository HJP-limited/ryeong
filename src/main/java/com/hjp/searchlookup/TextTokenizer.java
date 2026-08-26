package com.hjp.searchlookup;

import java.util.List;

public interface TextTokenizer {
    TokenizedInput tokenizeForModel(String text);
    String name();
    boolean isModelBacked();
    String statusMessage();

    final class TokenizedInput {
        public final long[] inputIds;
        public final long[] attentionMask;

        public TokenizedInput(long[] inputIds, long[] attentionMask) {
            this.inputIds = inputIds == null ? new long[0] : inputIds;
            this.attentionMask = attentionMask == null ? new long[0] : attentionMask;
        }
    }
}
