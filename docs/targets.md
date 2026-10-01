# Self-hosted native GUI gate (experimental)

## Status and feasibility

`gui_gate.runner` is a runnable **prepared-target harness**, not a shipped
VM manager. Its synthetic tests exercise concurrent stdio connections, evidence,
assertions, reset/cleanup ordering, and failure propagation. They do **not** qualify
Windows, Linux, macOS, snapshot performance, or permission persistence. No live
three-platform green run is recorded. A [UTM lifecycle adapter, guest recipe,
native calibration scenario, and campaign auditor](utm.md) are now implemented
and contract-tested; golden guest images, real device-state rollback, intended
application coverage, and rebuilt-guest qualification remain absent.

The proposed laptop-only topology is:

| Name | Guest | Local VM backend | Reset strategy |
| --- | --- | --- | --- |
| `macos` | macOS ARM64 | Apple Virtualization.framework via pinned UTM | UTM Apple checkpoint (macOS 27+/ASIF); separately qualify any clone alternative |
| `windows` | Windows 11 ARM64 | QEMU ARM64 + HVF, UEFI, required virtual TPM | Qualified disk/firmware/TPM checkpoint or stopped golden clone |
| `linux` | ARM64 Linux desktop | QEMU ARM64 + HVF | Qualified checkpoint or stopped golden clone |

Windows guests are not intrinsically impossible on Apple Silicon: ARM64 QEMU
virtualization is a different path from Hyper-V. This is a proposed target to
qualify, not evidence that this laptop or every Windows application works.
x86/x64 translation inside Windows is not equivalent to native x64 qualification.
QEMU TCG emulation of an x64 guest is another option, but unlikely to meet the
fast-loop objective. Windows guests and virtual devices need independent testing.

QEMU and UTM are free/self-hostable but are **not MIT-licensed**. Audit their
licenses if MIT-only dependencies are required. Windows is proprietary: free VM
software does not confer a Windows license. A valid existing entitlement might
avoid incremental spend; a time-limited evaluation is not a perpetual free CI
baseline. If there is no suitable Windows entitlement, the zero-spend enduring
Windows requirement remains blocked. Do not bypass activation or license terms.

One macOS guest plus one Windows and one Linux guest avoids the two-macOS-guest
ceiling; it does not avoid the laptop's CPU/RAM/storage limits. No absolute
capacity or latency is promised. Scaling beyond this laptop requires additional
self-hosted capacity; there is no unlimited free compute.

## Contract

Run with Python 3.10+ from a checkout; no cloud service, model, or additional
Python package is needed:

```sh
python3 -m gui_gate.runner --config targets.json --scenario scenario.json \
  --output gui-evidence --repetitions 20 --allow-disposable-guests
```

The explicit flag authorizes **all configured lifecycle commands and desktop
actions**. Inputs are trusted executable configuration, not untrusted PR data.
Use dedicated guests with no credentials and no personal desktop. The harness
never installs drivers or grants OS permissions. Configure SSH host keys and
noninteractive authentication beforehand; retain host-key verification.

The configuration has `version: 1`, optional positive `timeout_seconds` (default
120 per hook/MCP request), and exactly three entries under `targets`. Each entry:

```json
{
  "resource": "unique-guest-owned-by-this-campaign",
  "reset": ["/absolute/path/to/guest-adapter", "reset", "windows"],
  "verify": ["/absolute/path/to/guest-adapter", "verify", "windows"],
  "destroy": ["/absolute/path/to/guest-adapter", "destroy", "windows"],
  "mcp": ["/absolute/path/to/ssh", "-T", "-o", "BatchMode=yes", "gui-windows", "C:/gui/mcp-proxy.cmd"],
  "identity": {"account_sid": "PINNED-SID", "driver_sha256": "PINNED-SHA256"},
  "bindings": {"app": "YourApp"}
}
```

**These generic `guest-adapter`/`mcp-proxy.cmd` paths are placeholders.**
Use the bundled UTM adapter and fixed guest entrypoints in [the UTM recipe](utm.md)
or provide a separately qualified backend.
Configure actual pinned identity values; placeholders must not qualify a guest.
Commands are argv arrays, not local shell strings. SSH remote commands still
use the guest's shell; use fixed, reviewed wrapper paths. `environment` can
explicitly supply transport environment variables (e.g. `HOME` for SSH); the
shared Cua client otherwise forwards only its reviewed desktop environment.
Do not put secrets in configuration: the exact config is saved as evidence.

The runner supplies a unique `OCTET_GUI_GATE_OWNER` to reset/verify/destroy for
each target repetition; cleanup must never touch a different owner. Optional
`acceptance` budgets (`max_wave_seconds`, `max_reset_seconds`,
`max_campaign_seconds`) must be positive finite numbers chosen before execution;
the separate calibration audit enforces them, not the runner's task-success flag.
Optional target `oracles` maps read-only application oracle names to fixed argv.

Adapter responsibilities:

1. `reset`: acquire an exclusive guest lease; reject other campaigns; restore
   a known checkpoint or create an isolated golden clone; start it; wait for an
   unlocked, usable desktop and daemon. It must not return at mere SSH readiness.
2. `verify`: independently read actual guest OS, driver version/hash, account
   identity, permission state, desktop reachability, and signature identity.
   Output exactly one JSON object to stdout; diagnostics go to stderr:
   `{"os":"windows","identity":{...},"permissions_ready":true,"interactive_desktop":true}`.
   The identity object must equal the pinned configuration exactly. Do not echo
   expected values and call that verification. Include image/build provenance
   as additional fields, which the harness preserves.
3. `destroy`: idempotently stop/discard **only the leased disposable instance**
   and release the lease, even following partial reset failure. Never delete
   the golden image. It must fail if it cannot establish completed cleanup.
4. `mcp`: expose Cua's newline-delimited stdio MCP through a persistent proxy.
   Keep diagnostics off stdout. Do not create a different permission identity.

The harness runs three workers, one per OS; repetitions on a guest are serial.
A readiness barrier precedes scenario dispatch; a wave that cannot synchronize
all three authorized desktops cannot be green, though independent authorized
targets still finish their evidence. Desktop-ready/finished intervals are retained.
It rejects repeated resource names but cannot detect two names aliasing the
same VM. Cross-process leasing belongs to the adapter. A failed cleanup stops
further repetitions. Hook timeouts kill the direct child, not every descendant:
wrappers must own/reap their process trees, and cleanup must reconcile partial
starts. Abrupt host termination is not guaranteed cleanup; provide an operator
recovery command and persistent lease journal. Do not use a long-lived VM
process itself as a blocking `reset` command.

## One scenario, recorded assertions

Scenario format:

```json
{
  "version": 1,
  "steps": [
    {"id":"launch", "tool":"launch_app", "arguments":{"name":{"$ref":"/bindings/app"}}},
    {"id":"observe", "tool":"list_windows", "arguments":{},
     "assert":[{"path":"/structuredContent/windows", "op":"length_at_least", "value":1}]}
  ]
}
```

This is a **schema illustration**, not a qualified application test. Confirm the
pinned driver's actual result schema before choosing assertion pointers. An
arbitrary window existing proves neither a successful launch nor task completion.
A production scenario should locate the intended app/window, read its accessibility
state, act, then assert the specific resulting value or use an independent
application test oracle. Avoid OS-specific code by resolving app names and other
platform data from `bindings`. Literal objects of the form `{"$ref":"/results/observe/..."}`
resolve previous results; `/run_id` supplies the repetition label, and `/guest`
addresses the independently observed verification proof. There is no
expression evaluator or scenario shell. Tools must appear in every target's
catalog before any scenario action is dispatched.

Assertions use JSON Pointer paths into raw MCP results: `equals` (same JSON
value type), `contains`, or `length_at_least` (positive integer). Missing evidence,
tool errors, assertion failures, failed identity/readiness, and cleanup errors
all prevent green. At least one assertion is mandatory. Prefer accessibility
or independent application state over screenshots. A screenshot alone never
constitutes a passing assertion. For independent application state, a step can
replace `tool` with `oracle`, naming an oracle configured on **every** target.
Its resolved arguments are JSON on stdin; it returns one JSON result object on
stdout. Raw stdout/stderr and normalized evidence are retained. Tool errors,
nonzero oracle exits, invalid JSON, and failed assertions remain red. Each step
uses exactly one tool/oracle; a scenario still requires at least one driver tool.

The bundled native app publishes its real Tk field state; its read-only oracle
can wait for the expected marker within a bounded deadline, returning observed
wrong state on expiry so assertions fail. There is no generic expression engine,
selector DSL, or automatic retry of desktop actions. Other applications need
qualified semantic responses or their own independent read-only oracle.

Every invocation gets a new campaign directory with the exact configuration and
scenario, per-run/per-OS hook stdout/stderr, raw per-step arguments/results,
SHA-256 hashes, timing measurements, `report.json`, and `summary.json`. Exit 0
requires all requested runs on all three targets to pass. Keep artifacts in
restricted storage: accessibility trees and screenshots can contain sensitive
data. Hashes detect accidental alteration; they are not signed attestations.

## Golden-image recipe and permission identity

Before automating a guest, document and pin:

- Hardware architecture, OS installer source/license, installer SHA-256, OS build,
  VM backend/version, firmware/hash, machine UUID, MAC, and disk/device layout.
- CPU/RAM allocation, user identity, desktop/autologin policy, SSH keys/host keys,
  application build/hash, driver version/wheel hash, and dependencies.
- Guest bootstrap commands, daemon startup mechanism, interactive desktop probe,
  signature probe commands and their **observed** outputs.
- Checkpoint creation/restoration commands and all coupled persistent state
  (disks, EFI variables, TPM, VM configuration, and memory when supported).

Install OS and app into an isolated guest. Install a pinned Cua Driver. Perform
one attended preparation pass, then stop the guest cleanly and seal the golden
artifact read-only. Recreate it from the same documented inputs and compare the
observed identity to the previous manifest before accepting it.

**macOS:** use the same valid upstream release-signed Cua app (or a deliberately
stable development signing identity, qualified separately). Record bundle ID,
Team ID, designated requirement from `codesign -d -r-`, signature verification,
and app hash. Launch the app through LaunchServices so daemon attribution is to
the app, not the SSH/terminal parent. The owner grants Accessibility/Screen
Recording in the guest. Verify actual daemon-attributed grants and a real capture/
accessibility read after restore. Do not edit TCC databases or grant permissions
programmatically. Signature identity equality is necessary but does **not** prove
a cloned or freshly rebuilt OS retained consent. A fresh rebuild may require
another attended grant; unattended refers to subsequent runs, not initial setup.

**Windows:** run `cua-driver serve` in the dedicated user's interactive session,
not Session 0 from SSH. Use an attended-installed logon task or equivalent
user-session startup. Record the actual account SID; connect the MCP proxy to
the daemon's matching per-account named pipe using the pinned driver's supported
endpoint syntax. Do not guess pipe names. Verify a sentinel app's accessible
window/tree, not merely a successful socket connection or an empty window list.
A recreated account with the same name has a different SID: retain the provisioned
account state or update/qualify the identity explicitly. Do not drive UAC or the
secure desktop. Remote-session locking/disconnection behavior must be qualified.

**Linux:** the daemon/proxy must address the graphical user's display and session
bus with AT-SPI installed for semantic evidence. Choose one qualified desktop
stack and preserve its startup/env recipe. SSH readiness is not desktop readiness.

## Qualify the cheap loop before relying on it

A stopped disk clone is rollback, but still pays boot cost. Do not label it a
fast snapshot solution. APFS clones reduce copy cost, not boot time. macOS
Virtualization save/restore support varies by host/guest OS and devices; qualify
it rather than promising memory snapshots. QEMU disk-only overlays do not reset
RAM, EFI variables, or TPM state. Internal/savevm snapshots and HVF/device support
must be tested for the exact stack; unsupported configurations remain blocked.

For each backend, restore twice and prove that a run's marker disappears while
signature/account identity and live grants remain correct. If using RAM snapshots,
prove restored networking, clocks, sessions, and accessibility handles work.
Never share mutable guest state among simultaneous runs. Export observations
before rollback. Do not claim snapshot support from the mere existence of a
`reset` hook.

Measure 20–50 concurrent three-OS repetitions using the intended application.
Reports break out reset, verification, MCP connection, actions, and cleanup;
record host RAM pressure/swap, CPU, disk growth, errors, and p50/p95 completion
latency separately. Define an acceptable per-change time budget before declaring
success. Increase Linux/Windows capacity only after measured headroom; this
harness intentionally does not implement pools or fleet orchestration.

Remaining acceptance work: qualify the implemented lifecycle adapter and recorded
recipes on the actual laptop, establish Windows licensing, qualify the intended
application, prove rollback/permission persistence on rebuilt guests, and attach
a live concurrent all-OS campaign with acceptable repeated-run timings. Until then, this is a tested composition
boundary, **not completion of the six success criteria**.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```
