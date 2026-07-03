package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public final class LightweightTokenizer {
    public String normalize(String value) {
        if (value == null) return "";
        return value.toLowerCase(Locale.KOREAN)
                .replaceAll("[^0-9a-z가-힣@._+\\-\\s]", " ")
                .replaceAll("\\s+", " ")
                .trim();
    }

    public List<String> tokenize(String value) {
        String normalized = normalize(value);
        if (normalized.isEmpty()) return new ArrayList<>();
        List<String> tokens = new ArrayList<>();
        for (String token : normalized.split("\\s+")) {
            if (!token.isEmpty()) tokens.add(token);
        }
        return tokens;
    }

    public List<String> tokenizeWithNgrams(String value) {
        Set<String> tokens = new LinkedHashSet<>(tokenize(value));
        for (String token : new ArrayList<>(tokens)) {
            String compact = token.replaceAll("[^0-9a-z가-힣]", "");
            if (compact.length() < 2) continue;
            for (int n = 2; n <= 3; n++) {
                for (int i = 0; i <= compact.length() - n; i++) {
                    tokens.add(compact.substring(i, i + n));
                }
            }
        }
        return new ArrayList<>(tokens);
    }
}
