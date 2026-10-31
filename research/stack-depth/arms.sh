#!/usr/bin/env bash
# docs/108 arms — run ON the oracle.  One arm per process; $rsp per hit from gdb.
set -u
A_IDB='WebCore::createIDBKeyFromValue(JSC::JSGlobalObject&, JSC::JSValue, WTF::Vector<JSC::JSArray*, 0ul, WTF::CrashOnOverflow, 16ul, WTF::FastMalloc>&)'
A_CSS='WebCore::CSSParserImpl::consumeRegularRuleList(WebCore::CSSParserTokenRange)'
A_CLONE='WebCore::CloneSerializer::serialize(JSC::JSValue)'
A_DES='WebCore::CloneDeserializer::deserialize()'
case "${1:-}" in
  idb64)    bash ~/stkrun.sh idb64    8950 "arm=idb&d=64"    20 "$A_IDB" ;;
  idb2000)  bash ~/stkrun.sh idb2000  8951 "arm=idb&d=2000"  40 "$A_IDB" ;;
  idb1000)  bash ~/stkrun.sh idb1000  8952 "arm=idb&d=1000"  35 "$A_IDB" ;;
  widb2000) bash ~/stkrun.sh widb2000 8953 "arm=widb&d=2000" 45 "$A_IDB" ;;
  widb8)    bash ~/stkrun.sh widb8    8958 "arm=widb&d=8"    25 "$A_IDB" ;;
  css128)   bash ~/stkrun.sh css128   8954 "arm=css&d=128"   30 "$A_CSS" ;;
  css64)    bash ~/stkrun.sh css64    8955 "arm=css&d=64"    30 "$A_CSS" ;;
  clone20k) bash ~/stkrun.sh clone20k 8956 "arm=clone&d=20000" 30 "$A_CLONE" ;;
  clone41k) bash ~/stkrun.sh clone41k 8959 "arm=clone&d=41000" 25 ;;
  mp20k)    bash ~/stkrun.sh mp20k    8960 "arm=mp&d=20000"    30 "$A_DES" ;;
  json100k) bash ~/stkrun.sh json100k 8957 "arm=json&d=100000" 30 ;;
  ul1024)   STK_ULIMIT=1024 bash ~/stkrun.sh ul1024 8961 "arm=widb&d=8" 25 "$A_IDB" ;;
  *) echo "unknown arm: ${1:-}"; exit 2 ;;
esac
