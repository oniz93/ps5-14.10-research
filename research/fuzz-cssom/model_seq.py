#!/usr/bin/env python3
"""Offline model of research/fuzz-cssom/seq.html's op stream — the minimiser and the determinism check.

Rebuilds the page's xorshift32 and its *round* structure from the weight table alone, then prints the
op stream it predicts.  Used for two things only:

  1. determinism: the predicted per-op census must equal the page's own `m=census` beacons, which is
     what makes `n=`/`only=`/`skip=` a valid minimiser (docs/85 §2);
  2. replay: `--round R` prints the exact chain of operations a beacon left off in, so a failing
     round can be read without re-running the fuzzer.

Usage:
    model_seq.py --seed 1 --rounds 200                 # census + totals
    model_seq.py --seed 1 --rounds 200 --round 63      # one round's chain
    model_seq.py --seed 1 --rounds 200 --census-file c.txt   # compare with the page's census
"""
import argparse
import re
import sys

# Weights in declaration order: the 29 ops extracted verbatim from fuzz.html (docs/84), the two
# docs/85 adds, the three docs/86 adds, then the three docs/87 adds.  Keep in step with the builders —
# seq3.html's op table is the source of truth, and `--census-file` is how that is checked, not assumed.
WEIGHTS = [
    ("Fnew-local", 6), ("Fnew-url", 3), ("Fcheck", 3), ("Fload", 3), ("Fstatus", 3), ("Fdel", 2),
    ("Fstyle", 5), ("Fready", 1),
    ("Rfont", 6), ("Rplain", 4), ("Rdel", 4), ("Rmedia", 3), ("Rpage", 1), ("Rnest-inline", 2),
    ("Rnest-link", 1), ("Rlinkplain", 2), ("Rlinkdel", 2), ("Rdetach", 2),
    ("Cdef", 2), ("Cup", 3), ("Cupgrade", 2), ("Cattr", 2),
    ("Grange", 3), ("Gsel", 2), ("Gchurn", 2), ("Gsurround", 1),
    ("Llayout", 6), ("Ltext", 2), ("Mchurn", 2),
    ("Fnew-good", 6), ("Fdoc", 6),
    # docs/86: a second document, Animation's resolve frames, a worker
    ("Aanim", 4), ("Aframe", 4), ("Aworker", 3),
    # docs/87: structuredClone's serializer, IndexedDB's key builder, MutationObserver
    ("Cclone", 5), ("Ikey", 3), ("Mobs", 3),
    # docs/88: the delivery loop's own nested frame (an op so the stream gives it draws; the nesting
    # itself happens inside the delivery, which is why the weight is small)
    ("Mofr", 2),
]
SLOTS = 6


class Prng:
    def __init__(self, seed: int):
        self.st = seed & 0xFFFFFFFF or 1

    def rnd(self) -> int:
        st = self.st
        st = (st ^ ((st << 13) & 0xFFFFFFFF)) & 0xFFFFFFFF
        st = (st ^ (st >> 17)) & 0xFFFFFFFF
        st = (st ^ ((st << 5) & 0xFFFFFFFF)) & 0xFFFFFFFF
        self.st = st
        return st


def stream(seed: int, rounds: int):
    """Yield (round_index, [(op_name, (d1, d2, d3)), ...]) for every round."""
    total = sum(w for _, w in WEIGHTS)
    cum, acc = [], 0
    for _, w in WEIGHTS:
        acc += w
        cum.append(acc)

    def pick(x):
        v = x % total
        for i, c in enumerate(cum):
            if v < c:
                return WEIGHTS[i][0]
        return WEIGHTS[-1][0]

    p = Prng(seed)
    for r in range(1, rounds + 1):
        nlive = 3 + (p.rnd() % 4)
        chain = []
        for s in range(SLOTS):
            d0, d1, d2, d3 = p.rnd(), p.rnd(), p.rnd(), p.rnd()
            if s < nlive:
                chain.append((pick(d0), (d1, d2, d3)))
        yield r, chain


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--only")
    ap.add_argument("--skip")
    ap.add_argument("--census-file")
    args = ap.parse_args()

    if args.round:
        for r, chain in stream(args.seed, args.round):
            if r == args.round:
                print("round %d: %d ops" % (r, len(chain)))
                for name, (a, b, c) in chain:
                    print("   %-12s a=%d b=%d c=%d" % (name, a, b, c))
        return

    only = set(args.only.split(",")) if args.only else None
    skip = set(args.skip.split(",")) if args.skip else None
    counts, executed = {}, 0
    for _, chain in stream(args.seed, args.rounds):
        for name, _ in chain:
            if only and name not in only:
                continue
            if skip and name in skip:
                continue
            counts[name] = counts.get(name, 0) + 1
            executed += 1

    if args.census_file:
        page = {}
        for line in open(args.census_file):
            m = re.match(r"census&op=([A-Za-z0-9-]+)&n=(\d+)&e=(\d+)", line.strip())
            if m:
                page[m.group(1)] = int(m.group(2))
        names = sorted(set(page) | set(counts))
        bad = [(n, counts.get(n, 0), page.get(n, -1)) for n in names if counts.get(n, 0) != page.get(n, -1)]
        for n, a, b in bad:
            print("MISMATCH %-12s model=%d page=%d" % (n, a, b))
        print("census: %d/%d ops match, model total %d, page total %d"
              % (len(names) - len(bad), len(names), executed, sum(page.values())))
        sys.exit(1 if bad else 0)

    for name, _ in WEIGHTS:
        if counts.get(name):
            print("%-12s %d" % (name, counts[name]))
    print("total executed %d in %d rounds" % (executed, args.rounds))


if __name__ == "__main__":
    main()
