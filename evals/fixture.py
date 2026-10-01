"""A fake desktop with independent persistent state and injected faults.

All three OS names are labels on the current host, not real guest OSes.
"""
import json
import os
from pathlib import Path
import sys
import time


def main():
    phase, root, name, fault = sys.argv[1:]
    root = Path(root)
    directory = root / name
    directory.mkdir(exist_ok=True)
    state = directory / 'state.json'
    events = directory / 'events.jsonl'

    def event(kind):
        with events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'kind': kind, 'time_ns': time.time_ns(), 'pid': os.getpid()}) + '\n')

    def reply(request, result):
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)

    event(phase)
    if phase == 'reset':
        if fault == 'reset_error':
            raise SystemExit(7)
        if fault == 'reset_timeout':
            time.sleep(10)
        if fault == 'overlap':
            (directory / 'arrived').touch()
            deadline = time.monotonic() + 5
            while not all((root / target / 'arrived').exists() for target in ('macos', 'windows', 'linux')):
                if time.monotonic() > deadline:
                    raise SystemExit(8)
                time.sleep(0.01)
        if fault == 'slow_reset':
            # Deterministic in-flight operation for protocol cancellation evals:
            # do not race cancellation against an arbitrary sleep interval.
            deadline = time.monotonic() + 8
            while not list(root.parent.glob('state/gui-gate/*/cancel')):
                if time.monotonic() > deadline:
                    raise SystemExit(10)
                time.sleep(0.01)
        # Carrying previous-run state is an injected failed rollback.
        if fault != 'stale_reset' or not state.exists():
            state.write_text(json.dumps({'text': '', 'identity': 'golden'}), encoding='utf-8')
        event('reset_done')
    elif phase == 'destroy':
        if fault == 'cleanup_error':
            raise SystemExit(9)
        event('destroy_done')
    elif phase == 'verify':
        if fault == 'bad_verify_json':
            print('not JSON')
            return
        identity = {'account': name + '-account', 'driver_sha256': 'fixture-only', 'signature': 'golden'}
        if fault == 'identity_changed':
            identity['signature'] = 'rebuilt-ad-hoc'
        if fault == 'boolean_identity':
            identity['signature'] = True
        print(json.dumps({'os': 'linux' if fault == 'wrong_os' and name != 'linux' else name,
                          'identity': identity, 'permissions_ready': fault != 'permission_denied',
                          'interactive_desktop': fault != 'session0', 'fixture': True,
                          'provider_secret_present': any(os.environ.get(k) for k in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY'))}))
    elif phase == 'mcp':
        for line in sys.stdin:
            request = json.loads(line)
            if 'id' not in request:
                continue
            method = request['method']
            if method == 'initialize':
                reply(request, {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'eval-fake', 'version': '1'}})
            elif method == 'tools/list':
                names = ['read'] if fault == 'missing_tool' else ['read', 'write']
                reply(request, {'tools': [{'name': tool, 'inputSchema': {'type': 'object'}} for tool in names]})
            else:
                tool = request['params']['name']
                event(tool)
                if fault == 'transport_closed':
                    return
                if fault == 'rpc_error':
                    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32000, 'message': 'injected RPC failure'}}), flush=True)
                    continue
                if fault == 'notification_timeout':
                    for _ in range(500):
                        print(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {}}), flush=True)
                        time.sleep(0.01)
                    continue
                if fault == 'tool_error':
                    reply(request, {'isError': True, 'structuredContent': {'text': ''}})
                    continue
                if fault == 'screenshot_only':
                    reply(request, {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': 'fixture-not-an-image'}]})
                    continue
                current = json.loads(state.read_text(encoding='utf-8'))
                if tool == 'write' and fault != 'false_ack':
                    current['text'] = request['params']['arguments']['text']
                    state.write_text(json.dumps(current, ensure_ascii=False), encoding='utf-8')
                result = {'text': current['text']}
                if fault == 'empty_tree':
                    result = {}
                elif fault == 'unicode_corruption' and tool == 'read' and current['text']:
                    result['text'] = current['text'].encode('ascii', 'replace').decode('ascii')
                reply(request, {'structuredContent': result})
    else:
        raise ValueError(phase)


if __name__ == '__main__':
    main()
