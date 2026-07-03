package com.hjp.searchlookup.eval;

import com.hjp.searchlookup.SearchResult;

import java.util.Arrays;
import java.util.List;

public final class RagEvaluator {
    private RagEvaluator() {
    }

    public static Metrics evaluateAt5(List<EvalCase> cases, ResultProvider provider) {
        if (cases == null || cases.isEmpty()) return new Metrics(0.0, 0.0, 0.0);
        double recall = 0.0;
        double mrr = 0.0;
        double top1 = 0.0;
        for (EvalCase evalCase : cases) {
            List<SearchResult> results = provider.search(evalCase.query, 5);
            int firstRank = firstRelevantRank(results, evalCase.relevantCardIds, 5);
            if (firstRank > 0) {
                recall += 1.0;
                mrr += 1.0 / firstRank;
                if (firstRank == 1) top1 += 1.0;
            }
        }
        double total = cases.size();
        return new Metrics(recall / total, mrr / total, top1 / total);
    }

    public static List<EvalCase> sampleCases() {
        return Arrays.asList(
                new EvalCase("AI 개발팀 사람 찾아줘", Arrays.asList("C002")),
                new EvalCase("투자 미팅에서 만난 대표", Arrays.asList("C001")),
                new EvalCase("코어AI 검색 담당자", Arrays.asList("C002"))
        );
    }

    private static int firstRelevantRank(List<SearchResult> results, List<String> relevantIds, int limit) {
        if (results == null || relevantIds == null) return -1;
        int max = Math.min(limit, results.size());
        for (int i = 0; i < max; i++) {
            if (relevantIds.contains(results.get(i).cardId)) return i + 1;
        }
        return -1;
    }

    public interface ResultProvider {
        List<SearchResult> search(String query, int limit);
    }

    public static final class EvalCase {
        public final String query;
        public final List<String> relevantCardIds;

        public EvalCase(String query, List<String> relevantCardIds) {
            this.query = query;
            this.relevantCardIds = relevantCardIds;
        }
    }

    public static final class Metrics {
        public final double recallAt5;
        public final double mrrAt5;
        public final double top1Accuracy;

        public Metrics(double recallAt5, double mrrAt5, double top1Accuracy) {
            this.recallAt5 = recallAt5;
            this.mrrAt5 = mrrAt5;
            this.top1Accuracy = top1Accuracy;
        }
    }
}
