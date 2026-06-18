CREATE OR REPLACE VIEW runtime_comparison AS
SELECT
    benchmark_id,
    slice_id,
    adapter_id,
    runtime_id,
    model_id,
    run_id,
    COUNT(*) AS attempt_count,
    SUM(CASE WHEN primary_pass THEN 1 ELSE 0 END) AS pass_count,
    AVG(partial_score) AS mean_partial_score,
    SUM(cost_usd) AS total_cost_usd,
    SUM(latency_sec) AS total_latency_sec
FROM attempts
WHERE benchmark_id IS NOT NULL
    AND runtime_id IS NOT NULL
GROUP BY benchmark_id, slice_id, adapter_id, runtime_id, model_id, run_id;
