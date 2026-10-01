# UTM laptop recipe and native calibration (not live-qualified)

The repository now includes a UTM lifecycle adapter, interactive identity probe,
read-only application oracle, and one native calibration scenario. **No real VM
has been run with these here.** These recipes are preparation instructions, not
recorded proof of provisionability, performance, consent persistence, or licensing.
They need an operator-owned Apple Silicon laptop and attended initial setup.

Quick path: (1) check backend capabilities/entitlements; (2) prepare and authorize
three isolated guests; (3) record observed identities and seal pristine checkpoints;
(4) fill the templates, choosing numeric budgets before running; (5) run 20 waves
and audit the returned campaign. The exact preparation/recovery details follow.
There are deliberately no commands that silently grant consent or license an OS.

## 1. Freeze the host and guest inputs

Use a free self-hosted UTM build supporting the snapshot CLI. The implementation
was checked against upstream source, not a running UTM installation:

- [UTM `utmctl`](https://github.com/utmapp/UTM/blob/7eadb056ae0f91d979059544d0ddcd2d5a40be92/utmctl/UTMCtl.swift)
- [Apple snapshot backend](https://github.com/utmapp/UTM/blob/7eadb056ae0f91d979059544d0ddcd2d5a40be92/Services/UTMAppleSnapshotBackend.swift)
- [QEMU snapshot backend](https://github.com/utmapp/UTM/blob/7eadb056ae0f91d979059544d0ddcd2d5a40be92/Services/UTMQemuSnapshotBackend.swift)
- [Cua proxy CLI](https://github.com/trycua/cua/blob/9545a3d17b44b587b593d59090dc140740876a6e/libs/cua-driver/rust/crates/cua-driver/src/cli.rs)
- [Linux permission/tool schemas](https://github.com/trycua/cua/blob/9545a3d17b44b587b593d59090dc140740876a6e/libs/cua-driver/rust/crates/platform-linux/src/tools/impl_.rs)

A released UTM version may not expose this API. Confirm `utmctl snapshot --help`
and pin the **actual executable hash and backend build**, not just this source
reference. The pinned Apple snapshot implementation requires **macOS 27+ and
ASIF disks**. Memory save/restore additionally depends on the VM/device support.
An unsupported laptop/backend is a blocker, not a reason to pretend disk copies
are RAM snapshots. The adapter checks the selected checkpoint's actual capability.

Create three dedicated ARM64 guests in UTM, one per OS. Never exceed two macOS
VMs; this baseline uses one. Record the following in a private, versioned recipe
manifest **before sealing** each guest:

- Host model/OS/RAM, extension revision, UTM/QEMU build and executable hashes.
- Installer origin, license/entitlement, SHA-256, OS edition/build/architecture.
- VM UUID, MAC, firmware hashes, disk formats/sizes, boot/device configuration,
  TPM configuration, CPU/RAM allocations, and all writable external state.
- Dedicated account, SSH public/host-key fingerprints, desktop session/autologin
  policy, Python/Tk build, pinned Cua artifact/signature, and application hashes.
- Exact setup commands and user-owned permission grants, including host Automation
  consent for `utmctl` if macOS asks. Do not distribute credentials or OS images
  without their owners' authorization.

Use Apple's macOS restore image with Apple Virtualization; a licensed Windows
ARM64 installation with QEMU/HVF and its required devices; and an ARM64 Linux
**GNOME Xorg** desktop with QEMU/HVF. UTM's installer UI supplies initial VM creation;
this adapter does not install OSes or accept license terms. Freeze the chosen
hardware settings instead of accepting evolving wizard defaults.

**Windows entitlement is required.** QEMU/UTM do not license Windows. An evaluation
expiry or an activation/setup bypass is not an enduring free baseline. Confirm
that the selected Windows/TPM/device combination supports the actual checkpoint
operation. Upstream QEMU snapshots include internal writable disks and the
configured UEFI variable image; this adapter has no separate external TPM-folder
or arbitrary sidecar manager. Do not assume it resets such state. The full product
gate stays red until coupled device-state rollback is independently demonstrated.

## 2. Prepare each interactive guest

Install Python 3.10+ with Tk, the exact reviewed repository revision, and the
pinned driver. No paid service, model, or Python package is used by this extension.
Tk may require the OS's `python3-tk` package on Linux. Restrict these guests to
non-sensitive test data and local networking; verify SSH host keys through the
UTM console rather than disabling verification.

Choose absolute paths for `guest.json`, `native-state.json`, and a private
`probe-mailbox` directory. `guest.json` contains paths, **never expected grants**:

```json
{
  "driver": "/Applications/CuaDriver.app/Contents/MacOS/cua-driver",
  "bundle": "/Applications/CuaDriver.app",
  "socket": "/Users/gui/Library/Caches/cua-driver/cua-driver.sock",
  "app_state": "/Users/gui/native-state.json"
}
```

These are illustrative macOS paths. Confirm the **selected** upstream endpoint
and release namespace. Windows has a [configuration template](../examples/guest-windows.example.json);
use its actual supported named pipe, not a guessed SID-derived convention. Linux
uses absolute driver/state paths and the graphical user's actual daemon socket;
omit `bundle` outside macOS.

From that user's **interactive logon session**, arrange startup of:

1. The standalone Cua daemon. On macOS launch the release-signed `CuaDriver.app`
   via LaunchServices, e.g. `open /Applications/CuaDriver.app --args serve`.
   On Windows/Linux use the pinned driver's `serve --socket EXACT_ENDPOINT` in
   the graphical user's session. Select/review the driver's app-capability policy
   during attended setup so the isolated calibration app's foreground typing is
   authorized. This is separate from OS consent. Never use `serve --embedded` for
   the macOS standalone baseline, and never change grants in the runner.
2. `python -m gui_gate.native_probe app --state ABSOLUTE_STATE_FILE`
3. `python -m gui_gate.guest_probe serve --config ABSOLUTE_GUEST_JSON --mailbox ABSOLUTE_MAILBOX`

Use an attended-installed user LaunchAgent/login item on macOS, a Windows logon
startup task **running only when the user is logged on**, or Linux graphical
session autostart. Pin the actual startup files/commands, account, and environment
in the recipe. Start the three commands independently; the mailbox worker retries
readiness on new challenges. Do not run the app, daemon, or probe agent as an SSH
service/Session 0 process. Avoid an automatic restart loop that creates duplicate
app windows. Configure log redirection and restrictive directory permissions.

The owner grants Accessibility and Screen Recording to the same signed macOS
release app. Preparation must include a successful attended real window capture
so any additional capture consent is already resolved. The helper verifies the
Developer ID signature, bundle ID, Team ID, designated requirement, bundle/binary
hashes, live `driver-daemon` TCC attribution, and the app's actual window/capture.
It never calls a permission-grant API and refuses host-attributed grants.

Windows verification reads the actual account/process SID and requires both app
and probe agent in the same nonzero, unlocked interactive session. Linux requires
the same graphical UID, an active unlocked local logind session, a reachable X11
or native Wayland display, and AT-SPI. The Linux recipe currently assumes a
**systemd/logind GNOME Xorg desktop**; select and record that session explicitly.
Native Wayland is not this baseline: the pinned driver can refuse an unprovable
window capture there. Other session stacks need independent adapters.
Do not claim a successful socket connection is desktop readiness.

## 3. Fixed SSH entrypoints (review and pin)

SSH should enter the same dedicated account. It only requests a fresh interactive
proof, proxies MCP, or reads the native app's state; it does not start a desktop.
For example, a POSIX guest's `proxy.sh`:

```sh
#!/bin/sh
set -eu
cd /absolute/guest/octet-gui-gate
exec /absolute/guest/python3 -m gui_gate.guest_probe mcp --config /absolute/guest/guest.json
```

`probe.sh` has the same preamble, ending in:

```sh
exec /absolute/guest/python3 -m gui_gate.guest_probe request --mailbox /absolute/guest/probe-mailbox
```

`oracle.sh` ends in:

```sh
exec /absolute/guest/python3 -m gui_gate.native_probe oracle --state /absolute/guest/native-state.json
```

For Windows use fixed `.cmd` wrappers, e.g. `C:\gui\proxy.cmd`:

```bat
@echo off
cd /d C:\gui\octet-gui-gate
C:\gui\Python\python.exe -m gui_gate.guest_probe mcp --config C:\gui\guest.json
```

`probe.cmd` invokes `guest_probe request --mailbox C:\gui\probe-mailbox`;
`oracle.cmd` invokes `native_probe oracle --state C:\gui\native-state.json`.
Use quoted paths if they contain spaces; adjust all paths to the installed build.
There must be no banner/logging on stdout. SSH transmits oracle arguments as JSON
on stdin. Keep its authentication/key handling noninteractive and host-key
verification enabled. Keep SSH aliases local to these UTM guests and record the
console-paired host keys in the recipe.

The proxy uses `mcp --embedded --socket EXACT_ENDPOINT` **only for the MCP client**.
In the pinned upstream implementation this refuses auto-launch when the selected
service is missing; it does not alter the already-running daemon's TCC identity.
There is no direct-mode fallback, daemon installation, or permission-grant flag.
The macOS probe still demands standalone `driver-daemon` attribution.

Each request creates a new random challenge; the interactive agent publishes a
matching response **after a new actual probe**. A cached `ready.json` or restored
old response cannot qualify readiness. SSH Session 0 thus never claims to have
measured Windows's active desktop. If the agent is absent, the request times out.
Mailbox directories must be private to that account; this is not an authenticated
service for untrusted local users.

## 4. Seal the checkpoint and observed identity

Wait for the native app's field to be empty and focused. From the host run the
fixed `probe` wrapper and retain its complete output. It must report true grants
and a usable desktop. Copy its **observed** `identity` into both the host target
and UTM descriptor; never fill these with expected values invented by a script.
The helper deliberately accepts no configured identity/grant values.

For QEMU, use the supported snapshot operation while the pristine VM is running.
For Apple VMs, suspend first if RAM save is supported, then create the checkpoint:

```sh
/Applications/UTM.app/Contents/MacOS/utmctl suspend MACOS_VM_UUID --save-state
/Applications/UTM.app/Contents/MacOS/utmctl snapshot create VM_UUID --name gui-gate-pristine
/Applications/UTM.app/Contents/MacOS/utmctl snapshot list VM_UUID --json
shasum -a 256 /Applications/UTM.app/Contents/MacOS/utmctl
```

Record the returned snapshot UUID, not a mutable name. Check `dataMissing:false`
and `includesRunningState:true` before relying on RAM restore. A disk-only
checkpoint requires **explicit** `require_running_state:false`; it still must
meet the predeclared real latency budget and must not be advertised as RAM restore.
Retain a quiescent, hashed full VM bundle/configuration and its external state for
rebuild; a disk-only export is not a full permission/device-state backup.

Create one host descriptor per OS using
[the descriptor template](../examples/utm-descriptor.example.json). Set actual
UUIDs, executable hash, observed identity, and fixed SSH probe wrapper. Its total
operation deadline should be less than the runner hook timeout (example: 90 vs
120 seconds) to leave time for error reporting/cleanup. Do not change descriptors,
wrappers, driver files, or VM configuration during a campaign.

## 5. Run and independently audit

Fill [the target template](../examples/utm-targets.example.json). `resource` is the
actual VM UUID. Choose numeric reset, full-wave, and whole-campaign budgets
**before** running; the illustrative 3/8/180-second budgets are requirements to
measure, not promises. Run from the repository checkout or through `/gui-gate`:

```sh
python3 -m gui_gate.runner --config targets.json \
  --scenario examples/native-probe.scenario.json --output gui-evidence \
  --repetitions 20 --allow-disposable-guests
python3 -m gui_gate.audit --campaign gui-evidence/RETURNED_CAMPAIGN
```

The adapter atomically leases the canonical VM UUID under
`~/Library/Application Support/octet-gui-gate/leases/`. The runner passes a
unique `OCTET_GUI_GATE_OWNER` to all three lifecycle phases. A losing campaign's
cleanup cannot stop the existing owner. Each reset restores the selected
checkpoint, starts the VM, and waits for an actual fresh identity/desktop probe.
Cleanup stops and restores the leased VM before releasing it, without deleting
the VM or overwriting the checkpoint. Cleanup failure retains the lease.

All three workers reach a desktop-ready barrier before scenario dispatch.
The native scenario reads pristine app state, captures the intended window,
types the unique repetition marker in foreground, then reads state independently
from the app's Tk event loop. Driver acknowledgements do not determine success.
Repetition restores must remove the prior marker; postcondition checks bind to
the observed visible app PID. The audit independently checks raw outcomes,
hashes, roles, identities, fresh challenges, unchanged backend/checkpoints,
**desktop-ready interval overlap**, ordered 20+ waves, and all three latency
budgets (including the full campaign span). It does not interpret screenshots as task
success or silently accept a dropped repetition.

An audit green is only **native calibration campaign evidence from a trusted
operator**. Hashes and host/guest metadata are not signed remote attestation.
The auditor's fabricated positive/29 negative test controls exercise its contract,
not live GUI behavior. `product_qualified` remains false, including after audit
success. Complete the live negative controls, crash recovery, host CPU/RAM/swap/
disk measurements, Windows entitlement, coupled device-state proof, rebuilt-guest
consent checks, and intended application qualification in [the release protocol](evaluation.md).

## Recovery and rebuild

After an interrupted campaign, inspect the stopped/running VM, owner journal,
checkpoint, and original worker before taking ownership. Never automatically
steal a lease. If its worker is definitively gone, the operator can run `destroy`
with that journal's owner token and the unchanged descriptor to reconcile the
original instance. An incomplete owner journal/checkpoint requires manual
inspection/repair; **do not delete the lease while the VM may still be running**.

Rebuild from the recorded installers/hardware/setup recipe and compare observed
identities, or rehydrate the quiescent sealed full bundle/account state. A fresh
Windows account with the same name has a different SID and must be rejected.
A fresh macOS installation may need attended consent again even for an identical
release signature. Restoring an owner's already-authorized checkpoint is not a
new programmatic grant. Record any attended regrant; then repeat live probes and
native scenario tests before admitting the rebuilt target. No such rebuild or
permission-persistence proof has been executed here.
