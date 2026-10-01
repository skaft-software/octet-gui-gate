# Third-party notices

## Octet Python extension SDK

`vendor/octet_extension/` is copied, without runtime modifications, from
[`skaft-software/octet`](https://github.com/skaft-software/octet),
`sdk/python/octet_extension`, commit
`ab882984ecfde160254c2aae8d4bb7245260ee65` (SDK 0.8.2).

License: MIT. Copyright (c) 2026 Achuthan Mukundan and Skaft Software contributors.
The complete license text is included in [LICENSE](LICENSE).
Generated protocol types shipped with that SDK retain their original headers.

## Octet Cua Driver MCP client

`gui_gate/driver_client.py` is derived from the same Octet commit's
`extensions/octet-computer-use/octet_computer_use/driver_client.py`.
Local changes add validated explicit transport argv for prepared remote guests,
identify this harness in the MCP handshake, and use an absolute request deadline
so notifications cannot extend request timeouts.

License: MIT. Copyright (c) 2026 Achuthan Mukundan and Skaft Software contributors.
The complete license text is included in [LICENSE](LICENSE).

## External software, not bundled

[Cua Driver](https://github.com/trycua/cua) is MIT licensed and must be installed
separately in each prepared guest. This repository does not vendor its runtime.
VM software, firmware, guest operating systems, and application binaries are
not included. Their licensing and redistribution terms must be assessed
independently; in particular, MIT licensing of this harness does not license
Windows or Apple software.
