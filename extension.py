#!/usr/bin/env python3
"""Standalone, unofficial Octet extension for Skaft's prepared-guest GUI gate."""
from pathlib import Path
import os
import sys
import json

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from octet_extension import CancelledError, Extension, text_content, tool_result  # noqa: E402
from gui_gate.job import Jobs  # noqa: E402

USAGE = "/gui-gate run CONFIG SCENARIO [REPETITIONS] | status JOB_ID | cancel JOB_ID"


def create_extension(state=None):
    extension = Extension(api_version="0.4", max_concurrent_requests=1,
                          supported_features=("request_cancellation", "content_parts"))
    if state is None:
        base = Path(os.environ["OCTET_STATE_DIR"]) if os.environ.get("OCTET_STATE_DIR") else Path.home() / ".octet"
        state = base / "gui-gate"
    jobs = Jobs(state)

    def result(value):
        return {"text": json.dumps(value, indent=2)}

    def command(arguments, _context):
        try:
            if not arguments:
                return {"text": USAGE}
            action = arguments[0]
            if action == "run" and len(arguments) in (3, 4):
                repetitions = int(arguments[3]) if len(arguments) == 4 else 1
                config, scenario, repetitions = jobs.load(arguments[1], arguments[2], repetitions)
                extension.cancellation.raise_if_cancelled()
                if not extension.confirm(
                    "Run the GUI gate against three disposable guests?",
                    detail=(f"Authorize the reviewed configuration's reset, native GUI actions, and destroy commands for {repetitions} repetitions. "
                            "This must not address personal desktops. OS permissions must already be granted by their owner."),
                    destructive=True, default=False,
                ):
                    return {"text": "GUI gate declined; no guest commands were dispatched."}
                extension.cancellation.raise_if_cancelled()
                return result(jobs.start(config, scenario, repetitions))
            if action == "status" and len(arguments) == 2:
                return result(jobs.status(arguments[1]))
            if action == "cancel" and len(arguments) == 2:
                return result(jobs.cancel(arguments[1]))
            raise ValueError(USAGE)
        except CancelledError:
            raise
        except Exception as error:
            return {"text": f"GUI gate: {error}"}

    extension.command(name="gui-gate", description="Run or inspect an explicitly authorized prepared-guest GUI campaign", usage=USAGE)(command)

    @extension.tool(name="gui_gate_status", description="Read an existing GUI gate job's status and retained evidence paths; never starts a guest",
                    parameters={"type": "object", "properties": {"job_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}, "required": ["job_id"], "additionalProperties": False},
                    output_schema={"type": "object"})
    def status(arguments, _context):
        try:
            value = jobs.status(arguments["job_id"])
            return tool_result(text_content(json.dumps(value, indent=2)), structured_content=value)
        except (ValueError, KeyError, OSError) as error:
            return tool_result(text_content(str(error)), is_error=True)

    extension.on_shutdown(jobs.shutdown)
    return extension, jobs


if __name__ == "__main__":
    create_extension()[0].run()
