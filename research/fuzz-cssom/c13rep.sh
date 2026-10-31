#!/usr/bin/env bash
# docs/92 repetition wrapper: run one caps13 arm until N attempts have actually loaded the page.
# A flaked attempt (empty server log: the browser never fetched) is retried and reported as such.
# usage: c13rep.sh <arm> <n_good> <portbase> <secs>
set -u
ARM=${1:?}; NEED=${2:-3}; PB=${3:-12300}; SECS=${4:-25}
good=0; try=0; max=$((NEED*3))
while [ $good -lt $NEED ] && [ $try -lt $max ]; do
  try=$((try+1)); P=$((PB+try))
  out=$(bash /tmp/wkp/c13run.sh "${ARM}_r${try}" "$P" "$SECS" "arm=$ARM" 2>&1)
  if grep -aq "GET /ev?m=" "/tmp/srv$P.log" 2>/dev/null; then
    good=$((good+1))
    echo "$out" | grep -aE "^===|SUMMARY: AddressSanitizer|access: none|ImageBuffer.cpp:119|ImageBitmapBacking.cpp|#4 .*SerializedScriptValue|EXIT=" | sed 's/^/  /'
    echo "$out" | grep -a "  cap\|  pre&\|  getter\|  closed\|  wpost\|  wkrpost\|  rx&\|  xmid&\|  xother\|  done" | sed 's/^/  B/'
  else
    echo "  !!! attempt $try on port $P flaked (no page request) — retried"
    pkill -f "[h]ttp.server $P" 2>/dev/null
  fi
done
echo "=== $ARM: $good good of $try tries"
