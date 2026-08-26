# `results/proofs/` — local private proof store (gitignored)

Finalized `private_proof_v1` directories live here. They retain raw/capture
artifacts and logs and are **machine-local**.

```gitignore
results/proofs/*
!results/proofs/README.md
```

Only this README is tracked. Installed proofs land under `sha256/<digest>/` and
are indexed by ignored `proofs.jsonl`.
