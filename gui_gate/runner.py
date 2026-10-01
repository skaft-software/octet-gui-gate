#!/usr/bin/env python3
"""Opt-in native GUI gate against three operator-owned, disposable guests.

Configuration and scenarios are trusted executable inputs. This is a harness,
not a VM manager or an OS permission installer. See docs/targets.md.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
import platform
import re
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from .driver_client import DriverClient

TARGETS = ("macos", "windows", "linux")


def argv(value):
    if not isinstance(value, list) or not value or any(not isinstance(s, str) or not s or "\0" in s for s in value):
        raise ValueError("commands must be nonempty argv arrays, not shell strings")
    return value


def json_equal(left, right):
    """Compare JSON values without Python's bool/int equality coercion."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def validate_pointer(path):
    if not isinstance(path, str) or (path and not path.startswith("/")) or re.search(r"~(?![01])", path):
        raise ValueError("expected a valid JSON Pointer")


def pointer(value, path):
    """Strict JSON Pointer lookup; missing evidence is always a failure."""
    validate_pointer(path)
    if path == "":
        return value
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
        passed = json_equal(actual, expected)
    elif op == "contains":
        if not isinstance(actual, (str, list, dict)):
            raise ValueError("contains requires text, array, or object evidence")
        if isinstance(actual, list):
            passed = any(json_equal(item, expected) for item in actual)
        else:
            if not isinstance(expected, str):
                raise ValueError("text/object contains requires a string value")
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
    if not isinstance(config, dict) or not isinstance(scenario, dict):
        raise ValueError("configuration and scenario must be objects")
    if type(config.get("version")) is not int or type(scenario.get("version")) is not int or config["version"] != 1 or scenario["version"] != 1:
        raise ValueError("configuration and scenario version must be integer 1")
    # Reject non-JSON numerical values before any lifecycle command dispatch.
    json.dumps(config, allow_nan=False)
    json.dumps(scenario, allow_nan=False)
    if not isinstance(config["targets"], dict) or set(config["targets"]) != set(TARGETS):
        raise ValueError("exactly macos, windows, and linux targets are required")
    timeout = config.get("timeout_seconds", 120)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    budgets = config.get('acceptance', {})
    if not isinstance(budgets, dict) or set(budgets) - {'max_wave_seconds', 'max_reset_seconds', 'max_campaign_seconds'}:
        raise ValueError('unsupported acceptance budget')
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in budgets.values()):
        raise ValueError('acceptance budgets must be finite positive numbers')
    resources = []
    for target in config["targets"].values():
        if not isinstance(target, dict):
            raise ValueError("each target must be an object")
        resources.append(target["resource"])
        if not isinstance(target["resource"], str) or not target["resource"]:
            raise ValueError("each guest must have a resource name")
        for key in ("reset", "verify", "destroy", "mcp"):
            argv(target[key])
        if not isinstance(target["identity"], dict) or not target["identity"]:
            raise ValueError("a pinned permission identity is required")
        if not isinstance(target.get("bindings", {}), dict):
            raise ValueError("bindings must be an object")
        oracles = target.get('oracles', {})
        if not isinstance(oracles, dict) or any(not isinstance(k, str) or not k for k in oracles):
            raise ValueError('oracles must map nonempty names to argv arrays')
        for command in oracles.values():
            argv(command)
        environment = target.get("environment", {})
        if not isinstance(environment, dict) or any(not isinstance(k, str) or not k or "=" in k or "\0" in k or not isinstance(v, str) or "\0" in v for k, v in environment.items()):
            raise ValueError("environment must map valid names to string values")
    if len(set(resources)) != 3:
        raise ValueError("concurrent targets must own distinct guests")
    steps = scenario["steps"]
    if not isinstance(steps, list) or not steps or any(not isinstance(s, dict) for s in steps) or not any(s.get("assert") for s in steps):
        raise ValueError("scenario requires at least one machine assertion")
    names = set()
    for step in steps:
        if not isinstance(step.get("arguments", {}), dict) or not isinstance(step.get("assert", []), list):
            raise ValueError("step arguments must be an object and assert must be an array")
        if not isinstance(step["id"], str) or not step["id"] or step["id"] in names:
            raise ValueError("step IDs must be nonempty and unique")
        names.add(step["id"])
        if ('tool' in step) == ('oracle' in step):
            raise ValueError('each step requires exactly one tool or application oracle')
        if 'tool' in step:
            if not isinstance(step['tool'], str) or not step['tool']:
                raise ValueError('each tool step requires a tool name')
        else:
            if not isinstance(step['oracle'], str) or not step['oracle']:
                raise ValueError('each oracle step requires an oracle name')
            if any(step['oracle'] not in target.get('oracles', {}) for target in config['targets'].values()):
                raise ValueError('oracle must be configured on every target')
        for check in step.get("assert", []):
            if not isinstance(check, dict):
                raise ValueError("assertions must be objects")
            if check["op"] not in ("equals", "contains", "length_at_least"):
                raise ValueError("unsupported assertion operator")
            validate_pointer(check["path"])
            if "value" not in check:
                raise ValueError("assertions require a value")
    if not any('tool' in step for step in steps):
        raise ValueError('native GUI scenarios require at least one driver tool')


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def hook(command, directory, phase, timeout, owner=None, input_payload=None):
    # Files retain diagnostics and avoid buffering arbitrary hook output in RAM.
    with (directory / f"{phase}.stdout").open("wb") as out, (directory / f"{phase}.stderr").open("wb") as err:
        started = time.monotonic()
        environment = os.environ.copy()
        if owner is not None:
            environment['OCTET_GUI_GATE_OWNER'] = owner
        result = subprocess.run(argv(command), input=input_payload, stdout=out, stderr=err,
                                timeout=timeout, check=False, env=environment)
    if result.returncode:
        raise RuntimeError(f"{phase} exited {result.returncode}")
    return time.monotonic() - started


def check_cancelled(cancel_file):
    if cancel_file is not None and cancel_file.exists():
        raise RuntimeError("campaign cancelled; cleanup still required")


def run_target(name, target, scenario, directory, timeout, cancel_file=None, desktop_barrier=None):
    directory.mkdir(mode=0o700)
    owner = uuid.uuid4().hex
    report = {"target": name, "resource": target["resource"], "lease_owner": owner, "passed": False,
              "steps": [], "timings_seconds": {}, "started_monotonic_ns": time.monotonic_ns()}
    started = time.monotonic()
    client = None
    try:
        check_cancelled(cancel_file)
        report["timings_seconds"]["reset"] = hook(target["reset"], directory, "reset", timeout, owner)
        check_cancelled(cancel_file)
        report["timings_seconds"]["verify"] = hook(target["verify"], directory, "verify", timeout, owner)
        proof = json.loads((directory / "verify.stdout").read_text(encoding="utf-8"))
        json.dumps(proof, allow_nan=False)
        if proof.get("os") != name or not json_equal(proof.get("identity"), target["identity"]):
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
        missing = {step['tool'] for step in scenario['steps'] if 'tool' in step} - tools
        if missing:
            raise RuntimeError(f"guest lacks scenario tools: {sorted(missing)}")
        report['desktop_ready_monotonic_ns'] = time.monotonic_ns()
        if desktop_barrier is not None:
            try:
                desktop_barrier.wait(timeout=timeout)
                report['all_desktops_synchronized'] = True
            except threading.BrokenBarrierError:
                # A failed target cannot make the campaign green, but other
                # authorized targets still produce their independent evidence.
                report['all_desktops_synchronized'] = False
        check_cancelled(cancel_file)
        context = {"bindings": target.get("bindings", {}), "guest": proof, "results": {},
                   "run_id": directory.parent.parent.name + "/" + directory.parent.name}
        for index, step in enumerate(scenario["steps"]):
            check_cancelled(cancel_file)
            kind = 'tool' if 'tool' in step else 'oracle'
            entry = {"id": step["id"], kind: step[kind], "passed": False,
                     "started_monotonic_ns": time.monotonic_ns()}
            report["steps"].append(entry)
            step_start = time.monotonic()
            arguments = resolve(step.get("arguments", {}), context)
            if kind == 'tool':
                result = client.call(step['tool'], arguments, timeout=timeout)
            else:
                phase = f'oracle-{index:03d}'
                hook(target['oracles'][step['oracle']], directory, phase, timeout, owner,
                     json.dumps(arguments, allow_nan=False).encode('utf-8'))
                result = json.loads((directory / f'{phase}.stdout').read_text(encoding='utf-8'))
                if not isinstance(result, dict):
                    raise ValueError('oracle must return a JSON result object')
            evidence = f"step-{index:03d}.json"
            save(directory / evidence, {"arguments": arguments, "result": result})
            entry["evidence"] = evidence
            entry["sha256"] = hashlib.sha256((directory / evidence).read_bytes()).hexdigest()
            entry["seconds"] = time.monotonic() - step_start
            entry['finished_monotonic_ns'] = time.monotonic_ns()
            if result.get("isError") or result.get("is_error"):
                raise RuntimeError(f'{kind} failed: {step[kind]}')
            for check in step.get("assert", []):
                assert_evidence(check, result, context)
            context["results"][step["id"]] = result
            entry["passed"] = True
        report['desktop_finished_monotonic_ns'] = time.monotonic_ns()
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if desktop_barrier is not None and 'all_desktops_synchronized' not in report:
            desktop_barrier.abort()
        try:
            if client is not None:
                client.close()
        except Exception as error:
            report["passed"] = False
            report["close_error"] = str(error)
        try:
            report["timings_seconds"]["destroy"] = hook(target["destroy"], directory, "destroy", timeout, owner)
        except Exception as error:
            report["passed"] = False
            report["cleanup_error"] = str(error)
        report["timings_seconds"]["total"] = time.monotonic() - started
        report["finished_monotonic_ns"] = time.monotonic_ns()
        save(directory / "report.json", report)
    return report


def run(config, scenario, output, repetitions, cancel_file=None):
    validate(config, scenario)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be positive")
    campaign_started = time.monotonic()
    campaign = output / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
    campaign.mkdir(parents=True, mode=0o700)
    save(campaign / "config.json", config)
    save(campaign / "scenario.json", scenario)
    summary = {"schema": "octet.gui-gate.v1", "passed": True, "runs": [],
               "requested_repetitions": repetitions,
               "host": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
               "config_sha256": hashlib.sha256((campaign / 'config.json').read_bytes()).hexdigest(),
               "scenario_sha256": hashlib.sha256((campaign / 'scenario.json').read_bytes()).hexdigest()}
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
            desktop_barrier = threading.Barrier(3)
            futures = [pool.submit(run_target, name, config["targets"][name], scenario, iteration / name,
                                   config.get("timeout_seconds", 120), cancel_file, desktop_barrier) for name in TARGETS]
            reports = [f.result() for f in futures]
            summary["runs"].append(reports)
            summary["passed"] = (summary["passed"] and all(r["passed"] for r in reports)
                                 and all(r.get('all_desktops_synchronized') is True for r in reports))
            if cancel_file is not None and cancel_file.exists():
                summary["passed"] = False
                summary["cancelled"] = True
            save(campaign / "summary.json", summary)
            # A failed cleanup leaves ownership uncertain: do not reset again.
            if any("cleanup_error" in r or "close_error" in r for r in reports):
                break
    summary['campaign_seconds'] = time.monotonic() - campaign_started
    save(campaign / 'summary.json', summary)
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
