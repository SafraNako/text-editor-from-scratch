"""Vim's word motions, ported step by step because their corner cases (empty lines, the end of a line, punctuation next to words) are what people feel when they use an
editor. A position may sit on the "NUL" just past the last character of a line (column == len(line)): such a position has the class of white space."""
from __future__ import annotations

from .text import word_class


class Cur:
    """A cursor that walks over the lines the way vim's inc() and dec() do."""
    __slots__ = ("lines", "row", "col")

    def __init__(self, lines, row, col):
        self.lines, self.row, self.col = lines, row, col

    def char(self):
        line = self.lines[self.row]
        return line[self.col] if self.col < len(line) else None

    def cls(self, big):
        return word_class(self.char(), big)

    def inc(self):
        """0: moved within the line; 2: moved onto the end of the line; 1: moved to the start of the next line; -1: at the end of the buffer."""
        line = self.lines[self.row]
        if self.col < len(line):
            self.col += 1
            return 0 if self.col < len(line) else 2
        if self.row < len(self.lines) - 1:
            self.row += 1
            self.col = 0
            return 1
        return -1

    def dec(self):
        if self.col > 0:
            self.col -= 1
            return 0
        if self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])
            return 1
        return -1

    def empty_line(self):
        return self.lines[self.row] == ""

    def pos(self):
        return (self.row, self.col)


def _skip(cur, cclass, forward, big):
    """Skip over characters of one class; True if the start or end of the buffer was reached."""
    while cur.cls(big) == cclass:
        if (cur.inc() if forward else cur.dec()) == -1:
            return True
    return False


def fwd_word(cur, count, big, eol):
    """w / W. ``eol``: with an operator, the last word stops at the end of its line. Returns False when it started on the last character of the buffer."""
    while count > 0:
        count -= 1
        sclass = cur.cls(big)
        last_line = cur.row == len(cur.lines) - 1
        i = cur.inc()
        if i == -1 or (i >= 1 and last_line):
            return False
        if i >= 1 and eol and count == 0:
            return True
        if sclass != 0:
            while cur.cls(big) == sclass:
                i = cur.inc()
                if i == -1 or (i >= 1 and eol and count == 0):
                    return True
        while cur.cls(big) == 0:
            if cur.col == 0 and cur.empty_line():
                break
            i = cur.inc()
            if i == -1 or (i >= 1 and eol and count == 0):
                return True
    return True


def bck_word(cur, count, big, stop):
    """b / B."""
    while count > 0:
        count -= 1
        sclass = cur.cls(big)
        if cur.dec() == -1:
            return False
        finished = False
        if not stop or sclass == cur.cls(big) or sclass == 0:
            while cur.cls(big) == 0:
                if cur.col == 0 and cur.empty_line():
                    finished = True
                    break
                if cur.dec() == -1:
                    return True
            if not finished and _skip(cur, cur.cls(big), False, big):
                return True
        if not finished:
            cur.inc()
        stop = False
    return True


def end_word(cur, count, big, stop, empty):
    """e / E (``stop``: do not leave the word if already on its last character, which is what cw wants)."""
    while count > 0:
        count -= 1
        sclass = cur.cls(big)
        if cur.inc() == -1:
            return False
        finished = False
        if cur.cls(big) == sclass and sclass != 0:
            if _skip(cur, sclass, True, big):
                return False
        elif not stop or sclass == 0:
            while cur.cls(big) == 0:
                if empty and cur.col == 0 and cur.empty_line():
                    finished = True
                    break
                if cur.inc() == -1:
                    return False
            if not finished and _skip(cur, cur.cls(big), True, big):
                return False
        if not finished:
            cur.dec()
        stop = False
    return True


def bckend_word(cur, count, big, eol):
    """ge / gE."""
    while count > 0:
        count -= 1
        sclass = cur.cls(big)
        i = cur.dec()
        if i == -1:
            return False
        if eol and i == 1:
            return True
        if sclass != 0:
            while cur.cls(big) == sclass:
                i = cur.dec()
                if i == -1 or (eol and i == 1):
                    return True
        while cur.cls(big) == 0:
            if cur.col == 0 and cur.empty_line():
                break
            i = cur.dec()
            if i == -1 or (eol and i == 1):
                return True
    return True


PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {v: k for k, v in PAIRS.items()}


def match_pair(lines, row, col):
    """The % motion: from the first bracket at or after the cursor on its line to the matching one, or None."""
    line = lines[row]
    i = col
    while i < len(line) and line[i] not in PAIRS and line[i] not in CLOSERS:
        i += 1
    if i >= len(line):
        return None
    c = line[i]
    forward = c in PAIRS
    other = PAIRS[c] if forward else CLOSERS[c]
    depth = 0
    r, k = row, i
    while True:
        text = lines[r]
        while 0 <= k < len(text):
            ch = text[k]
            if ch == c:
                depth += 1
            elif ch == other:
                depth -= 1
                if depth == 0:
                    return (r, k)
            k += 1 if forward else -1
        r += 1 if forward else -1
        if r < 0 or r >= len(lines):
            return None
        k = 0 if forward else len(lines[r]) - 1


def find_paragraph(lines, row, forward, count):
    """{ and }: the row of the next empty line (skipping the ones we start on), or the end of the buffer. Returns (row, hit_end_of_buffer) or None when it cannot move."""
    curr = row
    while count > 0:
        count -= 1
        did_skip = False
        first = True
        while True:
            if lines[curr] != "":
                did_skip = True
            if not first and did_skip and lines[curr] == "":
                break
            curr += 1 if forward else -1
            if curr < 0 or curr >= len(lines):
                if count:
                    return None
                curr -= 1 if forward else -1
                break
            first = False
    return curr


def incl(cur):
    """inc() that does not stop on the end of a line: returns the same codes, but steps over the end position."""
    r = cur.inc()
    if r >= 1 and cur.col:
        r = cur.inc()
    return r


def decl(cur):
    r = cur.dec()
    if r == 1 and cur.col:
        r = cur.dec()
    return r


def in_indent(lines, row, col, extra=1):
    """vim's inindent(): is the position inside (or at the end of) the leading white space of its line?"""
    line = lines[row]
    n = 0
    while n < len(line) and line[n] in " \t":
        n += 1
    return n >= col + extra


def find_unmatched(lines, row, col, open_c, close_c, mode):
    """Search from just after/before (row, col) for an unmatched bracket. ``mode``: "open" backwards for the opening one, "close" forwards for the closing one,
    "next_open" forwards for the next opening one (what a text object does when the cursor is in no block)."""
    cur = Cur(lines, row, col)
    depth = 0
    while True:
        if mode == "open":
            if cur.dec() == -1:
                return None
        else:
            if cur.inc() == -1:
                return None
        c = cur.char()
        if mode == "open":
            if c == close_c:
                depth += 1
            elif c == open_c:
                if depth == 0:
                    return cur.pos()
                depth -= 1
        elif mode == "close":
            if c == open_c:
                depth += 1
            elif c == close_c:
                if depth == 0:
                    return cur.pos()
                depth -= 1
        else:
            if c == close_c:
                depth += 1
            elif c == open_c:
                if depth == 0:
                    return cur.pos()
                depth -= 1
