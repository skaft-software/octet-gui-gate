import sys
import time
import unittest

from gui_gate.driver_client import DriverClient, McpError


NOTIFICATIONS = '''import json, sys, time
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request: continue
    method=request['method']
    if method == 'tools/call':
        for index in range(100):
            print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{}}), flush=True)
            time.sleep(0.02)
        continue
    result = {'tools': [{'name': 'observe', 'inputSchema': {}}]} if method == 'tools/list' else {}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)
'''


class ClientTests(unittest.TestCase):
    def test_transport_command_rejects_shell_strings_and_nul(self):
        for command in ('ssh guest cua-driver mcp', [], ['bad\0command']):
            with self.subTest(command=command), self.assertRaises(ValueError):
                DriverClient('unused', transport_command=command)

    def test_notifications_cannot_extend_request_deadline(self):
        client = DriverClient('unused', transport_command=[sys.executable, '-u', '-c', NOTIFICATIONS])
        try:
            client.start(timeout=5)
            started = time.monotonic()
            with self.assertRaises(McpError): client.call('observe', timeout=0.15)
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
