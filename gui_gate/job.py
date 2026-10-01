"""Persistent, bounded campaign workers; no installation or permission grants."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .runner import save, validate

ROOT = Path(__file__).resolve().parents[1]


class Jobs:
    def __init__(self, state):
        self.state = Path(state).expanduser().resolve()
        self.children = {}

    def load(self, config_path, scenario_path, repetitions):
        if type(repetitions) is not int or not 1 <= repetitions <= 1000:
            raise ValueError("repetitions must be between 1 and 1000")
        config = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        scenario = json.loads(Path(scenario_path).expanduser().read_text(encoding="utf-8"))
        validate(config, scenario)
        return config, scenario, repetitions

    def start(self, config, scenario, repetitions):
        # The extension owns one campaign at a time. Resource leases in the VM
        # adapter must also fence CLI runs and separate extension processes.
        for child in self.children.values():
            if child.poll() is None:
                raise RuntimeError("a campaign is already running; inspect it before launching another")
        job_id = uuid.uuid4().hex
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = self.state / job_id
        directory.mkdir(mode=0o700)
        save(directory / "config.json", config)
        save(directory / "scenario.json", scenario)
        save(directory / "job.json", {"job_id": job_id, "repetitions": repetitions})
        command = [sys.executable, "-m", "gui_gate.job", str(directory), str(repetitions)]
        options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        # No provider credentials or arbitrary inherited variables in workers.
        from .driver_client import _child_environment
        environment = _child_environment()
        for name in ("PATH", "HOME", "TMP", "TEMP"):
            if os.environ.get(name):
                environment[name] = os.environ[name]
        try:
            with (directory / "worker.stdout").open("wb") as out, (directory / "worker.stderr").open("wb") as err:
                child = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=out, stderr=err, **options)
        except OSError as error:
            save(directory / "terminal.json", {"status": "failed", "error": str(error), "passed": False})
            raise
        self.children[job_id] = child
        return self.status(job_id)

    def directory(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("expected a 32-character job ID")
        directory = self.state / job_id
        if not (directory / "job.json").is_file():
            raise ValueError("unknown job ID")
        return directory

    def status(self, job_id):
        directory = self.directory(job_id)
        result = {"job_id": job_id, "directory": str(directory), "cancel_requested": (directory / "cancel").exists()}
        terminal = directory / "terminal.json"
        if terminal.is_file():
            result.update(json.loads(terminal.read_text(encoding="utf-8")))
        else:
            child = self.children.get(job_id)
            if child is None:
                result["status"] = "unknown"
            elif child.poll() is None:
                result["status"] = "running"
            else:
                result.update(status="failed", passed=False, error=f"worker exited {child.returncode} without a terminal report; inspect guest leases")
        return result

    def cancel(self, job_id):
        directory = self.directory(job_id)
        (directory / "cancel").touch()
        return self.status(job_id)

    def shutdown(self):
        # Workers attempt cleanup after graceful extension exit. Host-level
        # process-tree termination can still interrupt them; never deliberately
        # terminate a worker halfway through rollback.
        for job_id, child in self.children.items():
            if child.poll() is None:
                self.cancel(job_id)


def worker(directory, repetitions):
    from .runner import run
    try:
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        scenario = json.loads((directory / "scenario.json").read_text(encoding="utf-8"))
        campaign, summary = run(config, scenario, directory / "evidence", repetitions, directory / "cancel")
        terminal = {"status": "finished", "passed": summary["passed"], "cancelled": summary.get("cancelled", False), "campaign": str(campaign), "summary": str(campaign / "summary.json")}
    except Exception as error:
        terminal = {"status": "failed", "passed": False, "error": f"{type(error).__name__}: {error}"}
    # Readers never see a partially written terminal record.
    save(directory / "terminal.tmp", terminal)
    (directory / "terminal.tmp").replace(directory / "terminal.json")
    return 0 if terminal["passed"] else 1


if __name__ == "__main__":
    sys.exit(worker(Path(sys.argv[1]), int(sys.argv[2])))
