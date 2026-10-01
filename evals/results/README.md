# Observed results (not live guest evidence)

## Initial harness/evaluator

- `before-identity-fix.json`: the initial 51-case fault-injection eval found one
  false green (identity `true` accepted as pinned `1`). This predates the added
  boundary/assertion/protocol cases; it is not an 80-case baseline comparison.
- `windows-host.json`: **80/80 contract cases passed**, **0/49 injected-fault
  false greens**, on Windows AMD64 with Python 3.14.4. Its separate regression
  suite passed 27/27 tests. This is historical evidence, not the current adapter.
- The subsequently pushed harness/evaluator commit `6cd7b23` passed synthetic CI
  on macOS, Windows, and Linux: [run 36809072232](https://github.com/skaft-software/octet-gui-gate/actions/runs/36809072232).

Historical raw evidence directory:
`eval-artifacts/eval-f1c3ca4e6a8f417dab8dd3a4124ff035/`.

## UTM/native calibration candidate

`windows-host-utm.json` records **80/80 contract cases passed**, **0/49 injected-fault
false greens**, on Windows AMD64 with Python 3.14.4. Separate local verification:

- 64 regression tests: **63 passed, one macOS-only API test skipped**.
- The calibration auditor's fabricated positive and 29 negative controls passed.
- Native Windows SID/session readout and concurrent filesystem publication were
  exercised locally; this does **not** qualify Windows guest GUI automation.
- `compileall` and the tracked diff whitespace check passed.
- The full-product eval was rerun and returned **1**, as expected; all its 80
  synthetic cases still passed and `product_qualified` remained false.

Evaluated source fingerprint:
`41262a4777ae8b89cf98ec779aed37f317bd128ed7af12e42f429fe46ac5a892`.

Raw contract evidence:
`eval-artifacts/staged-py310-evidence/eval-80ddea2e5dac4e4d831063092846ca3d/`.
Blocked product-gate evidence:
`eval-artifacts/staged-py310-evidence/eval-18e71dc392c1420eac6ba4d6ce11dd35/`.
Regression log: `eval-artifacts/staged-py310-unit.log`.

The candidate snapshot records Git HEAD `424f506` **and a dirty worktree**; the
recorded file hashes, not that HEAD alone, identify the tested candidate. Its
manifest includes new code/tests and example JSON. Verification used an isolated
archive of the staged source to avoid CRLF/LF differences in the original Windows
worktree: all **33** evaluated file hashes match Git's staged bytes. Result
snapshots and these notes are not part of their own source fingerprint. CI
evaluates the subsequently pushed exact revision separately; do not infer
candidate CI results from the historical run above.

The first adapter [CI run 36818804675](https://github.com/skaft-software/octet-gui-gate/actions/runs/36818804675)
failed on Python 3.10: a test f-string used newer syntax, and Windows's coarse
monotonic clock collapsed short desktop intervals. This candidate fixes the
fixture syntax and uses the high-resolution monotonic performance counter for
retained intervals/timings. The strict overlap assertion now also runs with a
frozen coarse clock; no overlap or negative control was weakened. Local checks
remain Python **3.14.4**; Python 3.10 runtime verification is a separate CI result.

Raw artifacts are intentionally ignored by Git. Relative `artifact` paths in each
snapshot resolve inside its original eval directory, not this results directory
or a fresh clone. CI retains evidence for 14 days; archive important evidence
outside ephemeral CI retention before a qualified release.

Synthetic latency numbers are **not VM boot, snapshot, or real desktop
measurements**. No live three-OS campaign, headroom measurement, or rebuild/consent
proof has been collected here. Both the calibration audit and full product gate
keep `product_qualified:false`. See [the evaluation policy](../../docs/evaluation.md).
