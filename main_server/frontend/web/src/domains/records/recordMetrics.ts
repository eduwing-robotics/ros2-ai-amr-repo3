import type { PollMetric } from "../../hooks/useCommLogs";

export function summarizePollMetrics(metrics: PollMetric[]) {
  const totals = metrics.reduce(
    (summary, metric) => ({
      requests: summary.requests + metric.request_count,
      successes: summary.successes + metric.success_count,
      elapsed: summary.elapsed + metric.average_elapsed_ms * metric.request_count,
    }),
    { requests: 0, successes: 0, elapsed: 0 },
  );
  return {
    requests: totals.requests,
    successRate: totals.requests ? ((totals.successes * 100) / totals.requests).toFixed(1) : "—",
    averageMs: totals.requests ? (totals.elapsed / totals.requests).toFixed(1) : "—",
  };
}
