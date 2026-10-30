#!/usr/bin/env bash
# docs/88 sweep: the arms after S1, one per line, serially, each with a fresh port.
set -u
cd /tmp/wkp
COMMON="n=20000&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250"
PAGE=seq4.html RUN=nq bash ./srun.sh "S2 10012 400 n=20000&seed=2&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250"
PAGE=seq4.html RUN=nq bash ./srun.sh "S3 10013 400 n=20000&seed=3&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250"
PAGE=seq4.html RUN=nq bash ./srun.sh "S4 10014 400 n=20000&seed=4&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250"
PAGE=seq4.html RUN=nq bash ./srun.sh "S5 10015 400 n=20000&seed=1&then=1&ath=1&extf=1&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250"
PAGE=seq4.html RUN=nq bash ./srun.sh "GC4 10016 500 n=20000&seed=1&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&gc=1&gcmax=60&skip=Rpage,Rnest-link,Fdoc&every=250"
PAGE=seq4.html RUN=nq bash ./srun.sh "C2 10017 400 n=20000&seed=1&then=0&ath=0&extf=0&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250"
echo "ALL ARMS DONE"
