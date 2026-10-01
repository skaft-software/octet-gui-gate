# Implementation defense

## What can honestly be defended

This is the right **harness boundary**, not yet a complete implementation of the
problem statement. The evals support its control-flow, evidence, and consent
properties. They do not establish that Skaft can run a free unattended native
GUI suite on three real guests from its laptop. VM lifecycle and live acceptance
are part of the requested deliverable, not optional future polish. An experimental
lease-fenced UTM implementation, interactive probe, native oracle, calibration
auditor, and [attended recipe](utm.md) are now bundled; their tests are still not
live qualification.

### 1. Keep the one proven cross-platform control primitive

Using Cua Driver's stdio MCP prevents three competing desktop automation stacks.
A local process and an SSH-proxied guest present the same transport to the
scenario. The scenario contains tool calls, references, and assertions; platform
app names are data bindings, not platform-specific scenario code. The synthetic
fixtures evaluate identical scenario execution and Unicode round trips through
that seam. The native recipe uses source-checked pinned Cua argument schemas
(including Linux's empty permission-probe arguments); it still needs live parity
and actual intended-application evaluation.

### 2. Separate machine lifecycle from desktop authority

`reset → verify → drive → destroy` gives one lifecycle contract around each
scenario. It avoids claiming that Cua creates machines or supplies snapshots.
Backend adapters must implement actual rollback, coupled VM state, ownership,
and readiness. The harness can reject stale state and stop following failed
cleanup, but cannot make a no-op hook into a snapshot manager. The bundled UTM
adapter now calls a pinned `utmctl` by VM/checkpoint UUID, claims a canonical atomic
lease, fences phases with a campaign owner token, waits for actual guest proofs,
and restores before releasing ownership. It never steals stale leases. External
TPM/device sidecars are not managed or qualified by this implementation.

Verification requires a pinned OS/permission identity and an authorized
interactive desktop before any scenario tool call. Windows Session 0, changed
macOS signatures, and missing grants therefore have a fail-closed seam. Owners
still make OS grants themselves. This is the appropriate authority split for
user-owned consent; an automated TCC editor would violate the constraints.
Fresh mailbox challenges ask an actual interactive agent to observe readiness;
an SSH Session 0 request cannot certify Windows's desktop or reuse restored
readiness. Fixed MCP proxies refuse implicit daemon launch/direct fallback.

### 3. Verify the task, not the acknowledgement

Assertions grade semantic state, and every step retains raw evidence and its
hash. The independent eval oracle exposes successful-looking calls that do not
change state, empty trees, screenshots without the required semantic field, and
Unicode corruption. This directly addresses the current manual eyeballing gap.
A screenshot does not become success merely because a driver returned it.
An inadequate application assertion is still inadequate: actual scenarios need
qualified semantic or independent application oracles. The bundled Tk app
publishes its actual field value from its event loop; the external oracle is
read-only, and the separate calibration audit inspects raw before/after state,
PID/window bindings, capture presence, hashes, and budget/overlap evidence. A
fabricated fixture can satisfy that contract, so it is explicitly not signed
attestation or full product qualification.

### 4. Bound concurrency without inventing a fleet

One worker per OS gives the required three-way topology while using only one
macOS slot. Repetitions on each resource are serial. Actual overlapping fixture
process intervals demonstrate scheduling, not merely a mocked executor call.
No pool scheduler, image distribution, hosted Fleet product, or general CI
platform was added. A three-desktop barrier and retained live-ready intervals
make the intended overlap contract explicit, with auditor negative controls.
Actual host capacity, VM licensing, and backend behavior remain constraints
that must be measured and qualified, not abstracted away.

### 5. Match Octet's extension lifecycle

A user command authorizes the workflow; a read-only tool exposes results. Long
campaigns run outside the command RPC deadline, retaining terminal evidence so
results can be inspected after extension restart. Cooperative cancellation tries
to finish cleanup instead of killing a worker during rollback. Real extension
protocol evals cover approval, refusal, cancellation, shutdown, and credential
isolation. This is more credible than testing only mocked Python handlers.
It does not qualify every native host process-tree termination path.

### 6. Prefer objective, free evaluation to an LLM verdict

The correctness questions here have exact answers: did the marker change, did
identity match by type and value, did three intervals overlap, did cleanup run,
and did a denied workflow dispatch nothing? Code grading is cheaper, repeatable,
and more falsifiable than asking a model to judge a transcript or screenshot.
The eval actually caught a false green and the implementation changed rather
than the expected labels. Safety cases cannot be averaged away by happy paths.

## Why this is not yet the full answer

The initial implementation deferred missing pieces to hooks. The local adapter,
probe, calibration app, auditor, and recipe now fill that implementation seam,
but the original composition problem remains only partly solved. There is still
no qualified laptop-local Windows VM path, measured snapshot/device-state proof,
intended application suite, or rebuilt-guest identity/consent proof. The pinned
Apple backend requires macOS 27+ and ASIF disks; the actual laptop's capabilities
are unknown. Free QEMU does not supply a Windows license; ARM64 execution
also does not qualify every x64 native application.

The correct decision is therefore:

- Use this as an **evaluated experimental harness/adapter** for performing
  attended preparation and collecting independently audited native calibration.
- Do **not** ship or describe it as the completed cross-platform GUI gate.
- Keep the product gate blocked until the [live acceptance protocol](evaluation.md#live-acceptance-protocol-not-yet-executed)
  produces independently graded evidence for all six original success criteria.

This defense is deliberately narrower than a product-success claim, because
stating that all requirements are satisfied would contradict the observed
results and the current implementation.
