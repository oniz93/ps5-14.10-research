#!/usr/bin/env python3
"""Read single members out of a huge remote ZIP without downloading it.

Sony publishes its PS5 OSS source drops as multi-gigabyte zips (WebKit_1400.zip is
1.6 GB). We only ever need a handful of files out of them -- a Version.xcconfig, a
ChangeLog, a header -- so this reads the central directory with HTTP range requests
and then pulls just the member's byte span.

    python3 remote_zip.py URL --list 'Version.xcconfig'
    python3 remote_zip.py URL --list 'Configurations/.*xcconfig' --count 40
    python3 remote_zip.py URL --read 'Source/JavaScriptCore/Configurations/Version.xcconfig'
    python3 remote_zip.py URL --grep 'MAJOR_VERSION' --name 'xcconfig'

Handles ZIP64 (WebKit has >65k members). Methods 0 (stored) and 8 (deflate) only,
which is all a source drop ever uses.
"""
from __future__ import annotations

import argparse
import re
import ssl
import struct
import sys
import time
import urllib.request
import zlib

EOCD = b"PK\x05\x06"
EOCD64 = b"PK\x06\x06"
EOCD64_LOC = b"PK\x06\x07"
CEN = b"PK\x01\x02"
LOC = b"PK\x03\x04"


class RemoteZip:
    def __init__(self, url: str, timeout: int = 60) -> None:
        self.url = url
        self.timeout = timeout
        self.size = self._size()
        self._cd: list[dict] = []
        self._load_central_directory()

    # ---- plumbing -------------------------------------------------------
    def _contexts(self) -> list:
        """PlayStation's CDN intermittently serves a chain without intermediates.
        The default store usually works; certifi's bundle often succeeds on the same
        edge, so cycle through both before giving up."""
        out = [ssl.create_default_context()]
        try:
            import certifi  # noqa: PLC0415
            out.append(ssl.create_default_context(cafile=certifi.where()))
        except Exception:  # noqa: BLE001
            pass
        return out

    def _open(self, req, attempts: int = 8):
        last = None
        ctxs = self._contexts()
        for i in range(attempts):
            ctx = ctxs[i % len(ctxs)]
            try:
                return urllib.request.urlopen(req, timeout=self.timeout, context=ctx)
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.0 + 1.0 * i)
        raise last

    def _size(self) -> int:
        req = urllib.request.Request(self.url, method="HEAD")
        with self._open(req) as r:
            n = r.headers.get("Content-Length")
            if not n:
                raise RuntimeError("server did not send Content-Length")
            return int(n)

    def _range(self, start: int, end: int) -> bytes:
        if start < 0:
            start = self.size + start
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end}"})
        with self._open(req) as r:
            data = r.read()
        want = end - start + 1
        if len(data) != want:
            raise RuntimeError(f"short read: asked {want}, got {len(data)}")
        return data

    # ---- central directory ---------------------------------------------
    def _load_central_directory(self) -> None:
        tail_len = min(self.size, 1 << 20)
        tail = self._range(self.size - tail_len, self.size - 1)

        i = tail.rfind(EOCD64_LOC)
        if i != -1:
            (eocd64_off,) = struct.unpack_from("<Q", tail, i + 8)
            head = self._range(eocd64_off, eocd64_off + 55)
            if not head.startswith(EOCD64):
                raise RuntimeError("bad ZIP64 EOCD")
            n_entries, cd_size, cd_off = struct.unpack_from("<QQQ", head, 32)
        else:
            j = tail.rfind(EOCD)
            if j == -1:
                raise RuntimeError("no end-of-central-directory record found")
            n_entries, cd_size, cd_off = struct.unpack_from("<HII", tail, j + 10)

        cd = self._range(cd_off, cd_off + cd_size - 1)
        self._cd = list(self._parse_cd(cd, n_entries))

    @staticmethod
    def _parse_cd(cd: bytes, n_entries: int):
        pos = 0
        seen = 0
        while pos + 46 <= len(cd) and cd[pos:pos + 4] == CEN:
            (method,) = struct.unpack_from("<H", cd, pos + 10)
            (crc,) = struct.unpack_from("<I", cd, pos + 16)
            csize, usize = struct.unpack_from("<II", cd, pos + 20)
            nlen, elen, clen = struct.unpack_from("<HHH", cd, pos + 28)
            (lho,) = struct.unpack_from("<I", cd, pos + 42)
            name = cd[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
            extra = cd[pos + 46 + nlen:pos + 46 + nlen + elen]

            # ZIP64 extended information: fields present only when the 32-bit
            # slot is saturated, and in a fixed order.
            if 0xFFFFFFFF in (csize, usize, lho) or 0xFFFFFFFF == lho:
                q = 0
                while q + 4 <= len(extra):
                    tag, ln = struct.unpack_from("<HH", extra, q)
                    if tag == 0x0001:
                        vals = extra[q + 4:q + 4 + ln]
                        k = 0

                        def take():
                            nonlocal k
                            (v,) = struct.unpack_from("<Q", vals, k)
                            k += 8
                            return v

                        if usize == 0xFFFFFFFF:
                            usize = take()
                        if csize == 0xFFFFFFFF:
                            csize = take()
                        if lho == 0xFFFFFFFF:
                            lho = take()
                        break
                    q += 4 + ln

            yield {
                "name": name,
                "crc": crc,
                "method": method,
                "csize": csize,
                "usize": usize,
                "offset": lho,
            }
            seen += 1
            pos += 46 + nlen + elen + clen
            if seen >= n_entries:
                break

    # ---- members --------------------------------------------------------
    def find(self, pattern: str) -> list[dict]:
        rx = re.compile(pattern)
        return [e for e in self._cd if rx.search(e["name"])]

    def read(self, name: str) -> bytes:
        for e in self._cd:
            if e["name"] == name:
                break
        else:
            raise KeyError(name)
        hdr = self._range(e["offset"], e["offset"] + 29)
        if not hdr.startswith(LOC):
            raise RuntimeError(f"bad local header for {name}")
        nlen, elen = struct.unpack_from("<HH", hdr, 26)
        start = e["offset"] + 30 + nlen + elen
        blob = self._range(start, start + e["csize"] - 1)
        if e["method"] == 0:
            return blob
        if e["method"] == 8:
            return zlib.decompress(blob, -15)
        raise RuntimeError(f"unsupported compression method {e['method']} for {name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--list", metavar="REGEX", help="list members whose path matches")
    ap.add_argument("--read", metavar="PATH", help="print one member")
    ap.add_argument("--grep", metavar="REGEX", help="search member contents (needs --name filter)")
    ap.add_argument("--name", metavar="REGEX", default=".", help="filename filter for --grep")
    ap.add_argument("--count", type=int, default=25)
    ap.add_argument("--manifest", metavar="PATH", help="write name/crc/size for every member, then exit")
    ap.add_argument("--max-bytes", type=int, default=20000, help="truncate --read/--grep output")
    a = ap.parse_args()

    z = RemoteZip(a.url)
    if a.manifest:
        import json as _json
        man = {e["name"]: [e["crc"], e["usize"], e["csize"]] for e in z._cd}
        _json.dump(man, open(a.manifest, "w"))
        print(f"{len(man)} members -> {a.manifest}", file=sys.stderr)
        return 0
    print(f"{a.url}\n  size {z.size:,} bytes, {len(z._cd):,} members", file=sys.stderr)

    if a.read:
        data = z.read(a.read)
        sys.stdout.write(data[:a.max_bytes].decode("utf-8", "replace"))
        if len(data) > a.max_bytes:
            print(f"\n... [{len(data):,} bytes total]", file=sys.stderr)
        return 0

    if a.grep:
        rx = re.compile(a.grep.encode())
        hits = 0
        for e in z.find(a.name):
            if e["usize"] > 4_000_000:
                continue
            try:
                body = z.read(e["name"])
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {e['name']}: {exc}", file=sys.stderr)
                continue
            if rx.search(body):
                text = body.decode("utf-8", "replace")
                for line in text.splitlines():
                    if rx.search(line.encode()):
                        print(f"{e['name']}: {line.strip()[:300]}")
                        break
                hits += 1
                if hits >= a.count:
                    break
        print(f"\n[{hits} member(s) matched]", file=sys.stderr)
        return 0

    matches = z.find(a.list or ".")
    for e in matches[: a.count]:
        print(f"{e['usize']:>10,}  {e['name']}")
    print(f"\n[{len(matches)} match(es), showing {min(len(matches), a.count)}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
