"""Searching: /, ?, n, N, * and #, on top of the vim pattern translation."""
from __future__ import annotations

from . import text as T
from .errors import CmdError
from .vimregex import compile_pattern


class SearchMixin:
    def compile(self, pat, use_smartcase=True):
        return compile_pattern(pat, self.opts["ignorecase"], self.opts["smartcase"], use_smartcase)

    def find_match(self, rx, row, col, forward, count=1):
        """The position of the count-th match after (or before) ``(row, col)``, wrapping round the buffer if 'wrapscan' is on; None if there is no match.
        A match at the end of a line counts as being on the last character, like in vim, so that /$ does not get stuck."""
        lines = self.lines
        n = len(lines)
        pos = (row, col)
        wrapped = False
        for _ in range(count):
            found = self._one_match(rx, pos, forward)
            if found is None and self.opts["wrapscan"]:
                found = self._one_match(rx, (-1, 0) if forward else (n, 0), forward)
                wrapped = found is not None
            if found is None:
                return None
            pos = found
        self.search_wrapped = wrapped
        return pos

    def _one_match(self, rx, pos, forward):
        lines = self.lines
        row, col = pos
        n = len(lines)
        if forward:
            r = max(row, 0)
            while r < n:
                line = lines[r]
                start = 0
                while start <= len(line):
                    m = rx.search(line, start)
                    if m is None:
                        break
                    mc = m.start()
                    eff = mc - 1 if (mc == len(line) and mc > 0) else mc
                    if r != row or eff > col:
                        return (r, mc)
                    start = mc + 1 if m.end() == mc else max(m.end(), mc + 1)
                r += 1
            return None
        r = min(row, n - 1)
        while r >= 0:
            line = lines[r]
            best = None
            start = 0
            while start <= len(line):
                m = rx.search(line, start)
                if m is None:
                    break
                mc = m.start()
                if r != row or mc < col:                    # (backwards, a match on the end of a line is not moved back by one)
                    best = mc
                start = mc + 1 if m.end() == mc else max(m.end(), mc + 1)
            if best is not None:
                return (r, best)
            r -= 1
        return None

    def search_command(self, pat, forward, count, remember=True, use_smart=True):
        """Run a search from the cursor: returns the target position (None if not found) and sets the last pattern."""
        if pat == "":
            if self.last_search is None:
                raise CmdError("E35: No previous regular expression")
            pat = self.last_search[0]
        rx = self.compile(pat, use_smart)
        if remember:
            self.last_search = (pat, forward)
        pos = self.find_match(rx, self.row, self.col, forward, count)
        if pos is None:
            raise CmdError("E486: Pattern not found: %s" % pat)
        if self.search_wrapped:
            self.say("search hit %s, continuing at %s" % (("BOTTOM", "TOP") if forward else ("TOP", "BOTTOM")), error=True)
        else:
            self.say(("/" if forward else "?") + pat)
        return pos

    def word_under_cursor(self):
        """The word at or after the cursor on its line, for * and #: (text, is_keyword)."""
        line = self.line
        i = self.col
        while i < len(line) and T.word_class(line[i]) != 2:
            i += 1
        if i < len(line):
            s = i
            while s > 0 and T.word_class(line[s - 1]) == 2:
                s -= 1
            e = i
            while e < len(line) and T.word_class(line[e]) == 2:
                e += 1
            return line[s:e], True, s
        i = self.col
        while i < len(line) and T.word_class(line[i]) == 0:
            i += 1
        if i >= len(line):
            return None, False, 0
        s = i
        while s > 0 and T.word_class(line[s - 1]) == 1:
            s -= 1
        e = i
        while e < len(line) and T.word_class(line[e]) == 1:
            e += 1
        return line[s:e], False, s
