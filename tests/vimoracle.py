"""Real vim as the oracle: the same keystrokes are given to this editor (headless) and to vim running in a pseudo-terminal, and the files they write are compared."""
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from kendi_editor import Editor

VIM = shutil.which("vim")
VIM_OPTIONS = ["-u", "NONE", "-N", "-n", "-i", "NONE", "--cmd", "set backspace=indent,eol,start cmdheight=30 ttimeout ttimeoutlen=5"]
MARKER = "i@\x1b"                                   # shows where the cursor ended up
FINISH = ":wq\r"


def run_vim(text, keys, extra_cmds=(), timeout=15):
    """The bytes vim writes after the keys are typed to it in a pseudo-terminal (None if vim hung). The keys are typed, not read from a script file (``-s``): a script is
    one undo step to vim; and a pause follows every <Esc> so that vim does not take the next characters for a key code."""
    d = tempfile.mkdtemp(prefix="vimoracle-")
    try:
        path = os.path.join(d, "f.txt")
        with open(path, "wb") as f:
            f.write(text.encode("utf-8", "surrogateescape"))
        master, slave = pty.openpty()
        env = dict(os.environ, TERM="dumb", LINES="60", COLUMNS="80")
        cmd = [VIM] + VIM_OPTIONS
        for c in extra_cmds:
            cmd += ["--cmd", c]
        cmd.append(path)
        p = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
        os.close(slave)
        start = time.time()
        # wait for vim to draw its first screen, then type
        while time.time() - start < timeout:
            r, _, _ = select.select([master], [], [], 0.05)
            if r:
                try:
                    os.read(master, 65536)
                except OSError:
                    break
                break
        time.sleep(0.03)
        data = (keys + MARKER + FINISH).encode("utf-8", "surrogateescape")
        pieces = []
        cur = b""
        for b in data:
            cur += bytes([b])
            if b == 0x1B:
                pieces.append(cur)
                cur = b""
        if cur:
            pieces.append(cur)
        try:
            for piece in pieces:
                os.write(master, piece)
                if piece.endswith(b"\x1b"):
                    time.sleep(0.02)
        except OSError:
            pass
        while p.poll() is None and time.time() - start < timeout:
            r, _, _ = select.select([master], [], [], 0.05)
            if r:
                try:
                    os.read(master, 65536)
                except OSError:
                    break
        hung = p.poll() is None
        if hung:
            p.kill()
            p.wait()
        os.close(master)
        if hung:
            return None
        with open(path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_ours(text, keys, options=(), size=(24, 80)):
    """The bytes this editor writes after the same keys."""
    d = tempfile.mkdtemp(prefix="edoracle-")
    try:
        path = os.path.join(d, "f.txt")
        with open(path, "wb") as f:
            f.write(text.encode("utf-8", "surrogateescape"))
        ed = Editor.open(path, size)
        for name, value in options:
            ed.opts[name] = value
        try:
            ed.feed_keys(list(keys + MARKER + FINISH))
        except Exception as exc:                                            # a bug in the editor: report it as a difference, with the traceback
            import traceback
            return ("CRASH: %s\n%s" % (exc, traceback.format_exc())).encode()
        with open(path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def compare(cases, workers=None, extra_cmds=(), options=()):
    """Run (text, keys) cases through both; returns the list of (text, keys, ours, vim) that differ."""
    workers = workers or min(8, (os.cpu_count() or 2))
    with ThreadPoolExecutor(workers) as pool:
        vims = list(pool.map(lambda c: run_vim(c[0], c[1], extra_cmds), cases))
    out = []
    for (text, keys), theirs in zip(cases, vims):
        ours = run_ours(text, keys, options)
        if theirs is None:
            continue
        if ours != theirs:
            out.append((text, keys, ours, theirs))
    return out


def show(keys):
    return keys.replace("\x1b", "<Esc>").replace("\r", "<CR>").replace("\x7f", "<BS>").replace("\t", "<Tab>").replace("\x12", "<C-R>").replace("\x16", "<C-V>")
