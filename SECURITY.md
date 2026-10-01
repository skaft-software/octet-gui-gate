# Security

This is an experimental Skaft utility, not a sandbox. Both extension and CLI run
with the operator's filesystem, process, and network authority. Configuration
is executable trusted input; a malicious hook or MCP command can run arbitrary
programs. Review the exact commit and configuration before authorizing a run.
An Octet workflow confirmation authorizes the whole campaign, not individual
GUI actions. Do not use it where per-action approval is required.

Use isolated disposable guests, scoped SSH keys, verified SSH host keys, exclusive
VM leases, and no personal credentials. Never address the user's everyday
desktop. OS permissions must be granted by the OS user outside this extension;
no code edits permission databases or grants permissions on the user's behalf.

Artifacts include raw accessibility data, screenshots when returned by the
driver, configuration, and logs. They may expose secrets. Keep state/evidence in
operator-controlled private storage. POSIX directory mode hints do not provide
Windows ACL isolation; configure permissions yourself. Evidence hashes are not
cryptographic attestations of target trust. Guest identity verification is only
as reliable as the independently implemented verification adapter.

Cancellation is cooperative, not rollback. Hooks must handle partial starts,
reap descendants, and journal leases. Request timeouts apply per operation, not
to the whole campaign. MCP stderr is discarded by the client; lifecycle logs and
worker diagnostics are retained. Host crashes or process-tree termination may
prevent cleanup. Inspect and recover guest leases before retrying an unknown
outcome. Status does not infer success from a PID or a screenshot.

Do not run untrusted pull-request configuration in CI. The included CI tests use
synthetic targets and never install drivers, provision VMs, or operate desktops.

For a sensitive issue, contact Skaft through its existing private security
channel rather than posting credentials or desktop artifacts in public issues.
