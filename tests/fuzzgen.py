"""Random editing sessions: a small text and a random sequence of vim commands from the subset this editor implements."""
import random

WORDS = ["foo", "bar", "baz", "x", "hello", "world", "a_b", "x1", "é", "∑", "12", "end"]
PUNCT = [".", ",", "(", ")", "{", "}", "[", "]", "-", "+", "=", ";", ":", "\"", "'", "/"]


def random_text(rng):
    lines = []
    for _ in range(rng.randint(1, 8)):
        r = rng.random()
        if r < 0.12:
            lines.append("")
            continue
        if r < 0.18:
            lines.append(rng.choice(["  ", "\t", " \t "]))
            continue
        parts = []
        if rng.random() < 0.3:
            parts.append(rng.choice(["  ", "\t", "    ", " "]))
        for _ in range(rng.randint(1, 6)):
            parts.append(rng.choice(WORDS) if rng.random() < 0.7 else rng.choice(PUNCT))
            parts.append(rng.choice([" ", " ", " ", "  ", "", "\t"]))
        lines.append("".join(parts).rstrip() if rng.random() < 0.8 else "".join(parts))
    text = "\n".join(lines)
    return text + "\n"


MOTIONS = ["h", "l", "j", "k", "w", "W", "b", "B", "e", "E", "0", "^", "$", "gg", "G", "ge", "gE", "+", "-", "_", "|", "\x08", " "]
FIND = ["f", "F", "t", "T"]
CHARS = list("abcdeolrwx. (-") + ["é"]


class Gen:
    def __init__(self, seed, level="motions"):
        self.rng = random.Random(seed)
        self.level = level

    nlines = 8

    def count(self, p=0.25):
        return str(self.rng.choice([1, 2, 3, 5, 10])) if self.rng.random() < p else ""

    def counted(self, p=0.25):
        c = self.count(p)
        return c + self.motion(c)

    def motion(self, count=""):
        m = self._motion()
        return "^" if (count and m == "0") else m

    def _motion(self):
        r = self.rng.random()
        if r < 0.15:
            return self.rng.choice(FIND) + self.rng.choice(CHARS)
        if r < 0.2:
            return self.rng.choice([";", ","])
        return self.rng.choice(MOTIONS)

    def session(self):
        out = []
        for _ in range(self.rng.randint(1, 14)):
            out.append(self.counted())
        return "".join(out)


OPS = ["d", "d", "d", "c", "c", "y", "y", "<", ">", "g~", "gu", "gU"]
DOUBLE = {"d": "d", "c": "c", "y": "y", "<": "<", ">": ">", "g~": "g~", "gu": "gu", "gU": "gU"}
OBJECTS = ["w", "W", "\"", "'", "(", ")", "b", "{", "}", "B", "[", "]", "<", ">", "p"]
TYPED = ["foo", "bar", " ", "x", "1", "é", "\r", "\r", "\t", "  ", ".", "-", "end"]
PATTERNS = ["foo", "bar", "o", "x", "^", "$", "\\<e", "a*", "\\d\\+", "[a-c]", ".", "\\s", "e\\w*", "end$", "^$", "^\\s", "b\\|f"]
REGS = ["a", "b", "A", "_", "0", "1", "-"]


class Gen2(Gen):
    """The wider subset: operators with motions and text objects, inserts, put, join, replace, undo, visual mode, searches, ex commands."""

    def typed(self, special=True):
        n = self.rng.randint(0, 5)
        s = "".join(self.rng.choice(TYPED) for _ in range(n))
        if special and self.rng.random() < 0.15:
            s += "\x08" * self.rng.randint(1, 3) + self.rng.choice(TYPED)
        return s

    def insert_session(self, start=None):
        start = start or self.rng.choice(["i", "a", "I", "A", "o", "O"])
        text = self.typed()
        count = "" if "\x08" in text else self.count(0.15)         # (a count and a backspace in the typed text: vim repeats the keys, with surprising results)
        return count + start + text + "\x1b"

    def reg(self, p=0.15):
        return '"' + self.rng.choice(REGS) if self.rng.random() < p else ""

    def target(self):
        r = self.rng.random()
        if r < 0.22:
            return self.rng.choice("ia") + self.rng.choice(OBJECTS)
        if r < 0.36:
            return self.rng.choice(["/", "?"]) + self.rng.choice(PATTERNS) + "\r"
        if r < 0.42:
            return self.rng.choice(["}", "{", "%"])
        return self.counted(0.2)

    def operator(self):
        op = self.rng.choice(OPS)
        if self.rng.random() < 0.2:
            seq = self.count(0.2) + self.reg() + op + (op if len(op) == 1 else op[1])        # dd cc yy << >> g~~ guu gUU
        else:
            seq = self.count(0.15) + self.reg() + op + self.target()
        if op == "c":
            seq += self.typed() + "\x1b"
        return seq

    def simple(self):
        r = self.rng.random()
        if r < 0.12:
            return self.count(0.2) + self.rng.choice(["x", "X", "D", "Y", "J", "~", "gJ", "p", "P"])
        if r < 0.2:
            return self.count(0.2) + self.reg(0.3) + self.rng.choice(["p", "P", "x", "dd", "yy", "yw", "D"])
        if r < 0.28:
            return self.count(0.1) + "r" + self.rng.choice(CHARS + ["\r"])
        if r < 0.36:
            return self.count(0.15) + self.rng.choice(["C", "s", "S"]) + self.typed() + "\x1b"
        if r < 0.42:
            return self.rng.choice(["u", "u", "\x12", ".", ".", "2u", "3."])
        return self.insert_session()

    def visual(self):
        v = self.rng.choice(["v", "V"])
        moves = "".join(self.counted(0.2) for _ in range(self.rng.randint(0, 3)))
        if self.rng.random() < 0.1:
            moves += "i" + self.rng.choice(["w", "(", "\"", "p"])
        end = self.rng.choice(["d", "y", "c", "<", ">", "~", "u", "U", "J", "x", "o" + self.motion() + "d", "r" + self.rng.choice(CHARS), "p", "\x1b", "X", "D", "Y", "S", "R", "gJ"])
        s = v + moves + end
        if end in ("c", "S", "R"):
            s += self.typed() + "\x1b"
        if end == "p":
            s = "yy" + s
        return s

    def search(self):
        r = self.rng.random()
        if r < 0.5:
            return self.rng.choice(["/", "?"]) + self.rng.choice(PATTERNS) + "\r"
        return self.count(0.2) + self.rng.choice(["n", "N", "*", "#"])

    def ex(self):
        rng = self.rng
        n = self.nlines
        rngs = rng.choice(["", "", "%", "1,%d" % min(2, n), "%d,$" % min(2, n), ".,+1" if n > 1 else ".", "$", "1", ".", "%d" % min(2, n), "/foo/", "'a,.", ".,.+%d" % min(2, n - 1)])
        pat = rng.choice(["foo", "o", "a", "x", "e", "^", "$", "\\s\\+", "\\w\\+", "b\\(a\\)r", ".", "\\<", "[aeiou]"])
        rep = rng.choice(["X", "&&", "[&]", "\\1", "\\r", "-", "", "\\u&", "\\U&\\E!", "a\\tb"])
        flags = rng.choice(["", "g", "g", "gi", "i"])
        cmds = [rngs + "s/" + pat + "/" + rep + "/" + flags, rngs + "d", rngs + "y", rngs + "m0", rngs + "m$", rngs + "t.", rngs + "t0", rngs + "j", rngs,
                "g/" + pat + "/d", "v/" + pat + "/d", "g/" + pat + "/s/" + "o" + "/0/", "g/" + pat + "/normal Ax", rngs + "normal Ix", "%norm A;", "g/" + pat + "/m0",
                rngs + "sort", "set ts=4", "set sw=4 et", "noh", rngs + "pu", rngs + "pu!", "%s//Z/g", "s", "&&", "ka", rngs + "j!"]
        return ":" + rng.choice(cmds) + "\r"

    def session(self):
        return "".join(self.parts())

    def parts(self):
        out = []
        for _ in range(self.rng.randint(1, 10)):
            r = self.rng.random()
            if r < 0.22:
                out.append(self.counted())
            elif r < 0.55:
                out.append(self.operator())
            elif r < 0.72:
                out.append(self.simple())
            elif r < 0.8:
                out.append(self.visual())
            elif r < 0.88:
                out.append(self.search())
            elif r < 0.93:
                out.append(self.rng.choice(["ma", "mb"]) if self.rng.random() < 0.5 else "'" + self.rng.choice("ab") + self.rng.choice(["", "d'a"]))
            else:
                out.append(self.ex())
        return out
