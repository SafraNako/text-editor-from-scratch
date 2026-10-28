"""Record what vim does for the command table of test_vim_differential.py, into recorded_vim.json, so that the same expectations can be checked without vim
(test_recorded.py). Run it with real vim installed:  python tests/record_vim.py"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import vimoracle  # noqa: E402
from test_vim_differential import GROUPS  # noqa: E402


def main():
    cases = [(group, text, keys) for group in sorted(GROUPS) for text, keys in GROUPS[group]]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda c: vimoracle.run_vim(c[1], c[2]), cases))
    out = []
    version = os.popen("vim --version | head -1").read().strip()
    for (group, text, keys), vim in zip(cases, results):
        if vim is None:
            continue
        out.append({"group": group, "text": text, "keys": keys, "vim": vim.decode("utf-8", "surrogateescape")})
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorded_vim.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"vim": version, "cases": out}, f, ensure_ascii=False, indent=0)
    print("recorded %d cases from %s" % (len(out), version))


if __name__ == "__main__":
    main()
