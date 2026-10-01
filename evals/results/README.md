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
`9f35e59eae7e4c75e8f32017ffd5c64e44851c1e04b55ec3f9b8383757b161f5`.

Raw contract evidence:
`eval-artifacts/staged-evidence/eval-2ed5773f475b4fe7b3e02abf58e5dc61/`.
Blocked product-gate evidence:
`eval-artifacts/staged-evidence/eval-f4886388403e47d48f705d1fb7ca5769/`.
Regression log: `eval-artifacts/staged-unit.log`.

The candidate snapshot records Git HEAD `6cd7b23` **and a dirty worktree**; the
recorded file hashes, not that HEAD alone, identify the tested candidate. Its
manifest includes new code/tests and example JSON. Verification used an isolated
archive of the staged source to avoid CRLF/LF differences in the original Windows
worktree: all **33** evaluated file hashes match Git's staged bytes. Result
snapshots and these notes are not part of their own source fingerprint. CI
evaluates the subsequently pushed exact revision separately; do not infer
candidate CI results from the historical run above.

Raw artifacts are intentionally ignored by Git. Relative `artifact` paths in each
snapshot resolve inside its original eval directory, not this results directory
or a fresh clone. CI retains evidence for 14 days; archive important evidence
outside ephemeral CI retention before a qualified release.

Synthetic latency numbers are **not VM boot, snapshot, or real desktop
measurements**. No live three-OS campaign, headroom measurement, or rebuild/consent
proof has been collected here. Both the calibration audit and full product gate
keep `product_qualified:false`. See [the evaluation policy](../../docs/evaluation.md).
