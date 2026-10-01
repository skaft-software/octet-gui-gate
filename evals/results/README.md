# Observed local results

- `before-identity-fix.json`: the initial 51-case fault-injection eval found one
  false green (identity `true` accepted as pinned `1`). This predates the added
  boundary/assertion/protocol cases; it is not an 80-case baseline comparison.
- `windows-host.json`: **80/80 contract cases passed**, **0/49 injected-fault
  false greens**, on Windows AMD64 with Python 3.14.4. The separate regression
  suite passed **27/27** tests; compileall and the tracked diff whitespace check
  also passed. The full-product CLI gate was exercised and returned **1**, as
  expected, because live qualification is absent.

The current snapshot records the unchanged Git HEAD **and a dirty worktree**.
The evaluated file hashes, not that HEAD alone, identify the tested candidate.
Result snapshots are not part of their own source fingerprint. This is local
host evidence, not a claim that the new evals ran on remote macOS/Linux CI.

Full raw case evidence and extension-protocol transcripts remain locally at:

```text
eval-artifacts/eval-f1c3ca4e6a8f417dab8dd3a4124ff035/
```

Raw files are intentionally ignored by Git. The future CI workflow retains its
own runs as artifacts for 14 days. Keep a permanent archive before a qualified
release. Relative `artifact` paths in the snapshot resolve inside the original
eval directory above, not inside this results directory or a fresh clone.

The observed synthetic p50/p95 timings in the snapshot are **not VM boot,
snapshot, or real desktop measurements**. `product_qualified` remains false.
See [the evaluation policy](../../docs/evaluation.md) for the live release block.
