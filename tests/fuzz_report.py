"""Look for differences from vim with random sessions, and shrink each to a few commands.  python tests/fuzz_report.py LEVEL FIRST_SEED COUNT [SHOWN] [min]
LEVEL is "motions" or "ops"; with "min" every session that differs is cut down, command by command, as far as the difference remains."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import fuzzgen  # noqa: E402
import vimoracle  # noqa: E402


def differs(text, parts):
    keys = "".join(parts)
    ours, theirs = vimoracle.run_ours(text, keys), vimoracle.run_vim(text, keys)
    return theirs is not None and ours != theirs


def main():
    level, first, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    shown = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    shrink = len(sys.argv) > 5 and sys.argv[5] == "min"
    cases, parts_of = [], []
    for seed in range(first, first + count):
        rng = random.Random(seed)
        text = fuzzgen.random_text(rng)
        g = fuzzgen.Gen2(seed * 31 + 7, level) if level != "motions" else fuzzgen.Gen(seed * 31 + 7, level)
        g.nlines = max(text.count("\n"), 1)
        parts = g.parts() if hasattr(g, "parts") else [g.session()]
        cases.append((text, "".join(parts)))
        parts_of.append(parts)
    bad = vimoracle.compare(cases)
    print("sessions %d, differing %d" % (count, len(bad)))
    for text, keys, ours, theirs in bad[:shown]:
        parts = parts_of[cases.index((text, keys))]
        if shrink:
            changed = True
            while changed:
                changed = False
                for i in range(len(parts)):
                    trial = parts[:i] + parts[i + 1:]
                    if trial and differs(text, trial):
                        parts, changed = trial, True
                        break
            keys = "".join(parts)
            ours, theirs = vimoracle.run_ours(text, keys), vimoracle.run_vim(text, keys)
        print("----- keys:", vimoracle.show(keys))
        print("text:", repr(text))
        print("ours:", ours)
        print("vim: ", theirs)


if __name__ == "__main__":
    main()
