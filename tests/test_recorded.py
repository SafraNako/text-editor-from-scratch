"""The command table of test_vim_differential.py, replayed against what vim 9 did (recorded by record_vim.py): no vim needed. A '@' in the expected text marks the cursor."""
import json
import os

import pytest

from vimoracle import run_ours, show

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorded_vim.json")
with open(PATH, encoding="utf-8") as f:
    RECORDED = json.load(f)
CASES = RECORDED["cases"]


@pytest.mark.parametrize("group", sorted({c["group"] for c in CASES}))
def test_recorded_vim_behaviour(group):
    wrong = []
    cases = [c for c in CASES if c["group"] == group]
    for c in cases:
        ours = run_ours(c["text"], c["keys"]).decode("utf-8", "surrogateescape")
        if ours != c["vim"]:
            wrong.append((c, ours))
    assert len(wrong) <= len(cases) // 50, "%d of %d differ from what %s did, the first of them:\n%s" % (len(wrong), len(cases), RECORDED["vim"], "\n".join(
        "keys %r on %r\n    ours: %r\n    vim:  %r" % (show(c["keys"]), c["text"], o, c["vim"]) for c, o in wrong[:3]))
