package com.hjp.searchlookup;

import java.util.*;

public final class QueryAnalyzer {
    public QueryAnalysis analyze(String rawQuery) {
        String raw = rawQuery == null ? "" : rawQuery;
        String normalized = normalize(raw);
        List<String> tokens = tokenize(normalized);
        return new QueryAnalysis(raw, normalized, String.join(" ", tokens), normalized, tokens);
    }

    public String normalize(String raw) {
        if (raw == null) return "";
        String lower = raw.trim().toLowerCase(Locale.ROOT);
        // Preserve Korean/English/numbers plus email/phone-friendly characters: @ . + - _ #
        String cleaned = lower.replaceAll("[^\\p{IsHangul}\\p{L}\\p{N}@._+\\-#\\s]", " ");
        cleaned = cleaned.replaceAll("(?<![\\p{L}\\p{N}])#", " ");
        return cleaned.replaceAll("\\s+", " ").trim();
    }

    private List<String> tokenize(String normalized) {
        if (normalized == null || normalized.isEmpty()) return Collections.emptyList();
        List<String> out = new ArrayList<>();
        for (String token : normalized.split("\\s+")) {
            String t = token.trim();
            if (!t.isEmpty()) out.add(t);
        }
        return out;
    }
}
