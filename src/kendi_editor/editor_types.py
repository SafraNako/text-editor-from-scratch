"""Small types shared by the editor modules."""
from __future__ import annotations


class Register:
    """The content of a register: the text split into lines, and whether it was taken linewise."""
    __slots__ = ("lines", "linewise")

    def __init__(self, lines, linewise):
        self.lines, self.linewise = lines, linewise

    def text(self):
        return "\n".join(self.lines) + ("\n" if self.linewise else "")


class RowTracker:
    """Rows that :global and :normal have to go back to while the commands they run insert and delete lines: they are followed through those changes. The rows are visited in
    increasing order, and a change before the next one to visit (nearly always the case: a command works on the line it is at) is recorded as one lazy offset, so that
    ``:g/x/d`` on a big file stays linear."""

    def __init__(self, rows):
        self.rows = list(rows)              # increasing
        self.dead = set()                   # indexes of rows whose line was deleted
        self.i = 0                          # the next index to visit
        self.lazy = 0                       # added to every row from index i on

    def next(self):
        """The current row of the next line to visit, or None when all were visited."""
        while self.i < len(self.rows):
            k = self.i
            self.i += 1
            if k not in self.dead:
                return self.rows[k] + self.lazy
        return None

    def _split(self, real):
        """The first index >= i whose current row is at least ``real``."""
        from bisect import bisect_left
        return bisect_left(self.rows, real - self.lazy, self.i)

    def inserted(self, r, k):
        lo = self._split(r)
        if lo == self.i:
            self.lazy += k
        else:
            for j in range(lo, len(self.rows)):
                self.rows[j] += k

    def deleted(self, r, n):
        lo, hi = self._split(r), self._split(r + n)
        for j in range(lo, hi):
            self.dead.add(j)
        if lo == self.i:
            self.lazy -= n
        else:
            for j in range(hi, len(self.rows)):
                self.rows[j] -= n
