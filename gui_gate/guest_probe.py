"""Read actual guest identity and the selected live Cua daemon; never grant consent.

Configuration contains absolute driver/socket/app-state paths, not expected
identity values. Run inside the dedicated guest account over a fixed SSH wrapper.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import struct
import subprocess
import sys
import time
import uuid
import zlib

from .driver_client import DriverClient
from .native_probe import read_state


def digest(path):
    with path.open('rb') as stream:
        return _digest_stream(stream)


def _digest_stream(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        value.update(chunk)
    return value.hexdigest()


def tree_digest(root):
    records = {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode('utf-8')).hexdigest()


def command(*args):
    return subprocess.run(args, capture_output=True, check=True, timeout=15)


def release_signature(bundle):
    command('/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle))
    details = command('/usr/bin/codesign', '-d', '--verbose=4', '-r-', str(bundle)).stderr.decode('utf-8')
    team = re.search(r'^TeamIdentifier=(.+)$', details, re.M)
    requirement = re.search(r'^designated => (.+)$', details, re.M)
    with (bundle / 'Contents' / 'Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    if (not team or team[1] == 'not set' or not requirement
            or 'Authority=Developer ID Application:' not in details or 'Signature=adhoc' in details):
        raise RuntimeError('macOS baseline requires a verified Developer ID release-signed app')
    return {'bundle_id': info['CFBundleIdentifier'], 'team_id': team[1],
            'designated_requirement': requirement[1], 'app_sha256': tree_digest(bundle)}, details


def mac_desktop_unlocked():
    cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32)
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFBooleanGetValue.argtypes = (ctypes.c_void_p,)
    cf.CFBooleanGetValue.restype = ctypes.c_bool
    cf.CFRelease.argtypes = (ctypes.c_void_p,)
    session = cg.CGSessionCopyCurrentDictionary()
    if not session:
        return False
    try:
        values = {}
        for name in ('kCGSessionOnConsoleKey', 'kCGSessionLoginDoneKey', 'CGSSessionScreenIsLocked'):
            key = cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
            try:
                value = cf.CFDictionaryGetValue(session, key)
                values[name] = bool(cf.CFBooleanGetValue(value)) if value else None
            finally:
                cf.CFRelease(key)
        return (values['kCGSessionOnConsoleKey'] is True and values['kCGSessionLoginDoneKey'] is True
                and values['CGSSessionScreenIsLocked'] is not True)
    finally:
        cf.CFRelease(session)


def windows_process(pid):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.ProcessIdToSessionId.argtypes = (w.DWORD, ctypes.POINTER(w.DWORD))
    advapi.OpenProcessToken.argtypes = (w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE))
    advapi.GetTokenInformation.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD))
    advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(w.LPWSTR))
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    token = w.HANDLE()
    try:
        if not advapi.OpenProcessToken(process, 8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        text = w.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid = text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        session = w.DWORD()
        if not kernel.ProcessIdToSessionId(pid, ctypes.byref(session)):
            raise ctypes.WinError(ctypes.get_last_error())
        return sid, session.value
    finally:
        if token:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)


def windows_unlocked():
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.OpenInputDesktop.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    user.OpenInputDesktop.restype = w.HANDLE
    user.GetUserObjectInformationW.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD))
    user.CloseDesktop.argtypes = (w.HANDLE,)
    desktop = user.OpenInputDesktop(0, False, 1)
    if not desktop:
        return False
    try:
        name, size = ctypes.create_unicode_buffer(256), w.DWORD()
        return bool(user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(size))) and name.value == 'Default'
    finally:
        user.CloseDesktop(desktop)


def linux_unlocked(uid):
    session = command('loginctl', 'show-user', str(uid), '--property=Display', '--value').stdout.decode().strip()
    if not session:
        return False
    lines = command('loginctl', 'show-session', session, '--property=Active', '--property=Remote',
                    '--property=State', '--property=LockedHint').stdout.decode().splitlines()
    return dict(line.split('=', 1) for line in lines) == {'Active': 'yes', 'Remote': 'no', 'State': 'active', 'LockedHint': 'no'}


def capture_present(result):
    for item in result.get('content', []):
        if item.get('type') == 'image' and item.get('mimeType') == 'image/png':
            image = base64.b64decode(item['data'], validate=True)
            if len(image) < 33 or image[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
                continue
            if not all(struct.unpack('>II', image[16:24])):
                continue
            offset, has_pixels = 8, False
            while offset + 12 <= len(image):
                size = struct.unpack('>I', image[offset:offset + 4])[0]
                end = offset + 12 + size
                if end > len(image):
                    break
                kind = image[offset + 4:offset + 8]
                body = image[offset + 4:end - 4]
                if zlib.crc32(body) != struct.unpack('>I', image[end - 4:end])[0]:
                    break
                has_pixels = has_pixels or (kind == b'IDAT' and size > 0)
                if kind == b'IEND':
                    if size == 0 and end == len(image) and has_pixels:
                        return True
                    break
                offset = end
    return False


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) - {'driver', 'socket', 'app_state', 'bundle'}:
        raise ValueError('guest probe config accepts paths, never expected identity/grant values')
    if (not Path(spec['driver']).is_absolute() or not Path(spec['app_state']).is_absolute()
            or not isinstance(spec['socket'], str) or not spec['socket'] or '\0' in spec['socket']):
        raise ValueError('absolute driver/app-state paths and an explicit daemon endpoint are required')


def probe(spec):
    validate_spec(spec)
    system = {'Darwin': 'macos', 'Windows': 'windows', 'Linux': 'linux'}[platform.system()]
    driver = Path(spec['driver']).resolve(strict=True)
    state = read_state(Path(spec['app_state']))
    identity = {'driver_sha256': digest(driver),
                'driver_version': command(str(driver), '--version').stdout.decode('utf-8').strip(),
                'native_app_sha256': digest(Path(__file__).with_name('native_probe.py'))}
    proof = {'os': system, 'architecture': platform.machine(), 'identity': identity,
             'permissions_ready': False, 'interactive_desktop': False, 'daemon_socket': spec['socket']}
    if system == 'macos':
        bundle = Path(spec['bundle']).resolve(strict=True)
        if driver != bundle / 'Contents' / 'MacOS' / 'cua-driver':
            raise RuntimeError('driver must reside in the selected release app bundle')
        signature, details = release_signature(bundle)
        identity.update(signature)
        proof['signature_evidence'] = details
        unlocked = mac_desktop_unlocked()
    elif system == 'windows':
        sid, caller_session = windows_process(os.getpid())
        app_sid, session = windows_process(state['pid'])
        identity['account_sid'] = sid
        proof['app_account_sid'], proof['app_session_id'] = app_sid, session
        # SSH runs in Session 0. Its input-desktop probe cannot establish whether
        # the *interactive* session is unlocked. An attended logon wrapper must
        # run this helper inside that session, or this check fails closed.
        proof['caller_session_id'] = caller_session
        unlocked = app_sid == sid and session > 0 and caller_session == session and windows_unlocked()
    else:
        identity['uid'] = os.getuid()
        app_uid = Path(f"/proc/{state['pid']}").stat().st_uid
        proof['app_uid'] = app_uid
        unlocked = app_uid == identity['uid'] and linux_unlocked(identity['uid'])
    proof['desktop_session_unlocked'] = bool(unlocked)
    proof['driver_path'] = str(driver)
    client = DriverClient('unused', transport_command=[str(driver), 'mcp', '--embedded', '--socket', spec['socket']],
                          environment={'HOME': str(Path.home())})
    try:
        client.start(timeout=20)
        if system in ('macos', 'linux'):
            permissions = client.call('check_permissions', {'prompt': False} if system == 'macos' else {}, timeout=20)
            if permissions.get('isError'):
                raise RuntimeError('live permission probe failed')
            value = permissions.get('structuredContent', {})
            proof['permission_observation'] = permissions
            if system == 'macos':
                source = value.get('source', {})
                ready = (value.get('accessibility') is True and value.get('screen_recording') is True
                         and source.get('attribution') == 'driver-daemon' and source.get('bundle_id') == identity['bundle_id']
                         and Path(source.get('executable', '')).resolve() == driver)
            else:
                ready = (value.get('x11') is True or (value.get('wayland') is True and value.get('wayland_enabled') is True)) and value.get('atspi') is True
        else:
            ready = unlocked
        proof['permissions_ready'] = bool(ready)
        if not ready or not unlocked:
            proof['probed_at_unix_ns'] = time.time_ns()
            return proof  # no capture/actions against an unauthorized or locked desktop
        windows = client.call('list_windows', {}, timeout=20)
        matches = [window for window in windows.get('structuredContent', {}).get('windows', [])
                   if window.get('title') == state['title'] and window.get('pid') == state['pid']]
        if windows.get('isError') or len(matches) != 1:
            raise RuntimeError('native sentinel window is missing or ambiguous')
        window = matches[0]
        snapshot = client.call('get_window_state', {'pid': window['pid'], 'window_id': window['window_id'],
                                                    'include_screenshot': True, 'max_dimension': 512}, timeout=20)
        proof['window'], proof['desktop_observation'] = window, snapshot
        proof['permissions_ready'] = bool(ready)
        proof['interactive_desktop'] = bool(unlocked and not snapshot.get('isError') and capture_present(snapshot))
        proof['probed_at_unix_ns'] = time.time_ns()
    finally:
        client.close()
    return proof


def mailbox_request(directory, timeout=45):
    directory.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    request, response = directory / f'request-{nonce}.json', directory / f'response-{nonce}.json'
    deadline = time.monotonic() + timeout
    request.write_text(nonce, encoding='ascii')
    try:
        while time.monotonic() < deadline:
            if response.exists():
                value = json.loads(response.read_text(encoding='utf-8'))
                if value['request_id'] != nonce:
                    raise RuntimeError('stale or mismatched interactive proof')
                if 'error' in value:
                    raise RuntimeError(value['error'])
                return value['proof']
            time.sleep(0.05)
        raise TimeoutError('interactive probe agent did not answer a fresh challenge')
    finally:
        request.unlink(missing_ok=True)
        response.unlink(missing_ok=True)


def mailbox_serve(directory, spec):
    validate_spec(spec)
    directory.mkdir(parents=True, exist_ok=True)
    while True:
        for request in sorted(directory.glob('request-*.json')):
            nonce = request.stem.removeprefix('request-')
            if not re.fullmatch('[0-9a-f]{32}', nonce):
                continue
            value = {'request_id': nonce}
            try:
                value['proof'] = probe(spec)
                value['proof']['probe_request_id'] = nonce
            except Exception as error:
                value['error'] = f'{type(error).__name__}: {error}'
            response = directory / f'response-{nonce}.json'
            temporary = response.with_suffix('.tmp')
            temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            temporary.replace(response)
            request.unlink(missing_ok=True)
        time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('probe', 'serve', 'request', 'mcp'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--mailbox', type=Path)
    args = parser.parse_args()
    if args.action != 'request' and args.config is None:
        parser.error('probe/serve/mcp require --config')
    if args.action in ('request', 'serve') and args.mailbox is None:
        parser.error('request/serve require --mailbox')
    try:
        if args.action == 'request':
            value = mailbox_request(args.mailbox)
        else:
            spec = json.loads(args.config.read_text(encoding='utf-8'))
            if args.action == 'mcp':
                validate_spec(spec)
                # A persistent stdio proxy to the selected interactive daemon,
                # never direct mode or a permission/installation fallback.
                return subprocess.run([spec['driver'], 'mcp', '--embedded', '--socket', spec['socket']], check=False).returncode
            if args.action == 'serve':
                mailbox_serve(args.mailbox, spec)
                return 0
            value = probe(spec)
        print(json.dumps(value, allow_nan=False))  # UTF-8-safe JSON on legacy Windows stdout
    except Exception as error:
        print(f'guest probe failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
