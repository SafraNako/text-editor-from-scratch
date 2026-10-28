"""Insert mode and replace mode: the commands that start them (i a I A o O) and what typed keys do while they last."""
from __future__ import annotations

from . import text as T

ESC = "\x1b"
ARROWS = ("<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>")


class InsertState:
    def __init__(self, kind, count):
        self.kind = kind
        self.count = count
        self.keys = []                   # the keys typed in this insert, to be repeated by a count and by '.'
        self.start = None                # where the insert began (Ctrl-U and Ctrl-W stop there first)
        self.literal = False
        self.ai_row = None               # a line that holds only automatic indent
        self.replaced = []               # replace mode: the characters that were overwritten


class InsertMixin:
    ai_pending = False

    def start_insert(self, k, count):
        n = count or 1
        line = self.line
        if k == "a" and line:
            self.col = min(self.col + 1, len(line))
        elif k == "A":
            self.col = len(line)
        elif k == "I":
            self.col = T.first_nonblank(line)
        elif k in ("o", "O"):
            indent = line[:T.first_nonblank(line)] if self.opts["autoindent"] else ""
            at = self.row + 1 if k == "o" else self.row
            self.ins_lines(at, [indent])
            self.row, self.col = at, len(indent)
            self.ai_pending = bool(indent)
        else:
            self.ai_pending = False
        yield from self.insert_session(n, k)

    def insert_session(self, count, kind):
        self.mode = "i"
        self.pending = ""
        self.ins = InsertState(kind, count)
        self.ins.start = (self.row, self.col)
        if self.ai_pending:
            self.ins.ai_row = self.row
            self.ai_pending = False
        self.check_cursor()
        self.set_curswant()
        while True:
            k = yield from self.getkey()
            if k in (ESC, "\x03") and not self.ins.literal:
                break
            if k in ARROWS:
                self.cursor_key_in_insert(k)
                continue
            self.ins.keys.append(k)
            self.insert_key(k)
        self.finish_insert()

    def cursor_key_in_insert(self, k):
        """A cursor key ends the insert as far as undo and '.' are concerned: what is typed next starts a new change."""
        self.end_group(self._snap)
        self._snap = self.begin_group()
        line = self.line
        if k == "<Left>":
            self.col = max(self.col - 1, 0)
        elif k == "<Right>":
            self.col = min(self.col + 1, len(line))
        elif k == "<Home>":
            self.col = 0
        elif k == "<End>":
            self.col = len(line)
        else:
            want = self.curswant
            r = self.row + (1 if k == "<Down>" else -1)
            if 0 <= r < len(self.lines):
                self.row = r
                self.col = min(T.col_at_vcol(self.lines[r], want, self.opts["tabstop"]), len(self.lines[r]))
        self.set_curswant() if k not in ("<Up>", "<Down>") else None
        self.ins = type(self.ins)("i", 1)
        self.ins.start = (self.row, self.col)
        self.rec = ["i"]

    def finish_insert(self):
        ins = self.ins
        count = ins.count
        keys = list(ins.keys)
        if count > 1 and (keys or ins.kind in ("o", "O")):
            for _ in range(count - 1):
                if ins.kind in ("o", "O"):
                    self.insert_key("\r")
                for key in keys:
                    self.insert_key(key)
        self.clean_auto_indent()
        self.ins = None
        self.mode = "n"
        if self.col > 0:
            self.col -= 1
        self.check_cursor()
        self.set_curswant()

    def clean_auto_indent(self):
        ins = self.ins
        if ins is not None and ins.ai_row is not None and ins.ai_row < len(self.lines) and self.lines[ins.ai_row].strip(" \t") == "" and self.lines[ins.ai_row]:
            self.set_line(ins.ai_row, "")
            if self.row == ins.ai_row:
                self.col = 0
        if ins is not None:
            ins.ai_row = None

    # --- the keys of insert mode -----------------------------------------------------------------------------------------------------------------
    def insert_key(self, k):
        ins = self.ins
        if ins.literal:
            ins.literal = False
            if len(k) == 1:
                self.insert_text(k)
            return
        if k == "\x16":
            ins.literal = True
            return
        if k == "\r" or k == "\n":
            self.insert_newline()
        elif k in ("\x7f", "\x08"):
            self.backspace()
        elif k == "<Delete>":
            self.delete_forward()
        elif k == "\t":
            if self.opts["expandtab"]:
                v = T.vcol_start(self.line, self.col, self.opts["tabstop"])
                ts = self.opts["tabstop"]
                self.insert_text(" " * (ts - v % ts))
            else:
                self.insert_text("\t")
        elif k == "\x17":
            self.delete_word_before()
        elif k == "\x15":
            self.delete_line_before()
        elif k == "\x12":
            pass                                   # Ctrl-R {register}: the register name arrives as the next key (handled below)
        elif len(k) == 1 and (ord(k) >= 32 and k != "\x7f"):
            self.insert_text(k)
        # other control keys do nothing in this editor

    def insert_text(self, s):
        ins = self.ins
        if ins is not None:
            ins.ai_row = None
        line = self.line
        if ins is not None and ins.kind == "R":
            end = self.col + len(s)
            ins.replaced.append(line[self.col:end])
            self.set_line(self.row, line[:self.col] + s + line[end:])
            self.col += len(s)
        else:
            self.set_line(self.row, line[:self.col] + s + line[self.col:])
            self.col += len(s)
        self.set_curswant()

    def insert_newline(self):
        ins = self.ins
        line = self.line
        before, after = line[:self.col], line[self.col:]
        if ins is not None and ins.kind == "R":
            ins.replaced.append("\n")
        indent = ""
        if self.opts["autoindent"]:
            indent = line[:T.first_nonblank(line)]
            if ins is not None and ins.ai_row == self.row and before.strip(" \t") == "":
                before = ""                                      # nothing was typed after the automatic indent: it goes
            if ins is not None:
                ins.ai_row = None
            if after:
                after = after.lstrip(" \t")
        self.set_line(self.row, before)
        self.ins_lines(self.row + 1, [indent + after])
        self.row += 1
        self.col = len(indent)
        if self.opts["autoindent"] and ins is not None and indent and not after:
            ins.ai_row = self.row
        self.set_curswant()

    def backspace(self):
        ins = self.ins
        line = self.line
        if ins is not None and ins.kind == "R":
            if not ins.replaced:
                self.col = max(self.col - 1, 0) if self.col else 0
                return
            orig = ins.replaced.pop()
            if orig == "\n":
                prev = self.lines[self.row - 1] if self.row else ""
                # undo a line break made in replace mode
                if self.row:
                    self.set_line(self.row - 1, prev + line)
                    self.del_lines(self.row, 1)
                    self.row -= 1
                    self.col = len(prev)
                return
            self.col -= 1
            self.set_line(self.row, line[:self.col] + orig + line[self.col + len(orig):] if len(line) > self.col else line[:self.col] + orig)
            if orig == "":
                self.set_line(self.row, line[:self.col])
            self.set_curswant()
            return
        if self.col > 0:
            self.set_line(self.row, line[:self.col - 1] + line[self.col:])
            self.col -= 1
        elif self.row > 0:
            prev = self.lines[self.row - 1]
            self.set_line(self.row - 1, prev + line)
            self.del_lines(self.row, 1)
            self.row -= 1
            self.col = len(prev)
        self.set_curswant()

    def delete_forward(self):
        line = self.line
        if self.col < len(line):
            self.set_line(self.row, line[:self.col] + line[self.col + 1:])
        elif self.row < len(self.lines) - 1:
            self.set_line(self.row, line + self.lines[self.row + 1])
            self.del_lines(self.row + 1, 1)

    def delete_word_before(self):
        line = self.line
        if self.col == 0:
            self.backspace()
            return
        c = self.col
        start = self.ins.start if self.ins else None
        while c > 0 and line[c - 1] in " \t":
            c -= 1
        if c > 0:
            cls = T.word_class(line[c - 1])
            while c > 0 and T.word_class(line[c - 1]) == cls and line[c - 1] not in " \t":
                c -= 1
        if start is not None and start[0] == self.row and c < start[1] < self.col:
            c = start[1]
        self.set_line(self.row, line[:c] + line[self.col:])
        self.col = c
        self.set_curswant()

    def delete_line_before(self):
        line = self.line
        if self.col == 0:
            self.backspace()
            return
        start = self.ins.start if self.ins else None
        c = 0
        if start is not None and start[0] == self.row and start[1] < self.col:
            c = start[1]
        else:
            c = T.first_nonblank(line) if T.first_nonblank(line) < self.col else 0
        self.set_line(self.row, line[:c] + line[self.col:])
        self.col = c
        self.set_curswant()

    def replace_mode(self, count):
        self.mode = "r"
        self.pending = ""
        self.ins = InsertState("R", count or 1)
        self.ins.start = (self.row, self.col)
        self.check_cursor()
        while True:
            k = yield from self.getkey()
            if k in (ESC, "\x03"):
                break
            self.ins.keys.append(k)
            self.insert_key(k)
        ins = self.ins
        for _ in range(ins.count - 1):
            for key in list(ins.keys):
                self.insert_key(key)
        self.ins = None
        self.mode = "n"
        if self.col > 0:
            self.col -= 1
        self.check_cursor()
        self.set_curswant()
