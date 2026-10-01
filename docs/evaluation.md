# Evaluation policy and requirement coverage

## The release decision

**The harness is evaluated; the cross-platform product is not qualified.**
Passing a synthetic eval is not permission to claim that the original six success
criteria are met. This repository publishes source, not a qualified GUI-testing
release. Do not tag/publish a supported release until the live acceptance work
below is completed and evaluated at the exact release revision.

```sh
# Fast regressions and grader sensitivity controls
python3 -m unittest discover -s tests -p 'test_*.py'

# Full code-graded synthetic contract evaluation; artifacts are retained
python3 -m evals.run --output eval-artifacts

# Full product gate: intentionally exits nonzero while live acceptance is absent
python3 -m evals.run --output eval-artifacts --require-product
```

The report separates `harness_passed` from `product_qualified`. The latter is
currently **always false** because live qualification has not been implemented
or performed; it cannot be flipped by a fixture's OS label or successful MCP
response. `--require-product` is a blocked release check, not a live-evidence
validator. A future live validator must be independently reviewed and evaluated
before removing this block.

CI runs regressions plus the full synthetic eval on Linux, Windows, and macOS
**hosts**, retaining artifacts even on failure. These do not create guests or
operate desktops. Manual CI dispatch can request the blocked full-product gate.
There is no release-publishing workflow or branch-protection guarantee here:
operators must not bypass the release policy through GitHub's release UI.

## Evaluation design

Applied the principles in Anthropic's
[Define success criteria and build evaluations](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)
(accessed October 1, 2026): define specific, measurable, relevant criteria; cover
normal and edge cases; automate grading; retain enough samples to evaluate
consistency rather than showcasing one successful demo.

This extension does not generate model responses, so a paid LLM judge would add
cost and ambiguity without improving these checks. Exact code grading and an
independent application-state oracle are the appropriate methods. No model API
or live desktop is invoked. The guidance's LLM evaluation examples are not used
as evidence of computer-use model quality or browser automation correctness.

### Thresholds, defined before grading

- **80/80 contract cases pass**; no average score can mask a safety failure.
- **0 false greens in 49 fault-injection cases**. This is a sample result, not a
  guarantee or a statistical estimate of live desktop reliability.
- **20/20 repeated three-label waves green** in the normal fixture; every wave
  begins with a pristine-state observation and verifies a Unicode write.
- All three subprocess reset intervals actually overlap in the concurrency case.
- Every retained step's recorded hash matches its file; every green scenario's
  raw before/action/after evidence matches the independent state oracle.
- Denied/unavailable workflow approval dispatches zero lifecycle commands.
- Identity, permission, desktop, catalog, or reset preflight failures dispatch
  zero tool calls on the failed target; cleanup must still be attempted.
- Failed cleanup stops retries, cancellations cannot be green, and gracefully
  shutting down the extension requests cleanup of already-started targets.
- Provider credential environment variables are not forwarded to workers/hooks.
- Invalid executable configuration is rejected before lifecycle dispatch.

### Distribution and independence

`evals/cases.json` contains 21 scenario definitions expanded to 51 subprocess
cases: two positive controls and 49 injected negative cases. Faults are exercised
against all three labels where relevant. Additional evaluations cover 11 invalid
configuration boundaries, 12 assertion/JSON Pointer edge cases, and six actual
Octet protocol workflows, for **80 cases** total.

`evals/fixture.py` is a fake desktop with persistent state. It is not Cua Driver,
a VM, a real accessibility tree, or an OS permission probe. The same scenario
reads pristine state, writes a per-target Unicode marker, and reads it back.
A successful write acknowledgement is not the oracle: `evals/run.py` inspects
raw observations and persisted state independently without using the production
assertion grader. Target names are deliberately different from the recorded
host OS. Concurrency is graded from subprocess timestamps, not from a mocked
thread-pool call.

`evals/wire.py` launches the actual extension entrypoint and acts as its Octet
JSON-RPC host. It evaluates approval, refusal, unavailable confirmation, absence
of a model-callable launch tool, cancellation, shutdown cleanup, status output,
and credential isolation. This evaluates the extension SDK protocol path, not
Octet's full host authority broker or its Windows process-tree supervision.

Grader sensitivity regressions reject an always-red campaign outcome, disabled
production assertions, and tampered step evidence. These controls are useful but
not an exhaustive mutation analysis. There is no held-out real-application
corpus yet. Add actual application regression scenarios and previously unseen
failure cases before claiming that this dataset represents production use.

## Original requirement matrix

| ID | Original requirement | What is evaluated | Remaining acceptance evidence |
| --- | --- | --- | --- |
| R1 | One scenario, named macos/windows/linux | Same scenario and data-only bindings; required catalogs; wire launch/status | Actual pinned Cua tool schemas and the intended app on all guests |
| R2 | Unattended all-OS green run from Apple Silicon, no paid capacity | Harness runs without model/service dependencies; unusable desktops fail closed | Laptop, local VM adapters, licensed Windows guest, pre-authorized desktops, live suite |
| R3 | Machine-verifiable durable outcome | Independent state oracle, false acknowledgements, Unicode, missing trees, screenshot-only responses, hash checks | Real app/accessibility oracle and retained live campaign artifacts |
| R4 | Tens of low-cost repeats; rollback | 20 fixture waves, stale reset detection, timeout cleanup, retry stop | Real snapshots/restore, readiness, host resource measurements, acceptable repeat budget |
| R5 | At least one of each OS concurrently | Overlapping three subprocess intervals; one worker per label | Overlapping three **live guest desktop** intervals on the laptop |
| R6 | Rebuild recipe and same permission identity | Changed/typed identity mismatch fails before tool dispatch | Rebuilt guests, recorded recipes, real signature/SID outputs, live consent checks |
| C4 | OS privilege/consent grants remain user-owned | Refusal/unavailable approval does not dispatch; absent grants deny tools | Attended initial authorization and independent post-restore permission probes |

## Results and reproducibility

Every eval invocation retains per-case configs, scenarios, hook logs, raw MCP
responses, protocol transcripts, an aggregated report, source/evaluator/dataset
SHA-256 hashes, Git revision/dirty state, and actual host/Python information.
A dirty-tree result qualifies only those recorded file hashes, not the unchanged
HEAD commit. CI retains raw artifacts for 14 days; archive important evidence
outside ephemeral CI retention before releasing.

The original implementation produced **one observed false green**: nested
identity `true` compared equal to `1` under Python equality. The new grader
caught it. The implementation now compares canonical JSON without bool/int
coercion, rejects nonfinite evidence, applies type-strict list membership, and
validates executable-input shapes and JSON Pointer escapes before dispatch.
These fixes are regression-evaluated; changing the expected label was not used
to make the failure disappear.

Synthetic latency metrics are named `synthetic_slowest_target_p50_seconds` and
`synthetic_slowest_target_p95_seconds`: they describe the maximum target duration
within each fixture wave, not full end-to-end VM or desktop latency. They must
not be advertised as snapshot/rollback performance.

## Live acceptance protocol (not yet executed)

1. Pin the release source, app build, Cua artifacts, OS installers, VM backend,
   firmware/TPM state, allocated resources, and guest identities. Document legal
   Windows entitlement and confirm no hosted service is used.
2. Implement/qualify lease-safe adapters. Prove a failed or interrupted reset
   cannot delete the golden image or another campaign's guest. Exercise recovery
   after worker/host termination, not just cooperative cancellation.
3. Prepare and authorize guests with their owners. Pin actual macOS bundle ID,
   Team ID, designated requirement, app hash, daemon attribution and live grants;
   pin the Windows interactive account SID/pipe and Linux graphical session.
4. Use the same real native-app scenario with an independent semantic oracle on
   all three guests. Include intentional app regressions and inaccessible trees
   to show that a successful action acknowledgement cannot masquerade as success.
5. Run at least 20 simultaneous three-OS waves from the Apple Silicon laptop.
   Preserve live target intervals (including actual desktop-ready evidence),
   all observations, host CPU/RAM/swap/disk samples, and p50/p95 end-to-end timing.
6. Choose the numeric per-change and reset-time budgets **before** that run;
   record them with the acceptance manifest. Compare measured reset time to the
   existing cold-clone/boot baseline. Prove each restore removes the prior marker
   without changing permission identity or losing live grants. Do not substitute
   the synthetic ~millisecond-scale measurement for this experiment.
7. Independently rebuild all guests from pinned recipes. Compare observed
   identity outputs to the previous baseline, then rerun permission and app-state
   probes. Equal signatures are necessary, not proof that a new OS retained TCC
   consent. Any attended regrant must be recorded, not silently automated.
8. Evaluate the exact candidate release again. Keep unsupported x64 app coverage,
   reboot/lock behavior, memory snapshots, crash recovery, and macOS guest counts
   explicit. Until these artifacts and an evaluated live grader exist, the full
   product release gate remains red.
