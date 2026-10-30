# cand-audit/thenable — probe A/B for `docs/69`

Seven runs answering one question: is a `then` accessor on `Array.prototype` / `Object.prototype` a
**synchronous script window** inside this drop's own promise resolutions?

Pages
- `research/cve-2026-43715/thenable.html` (A*), md5 `3c3126bd65b6f576c28ac84ada8ed09b`
- `research/cve-2026-43715/thenable2.html` (B*), md5 `df4c4314e62101e8d4f9809377f99d65` — adds a
  synchronous `AFTERLOAD` beacon on the line after `document.fonts.load()`, which is what pins the
  window to `FontFaceSet.cpp:215` rather than to the later `faceFinished` resolve.

Served from `/tmp/wkp`, one fresh port per run, quarantine **off** (`~/wk/run_nq.sh`, 18 s), scored only
from the `GET /ev?m=` beacon log. Runs must execute inside the distrobox (`distrobox enter wk`) — outside
it the build dies with `libasan.so.8: cannot open shared object file`.

| file | query | what it shows |
|------|-------|---------------|
| `A1.txt` | `k=none&td=0` | control: `hits=0`, `LOADOK n=1`, `READY` |
| `A2.txt` | `k=arr&td=0` | `THENARR hit=1 len=1` — the array `then` getter fires |
| `A3.txt` | `k=obj&td=0` | `THENOBJ hit=1 len=1` then `hit=2 len=undefined` (the `document.fonts.ready` wrapper) |
| `A4.txt` | `k=arr&td=1` | teardown inside the window (`size` 2 → 0), no ASAN |
| `A5.txt` | `k=obj&td=1` | same for the wrapper window |
| `B1.txt` | `thenable2 k=arr&td=0` | `THENARR` **before** `AFTERLOAD` → the resolve is the one inside `load()` |
| `B2.txt` | `thenable2 k=obj&td=0` | `hit=2` **after** `AFTERLOAD` → the `ready` wrapper resolve |

Every file carries the exact query, the sanitizer verdict (`access: none`, `SUMMARY: none` in all
seven), the harness `EXIT=` line (124 is normal — `run_nq.sh` wraps MiniBrowser in `timeout`) and every
beacon in order.
