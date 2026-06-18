CREATE OR REPLACE VIEW cost_latency AS
SELECT
    run_id,
    benchmark_id,
    slice_id,
    runtime_id,
    model_id,
    task_id,
    instance_id,
    primary_pass,
    cost_usd,
    latency_sec,
    created_at
FROM attempts;
