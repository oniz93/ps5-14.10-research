#!/usr/bin/env bash
# docs/89 sweep arms, one per line, serially, each with a fresh port.  Quarantine OFF (run_nq.sh).
# The four required arms move only the seed; `wxt=1` adds the two transfer ops to the alphabet, and
# `wxk=1` is the transfer-list spelling.  GC4 puts a collection inside the windows; C2 is the
# window-axis control (then=0&ath=0).  `skip=` keeps the two known deterministic crashes out.
set -u
cd /tmp/wkp || exit 2
S="skip=Rpage,Rnest-link,Fdoc&every=250&ath=1&extf=0&extw=1&extm=1&mof=1&wxt=1"
PAGE=seq5.html RUN=nq bash ./srun.sh "S1 10021 300 n=20000&seed=1&then=1&$S"
PAGE=seq5.html RUN=nq bash ./srun.sh "S2 10022 300 n=20000&seed=2&then=1&$S"
PAGE=seq5.html RUN=nq bash ./srun.sh "S3 10023 300 n=20000&seed=3&then=1&$S"
PAGE=seq5.html RUN=nq bash ./srun.sh "S4 10024 300 n=20000&seed=4&then=1&$S"
PAGE=seq5.html RUN=nq bash ./srun.sh "GC4 10025 400 n=20000&seed=1&then=1&gc=1&gcmax=60&$S"
PAGE=seq5.html RUN=nq bash ./srun.sh "C2 10026 300 n=20000&seed=1&then=0&ath=0&$S"
echo "ALL ARMS DONE"
