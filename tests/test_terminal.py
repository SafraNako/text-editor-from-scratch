"""The real program in a real pseudo-terminal, drawn by pyte (an independent terminal emulator): raw mode, the escape sequences it writes, the keys it reads (cursor keys, a
lone <Esc>, pasted text), window resizes, signals, and the terminal being put back."""
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time

import pyte
import pytest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")


class Session:
    """``ked`` running in a pty of a given size, with pyte keeping the screen."""

    def __init__(self, args, rows=10, cols=40, env=None, cwd=None):
        self.rows, self.cols = rows, cols
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        e = dict(os.environ, TERM="xterm-256color", PYTHONPATH=SRC)
        e.update(env or {})
        self.proc = subprocess.Popen([sys.executable, "-m", "kendi_editor"] + list(args), stdin=slave, stdout=slave, stderr=slave, env=e, close_fds=True, start_new_session=True, cwd=cwd)
        os.close(slave)
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.raw = b""

    def pump(self, seconds=0.1):
        end = time.time() + seconds
        while True:
            left = end - time.time()
            r, _, _ = select.select([self.master], [], [], max(left, 0))
            if not r:
                return
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            self.raw += data
            self.stream.feed(data)

    def type(self, data):
        os.write(self.master, data if isinstance(data, bytes) else data.encode())

    def lines(self):
        return [line.rstrip() for line in self.screen.display]

    def status(self):
        return self.lines()[self.rows - 2]

    def message(self):
        return self.lines()[self.rows - 1]

    def cursor(self):
        return (self.screen.cursor.y, self.screen.cursor.x)

    def wait(self, condition, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.05)
            if condition():
                return True
        self.pump(0.1)
        return condition()

    def wait_text(self, text, timeout=8.0):
        return self.wait(lambda: any(text in line for line in self.lines()), timeout)

    def resize(self, rows, cols):
        self.rows, self.cols = rows, cols
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.screen.resize(rows, cols)
        self.proc.send_signal(signal.SIGWINCH)

    def finish(self, timeout=8.0):
        end = time.time() + timeout
        while self.proc.poll() is None and time.time() < end:
            self.pump(0.05)
        self.pump(0.2)
        return self.proc.poll()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        try:
            os.close(self.master)
        except OSError:
            pass


@pytest.fixture
def session():
    made = []

    def start(args, **kw):
        s = Session(args, **kw)
        made.append(s)
        return s
    yield start
    for s in made:
        s.close()


@pytest.fixture
def sample(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("hello world\nsecond line\n\tTabbed\nthird\n", encoding="utf-8")
    return p


def test_it_draws_the_file_and_a_status_line(session, sample):
    s = session(["sample.txt"], cwd=str(sample.parent))
    assert s.wait_text("NORMAL")
    lines = s.lines()
    assert lines[:4] == ["hello world", "second line", "        Tabbed", "third"]
    assert lines[4] == "~" and s.status().startswith(" NORMAL ") and s.status().endswith("1,1  All")
    assert s.message() == '"sample.txt" 4L, 38B' and s.cursor() == (0, 0)


def test_keys_move_and_edit(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.type("jwx")
    assert s.wait(lambda: s.lines()[1] == "second ine")
    assert s.cursor() == (1, 7) and "2,8" in s.status()
    s.type("G$")
    assert s.wait(lambda: s.cursor() == (3, 4))


def test_cursor_keys(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    for keys, where in [(b"\x1b[B", (1, 0)), (b"\x1b[C", (1, 1)), (b"\x1b[B", (2, 7)), (b"\x1b[A", (1, 1)), (b"\x1b[D", (1, 0)), (b"\x1b[F", (1, 10)), (b"\x1b[H", (1, 0)),
                        (b"\x1bOB", (2, 7)), (b"\x1bOA", (1, 0)), (b"\x1b[1;5C", (1, 1))]:
        s.type(keys)
        assert s.wait(lambda: s.cursor() == where), (keys, s.cursor())


def test_insert_and_save_and_quit(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.type("ggOtitle\x1b")
    assert s.wait(lambda: s.lines()[0] == "title" and " NORMAL " in s.status())       # a lone <Esc> is an <Esc> once nothing follows it
    assert "[+]" in s.status()
    s.type(":wq\r")
    assert s.finish() == 0
    assert sample.read_text() == "title\nhello world\nsecond line\n\tTabbed\nthird\n"


def test_a_lone_escape_is_not_taken_for_the_start_of_a_sequence(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.type("i")
    assert s.wait_text("INSERT")
    s.type("\x1b")
    assert s.wait(lambda: " NORMAL " in s.status())              # nothing follows the <Esc>: it is an <Esc>
    s.type("\x1b[99zix")                                          # an escape sequence that means nothing is swallowed whole
    assert s.wait(lambda: s.lines()[0].startswith("xhello"))


def test_bracketed_paste_is_inserted_as_it_is(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.type("A\x1b[200~ one\n  two\tthree\x1b[201~")
    assert s.wait(lambda: s.lines()[1] == "  two   three")
    s.type("\x1b:wq\r")
    assert s.finish() == 0
    assert sample.read_text().startswith("hello world one\n  two\tthree\nsecond line\n")


def test_a_window_resize_redraws(session, tmp_path):
    p = tmp_path / "long.txt"
    p.write_text("x" * 60 + "\nshort\n")
    s = session([str(p)], rows=8, cols=30)
    assert s.wait_text("NORMAL")
    assert s.lines()[0] == "x" * 30 and s.lines()[1] == "x" * 30 and s.lines()[2] == "short"
    s.resize(8, 50)
    assert s.wait(lambda: s.lines()[0] == "x" * 50 and s.lines()[1] == "x" * 10 and s.lines()[2] == "short")
    assert s.status().startswith(" NORMAL ") and s.status().endswith("1,1  All")
    s.resize(5, 20)
    assert s.wait(lambda: len(s.lines()) == 5 and s.status().startswith(" NORMAL"))


def test_the_terminal_is_put_back(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    raw_attrs = termios.tcgetattr(s.master)
    assert not raw_attrs[3] & termios.ECHO and not raw_attrs[3] & termios.ICANON and not raw_attrs[3] & termios.ISIG and not raw_attrs[0] & termios.IXON
    assert b"\x1b[?1049h" in s.raw
    s.type(":q\r")
    assert s.finish() == 0
    after = termios.tcgetattr(s.master)
    assert after[3] & termios.ECHO and after[3] & termios.ICANON and after[3] & termios.ISIG and after[0] & termios.ICRNL and after[1] & termios.OPOST
    assert b"\x1b[?1049l" in s.raw and b"\x1b[?25h" in s.raw


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_the_terminal_is_put_back_when_the_process_is_terminated(session, sample, sig):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.proc.send_signal(sig)
    assert s.finish() == 128 + sig or s.proc.returncode == 128 + sig
    after = termios.tcgetattr(s.master)
    assert after[3] & termios.ECHO and after[3] & termios.ICANON
    assert b"\x1b[?1049l" in s.raw


def test_ctrl_c_and_ctrl_s_are_keys_not_signals(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.type("i\x03")                                              # Ctrl-C leaves insert mode
    assert s.wait(lambda: " NORMAL " in s.status())
    s.type("\x13\x11jx")                                         # Ctrl-S and Ctrl-Q do not freeze the terminal
    assert s.wait(lambda: s.lines()[1] == "econd line")
    assert s.proc.poll() is None


def test_unicode_and_wide_characters(session, tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("héllo ∑ 日本語 x\nsecond\n", encoding="utf-8")
    s = session([str(p)])
    assert s.wait_text("NORMAL")
    assert s.lines()[0] == "héllo ∑ 日本語 x"
    s.type("fx")
    assert s.wait(lambda: s.cursor() == (0, 15))
    s.type("A日\x1b:wq\r")
    assert s.finish() == 0
    assert p.read_text(encoding="utf-8") == "héllo ∑ 日本語 x日\nsecond\n"


def test_line_number_and_start_options(session, sample):
    s = session(["+3", "-c", "set nu", str(sample)])
    assert s.wait_text("NORMAL")
    assert s.lines()[:4] == ["  1 hello world", "  2 second line", "  3         Tabbed", "  4 third"]
    assert s.cursor() == (2, 12)


def test_a_new_file_is_created(session, tmp_path):
    p = tmp_path / "brand-new.txt"
    s = session([str(p)])
    assert s.wait_text("[New]")
    s.type("ihello\x1b:wq\r")
    assert s.finish() == 0
    assert p.read_text() == "hello\n"


def test_a_big_file_opens_quickly(session, tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("".join("line number %d with some text in it\n" % i for i in range(300000)))
    started = time.time()
    s = session([str(p)], rows=20, cols=60)
    assert s.wait_text("line number 0 ")
    assert time.time() - started < 8
    s.type("G")
    assert s.wait_text("line number 299999")
    s.type("/number 1234\r")
    assert s.wait_text("line number 1234 ")


def test_dot_dot_and_undo_through_the_terminal(session, sample):
    s = session([str(sample)])
    assert s.wait_text("NORMAL")
    s.type("dd.u")
    assert s.wait(lambda: s.lines()[0] == "second line")
    s.type("\x12")
    assert s.wait(lambda: s.lines()[0] == "\tTabbed".replace("\t", "        "))


def run_cli(args, stdin=None, input=None, env=None):
    e = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run([sys.executable, "-m", "kendi_editor"] + list(args), stdin=stdin, input=input, capture_output=True, text=True, env=e, timeout=30)


def test_command_line_flags(tmp_path):
    r = run_cli(["--version"])
    assert r.returncode == 0 and r.stdout.startswith("ked 0.1")
    r = run_cli(["-h"])
    assert r.returncode == 0 and r.stdout.startswith("usage: ked")
    r = run_cli(["--bogus"])
    assert r.returncode == 2 and "unknown option" in r.stderr
    r = run_cli(["a", "b"])
    assert r.returncode == 2 and "only one file" in r.stderr


def test_it_refuses_to_run_without_a_terminal(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x\n")
    r = run_cli([str(p)], input="")
    assert r.returncode == 1 and "must be a terminal" in r.stderr and "-s" in r.stderr


def test_script_mode_types_keys_from_a_file_without_a_terminal(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("one two\nthree\n")
    script = tmp_path / "keys"
    script.write_bytes(b"wcwXXX\x1bjddgg:wq\r")
    r = run_cli(["-s", str(script), str(p)])
    assert r.returncode == 0 and p.read_text() == "one XXX\n"
    script.write_bytes(b"ix\x1b")
    r = run_cli(["-s", str(script), "-c", "set sw=4", "-c", "%s/one/ONE/", str(p)])
    assert r.returncode == 0 and p.read_text() == "one XXX\n"          # nothing was written: the script did not :w
