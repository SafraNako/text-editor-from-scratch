"""The terminal: raw mode, the alternate screen, the window size (and SIGWINCH when it changes), reading bytes with a timeout, and writing a frame. Everything the terminal was
in before is put back when the editor leaves, even if it crashes."""
from __future__ import annotations

import fcntl
import os
import select
import signal
import struct
import sys
import termios

ENTER = "\x1b[?1049h\x1b[?2004h\x1b[2J\x1b[H"
LEAVE = "\x1b[0m\x1b[?2004l\x1b[?25h\x1b[0 q\x1b[?1049l"


class Terminal:
    def __init__(self, fd_in=None, fd_out=None):
        self.fd_in = sys.stdin.fileno() if fd_in is None else fd_in
        self.fd_out = sys.stdout.fileno() if fd_out is None else fd_out
        self.saved = None
        self.wake_r = self.wake_w = None
        self.old_winch = None
        self.old_term = {}
        self.resized = False
        self.active = False

    def __enter__(self):
        if not (os.isatty(self.fd_in) and os.isatty(self.fd_out)):
            raise OSError("not a terminal")
        self.saved = termios.tcgetattr(self.fd_in)
        raw = termios.tcgetattr(self.fd_in)
        raw[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON | termios.INLCR | termios.IGNCR)
        raw[1] &= ~termios.OPOST
        raw[2] |= termios.CS8
        raw[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
        raw[6][termios.VMIN] = 1
        raw[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd_in, termios.TCSAFLUSH, raw)
        self.wake_r, self.wake_w = os.pipe()
        os.set_blocking(self.wake_w, False)
        self.old_winch = signal.signal(signal.SIGWINCH, self._on_winch)
        self.old_term = {}
        for sig in (signal.SIGTERM, signal.SIGHUP):               # leave through the normal exit, so that the terminal is put back
            try:
                self.old_term[sig] = signal.signal(sig, self._on_term)
            except ValueError:                                     # (not in the main thread)
                pass
        self.active = True
        self.write(ENTER)
        return self

    def __exit__(self, *exc):
        self.restore()
        return False

    def restore(self):
        if not self.active:
            return
        self.active = False
        try:
            self.write(LEAVE)
        except OSError:
            pass
        if self.saved is not None:
            termios.tcsetattr(self.fd_in, termios.TCSAFLUSH, self.saved)
        if self.old_winch is not None:
            signal.signal(signal.SIGWINCH, self.old_winch)
        for sig, old in self.old_term.items():
            signal.signal(sig, old)
        for fd in (self.wake_r, self.wake_w):
            if fd is not None:
                os.close(fd)
        self.wake_r = self.wake_w = None

    def _on_term(self, signum, frame):
        raise SystemExit(128 + signum)

    def _on_winch(self, signum, frame):
        self.resized = True
        try:
            os.write(self.wake_w, b"x")
        except OSError:
            pass

    def size(self):
        """(rows, columns) of the window."""
        try:
            data = fcntl.ioctl(self.fd_out, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
            rows, cols = struct.unpack("HHHH", data)[:2]
            if rows and cols:
                return rows, cols
        except OSError:
            pass
        return int(os.environ.get("LINES", 24)), int(os.environ.get("COLUMNS", 80))

    def read(self, timeout=None):
        """Bytes typed (up to what is available); b"" on a timeout; None when the window was resized."""
        r, _, _ = select.select([self.fd_in, self.wake_r], [], [], timeout)
        if not r:
            return b""
        if self.wake_r in r:
            try:
                os.read(self.wake_r, 64)
            except OSError:
                pass
            if self.fd_in not in r:
                return None
        try:
            data = os.read(self.fd_in, 4096)
        except OSError:
            return None
        if not data:
            raise EOFError("the terminal was closed")
        return data

    def write(self, text):
        data = text.encode("utf-8", "surrogateescape") if isinstance(text, str) else text
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd_out, view)
            except BlockingIOError:
                select.select([], [self.fd_out], [], 1.0)
                continue
            view = view[n:]
