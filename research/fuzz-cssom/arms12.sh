#!/usr/bin/env bash
# docs/91 arm sweep: each line "tag port query secs"
set -u
while read -r TAG PORT Q SECS; do
  [ -z "${TAG:-}" ] && continue
  bash /tmp/wkp/c12run.sh "$TAG" "$PORT" "${SECS:-20}" "$Q" >> /tmp/arms12.out 2>&1
done
