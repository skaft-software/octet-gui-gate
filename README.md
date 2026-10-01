# octet-gui-gate

**Experimental, open-source utility extension for Skaft's own Octet workflows.**
Not an official Octet bundle, not catalog-listed, and not a supported cross-platform
GUI-testing product. MIT licensed.

Runs the same JSON scenario against prepared `macos`, `windows`, and `linux`
guests concurrently using Cua Driver's stdio MCP protocol. Records machine
assertions, raw evidence, SHA-256 hashes, guest identity checks, lifecycle logs,
and timings. No hosted service or model is required.

**It does not create VMs.** You must supply qualified reset/verification/cleanup
adapters and prepared, pre-authorized disposable guests. Snapshot speed, Windows
licensing, live GUI parity, and consent persistence have not been qualified.
The automated tests use synthetic MCP processes, not real desktops.

## Install locally in Octet

Requires **Octet 0.8.2**, extension API 0.4, and Python **3.10+** on PATH.
The SDK is vendored; no pip installation is needed. Review the code first:
extensions run with your operating-system privileges.

```sh
git clone https://github.com/skaft-software/octet-gui-gate.git \
  ~/.octet/extensions/octet-gui-gate
octet --enable-extension octet-gui-gate
```

On Windows, clone into `%USERPROFILE%\.octet\extensions\octet-gui-gate` using
native Python (not WSL). Set `OCTET_STATE_DIR` to an existing writable state root
if your host does not provide a resolvable home directory. Jobs live under
`$OCTET_STATE_DIR/gui-gate`, or `~/.octet/gui-gate` by default.

This is a source installation. **`octet extension install octet-gui-gate` is not
available**, and this repository does not alter Octet's bundled extensions or
release catalog. Pin a reviewed commit for repeatable installation.

## Use from Octet

Prepare `targets.json` and `scenario.json` using the
[adapter contract and target qualification guide](docs/targets.md). The guide's
commands and identities are placeholders; no ready-to-run VM adapter is bundled.

```text
/gui-gate run /absolute/path/targets.json /absolute/path/scenario.json 20
/gui-gate status JOB_ID
/gui-gate cancel JOB_ID
```

`run` loads/validates the configuration, asks the operator to authorize its
reset/actions/destroy commands, and returns a job ID immediately. A background
worker runs the campaign without holding the extension RPC open. Only the user
command starts jobs; the model-callable `gui_gate_status` tool is read-only.

Consent to this workflow is **not** a grant of Accessibility, Screen Recording,
or any other OS permission. Grants are always the OS user's responsibility.
Never point a target at a personal desktop or a guest holding credentials.
Configuration is trusted executable input: lifecycle commands can run arbitrary
programs. Do not run unreviewed PR configurations, and never put secrets in
configuration because the exact input is retained as evidence.

Cancellation is cooperative: it stops between bounded operations and runs
cleanup. It is not rollback of an action already dispatched. Graceful extension
shutdown requests cancellation; workers are launched in a separate process
session/group to let cleanup finish. Host process-tree termination, a crash,
a power failure, or uncooperative adapter descendants can still interrupt it.
Adapters must maintain exclusive leases and an operator recovery procedure.
After restart, status reads terminal evidence; missing terminal evidence without
an owned worker is **unknown**, not green. Inspect leases before relaunching.
Only one campaign per live extension instance is allowed; adapters must fence
other extension instances and CLI invocations too.

Inspect the returned `status`, `passed`, `summary`, and per-target reports. A
finished job may have **failed**. Evidence is sensitive local data; keep it in
restricted storage. SHA-256 hashes are not signed attestations.

## Standalone / CI harness

From this repository:

```sh
python3 -m gui_gate.runner --config targets.json --scenario scenario.json \
  --output gui-evidence --repetitions 20 --allow-disposable-guests
```

Exit 0 requires every requested run on all three targets to pass. CLI authorization
replaces the Octet workflow confirmation; neither path grants OS permissions.
There are no cloud or hosted-capacity dependencies in the harness. GitHub Actions
runs only synthetic unit tests and does not qualify live GUI behavior.

## Tests and current limits

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

Tests cover real synthetic stdio connections, three-worker concurrency, repeated
runs, evidence retention, fail-closed identity/permission checks, cleanup failure,
workflow confirmation, extension protocol initialization, background jobs,
restart inspection, and cooperative cancellation.

Outstanding acceptance work: local VM adapters and reproducible golden recipes,
a valid Windows entitlement, application scenarios, actual rollback/permission
persistence checks, and a live concurrent three-OS campaign with measured repeat
cost. ARM64 Windows under QEMU/HVF is a route to **qualify**, not a guarantee of
native x64 application coverage or an enduring free Windows license.

See [LICENSE](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md), and
[security boundaries](SECURITY.md).
