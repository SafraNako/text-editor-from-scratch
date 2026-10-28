"""The editor without a terminal: a buffer, a cursor, modes, registers, undo, options and messages. Keys go in one at a time (``Editor.feed``); what is shown is read back with
``kendi_editor.screen``. Commands are written as generators that ask for the next key with ``yield``, so a command that needs several keys (``d2fx``, ``"ayy``, ``ciw``) is
just straight-line code."""
from __future__ import annotations

import os
import stat
import tempfile

from . import text as T
from .errors import CmdError
from .ex import ExMixin
from .insert import InsertMixin
from .normal import NormalMixin
from .editor_types import Register, RowTracker  # noqa: F401
from .search import SearchMixin

ESC = "\x1b"
DEFAULT_OPTIONS = {"tabstop": 8, "shiftwidth": 8, "expandtab": False, "ignorecase": False, "smartcase": False, "wrapscan": True, "number": False, "relativenumber": False,
                   "hlsearch": False, "startofline": True, "autoindent": False, "wrap": True, "list": False, "joinspaces": True}
OPTION_ALIASES = {"ts": "tabstop", "sw": "shiftwidth", "et": "expandtab", "ic": "ignorecase", "scs": "smartcase", "ws": "wrapscan", "nu": "number", "rnu": "relativenumber",
                  "hls": "hlsearch", "sol": "startofline", "ai": "autoindent", "js": "joinspaces"}


class UndoEntry:
    """One undo step: the changes made to the list of lines, each as (row, lines taken out, lines put in), the cursor before the first one, and the first row touched."""
    __slots__ = ("ops", "cursor", "empty_before", "empty_after", "ctop")

    def __init__(self, ops, cursor, empty_before, empty_after, ctop):
        self.ops, self.cursor, self.empty_before, self.empty_after, self.ctop = ops, cursor, empty_before, empty_after, ctop


class Editor(NormalMixin, InsertMixin, ExMixin, SearchMixin):
    def __init__(self, text="", filename=None, size=(24, 80)):
        self.filename = filename
        self.lines = [""]
        self.no_lines = True                       # the buffer holds no line at all (a new or emptied buffer): written as an empty file
        self.row = self.col = 0
        self.curswant = 0
        self.mode = "n"                            # n normal, i insert, v visual, V visual-line, c command line (shown), r replace
        self.vstart = None
        self.last_visual = None
        self.opts = dict(DEFAULT_OPTIONS)
        self.regs = {}
        self.msg = ""
        self.msg_error = False
        self.cmdline = None                        # the command line being typed: (prefix, text)
        self.undo_list = []
        self.undo_pos = 0
        self.ops = []
        self.group_empty = True
        self.touched = False
        self.touch_min = 0
        self.first_cursor = (0, 0)
        self.modified = False
        self.fileformat = "unix"
        self.noeol = False
        self.readonly = False
        self.mtime = None
        self.is_new = False                        # the file does not exist yet (set when a missing file is opened)
        self.size = size
        self.top = 0
        self.quit = False
        self.redo = None
        self.replaying = False
        self.last_search = None                    # (pattern, forward)
        self.last_find = None                      # (char, 'f'|'F'|'t'|'T')
        self.last_sub = None
        self.search_wrapped = False
        self.rec = []
        self.ins = None
        self.pending = ""                          # keys typed of an unfinished command, for display
        self.marks = {}                            # a-z -> [row, col], moved along when lines are inserted or deleted
        self.trackers = []                         # rows that :g and :normal go back to
        self._snap = None
        self.hl_off = False
        self.nested = 0                            # inside :normal / :g: commands do not make undo steps of their own
        self.global_busy = 0
        self.global_need_beginline = False
        if text:
            self.load_text(text)
        self._gen = self._main()
        next(self._gen)

    # --- loading and saving -----------------------------------------------------------------------------------------------------------------------
    def load_text(self, text):
        crlf = text.count("\r\n")
        if crlf and crlf == text.count("\n"):
            self.fileformat = "dos"
            text = text.replace("\r\n", "\n")
        self.noeol = bool(text) and not text.endswith("\n")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        self.lines = lines or [""]
        self.no_lines = not lines
        self.row = 0
        self.col = self.first_nonblank_col(0)               # vim starts on the first non-blank of the first line
        self.set_curswant()
        self.undo_list, self.undo_pos = [], 0
        self.modified = False

    @classmethod
    def open(cls, path, size=(24, 80)):
        ed = cls("", path, size)
        try:
            if os.path.isdir(path):
                ed.msg, ed.msg_error = '"%s" is a directory' % path, True
                return ed
            with open(path, "rb") as f:
                data = f.read()
            ed.is_new = False
            ed.mtime = os.stat(path).st_mtime_ns
            ed.readonly = not os.access(path, os.W_OK)
            ed.load_text(data.decode("utf-8", "surrogateescape"))
            nbytes = len(data)
            ed.msg = '"%s"%s %dL, %dB' % (path, " [noeol]" if ed.noeol else "", 0 if ed.no_lines else len(ed.lines), nbytes)
            if ed.fileformat == "dos":
                ed.msg = ed.msg.replace(" %dL" % len(ed.lines), "[dos] %dL" % len(ed.lines), 1)
        except FileNotFoundError:
            ed.is_new = True
            ed.msg = '"%s" [New]' % path
        except PermissionError:
            ed.msg, ed.msg_error = '"%s" [Permission Denied]' % path, True
        return ed

    def text(self):
        """The buffer as it would be written."""
        if self.no_lines:
            return ""
        eol = "\r\n" if self.fileformat == "dos" else "\n"
        return eol.join(self.lines) + eol

    def write(self, path=None, force=False, lines=None):
        """Write the buffer (or some of its lines) to a file; returns the message to show. A file that changed on disk since it was read is not overwritten without ``!``."""
        target = path or self.filename
        if target is None:
            raise CmdError("E32: No file name")
        whole = lines is None
        if whole and path is None and self.readonly and not force:
            raise CmdError("E45: 'readonly' option is set (add ! to override)")
        data_text = self.text() if whole else (("\r\n" if self.fileformat == "dos" else "\n").join(lines) + ("\r\n" if self.fileformat == "dos" else "\n"))
        data = data_text.encode("utf-8", "surrogateescape")
        same = self.filename is not None and os.path.abspath(target) == os.path.abspath(self.filename)
        if same and self.mtime is not None and not force:
            try:
                if os.stat(target).st_mtime_ns != self.mtime:
                    raise CmdError("WARNING: The file has been changed since reading it!!! Use ! to write anyway (E505 style)")
            except FileNotFoundError:
                pass
        elif not same and os.path.exists(target) and not force and path is not None:
            raise CmdError("E13: File exists (add ! to override)")
        real = os.path.realpath(target)
        directory = os.path.dirname(real) or "."
        try:
            mode = stat.S_IMODE(os.stat(real).st_mode)
        except FileNotFoundError:
            mode = 0o666 & ~_umask()
        try:
            fd, tmp = tempfile.mkstemp(prefix=".ked-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.chmod(tmp, mode)
                os.replace(tmp, real)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise CmdError('E212: Can\'t open file for writing: %s' % (exc.strerror or exc)) from None
        if whole and (same or self.filename is None):
            if self.filename is None:
                self.filename = target
            self.modified = False
            self.is_new = False
            self.noeol = False
        if same or self.filename == target:
            self.mtime = os.stat(real).st_mtime_ns
        nl = (0 if (whole and self.no_lines) else (len(self.lines) if whole else len(lines)))
        return '"%s" %dL, %dB written' % (target, nl, len(data))

    # --- the main loop: a generator that is sent keys ---------------------------------------------------------------------------------------------
    def feed(self, key):
        """Give the editor one key (a character, or a name such as "<Up>")."""
        if not self.quit:
            self._gen.send(key)

    def feed_keys(self, keys):
        for k in keys:
            self.feed(k)

    def feed_paste(self, text):
        """Text pasted into the terminal (bracketed paste): in insert mode it is typed without auto-indent, anywhere else it is inserted before the cursor."""
        if self.quit or not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if self.mode in ("i", "r"):
            ai, self.opts["autoindent"] = self.opts["autoindent"], False
            try:
                for ch in text:
                    self.feed("\r" if ch == "\n" else ch)
            finally:
                self.opts["autoindent"] = ai
            return
        if self.mode == "n":
            ai, self.opts["autoindent"] = self.opts["autoindent"], False
            try:
                self.feed("i")
                for ch in text:
                    self.feed("\r" if ch == "\n" else ch)
                self.feed("\x1b")
            finally:
                self.opts["autoindent"] = ai

    def _main(self):
        while True:
            try:
                yield from self.normal_command()
            except CmdError as exc:
                self.abort_command(str(exc))

    def abort_command(self, message=""):
        """A command failed or was cancelled: forget what was pending (an insert that was running is ended, a visual selection stays)."""
        if message:
            self.msg, self.msg_error = message, True
        self.cmdline = None
        self.pending = ""
        if self.ins is not None:
            self.ins = None
        if self.mode in ("i", "r", "c"):
            self.mode = "n"
        self.check_cursor()

    # --- undo ------------------------------------------------------------------------------------------------------------------------------------
    def begin_group(self):
        """Start recording the changes of one command (one undo step)."""
        self.touched = False
        self.ops = []
        self.group_empty = self.no_lines

    def end_group(self, _token=None):
        if not self.touched:
            return
        entry = UndoEntry(self.ops, self.first_cursor, self.group_empty, self.no_lines, self.touch_min)
        del self.undo_list[self.undo_pos:]
        self.undo_list.append(entry)
        self.undo_pos = len(self.undo_list)
        self.touched = False
        self.ops = []

    def undo(self, count=1):
        done = 0
        while done < count:
            if self.undo_pos == 0:
                if done == 0:
                    self.msg = "Already at oldest change"
                return
            e = self.undo_list[self.undo_pos - 1]
            for r, removed, inserted in reversed(e.ops):
                self.lines[r:r + len(inserted)] = removed
            self.no_lines = e.empty_before
            self.undo_pos -= 1
            self.modified = True
            self._undo_cursor(e)
            done += 1
        self.msg = ""

    def redo_change(self, count=1):
        done = 0
        while done < count:
            if self.undo_pos >= len(self.undo_list):
                if done == 0:
                    self.msg = "Already at newest change"
                return
            e = self.undo_list[self.undo_pos]
            for r, removed, inserted in e.ops:
                self.lines[r:r + len(removed)] = inserted
            self.no_lines = e.empty_after
            self.undo_pos += 1
            self.modified = True
            self._undo_cursor(e)
            done += 1
        self.msg = ""

    def _undo_cursor(self, e):
        """Where the cursor goes after an undo or redo: the first line the change touched (one line up if that is just below where the cursor was, which is what puts it back
        after "o"); on the column it had before the change if that is the same line, else the first non-blank."""
        row = e.ctop
        if e.cursor[0] + 1 == row and row > 0:
            row -= 1
        if row >= len(self.lines):
            self.row, self.col = len(self.lines) - 1, 0
        else:
            self.row = row
            if e.cursor[0] == row:
                self.col = e.cursor[1]
            else:
                self.col = self.first_nonblank_col(row)
        self.mode = "n"
        self.check_cursor()
        self.set_curswant()

    # --- changing the buffer ---------------------------------------------------------------------------------------------------------------------
    def touch(self, r):
        """A line is about to change: remember the first one and where the cursor was, for placing the cursor after an undo."""
        if not self.touched:
            self.first_cursor = (self.row, self.col)
            self.touch_min = r
        elif r < self.touch_min:
            self.touch_min = r
        self.touched = self.modified = True

    def set_line(self, r, s):
        self.touch(r)
        ops = self.ops
        last = ops[-1] if ops else None
        if last is not None and last[0] == r and len(last[1]) == 1 and len(last[2]) == 1:
            ops[-1] = (r, last[1], [s])                      # the same line again (typing): the first old text is all that is needed
        else:
            ops.append((r, [self.lines[r]], [s]))
        self.lines[r] = s
        self.no_lines = False

    def ins_lines(self, r, new):
        self.touch(r)
        new = list(new)
        self.ops.append((r, [], new))
        self.lines[r:r] = new
        self.no_lines = False
        k = len(new)
        for m in self.marks.values():
            if m[0] >= r:
                m[0] += k
        for t in self.trackers:
            t.inserted(r, k)

    def del_lines(self, r, n):
        self.touch(r)
        removed = self.lines[r:r + n]
        del self.lines[r:r + n]
        if not self.lines:
            self.lines = [""]
            self.no_lines = True
            self.ops.append((r, removed, [""]))
        else:
            self.ops.append((r, removed, []))
        for name in [name for name, m in self.marks.items() if r <= m[0] < r + n]:
            del self.marks[name]
        for m in self.marks.values():
            if m[0] >= r + n:
                m[0] -= n
        for t in self.trackers:
            t.deleted(r, len(removed))

    def replace_lines(self, a, b, new):
        """Replace the lines a..b by ``new`` without the buffer ever being empty in between (vim's :sort, :m)."""
        self.ins_lines(b + 1, list(new))
        self.del_lines(a, b - a + 1)

    # --- marks and tracked rows ------------------------------------------------------------------------------------------------------------------
    def set_mark(self, name, row, col=0):
        if not (len(name) == 1 and name.isalpha() and name.islower()):
            raise CmdError("E191: Argument must be a letter or forward/backward quote")
        self.marks[name] = [row, col]

    def get_mark(self, name):
        if name in ("<", ">") and self.last_visual:
            a, b = sorted((self.last_visual[1], self.last_visual[2]))
            return a if name == "<" else b
        m = self.marks.get(name)
        if m is None:
            raise CmdError("E20: Mark not set")
        return (m[0], m[1])

    def track(self, rows):
        tracker = RowTracker(rows)
        self.trackers.append(tracker)
        return tracker

    def untrack(self, tracker):
        self.trackers.remove(tracker)

    # --- cursor ----------------------------------------------------------------------------------------------------------------------------------
    @property
    def line(self):
        return self.lines[self.row]

    def check_cursor(self):
        """Keep the cursor inside the buffer, and (except in insert mode) on a character."""
        self.row = max(0, min(self.row, len(self.lines) - 1))
        n = len(self.lines[self.row])
        limit = n if self.mode in ("i", "r", "v", "V") else max(n - 1, 0)
        self.col = max(0, min(self.col, limit))

    def set_curswant(self):
        """Remember the screen column the cursor is at, for up and down motions."""
        line = self.lines[self.row]
        ts = self.opts["tabstop"]
        if self.mode in ("i", "r"):
            self.curswant = T.vcol_start(line, self.col, ts)
        else:
            self.curswant = T.vcol_end(line, self.col, ts)

    def col_for_want(self, row, want=None):
        """The column in ``row`` that the wanted screen column falls on (the last character if the line is shorter)."""
        line = self.lines[row]
        want = self.curswant if want is None else want
        if not line:
            return 0
        one_more = self.mode in ("i", "r", "v", "V")
        if want >= T.MAXCOL:
            return len(line) if one_more else len(line) - 1
        c = T.col_at_vcol(line, want, self.opts["tabstop"])
        return min(c, len(line)) if one_more else min(c, len(line) - 1)

    def first_nonblank_col(self, row):
        line = self.lines[row]
        c = T.first_nonblank(line)
        return min(c, max(len(line) - 1, 0))

    # --- registers -------------------------------------------------------------------------------------------------------------------------------
    def set_register(self, name, reg, deleting=False, small=False):
        """Store yanked or deleted text the way vim does: the unnamed register points at the latest, "0 holds the last yank, "1-"9 the last big deletes, "- the small ones."""
        if name == "_":
            return
        copy = Register(list(reg.lines), reg.linewise)
        if name and name.isalpha():
            if name.isupper():
                old = self.regs.get(name.lower())
                if old is not None:
                    if old.linewise or copy.linewise:
                        merged = old.lines + copy.lines
                        copy = Register(merged, True)
                    else:
                        merged = old.lines[:-1] + [old.lines[-1] + copy.lines[0]] + copy.lines[1:]
                        copy = Register(merged, False)
                name = name.lower()
            self.regs[name] = copy
            self.regs['"'] = copy
            if deleting and (copy.linewise or len(copy.lines) > 1):
                self._shift_numbered(copy)
            return
        if deleting:
            if copy.linewise or len(copy.lines) > 1:
                self._shift_numbered(copy)
            else:
                self.regs["-"] = copy
        else:
            self.regs["0"] = copy
        self.regs['"'] = copy

    def _shift_numbered(self, reg):
        for i in range(9, 1, -1):
            if str(i - 1) in self.regs:
                self.regs[str(i)] = self.regs[str(i - 1)]
        self.regs["1"] = reg
        self.regs['"'] = reg

    def get_register(self, name):
        if name in (None, '"'):
            name = '"'
        reg = self.regs.get(name.lower() if name.isalpha() else name)
        if reg is None:
            raise CmdError("E353: Nothing in register %s" % ('"' if name == '"' else name))
        return reg

    # --- messages and the command line -----------------------------------------------------------------------------------------------------------
    def say(self, text, error=False):
        self.msg, self.msg_error = text, error

    def read_cmdline(self, prefix):
        """Read a line of text typed after ':' '/' or '?' (a generator: ``text = yield from self.read_cmdline(':')``); Esc cancels."""
        buf = []
        self.cmdline = (prefix, "")
        old_mode = self.mode
        self.mode = "c"
        while True:
            k = yield
            self.rec.append(k)
            if k in ("\r", "\n"):
                break
            if k in (ESC, "\x03"):
                self.cmdline = None
                self.mode = old_mode
                raise CmdError("")
            if k in ("\x7f", "\x08"):
                if not buf:
                    self.cmdline = None
                    self.mode = old_mode
                    raise CmdError("")
                buf.pop()
            elif k == "\x15":
                buf = []
            elif k == "\x17":
                while buf and buf[-1] == " ":
                    buf.pop()
                while buf and buf[-1] != " ":
                    buf.pop()
            elif k == "\x16":
                k = yield
                buf.append(k)
            elif len(k) == 1:
                buf.append(k)
            self.cmdline = (prefix, "".join(buf))
        self.cmdline = None
        self.mode = old_mode
        return "".join(buf)


def _umask():
    m = os.umask(0)
    os.umask(m)
    return m
