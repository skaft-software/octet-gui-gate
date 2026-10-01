#!/usr/bin/env python3
"""Opt-in native GUI gate against three operator-owned, disposable guests.

Configuration and scenarios are trusted executable inputs. This is a harness,
not a VM manager or an OS permission installer. See docs/testing/gui-gate.md.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .driver_client import DriverClient

TARGETS = ("macos", "windows", "linux")


def argv(value):
    if not isinstance(value, list) or not value or any(not isinstance(s, str) or not s or "\0" in s for s in value):
        raise ValueError("commands must be nonempty argv arrays, not shell strings")
    return value


def pointer(value, path):
    """Strict JSON Pointer lookup; missing evidence is always a failure."""
    if path == "":
        return value
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("expected a JSON Pointer")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isascii() or not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                raise ValueError("array pointers require canonical nonnegative indices")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def resolve(value, context):
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return pointer(context, value["$ref"])
        return {k: resolve(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, context) for v in value]
    return value


def assert_evidence(check, result, context):
    actual = pointer(result, check["path"])
    expected = resolve(check["value"], context)
    op = check["op"]
    if op == "equals":
        passed = json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    elif op == "contains":
        if not isinstance(actual, (str, list, dict)):
            raise ValueError("contains requires text, array, or object evidence")
        passed = expected in actual
    elif op == "length_at_least":
        if type(expected) is not int or expected < 1 or not isinstance(actual, (str, list, dict)):
            raise ValueError("length_at_least requires a positive integer and collection evidence")
        passed = len(actual) >= expected
    else:
        raise ValueError(f"unknown assertion: {op}")
    if not passed:
        raise AssertionError(f"assertion failed: {check['path']} {op} {expected!r}")


def validate(config, scenario):
    if config.get("version") != 1 or scenario.get("version") != 1:
        raise ValueError("configuration and scenario version must be 1")
    if set(config["targets"]) != set(TARGETS):
        raise ValueError("exactly macos, windows, and linux targets are required")
    timeout = config.get("timeout_seconds", 120)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    resources = []
    for target in config["targets"].values():
        resources.append(target["resource"])
        if not isinstance(target["resource"], str) or not target["resource"]:
            raise ValueError("each guest must have a resource name")
        for key in ("reset", "verify", "destroy", "mcp"):
            argv(target[key])
        if not isinstance(target["identity"], dict) or not target["identity"]:
            raise ValueError("a pinned permission identity is required")
    if len(set(resources)) != 3:
        raise ValueError("concurrent targets must own distinct guests")
    steps = scenario["steps"]
    if not isinstance(steps, list) or not steps or not any(s.get("assert") for s in steps):
        raise ValueError("scenario requires at least one machine assertion")
    names = set()
    for step in steps:
        if not isinstance(step["id"], str) or not step["id"] or step["id"] in names:
            raise ValueError("step IDs must be nonempty and unique")
        names.add(step["id"])
        if not isinstance(step["tool"], str) or not step["tool"]:
            raise ValueError("each step requires a tool")
        for check in step.get("assert", []):
            if check["op"] not in ("equals", "contains", "length_at_least"):
                raise ValueError("unsupported assertion operator")
            if not isinstance(check["path"], str) or (check["path"] and not check["path"].startswith("/")):
                raise ValueError("assertion paths must be JSON Pointers")
            if "value" not in check:
                raise ValueError("assertions require a value")


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def hook(command, directory, phase, timeout):
    # Files retain diagnostics and avoid buffering arbitrary hook output in RAM.
    with (directory / f"{phase}.stdout").open("wb") as out, (directory / f"{phase}.stderr").open("wb") as err:
        started = time.monotonic()
        result = subprocess.run(argv(command), stdout=out, stderr=err, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{phase} exited {result.returncode}")
    return time.monotonic() - started


def check_cancelled(cancel_file):
    if cancel_file is not None and cancel_file.exists():
        raise RuntimeError("campaign cancelled; cleanup still required")


def run_target(name, target, scenario, directory, timeout, cancel_file=None):
    directory.mkdir(mode=0o700)
    report = {"target": name, "resource": target["resource"], "passed": False, "steps": [], "timings_seconds": {}}
    started = time.monotonic()
    client = None
    try:
        check_cancelled(cancel_file)
        report["timings_seconds"]["reset"] = hook(target["reset"], directory, "reset", timeout)
        check_cancelled(cancel_file)
        report["timings_seconds"]["verify"] = hook(target["verify"], directory, "verify", timeout)
        proof = json.loads((directory / "verify.stdout").read_text(encoding="utf-8"))
        if proof.get("os") != name or proof.get("identity") != target["identity"]:
            raise RuntimeError("guest OS or permission identity differs from pinned identity")
        if proof.get("permissions_ready") is not True or proof.get("interactive_desktop") is not True:
            raise RuntimeError("guest has no authorized, interactive desktop")
        report["guest"] = proof
        check_cancelled(cancel_file)
        client = DriverClient("unused", transport_command=target["mcp"], environment=target.get("environment", {}))
        connect = time.monotonic()
        client.start(timeout=timeout)
        report["timings_seconds"]["connect"] = time.monotonic() - connect
        tools = {t.name for t in client.tools()}
        missing = {step["tool"] for step in scenario["steps"]} - tools
        if missing:
            raise RuntimeError(f"guest lacks scenario tools: {sorted(missing)}")
        context = {"bindings": target.get("bindings", {}), "results": {}, "run_id": directory.parent.parent.name + "/" + directory.parent.name}
        for index, step in enumerate(scenario["steps"]):
            check_cancelled(cancel_file)
            entry = {"id": step["id"], "tool": step["tool"], "passed": False}
            report["steps"].append(entry)
            step_start = time.monotonic()
            arguments = resolve(step.get("arguments", {}), context)
            result = client.call(step["tool"], arguments, timeout=timeout)
            evidence = f"step-{index:03d}.json"
            save(directory / evidence, {"arguments": arguments, "result": result})
            entry["evidence"] = evidence
            entry["sha256"] = hashlib.sha256((directory / evidence).read_bytes()).hexdigest()
            entry["seconds"] = time.monotonic() - step_start
            if result.get("isError") or result.get("is_error"):
                raise RuntimeError(f"tool failed: {step['tool']}")
            for check in step.get("assert", []):
                assert_evidence(check, result, context)
            context["results"][step["id"]] = result
            entry["passed"] = True
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            if client is not None:
                client.close()
        except Exception as error:
            report["passed"] = False
            report["close_error"] = str(error)
        try:
            report["timings_seconds"]["destroy"] = hook(target["destroy"], directory, "destroy", timeout)
        except Exception as error:
            report["passed"] = False
            report["cleanup_error"] = str(error)
        report["timings_seconds"]["total"] = time.monotonic() - started
        save(directory / "report.json", report)
    return report


def run(config, scenario, output, repetitions, cancel_file=None):
    validate(config, scenario)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be positive")
    campaign = output / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
    campaign.mkdir(parents=True, mode=0o700)
    save(campaign / "config.json", config)
    save(campaign / "scenario.json", scenario)
    summary = {"schema": "octet.gui-gate.v1", "passed": True, "runs": []}
    # One worker per OS: at most one macOS guest, never multiple runs per guest.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index in range(repetitions):
            if cancel_file is not None and cancel_file.exists():
                summary["passed"] = False
                summary["cancelled"] = True
                save(campaign / "summary.json", summary)
                break
            iteration = campaign / f"run-{index:04d}"
            iteration.mkdir(mode=0o700)
            futures = [pool.submit(run_target, name, config["targets"][name], scenario, iteration / name, config.get("timeout_seconds", 120), cancel_file) for name in TARGETS]
            reports = [f.result() for f in futures]
            summary["runs"].append(reports)
            summary["passed"] = summary["passed"] and all(r["passed"] for r in reports)
            if cancel_file is not None and cancel_file.exists():
                summary["passed"] = False
                summary["cancelled"] = True
            save(campaign / "summary.json", summary)
            # A failed cleanup leaves ownership uncertain: do not reset again.
            if any("cleanup_error" in r or "close_error" in r for r in reports):
                break
    return campaign, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--cancel-file", type=Path, help="stop between bounded operations and then clean up")
    parser.add_argument("--allow-disposable-guests", action="store_true", help="authorize configured reset, GUI actions, and destroy commands")
    args = parser.parse_args()
    if not args.allow_disposable_guests:
        parser.error("requires --allow-disposable-guests; never point this at a personal desktop")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        campaign, summary = run(config, scenario, args.output, args.repetitions, args.cancel_file)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(campaign)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
