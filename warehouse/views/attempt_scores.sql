CREATE OR REPLACE VIEW attempt_scores AS
SELECT
    run_id,
    task_id,
    task_version,
    model_id,
    backend,
    execution_profile,
    primary_pass,
    partial_score,
    cost_usd,
    latency_sec,
    created_at
FROM attempts;
