"""Normal mode and visual mode: counts, registers, motions, operators (d c y < > g~ gu gU), text objects, and the single commands (x p J r . u ...), as vim does them."""
from __future__ import annotations

import re

from . import motions as MO
from . import text as T
from .errors import CmdError
from .editor_types import Register
from .motions import Cur

ESC = "\x1b"
OPERATORS = {"d": "d", "c": "c", "y": "y", "<": "<", ">": ">", "g~": "g~", "gu": "gu", "gU": "gU"}
MOTION_KEYS = set("hjkl0^$|wWbBeEfFtT;,%{}/?nN*#HMLG+-_ \r\n'`") | {"\x08", "\x7f", "\x0e", "\x10", "<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>"}


class Motion:
    """Where a motion goes and what kind it is: linewise, or charwise and inclusive of the last character or not."""
    __slots__ = ("row", "col", "linewise", "inclusive", "want", "start", "no_adjust", "reg_one", "failed", "visual_end")

    def __init__(self, row, col, linewise=False, inclusive=False, want=None, start=None, reg_one=False):
        self.row, self.col, self.linewise, self.inclusive = row, col, linewise, inclusive
        self.want = want                  # None: the cursor column becomes the wanted column; T.MAXCOL; or "keep"
        self.start = start                # text objects: where the region starts (instead of the cursor)
        self.no_adjust = False
        self.visual_end = None            # text objects: where a visual selection ends (it can include the line break)
        self.failed = False               # the motion could not be completed: the cursor still moves, but an operator is cancelled
        self.reg_one = reg_one            # a deletion goes to register 1 even when it is small


class NormalMixin:
    # --- reading keys ----------------------------------------------------------------------------------------------------------------------------
    def getkey(self):
        """The next key, recorded as part of the command for '.'."""
        k = yield
        self.rec.append(k)
        return k

    def normal_command(self):
        self.rec = []
        self.pending = ""
        count = None
        reg = None
        k = yield
        if not self.nested:
            self._snap = self.begin_group()                    # (taken when the first key arrives: the buffer may have been loaded since the last command)
            self.msg = ""
            self.msg_error = False
        while True:
            if k == '"':
                self.pending += k
                reg = yield
                self.pending += reg
                if not (len(reg) == 1 and (reg.isalnum() or reg in '"-_')):
                    raise CmdError("E354: Invalid register name: '%s'" % reg)
                k = yield
                continue
            if len(k) == 1 and k.isdigit() and (k != "0" or count is not None):
                count = (count or 0) * 10 + int(k)
                self.pending += k
                k = yield
                continue
            break
        self.rec = [k]
        self.pending += k
        self.mode_visual = self.mode in ("v", "V")
        self.pending_visual_redo = None
        if self.mode_visual:
            yield from self.visual_command(k, count, reg)
            if self.pending_visual_redo is not None and not self.replaying:
                r, c, sel = self.pending_visual_redo
                self.redo = (r, None, list(self.rec), sel)
        else:
            yield from self.command(k, count, reg)
        self.pending = ""
        if not self.nested:
            self.end_group(self._snap)
        if self.mode in ("n", "v", "V"):
            self.check_cursor()

    def remember_change(self, reg, count):
        """The command just done can be repeated with '.'."""
        if not self.replaying:
            self.redo = (reg, count, list(self.rec))

    # --- the commands of normal mode --------------------------------------------------------------------------------------------------------------
    def command(self, k, count, reg):
        n1 = count or 1
        if k in OPERATORS or k == "g":
            if k == "g":
                k2 = yield from self.getkey()
                self.pending += k2
                if k2 in ("~", "u", "U"):
                    yield from self.operator_command("g" + k2, count, reg)
                    return
                yield from self.g_command(k2, count, reg)
                return
            yield from self.operator_command(k, count, reg)
            return
        if k in MOTION_KEYS:
            m = yield from self.get_motion(k, count, None)
            self.apply_motion(m)
            return
        if k in ("i", "a", "I", "A", "o", "O"):
            yield from self.start_insert(k, count)
            self.remember_change(reg, count)
        elif k in ("x", "<Delete>", "X", "D", "C", "s", "S", "Y"):
            yield from self.abbreviated(k, count, reg)
        elif k in ("p", "P"):
            self.put(k == "p", count, reg)
            self.remember_change(reg, count)
        elif k == "J":
            self.join_lines(max(n1, 2), True)
            self.remember_change(reg, count)
        elif k == "r":
            c = yield from self.getkey()
            self.replace_chars(c, n1)
            self.remember_change(reg, count)
        elif k == "R":
            yield from self.replace_mode(count)
            self.remember_change(reg, count)
        elif k == "~":
            self.tilde(n1)
            self.remember_change(reg, count)
        elif k == "u":
            self.undo(n1)
        elif k == "\x12":
            self.redo_change(n1)
        elif k == ".":
            self.repeat_change(count)
        elif k == "v" or k == "V":
            self.start_visual(k)
        elif k == ":":
            text = yield from self.read_cmdline(":")
            self.run_ex(text)
        elif k == "Z":
            k2 = yield from self.getkey()
            if k2 == "Z":
                self.run_ex("x")
            elif k2 == "Q":
                self.run_ex("q!")
            else:
                raise CmdError("")
        elif k in ("\x01", "\x18"):
            self.add_to_number(n1 if k == "\x01" else -n1)
            self.remember_change(reg, count)
        elif k == "m":
            name = yield from self.getkey()
            self.set_mark(name, self.row, self.col)
        elif k == "&":
            self.run_ex("s")
        elif k == "\x07":
            self.say(self.file_info())
        elif k in ("\x0c",):
            pass
        elif k in ("\x04", "\x15", "\x06", "\x02", "\x05", "\x19", "<PageDown>", "<PageUp>"):
            self.scroll_command(k, count)
        elif k == "z":
            k2 = yield from self.getkey()
            self.z_command(k2, count)
        elif k in (ESC, "\x03"):
            self.pending = ""
        elif k == "\x1a":
            pass
        else:
            raise CmdError("")

    def g_command(self, k2, count, reg):
        n1 = count or 1
        if k2 == "g":
            m = yield from self.get_motion("gg", count, None)
            self.apply_motion(m)
        elif k2 in ("e", "E", "_", "j", "k", "0", "$", "^", "m", "M"):
            m = yield from self.get_motion("g" + k2, count, None)
            self.apply_motion(m)
        elif k2 == "J":
            self.join_lines(max(n1, 2), False)
            self.remember_change(reg, count)
        elif k2 == "I":
            self.col = 0
            yield from self.start_insert("i", count)
            self.remember_change(reg, count)
        elif k2 == "v":
            if self.last_visual:
                mode, a, b = self.last_visual
                self.vstart = a
                self.row, self.col = b
                self.mode = mode
                self.check_cursor()
        elif k2 == "p" or k2 == "P":
            self.put(k2 == "p", count, reg, cursor_after=True)
            self.remember_change(reg, count)
        elif k2 == "&":
            self.run_ex("%s//~/&")
        else:
            raise CmdError("")

    def abbreviated(self, k, count, reg):
        """x X D C s S Y are other commands in short: dl dh d$ c$ cl cc yy."""
        table = {"x": "dl", "<Delete>": "dl", "X": "dh", "D": "d$", "C": "c$", "s": "cl", "S": "cc", "Y": "yy"}
        keys = table[k]
        if k == "Y":
            yield from self.operator_command("y", count, reg, preset="y")
            return
        op = keys[0]
        rest = keys[1]
        yield from self.operator_command(op, count, reg, preset=rest)

    # --- motions ---------------------------------------------------------------------------------------------------------------------------------
    def apply_motion(self, m):
        if m is None:
            return
        self.row, self.col = m.row, m.col
        if m.want == "keep":
            pass
        elif m.want == T.MAXCOL:
            self.curswant = T.MAXCOL
        else:
            self.check_cursor_motion()
            self.set_curswant()

    def check_cursor_motion(self):
        n = len(self.lines[self.row])
        limit = n if self.mode in ("v", "V", "i", "r") else max(n - 1, 0)
        self.col = max(0, min(self.col, limit))

    def sol_motion(self, row, **kw):
        """Land on a line after a motion like G or +: the first non-blank (or the wanted column when 'startofline' is off)."""
        col = self.first_nonblank_col(row) if self.opts["startofline"] else self.col_for_want(row)
        return Motion(row, col, **kw)

    def get_motion(self, k, count, op):
        """Work out a motion (a generator because f, t, g, / and ? read more keys). Returns a Motion, or None if it cannot be done."""
        n1 = count or 1
        lines = self.lines
        row, col = self.row, self.col
        last = len(lines) - 1
        if k == "g" or k == "gg" or (len(k) == 2 and k[0] == "g"):
            if k == "g":
                k = "g" + (yield from self.getkey())
            if k == "gg":
                r = min(count - 1, last) if count else 0
                return self.sol_motion(r, linewise=True)
            if k in ("ge", "gE"):
                cur = Cur(lines, row, col)
                ok = MO.bckend_word(cur, n1, k == "gE", False)
                m = Motion(cur.row, cur.col, inclusive=True)
                m.failed = not ok
                return m if (ok or (cur.row, cur.col) != (row, col)) else None
            if k == "g_":
                r = row + n1 - 1
                if r > last:
                    return None
                line = lines[r]
                c = len(line) - 1
                while c > 0 and line[c] in " \t":
                    c -= 1
                return Motion(r, max(c, 0), inclusive=True)
            if k in ("gj", "gk"):
                return self.vertical(n1, k == "gj", op)
            if k == "g0":
                return Motion(row, 0)
            if k == "g^":
                return Motion(row, self.first_nonblank_col(row))
            if k == "g$":
                return Motion(row, max(len(lines[row]) - 1, 0), inclusive=True, want=T.MAXCOL)
            if k in ("gm", "gM"):
                return Motion(row, min(len(lines[row]) // 2, max(len(lines[row]) - 1, 0)))
            raise CmdError("")
        if k in ("h", "<Left>", "\x08", "\x7f"):
            wrap = k in ("\x08", "\x7f")
            r, c = row, col
            moved = 0
            nocadj = False
            for i in range(n1):
                if c > 0:
                    c -= 1
                    moved += 1
                    continue
                if wrap and r > 0:
                    r -= 1
                    c = max(len(lines[r]) - 1, 0)
                    if op in ("d", "c") and lines[r]:
                        c = len(lines[r])
                        nocadj = True
                    moved += 1
                    continue
                break
            if moved == 0 and op is None:
                return None
            m = Motion(r, c)
            m.no_adjust = nocadj
            return m
        if k in ("l", "<Right>", " "):
            wrap = k == " "
            r, c = row, col
            inclusive = False
            for i in range(n1):
                line = lines[r]
                at_last = c >= len(line) - 1 if self.mode not in ("v", "V") else c >= len(line)
                if not at_last:
                    c += 1
                    continue
                if wrap and r < last:
                    if op is not None and not inclusive and line:
                        inclusive = True
                    else:
                        r += 1
                        c = 0
                        inclusive = False
                    continue
                if op is None:
                    if i == 0:
                        return None
                elif lines[r]:
                    inclusive = True
                break
            return Motion(r, c, inclusive=inclusive)
        if k in ("j", "<Down>", "\x0e", "\n", "k", "<Up>", "\x10"):
            return self.vertical(n1, k in ("j", "<Down>", "\x0e", "\n"), op)
        if k == "0" or k == "<Home>":
            return Motion(row, 0)
        if k == "^":
            return Motion(row, self.first_nonblank_col(row))
        if k == "$" or k == "<End>":
            if n1 > 1 and row >= last:
                return None
            r = min(row + n1 - 1, last)
            line = lines[r]
            c = len(line) if (self.mode in ("v", "V") and line) else max(len(line) - 1, 0)
            return Motion(r, c, inclusive=True, want=T.MAXCOL)
        if k == "|":
            c = T.col_at_vcol(lines[row], n1 - 1, self.opts["tabstop"])
            return Motion(row, min(c, max(len(lines[row]) - 1, 0)))
        if k in ("+", "\r"):
            r = row + n1
            if row >= last:
                return None
            r = min(r, last)
            return Motion(r, self.first_nonblank_col(r), linewise=True)
        if k == "-":
            if row <= 0:
                return None
            r = max(row - n1, 0)
            return Motion(r, self.first_nonblank_col(r), linewise=True)
        if k == "_":
            r = row + n1 - 1
            if n1 > 1 and row >= last:
                return None
            r = min(r, last)
            return Motion(r, col if op == "y" else self.first_nonblank_col(r), linewise=True)
        if k == "G":
            r = min(count - 1, last) if count else last
            return self.sol_motion(r, linewise=True)
        if k in ("w", "W", "b", "B", "e", "E"):
            return self.word_motion(k, n1, op)
        if k in ("f", "F", "t", "T", ";", ","):
            return (yield from self.char_search(k, n1))
        if k == "%":
            if count:
                r = min((count * len(lines) + 99) // 100, len(lines)) - 1
                return self.sol_motion(r, linewise=True)
            pos = MO.match_pair(lines, row, col)
            if pos is None:
                return None
            return Motion(pos[0], pos[1], inclusive=True, reg_one=True)
        if k in ("{", "}"):
            fwd = k == "}"
            r = MO.find_paragraph(lines, row, fwd, n1)
            if r is None:
                return None
            if r == last:                              # (vim does not look at the direction here: { in a one-line buffer goes to the end of the line)
                line = lines[r]
                if line:
                    return Motion(r, len(line) - 1, inclusive=True, reg_one=True)
            return Motion(r, 0, reg_one=True)
        if k in ("/", "?"):
            text = yield from self.read_cmdline(k)
            pat, offset = self.split_search_offset(text, k)
            pos = self.search_command(pat, k == "/", n1)
            return self.search_motion(pos, offset)
        if k in ("n", "N"):
            if self.last_search is None:
                raise CmdError("E35: No previous regular expression")
            pat, fwd = self.last_search
            pos = self.search_command(pat, fwd if k == "n" else not fwd, n1, remember=False)
            return self.search_motion(pos, self.last_offset)
        if k in ("*", "#"):
            word, keyword, start = self.word_under_cursor()
            if word is None:
                raise CmdError("E348: No string under cursor")
            escaped = re.sub(r"([\\/.*$^~\[\]])", r"\\\1", word)
            pat = ("\\<" + escaped + "\\>") if keyword else escaped
            self.last_offset = None
            saved = self.col
            self.col = start                                   # (the search starts at the beginning of the word, so that the next match is another one)
            try:
                pos = self.search_command(pat, k == "*", n1, use_smart=False)
            finally:
                self.col = saved
            return Motion(pos[0], pos[1])
        if k in ("'", "`"):
            name = yield from self.getkey()
            r, c = self.get_mark(name)
            r = min(r, last)
            if k == "'":
                return Motion(r, self.first_nonblank_col(r), linewise=True)
            return Motion(r, min(c, max(len(lines[r]) - 1, 0)))
        if k in ("H", "M", "L"):
            top, bottom = self.visible_rows()
            if k == "H":
                r = min(top + max(n1 - 1, 0), bottom)
            elif k == "L":
                r = max(bottom - max(n1 - 1, 0), top)
            else:
                r = (top + bottom) // 2
            return self.sol_motion(r, linewise=True)
        raise CmdError("")

    last_offset = None
    pending_visual_redo = None

    def vertical(self, n, down, op):
        row = self.row
        last = len(self.lines) - 1
        if down:
            if row >= last:
                return None
            r = min(row + n, last)
        else:
            if row <= 0:
                return None
            r = max(row - n, 0)
        return Motion(r, self.col_for_want(r), linewise=True, want="keep")

    def word_motion(self, k, n1, op):
        big = k in ("W", "B", "E")
        cur = Cur(self.lines, self.row, self.col)
        start = (self.row, self.col)
        if k in ("w", "W"):
            if op == "c":
                ch = cur.char()
                if ch is not None and ch not in " \t":
                    ok = MO.end_word(cur, n1, big, True, False)
                    return self.finish_word(cur, start, True)
            ok = MO.fwd_word(cur, n1, big, op is not None)
            if not ok and op is None and (cur.row, cur.col) == start:
                return None
            return self.finish_word(cur, start, False)
        if k in ("b", "B"):
            ok = MO.bck_word(cur, n1, big, False)
            m = Motion(cur.row, cur.col)
            m.failed = not ok
            return m if (ok or (cur.row, cur.col) != start) else None
        ok = MO.end_word(cur, n1, big, False, False)
        if not ok and op is None and (cur.row, cur.col) == start:
            return None
        return self.finish_word(cur, start, True)

    def finish_word(self, cur, start, inclusive):
        """Don't leave the cursor on the end of the line: move back one character and include it."""
        row, col = cur.row, cur.col
        if (row, col) > start and col > 0 and col >= len(self.lines[row]):
            col -= 1
            inclusive = True
        return Motion(row, col, inclusive=inclusive)

    def char_search(self, k, n1):
        """f F t T ; ,  on the current line."""
        if k in (";", ","):
            if self.last_find is None:
                raise CmdError("")
            ch, kind = self.last_find
            if k == ",":
                kind = {"f": "F", "F": "f", "t": "T", "T": "t"}[kind]
            repeat = True
        else:
            ch = yield from self.getkey()
            if len(ch) != 1:
                raise CmdError("")
            kind = k
            repeat = False
            self.last_find = (ch, kind)
        forward = kind in ("f", "t")
        till = kind in ("t", "T")
        line = self.line
        c = self.col
        stop = not (repeat and till and n1 == 1)
        for _ in range(n1):
            while True:
                c += 1 if forward else -1
                if c < 0 or c >= len(line):
                    return None
                if line[c] == ch and stop:
                    break
                stop = True
        if till:
            c -= 1 if forward else -1
        return Motion(self.row, c, inclusive=forward)

    def split_search_offset(self, text, k):
        """Split "pat/e+1" at the first unescaped delimiter; only the end offset and plain line offsets are understood."""
        delim = k
        i = 0
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == delim:
                self.last_offset = text[i + 1:] or None
                return text[:i], self.last_offset
            i += 1
        self.last_offset = None
        return text, None

    def search_motion(self, pos, offset):
        """The motion for a search that found ``pos``; ``offset`` is what follows the second slash: a line offset (+1, -2), or e / s / b with a number of characters."""
        row, col = pos
        line = self.lines[row]
        if not offset:
            if col >= len(line) and col > 0:
                col = len(line) - 1                            # a match at the end of a line puts the cursor on its last character
            return Motion(row, col, reg_one=True)
        m = re.fullmatch(r"([esb]?)([+-]?)(\d*)", offset)
        if m is None:
            raise CmdError("E486: Pattern not found: %s" % offset)
        kind, sign, digits = m.groups()
        amount = int(digits) if digits else (1 if sign else 0)
        if sign == "-":
            amount = -amount
        if kind == "":
            r = max(0, min(row + amount, len(self.lines) - 1))
            return Motion(r, self.first_nonblank_col(r), linewise=True)
        last = max(len(line) - 1, 0)
        if kind == "e":
            found = self.compile(self.last_search[0]).match(line, col)
            end = found.end() - 1 if found and found.end() > col else col
            return Motion(row, max(0, min(end + amount, last)), inclusive=True, reg_one=True)
        return Motion(row, max(0, min(col + amount, last)), reg_one=True)

    # --- text objects ----------------------------------------------------------------------------------------------------------------------------
    def text_object(self, inner, key, count):
        """The region of iw aw i" a" i( a( ... as a Motion with ``start`` set, or None."""
        if key in ("w", "W"):
            return self.word_object(inner, key == "W", count)
        if key in ('"', "'", "`"):
            return self.quote_object(inner, key, count)
        pairs = {"(": ("(", ")"), ")": ("(", ")"), "b": ("(", ")"), "{": ("{", "}"), "}": ("{", "}"), "B": ("{", "}"), "[": ("[", "]"), "]": ("[", "]"), "<": ("<", ">"), ">": ("<", ">")}
        if key in pairs:
            return self.block_object(inner, pairs[key], count)
        if key == "p":
            return self.paragraph_object(inner, count)
        return None

    def word_object(self, inner, big, count):
        include = not inner
        lines = self.lines
        cur = Cur(lines, self.row, self.col)
        visual_extend = self.mode in ("v", "V") and (self.row, self.col) != self.vstart
        start = None if visual_extend else (self.row, self.col)
        backward = visual_extend and (self.row, self.col) < self.vstart
        inclusive = True
        include_white = False

        def back_in_line():
            sclass = cur.cls(big)
            while cur.col != 0:
                cur.dec()
                if cur.cls(big) != sclass:
                    cur.inc()
                    break

        def incl():
            r = cur.inc()
            if r >= 1 and cur.col:
                r = cur.inc()
            return r

        def decl():
            r = cur.dec()
            if r == 1 and cur.col:
                r = cur.dec()
            return r

        if not visual_extend:
            back_in_line()
            start = cur.pos()
            if (cur.cls(big) == 0) == include:
                if not MO.end_word(cur, 1, big, True, True):
                    return None
            else:
                MO.fwd_word(cur, 1, big, True)
                if cur.col == 0:
                    decl()
                elif cur.col > 0:
                    cur.col -= 1
                if include:
                    include_white = True
            count -= 1
        while count > 0:
            inclusive = True
            if backward:
                if decl() == -1:
                    return None
                if include != (cur.cls(big) != 0):
                    if not MO.bck_word(cur, 1, big, True) and count > 1:
                        return None
                else:
                    if not MO.bckend_word(cur, 1, big, True):
                        return None
                    incl()
                count -= 1
                continue
            if incl() == -1:
                return None
            if include != (cur.cls(big) == 0):
                if not MO.fwd_word(cur, 1, big, True) and count > 1:
                    return None
                if cur.col > 0:
                    cur.col -= 1
                else:
                    inclusive = False
            else:
                if not MO.end_word(cur, 1, big, True, True):
                    return None
            count -= 1
        if include_white and (cur.cls(big) != 0 or (cur.col == 0 and not inclusive)):
            save = cur.pos()
            cur.row, cur.col = start
            if cur.col > 0:
                cur.col -= 1
                back_in_line()
                if cur.cls(big) == 0 and cur.col > 0:
                    start = cur.pos()
            cur.row, cur.col = save
        return Motion(cur.row, cur.col, inclusive=inclusive, start=start)

    def quote_object(self, inner, q, count):
        line = self.line
        col = self.col

        def next_quote(c):
            while c < len(line):
                if line[c] == "\\":
                    c += 2
                    continue
                if line[c] == q:
                    return c
                c += 1
            return -1
        if col < len(line) and line[col] == q:
            cs = 0
            while True:
                cs = next_quote(cs)
                if cs < 0 or cs > col:
                    return None
                ce = next_quote(cs + 1)
                if ce < 0:
                    return None
                if cs <= col <= ce:
                    break
                cs = ce + 1
        else:
            cs = col
            while cs > 0:
                cs -= 1
                if line[cs] == q and not (cs > 0 and line[cs - 1] == "\\"):
                    break
            else:
                cs = -1 if not (line and line[0] == q) else 0
            if cs < 0 or cs >= len(line) or line[cs] != q or cs >= col:
                cs = next_quote(col)
                if cs < 0:
                    return None
            ce = next_quote(cs + 1)
            if ce < 0:
                return None
        if not inner:
            if ce + 1 < len(line) and line[ce + 1] in " \t":
                while ce + 1 < len(line) and line[ce + 1] in " \t":
                    ce += 1
            else:
                while cs > 0 and line[cs - 1] in " \t":
                    cs -= 1
            return Motion(self.row, ce, inclusive=True, start=(self.row, cs))
        if ce - cs <= 1:
            return Motion(self.row, cs + 1, inclusive=False, start=(self.row, cs + 1))
        return Motion(self.row, ce - 1, inclusive=True, start=(self.row, cs + 1))

    def block_object(self, inner, pair, count):
        """i( a( i{ a{ i[ a[ i< a< (vim's current_block): the innermost block around the cursor, the count-th one out; with the cursor in no block, the next one ahead."""
        open_c, close_c = pair
        lines = self.lines
        cur = Cur(lines, self.row, self.col)
        if open_c == "{":
            while MO.in_indent(lines, cur.row, cur.col, 1):
                if cur.inc() != 0:
                    break
        if cur.char() == open_c:
            cur.col += 1
        start = None
        pos = MO.find_unmatched(lines, cur.row, cur.col, open_c, close_c, "open")
        mode = "open" if pos is not None else "next_open"
        for _ in range(count):
            pos = MO.find_unmatched(lines, cur.row, cur.col, open_c, close_c, mode)
            if pos is None:
                break
            cur.row, cur.col = pos
            start = pos
        if pos is None or start is None:
            return None
        end = MO.find_unmatched(lines, start[0], start[1], open_c, close_c, "close")
        if end is None:
            return None
        if not inner:
            return Motion(end[0], end[1], inclusive=True, start=start)
        s = Cur(lines, start[0], start[1])
        MO.incl(s)
        e = Cur(lines, end[0], end[1])
        sol = e.col == 0
        MO.decl(e)
        while MO.in_indent(lines, e.row, e.col, 1):
            sol = True
            if MO.decl(e) != 0:
                break
        vis = e.pos()
        if sol and e.col < len(lines[e.row]):
            vis = (e.row, e.col + 1)                           # in visual mode the line break is selected too
        if sol:
            MO.incl(e)
            m = Motion(e.row, e.col, inclusive=False, start=s.pos())
        elif s.pos() <= e.pos():
            m = Motion(e.row, e.col, inclusive=True, start=s.pos())
        else:
            m = Motion(s.row, s.col, inclusive=False, start=s.pos())
        m.visual_end = vis
        return m

    def paragraph_object(self, inner, count):
        """ip / ap (vim's current_par): paragraphs and the white lines between them count as one object each."""
        include = not inner
        lines = self.lines
        last = len(lines) - 1
        white = lambda r: lines[r].strip(" \t") == ""   # noqa: E731
        start = self.row
        visual = self.mode in ("v", "V")
        if visual and self.vstart is not None and start != self.vstart[0]:
            return self.paragraph_extend(include, count, start)
        white_in_front = white(start)
        while start > 0:
            if white_in_front:
                if not white(start - 1):
                    break
            elif white(start - 1):
                break
            start -= 1
        end = start
        while end <= last and white(end):
            end += 1
        end -= 1
        i = count
        if not include and white_in_front:
            i -= 1
        do_white = False
        while i > 0:
            i -= 1
            if end == last:
                return None
            if not include:
                do_white = white(end + 1)
            if include or not do_white:
                end += 1
                while end < last and not white(end + 1):
                    end += 1
            if i == 0 and white_in_front and include:
                break
            if include or do_white:
                while end < last and white(end + 1):
                    end += 1
        if not white_in_front and not white(end) and include:
            while start > 0 and white(start - 1):
                start -= 1
        if visual:
            if self.mode == "V" and start == self.row:
                return self.paragraph_extend(include, count, self.row)
        return Motion(end, 0, linewise=True, start=(start, 0))

    def paragraph_extend(self, include, count, start):
        lines = self.lines
        last = len(lines) - 1
        white = lambda r: lines[r].strip(" \t") == ""   # noqa: E731
        direction = -1 if start < self.vstart[0] else 1
        for _ in range(count):
            if start == (0 if direction < 0 else last):
                return None
            prev_white = None
            for _t in range(2):
                start += direction
                start_white = white(start)
                if prev_white == start_white:
                    start -= direction
                    break
                while True:
                    if start == (0 if direction < 0 else last):
                        break
                    if start_white != white(start + direction):
                        break
                    start += direction
                if not include:
                    break
                if start == (0 if direction < 0 else last):
                    break
                prev_white = start_white
        return Motion(start, 0, linewise=True, start=self.vstart)

    # --- operators -------------------------------------------------------------------------------------------------------------------------------
    def operator_command(self, op, count, reg, preset=None):
        """d c y < > g~ gu gU followed by a motion or a text object (``preset``: the motion keys when it is an abbreviation such as x or D)."""
        mcount = None
        if preset is None:
            k = yield
            while len(k) == 1 and k.isdigit() and (k != "0" or mcount is not None):
                mcount = (mcount or 0) * 10 + int(k)
                self.pending += k
                k = yield
            self.rec.append(k)
            self.pending += k
        else:
            k = preset
        total = (count or 1) * (mcount or 1) if (count or mcount) else None
        n1 = total or 1
        double = {"d": "d", "c": "c", "y": "y", "<": "<", ">": ">", "g~": "~", "gu": "u", "gU": "U"}[op]
        start_pos = (self.row, self.col)
        # doubled operator: dd cc yy << >> g~~ guu gUU (also g~g~ ...)
        pre_g = False
        if op.startswith("g") and k == "g":
            k2 = yield from self.getkey()
            if k2 == op[1]:
                k = double
                pre_g = True
            else:
                k = "g" + k2                                   # g~gg, guge ...: a motion that starts with g
        if k == double or (preset is not None and op in "dcy" and k == op) or pre_g:
            last = len(self.lines) - 1
            if n1 > 1 and self.row >= last:
                raise CmdError("")
            r2 = min(self.row + n1 - 1, last)
            m = Motion(r2, self.col if op == "y" else self.first_nonblank_col(r2), linewise=True)
        elif k in ("i", "a") and preset is None:
            key = yield from self.getkey()
            m = self.text_object(k == "i", key, n1)
            if m is None:
                raise CmdError("")
        elif preset is not None:
            m = yield from self.get_motion(preset, total, op)
        else:
            if k in ("v", "V", "\x16"):
                raise CmdError("")
            m = yield from self.get_motion(k, total, op)
        if m is None:
            raise CmdError("")
        if m.failed:
            self.row, self.col = m.row, m.col
            self.check_cursor()
            self.set_curswant()
            raise CmdError("")
        yield from self.run_operator(op, reg, m, total, start_pos)
        if op != "y":
            self.remember_change(reg, count if mcount is None else total)

    def run_operator(self, op, reg, m, count, start_pos):
        """Carry out an operator on the region from the cursor to the motion's end (vim's do_pending_operator)."""
        lines = self.lines
        start = m.start if m.start is not None else start_pos
        end = (m.row, m.col)
        linewise = m.linewise
        inclusive = m.inclusive
        if end < start:
            start, end = end, start
        visual = False
        if not linewise and not inclusive and end[1] == 0 and end[0] > start[0] and not m.no_adjust:
            r = end[0] - 1
            self.row, self.col = start
            if start[1] <= T.first_nonblank(lines[start[0]]) and lines[start[0]][:start[1]].strip(" \t") == "":
                linewise = True
                end = (r, 0)
            else:
                n = len(lines[r])
                if n:
                    end = (r, n - 1)
                    inclusive = True
                else:
                    end = (r, 0)
        self.row, self.col = start
        empty = (not linewise and not inclusive and start == end)
        yield from self.apply_operator(op, reg, start, end, linewise, inclusive, empty, m, visual)

    def apply_operator(self, op, reg, start, end, linewise, inclusive, empty, m, visual):
        if op == "y":
            self.op_yank(reg, start, end, linewise, inclusive)
            self.row, self.col = start
            if linewise:
                self.col = start[1]
            self.check_cursor()
            self.set_curswant()
        elif op == "d":
            self.op_delete(reg, start, end, linewise, inclusive, empty, m, visual)
        elif op == "c":
            yield from self.op_change(reg, start, end, linewise, inclusive, empty, m, visual)
        elif op in ("<", ">"):
            self.op_shift(op, start[0], end[0], 1)
        elif op in ("g~", "gu", "gU"):
            self.op_case(op, start, end, linewise, inclusive)

    def region_text(self, start, end, linewise, inclusive):
        lines = self.lines
        if linewise:
            return lines[start[0]:end[0] + 1]
        ecol = end[1] + (1 if inclusive else 0)
        if start[0] == end[0]:
            return [lines[start[0]][start[1]:ecol]]
        return [lines[start[0]][start[1]:]] + lines[start[0] + 1:end[0]] + [lines[end[0]][:ecol]]

    def op_yank(self, reg, start, end, linewise, inclusive):
        from .editor_types import Register
        text = self.region_text(start, end, linewise, inclusive)
        self.set_register(reg, Register(text, linewise), deleting=False)
        n = len(text)
        if n > 2:
            self.say("%d lines yanked" % n)

    def op_delete(self, reg, start, end, linewise, inclusive, empty, m=None, visual=False):
        from .editor_types import Register
        lines = self.lines
        if empty:
            self.touch(start[0])
            return
        if not linewise and not visual and end[0] > start[0]:
            rest = lines[end[0]][end[1] + (1 if inclusive else 0):]
            if rest.strip(" \t") == "" and lines[start[0]][:start[1]].strip(" \t") == "":
                linewise = True
                end = (end[0], end[1])
        text = self.region_text(start, end, linewise, inclusive)
        reg_one = (m is not None and m.reg_one) or linewise or len(text) > 1
        self.store_deleted(reg, Register(text, linewise), reg_one)
        if linewise:
            self.del_lines(start[0], end[0] - start[0] + 1)
            self.row = min(start[0], len(lines) - 1)
            self.col = self.first_nonblank_col(self.row)
            n = end[0] - start[0] + 1
            if n > 2:
                self.say("%d fewer lines" % n)
        else:
            ecol = end[1] + (1 if inclusive else 0)
            new = lines[start[0]][:start[1]] + lines[end[0]][ecol:]
            self.set_line(start[0], new)
            if end[0] > start[0]:
                self.del_lines(start[0] + 1, end[0] - start[0])
            self.row, self.col = start
            if end[0] > start[0] and len(text) > 2:
                self.say("%d fewer lines" % (len(text) - 1))
        self.check_cursor()
        self.set_curswant()

    def store_deleted(self, reg, register, reg_one):
        """A deletion goes to the named register (and to "1 if big), or to "- if it is a small one, and the unnamed register points at it."""
        if reg == "_":
            return
        if reg and reg != '"':
            self.set_register(reg, register, deleting=True)
            if reg_one:
                self._shift_numbered(register)
            return
        if reg_one:
            self._shift_numbered(register)
        else:
            self.regs["-"] = register
            self.regs['"'] = register

    def op_change(self, reg, start, end, linewise, inclusive, empty, m=None, visual=False):
        from .editor_types import Register
        lines = self.lines
        if linewise:
            text = self.region_text(start, end, True, False)
            self.store_deleted(reg, Register(text, True), True)
            if end[0] > start[0]:
                self.del_lines(start[0] + 1, end[0] - start[0])
            indent = ""
            if self.opts["autoindent"]:
                line = lines[start[0]]
                indent = line[:T.first_nonblank(line)]
            self.set_line(start[0], indent)
            self.row, self.col = start[0], len(indent)
            self.ai_pending = bool(indent)
        else:
            if not empty:
                text = self.region_text(start, end, False, inclusive)
                self.store_deleted(reg, Register(text, False), (m is not None and m.reg_one) or len(text) > 1)
                ecol = end[1] + (1 if inclusive else 0)
                new = lines[start[0]][:start[1]] + lines[end[0]][ecol:]
                self.set_line(start[0], new)
                if end[0] > start[0]:
                    self.del_lines(start[0] + 1, end[0] - start[0])
            self.row, self.col = start
            self.col = min(self.col, len(self.lines[self.row]))
            self.ai_pending = False
        yield from self.insert_session(1, "c")

    def op_shift(self, op, r1, r2, amount):
        ts, sw = self.opts["tabstop"], self.opts["shiftwidth"] or self.opts["tabstop"]
        for r in range(r1, r2 + 1):
            line = self.lines[r]
            if line == "" and op == ">":
                continue
            width = T.indent_width(line, ts)
            body = line[T.first_nonblank(line):]
            width = width + sw * amount if op == ">" else max(width - sw * amount, 0)
            self.set_line(r, T.make_indent(width, ts, self.opts["expandtab"]) + body)
        self.row = r1
        self.col = self.first_nonblank_col(r1)
        self.set_curswant()
        n = r2 - r1 + 1
        if n > 2:
            self.say("%d lines %sed %d time" % (n, op, amount) + ("s" if amount > 1 else ""))

    def op_case(self, op, start, end, linewise, inclusive):
        lines = self.lines
        func = {"g~": str.swapcase, "gu": str.lower, "gU": str.upper}[op]
        if not linewise and not inclusive and start == end:
            # vim backs the end up by one before swapping an exclusive region: from column 0 that is the end of the previous line, and the whole line gets swapped
            if start[1] == 0:
                if start[0] > 0:
                    end, inclusive = (start[0], len(lines[start[0]]) - 1), True
                else:
                    inclusive = True
            else:
                self.row, self.col = start
                return
        for r in range(start[0], end[0] + 1):
            line = lines[r]
            if linewise:
                a, b = 0, len(line)
            else:
                a = start[1] if r == start[0] else 0
                b = (end[1] + (1 if inclusive else 0)) if r == end[0] else len(line)
            seg = line[a:b]
            new = self.convert_case(seg, func, op)
            self.set_line(r, line[:a] + new + line[b:])
        self.row, self.col = start
        if linewise:
            self.col = min(start[1], max(len(lines[start[0]]) - 1, 0))
        self.check_cursor()
        self.set_curswant()

    @staticmethod
    def convert_case(seg, func, op):
        out = []
        for ch in seg:
            c = func(ch)
            out.append(c if len(c) == 1 else ch)       # ß -> SS would change the length; vim keeps one character
        return "".join(out)

    # --- single commands -------------------------------------------------------------------------------------------------------------------------
    def tilde(self, n):
        line = self.line
        if not line:
            return
        end = min(self.col + n, len(line))
        seg = self.convert_case(line[self.col:end], str.swapcase, "g~")
        self.set_line(self.row, line[:self.col] + seg + line[end:])
        self.col = end
        self.check_cursor()
        self.set_curswant()

    def replace_chars(self, c, n):
        line = self.line
        if self.col + n > len(line):
            raise CmdError("")
        if c in ("\r", "\n"):
            self.set_line(self.row, line[:self.col])
            self.ins_lines(self.row + 1, [line[self.col + n:]])
            self.row += 1
            self.col = 0
        elif len(c) == 1 and c not in (ESC,):
            if c == "\x16":
                raise CmdError("")
            self.set_line(self.row, line[:self.col] + c * n + line[self.col + n:])
            self.col += n - 1
        else:
            raise CmdError("")
        self.set_curswant()

    def join_lines(self, count, spaces):
        """J / gJ: join ``count`` lines (at least two) starting at the cursor line, the way vim's do_join does: one space between, none after a tab or before a ')' or when
        the text so far is empty, none extra after a space, two after a full stop with 'joinspaces'."""
        lines = self.lines
        r = self.row
        if r + count - 1 > len(lines) - 1:
            if r >= len(lines) - 1:
                raise CmdError("")
            count = len(lines) - r
        pieces = []
        total = 0
        end1 = end2 = ""
        sep = ""
        curr = ""
        for t in range(count):
            curr = lines[r + t]
            sep = ""
            if spaces and t > 0:
                curr = curr.lstrip(" \t")
                if curr and curr[0] != ")" and total != 0 and end1 != "\t":
                    if end1 == " ":
                        end1 = end2
                    else:
                        sep = " "
                    if self.opts["joinspaces"] and end1 in (".", "?", "!"):
                        sep += " "
            pieces.append(sep + curr)
            total += len(sep) + len(curr)
            end1 = end2 = ""
            if spaces and curr:
                end1 = curr[-1]
                end2 = curr[-2] if len(curr) > 1 else ""
        col = total - len(curr) - len(sep)
        self.set_line(r, "".join(pieces))
        self.del_lines(r + 1, count - 1)
        self.row, self.col = r, col
        self.check_cursor()
        self.set_curswant()

    def put(self, after, count, reg, cursor_after=False):
        name = reg if reg else '"'
        if name == "_":
            return
        self.do_put(self.get_register(name), after, count or 1, cursor_after)

    def do_put(self, register, after, n, cursor_after=False, force_line=False, split=False):
        """p / P and the put of a visual selection. ``force_line``: take the text as whole lines; ``split``: break the current line first and put the lines between."""
        lines = self.lines
        text = register.lines
        linewise = register.linewise or force_line
        if split:
            line = lines[self.row]
            cut = self.col + (1 if (after and self.col < len(line)) else 0)
            self.set_line(self.row, line[:cut])
            self.ins_lines(self.row + 1, [line[cut:]])
            after = True
            linewise = True
        if linewise:
            at = self.row + 1 if after else self.row
            new = list(text) * n
            self.ins_lines(at, new)
            if cursor_after:
                self.row = min(at + len(new), len(self.lines) - 1)
                self.col = 0
            else:
                self.row = at
                self.col = self.first_nonblank_col(at)
            if len(new) > 2:
                self.say("%d more lines" % len(new))
        else:
            line = lines[self.row]
            idx = self.col + (1 if (after and line) else 0)
            idx = min(idx, len(line))
            if len(text) == 1:
                ins = text[0] * n
                self.set_line(self.row, line[:idx] + ins + line[idx:])
                self.col = (idx + len(ins) if cursor_after else idx + len(ins) - 1) if ins else idx
            else:
                before, rest = line[:idx], line[idx:]
                result = list(text)
                for _ in range(1, n):
                    result[-1] = result[-1] + text[0]
                    result.extend(text[1:])
                new_lines = [before + result[0]] + result[1:-1] + [result[-1] + rest]
                self.set_line(self.row, new_lines[0])
                self.ins_lines(self.row + 1, new_lines[1:])
                if cursor_after:
                    self.row += len(new_lines) - 1
                    self.col = len(result[-1])
                else:
                    self.col = idx
                if len(new_lines) > 2:
                    self.say("%d more lines" % (len(new_lines) - 1))
        self.check_cursor()
        self.set_curswant()

    def add_to_number(self, delta):
        """Ctrl-A / Ctrl-X: add to the number at or after the cursor."""
        line = self.line
        for m in re.finditer(r"-?\d+", line):
            if m.end() > self.col:
                text = str(int(m.group()) + delta)
                self.set_line(self.row, line[:m.start()] + text + line[m.end():])
                self.col = m.start() + len(text) - 1
                self.set_curswant()
                return
        raise CmdError("")

    def repeat_change(self, count):
        if self.redo is None:
            raise CmdError("")
        reg, cnt, keys = self.redo[:3]
        sel = self.redo[3] if len(self.redo) > 3 else None
        if count and sel is None:
            cnt = count
        saved = self.rec, self.replaying
        self.replaying = True
        try:
            if sel is not None:
                self.reselect(sel)
            gen = self.replay_command(reg, cnt, keys, sel is not None)
            next(gen)
            for k in keys[0:]:
                try:
                    gen.send(k)
                except StopIteration:
                    break
        finally:
            self.rec, self.replaying = saved
        if count and sel is None:
            self.redo = (reg, cnt, keys)

    def reselect(self, sel):
        """Repeating an operator that was done on a visual selection: select the same amount of text from the cursor."""
        mode, nrows, width = sel
        self.vstart = (self.row, self.col if mode == "v" else 0)
        last = len(self.lines) - 1
        r2 = min(self.row + nrows - 1, last)
        if mode == "V":
            self.row, self.col = r2, 0
        elif nrows == 1:
            self.col = min(self.col + width - 1, max(len(self.lines[r2]) - 1, 0))
        else:
            self.row = r2
            self.col = min(width - 1, max(len(self.lines[r2]) - 1, 0))
        self.mode = mode

    def replay_command(self, reg, count, keys, visual=False):
        """Run a recorded command again: its keys without the count and register, which are put in front again."""
        k = yield
        self.rec = [k]
        if visual:
            yield from self.visual_command(k, count, reg)
            return
        if self.mode in ("v", "V"):
            self.mode = "n"
        yield from self.command(k, count, reg)

    # --- scrolling and the screen ----------------------------------------------------------------------------------------------------------------
    def visible_rows(self):
        rows = max(self.size[0] - 2, 1)
        top = self.top
        return top, min(top + rows - 1, len(self.lines) - 1)

    def scroll_command(self, k, count):
        rows = max(self.size[0] - 2, 1)
        last = len(self.lines) - 1
        if k in ("\x04", "\x15"):
            amount = count or max(rows // 2, 1)
            if k == "\x04":
                if self.row >= last:
                    raise CmdError("")
                self.top = min(self.top + amount, last)
                self.row = min(self.row + amount, last)
            else:
                if self.row <= 0:
                    raise CmdError("")
                self.top = max(self.top - amount, 0)
                self.row = max(self.row - amount, 0)
            self.col = self.first_nonblank_col(self.row)
        elif k in ("\x06", "<PageDown>"):
            for _ in range(count or 1):
                self.top = min(self.top + max(rows - 2, 1), last)
            self.row = max(self.row, self.top)
            self.col = self.first_nonblank_col(self.row)
        elif k in ("\x02", "<PageUp>"):
            for _ in range(count or 1):
                self.top = max(self.top - max(rows - 2, 1), 0)
            self.row = min(self.row, self.top + rows - 1)
            self.col = self.first_nonblank_col(self.row)
        elif k == "\x05":
            self.top = min(self.top + (count or 1), last)
            self.row = max(self.row, self.top)
            self.col = self.col_for_want(self.row)
        elif k == "\x19":
            self.top = max(self.top - (count or 1), 0)
            self.row = min(self.row, self.top + rows - 1)
            self.col = self.col_for_want(self.row)
        self.set_curswant()

    def z_command(self, k, count):
        rows = max(self.size[0] - 2, 1)
        if count:
            self.row = min(count - 1, len(self.lines) - 1)
        if k in ("t", "\r"):
            self.top = self.row
        elif k in ("z", "."):
            self.top = max(self.row - rows // 2, 0)
        elif k in ("b", "-"):
            self.top = max(self.row - rows + 1, 0)
        else:
            raise CmdError("")
        if k in ("\r", ".", "-"):
            self.col = self.first_nonblank_col(self.row)

    def file_info(self):
        name = self.filename or "[No Name]"
        n = len(self.lines)
        pct = (self.row + 1) * 100 // n
        return '"%s"%s %d line%s --%d%%--' % (name, " [Modified]" if self.modified else "", n, "" if n == 1 else "s", pct)

    # --- visual mode -----------------------------------------------------------------------------------------------------------------------------
    def start_visual(self, k):
        self.vstart = (self.row, self.col)
        self.mode = k

    def end_visual(self):
        if self.vstart is not None:
            self.last_visual = (self.mode, self.vstart, (self.row, self.col))
        self.vstart = None
        self.mode = "n"

    def visual_region(self):
        a, b = self.vstart, (self.row, self.col)
        if b < a:
            a, b = b, a
        return a, b

    def visual_command(self, k, count, reg):
        n1 = count or 1
        if k in (ESC, "\x03"):
            self.end_visual()
            return
        if k in ("v", "V"):
            if self.mode == k:
                self.end_visual()
            else:
                self.mode = k
            return
        if k in ("o", "O"):
            self.vstart, (self.row, self.col) = (self.row, self.col), self.vstart
            self.set_curswant()
            return
        if k == ":":
            self.end_visual()
            text = yield from self.read_cmdline(":'<,'>")
            self.run_ex("'<,'>" + text)
            return
        if k in ("i", "a"):
            key = yield from self.getkey()
            m = self.text_object(k == "i", key, n1)
            if m is None:
                raise CmdError("")
            if m.linewise:
                self.mode = "V"
            elif self.mode == "V":
                self.mode = "v"
            if m.start is not None:
                self.vstart = m.start
            self.row, self.col = m.row, m.col
            if m.visual_end is not None:
                self.row, self.col = m.visual_end
            elif not m.inclusive and not m.linewise and self.col > 0:
                self.col -= 1
            return
        if k == "g":
            k2 = yield from self.getkey()
            if k2 in ("J",):
                a, b = self.visual_region()
                if self.mode == "V":
                    a = (a[0], 0)
                self.end_visual()
                self.row, self.col = a
                self.join_lines(max(b[0] - a[0] + 1, 2), False)
                return
            if k2 in ("u", "U", "~"):
                k = {"u": "u", "U": "U", "~": "~"}[k2]
            else:
                m = yield from self.get_motion("g" + k2, count, None)
                self.apply_motion(m)
                return
        if k in MOTION_KEYS:
            m = yield from self.get_motion(k, count, None)
            self.apply_motion(m)
            return
        ops = {"d": "d", "x": "d", "<Delete>": "d", "y": "y", "c": "c", "s": "c", "<": "<", ">": ">", "~": "g~", "u": "gu", "U": "gU"}
        if k in ops or k in ("X", "D", "Y", "C", "S", "R", "J", "r", "p", "P"):
            a, b = self.visual_region()
            linewise = self.mode == "V" or k in ("X", "D", "Y", "C", "S", "R")
            sel = ("V" if linewise else self.mode, b[0] - a[0] + 1, (b[1] - a[1] + 1) if a[0] == b[0] else b[1] + 1)
            if k not in ("y", "Y"):
                self.pending_visual_redo = (reg, count, sel)
            if linewise and self.vstart <= (self.row, self.col):
                a = (a[0], 0)                                  # (for a selection made backwards the start stays where the cursor is)
            if k == "J":
                self.end_visual()
                self.row, self.col = a
                self.join_lines(max(b[0] - a[0] + 1, 2), True)
                return
            if k == "r":
                c = yield from self.getkey()
                lines = self.lines
                for r in range(a[0], b[0] + 1):
                    line = lines[r]
                    if linewise:
                        lo, hi = 0, len(line)
                    else:
                        lo = a[1] if r == a[0] else 0
                        hi = (b[1] + 1) if r == b[0] else len(line)
                    hi = min(hi, len(line))
                    self.set_line(r, line[:lo] + c * (hi - lo) + line[hi:])
                self.end_visual()
                self.row, self.col = (a[0], 0) if linewise else a
                return
            if k in ("p", "P"):
                self.visual_put(k, reg, a, b, linewise)
                return
            op = ops.get(k) or {"X": "d", "D": "d", "Y": "y", "C": "c", "S": "c", "R": "c"}[k]
            self.end_visual()
            self.row, self.col = a
            yield from self.visual_operator(op, reg, a, b, linewise, True)
            return
        raise CmdError("")

    def visual_operator(self, op, reg, a, b, linewise, inclusive):
        start, end = a, b
        if not linewise and end[1] >= len(self.lines[end[0]]):
            inclusive = False
            if op not in ("<", ">") and end[0] < len(self.lines) - 1:
                end = (end[0] + 1, 0)
        self.row, self.col = start
        yield from self.apply_operator(op, reg, start, end, linewise, inclusive, False, None, True)

    def visual_put(self, k, reg, a, b, linewise):
        """p / P over a selection: delete the selection, then put the register where it was (above/before, or below/after if the deletion was at the end)."""
        name = reg if reg else '"'
        register = self.get_register(name)
        saved = Register(list(register.lines), register.linewise)
        mode = self.mode
        self.end_visual()
        start = (a[0], 0) if linewise else a
        end = b
        inclusive = True
        if not linewise and end[1] >= len(self.lines[end[0]]):
            inclusive = False
            if end[0] < len(self.lines) - 1:
                end = (end[0] + 1, 0)
        self.row, self.col = start
        regs_before = dict(self.regs) if k == "P" else None
        self.op_delete(None, start, end, linewise, inclusive, False, None, True)
        if regs_before is not None:
            self.regs = regs_before
        emptied = self.no_lines
        if linewise:
            after = self.row < start[0]
        else:
            after = self.col < start[1]
        if mode == "V":
            self.do_put(saved, after, 1, force_line=True)
        elif mode == "v" and saved.linewise:
            self.do_put(saved, after, 1, split=True)
        else:
            self.do_put(saved, after, 1)
        if emptied and len(self.lines) > 1 and self.lines[-1] == "":
            self.del_lines(len(self.lines) - 1, 1)
            self.row = min(self.row, len(self.lines) - 1)
        self.check_cursor()
        self.set_curswant()
