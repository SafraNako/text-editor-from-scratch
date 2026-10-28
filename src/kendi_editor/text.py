"""Characters and columns: how wide a character is on the screen, which class it has for word motions, and the conversions between a character index in a line and the screen
column ("virtual column") that vim's up and down motions keep."""
from __future__ import annotations

import unicodedata

MAXCOL = 1 << 30                                        # "as far right as possible" (what $ sets as the wanted column)
TABSTOP = 8


def char_cells(ch):
    """The screen cells of a character that is not a tab: control characters are shown as ^X, undecodable bytes as <xx>, wide characters take two, combining ones none."""
    o = ord(ch)
    if o < 32 or o == 127:
        return 2
    if o < 127:
        return 1
    if 0x80 <= o < 0xA0 or 0xDC80 <= o <= 0xDCFF:
        return 4
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def cells(ch, vcol, ts=TABSTOP):
    return ts - vcol % ts if ch == "\t" else char_cells(ch)


def vcol_start(line, col, ts=TABSTOP):
    """The screen column where the character ``col`` of the line starts (``col`` may be len(line): just past the end)."""
    v = 0
    for ch in line[:col]:
        v += ts - v % ts if ch == "\t" else char_cells(ch)
    return v


def vcol_end(line, col, ts=TABSTOP):
    """The screen column where the cursor is drawn in normal mode: the last cell of a tab, the first cell of any other character."""
    v = vcol_start(line, col, ts)
    if col < len(line) and line[col] == "\t":
        return v + cells("\t", v, ts) - 1
    return v


def line_cells(line, ts=TABSTOP):
    return vcol_start(line, len(line), ts)


def col_at_vcol(line, vcol, ts=TABSTOP):
    """The index of the character that covers screen column ``vcol``; len(line) if the line is shorter."""
    v = 0
    for i, ch in enumerate(line):
        w = ts - v % ts if ch == "\t" else char_cells(ch)
        if vcol < v + max(w, 1):
            return i
        v += w
    return len(line)


def word_class(ch, big=False):
    """0 blank (or the end of the line), 1 punctuation, 2 word character; with ``big`` every non-blank is 1 (WORDs)."""
    if ch is None or ch == " " or ch == "\t" or ch == "\xa0":
        return 0
    o = ord(ch)
    if o >= 0x100 and ch.isspace():
        return 0
    if big:
        return 1
    if ch.isalnum() or ch == "_":
        return 2 if o < 0x80 or o >= 0xC0 else 1
    return 1


def indent_width(line, ts=TABSTOP):
    """The screen width of the leading white space."""
    v = 0
    for ch in line:
        if ch == " ":
            v += 1
        elif ch == "\t":
            v += ts - v % ts
        else:
            break
    return v


def first_nonblank(line):
    i = 0
    while i < len(line) and line[i] in " \t":
        i += 1
    return i


def make_indent(width, ts, expandtab):
    if expandtab:
        return " " * width
    return "\t" * (width // ts) + " " * (width % ts)
