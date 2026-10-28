"""ked against vim on the same jobs, run as batch jobs on a big file (no terminal needed): ``ked -s SCRIPT FILE`` against ``vim -es -c COMMAND FILE``. Run: python benchmarks/bench.py [lines]
Each job is run on a fresh copy of the file; the two results must be the same file."""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
LINES = int(sys.argv[1]) if len(sys.argv) > 1 else 100000

JOBS = [
    ("open and write", ":wq\r", ["wq"]),
    ("%s/line/LINE/g", ":%s/line/LINE/g\r:wq\r", ["%s/line/LINE/g", "wq"]),
    ("g/7/d  (every line with a 7)", ":g/7/d\r:wq\r", ["g/7/d", "wq"]),
    ("sort!", ":sort!\r:wq\r", ["sort!", "wq"]),
    ("%normal A;", ":%normal A;\r:wq\r", ["%normal A;", "wq"]),
    ("%s/\\(\\w\\+\\) \\(\\w\\+\\)/\\2 \\1/", ":%s/\\(\\w\\+\\) \\(\\w\\+\\)/\\2 \\1/\r:wq\r", ["%s/\\(\\w\\+\\) \\(\\w\\+\\)/\\2 \\1/", "wq"]),
    ("search, delete a line (/number 77777 then dd)", "/number 77777\rdd:wq\r", ["/number 77777", "normal dd", "wq"]),
    ("2000 times 'ddp' typed one after the other", "ddp" * 2000 + ":wq\r", None),
    ("1000 times 'cwXY' + '.' on lines", ("cwXY\x1bj" * 1000) + ":wq\r", None),
    ("%j  (join all lines into one)", ":%j\r:wq\r", ["%j", "wq"]),
]


def timed(cmd, env=None):
    start = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, env=env, timeout=600)
    return time.perf_counter() - start, r.returncode


def main():
    d = tempfile.mkdtemp()
    base = os.path.join(d, "base.txt")
    with open(base, "w") as f:
        f.write("".join("line number %d with some words in it\n" % i for i in range(LINES)))
    vim = shutil.which("vim")
    env = dict(os.environ, PYTHONPATH=SRC)
    print("%d lines, %.1f MB" % (LINES, os.path.getsize(base) / 1e6))
    print("| job | ked | vim | ratio |")
    print("|---|---|---|---|")
    for name, keys, ex in JOBS:
        a, b = os.path.join(d, "a.txt"), os.path.join(d, "b.txt")
        shutil.copy(base, a)
        script = os.path.join(d, "script")
        with open(script, "wb") as f:
            f.write(keys.encode())
        t_ked, rc = timed([sys.executable, "-m", "kendi_editor", "-s", script, a], env)
        if ex is None or vim is None:
            print("| %s | %.2f s | %s | %s |" % (name, t_ked, "-", "-"))
            continue
        shutil.copy(base, b)
        cmd = [vim, "-es", "-u", "NONE", "-N", "-n", "-i", "NONE"]
        for c in ex:
            cmd += ["-c", c]
        cmd.append(b)
        t_vim, _ = timed(cmd)
        same = open(a, "rb").read() == open(b, "rb").read()
        ratio = t_ked / t_vim
        print("| %s | %.2f s | %.2f s | %s%s |" % (name, t_ked, t_vim, ("%.1f" % ratio) + "x" if ratio < 10 else "%.0fx" % ratio, "" if same else " (results differ!)"))
    shutil.rmtree(d)


if __name__ == "__main__":
    main()
