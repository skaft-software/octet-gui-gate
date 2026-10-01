"""Tiny native desktop calibration app; no browser, network, or automation API.

Start from the guest's interactive logon session. The read-only oracle sees only
state written by the application's real Tk event loop, never driver acknowledgements.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

TITLE = 'Octet GUI Gate Native Probe'


def _sharing_retry(operation):
    # Windows CRT readers do not share deletion. A concurrent read/rename can
    # briefly deny either operation; never change ACLs or hide persistent denial.
    deadline = time.monotonic() + 1
    while True:
        try:
            return operation()
        except PermissionError:
            if os.name != 'nt' or time.monotonic() >= deadline:
                raise
            time.sleep(.01)


def publish(path, text, revision):
    value = {'schema': 'octet.native-probe.v1', 'pid': os.getpid(), 'title': TITLE,
             'text': text, 'revision': revision, 'observed_unix_ns': time.time_ns()}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    _sharing_retry(lambda: temporary.replace(path))


def read_state(path):
    value = json.loads(_sharing_retry(lambda: path.read_text(encoding='utf-8')))
    if (value.get('schema') != 'octet.native-probe.v1' or value.get('title') != TITLE
            or type(value.get('pid')) is not int or value['pid'] <= 0
            or not isinstance(value.get('text'), str)
            or type(value.get('revision')) is not int or value['revision'] < 0):
        raise ValueError('invalid native app state')
    return value


def oracle(path, request, timeout=30):
    if not isinstance(request, dict) or set(request) - {'expected'}:
        raise ValueError('oracle accepts only optional expected text')
    expected = request.get('expected')
    if 'expected' in request and not isinstance(expected, str):
        raise ValueError('expected must be a string')
    deadline = time.monotonic() + timeout
    while True:
        state = read_state(path)
        if 'expected' not in request or state['text'] == expected:
            return {'structuredContent': state}
        if time.monotonic() >= deadline:
            # Preserve observed wrong state; the scenario assertion must fail.
            return {'structuredContent': state}
        time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('app', 'oracle'))
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'oracle':
        # ASCII-escaped JSON is UTF-8-safe even on Windows legacy stdout codecs.
        print(json.dumps(oracle(args.state, json.load(sys.stdin)), allow_nan=False))
        return
    import tkinter as tk
    from tkinter import ttk
    args.state.parent.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.title(TITLE)
    root.geometry('600x160')
    ttk.Label(root, text='Type a run marker into the native field below.').pack(padx=20, pady=15)
    text = tk.StringVar()
    entry = ttk.Entry(root, textvariable=text, width=70)
    entry.pack(padx=20, pady=10)
    revision = 0

    def changed(*_):
        nonlocal revision
        revision += 1
        publish(args.state, text.get(), revision)

    text.trace_add('write', changed)
    publish(args.state, '', revision)
    root.after(200, entry.focus_force)
    root.mainloop()


if __name__ == '__main__':
    main()
