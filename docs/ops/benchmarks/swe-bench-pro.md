# swe-bench-pro (pending Harbor adapter)

```bash
uv run bencheval benchmark show swe-bench-pro
```

- **Harness:** Harbor dataset `swebenchpro` (host pulls instance images).
- **Status:** cataloged only. `run swe-bench-pro` should fail until a real official task selector is wired.
- **Admission requirement:** add a typed slice with real upstream task ids/selectors from the host harness and parse official result artifacts.
- **Host deps:** Harbor + Docker; large image cache expected on the 2TB host.
- **Claim:** no benchmark-native claim until a live official run writes evidence.
