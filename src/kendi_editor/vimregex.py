"""Vim's search patterns (the "magic" syntax) turned into Python regular expressions: ``\\<`` ``\\>`` ``\\(`` ``\\)`` ``\\|`` ``\\+`` ``\\?`` ``\\=`` ``\\{n,m}``, the ``\\s \\d \\w \\a \\l \\u \\x``
classes, bracket expressions with ``[:alpha:]``, ``^`` and ``$`` only where they are anchors, ``\\c`` and ``\\C``. Patterns are matched line by line, so ``\\n`` is not supported."""
from __future__ import annotations

import re

from .errors import CmdError

CLASSES = {"s": "[ \\t]", "S": "[^ \\t]", "d": "[0-9]", "D": "[^0-9]", "w": "[0-9A-Za-z_]", "W": "[^0-9A-Za-z_]", "a": "[A-Za-z]", "A": "[^A-Za-z]", "l": "[a-z]", "L": "[^a-z]",
           "u": "[A-Z]", "U": "[^A-Z]", "x": "[0-9A-Fa-f]", "X": "[^0-9A-Fa-f]", "o": "[0-7]", "O": "[^0-7]", "h": "[A-Za-z_]", "H": "[^A-Za-z_]"}
POSIX = {"alpha": "A-Za-z", "digit": "0-9", "alnum": "0-9A-Za-z", "lower": "a-z", "upper": "A-Z", "space": " \\t\\n\\r\\f\\v", "blank": " \\t", "punct": "!-/:-@\\[-`{-~",
         "xdigit": "0-9A-Fa-f", "cntrl": "\\x00-\\x1f\\x7f", "print": " -~", "graph": "!-~"}
ESCAPES = {"e": "\\x1b", "t": "\\t", "r": "\\r", "b": "\\x08"}


def translate(pat):
    """``(python pattern, case flag)``: the flag is "i", "I" (ignore / match case, from \\c and \\C) or None."""
    out = []
    flag = None
    i, n = 0, len(pat)
    at_start = True                                   # at the start of the pattern, of a group or of an alternative: ^ is an anchor and * is literal
    while i < n:
        c = pat[i]
        if c == "\\":
            i += 1
            if i >= n:
                raise CmdError("E10: \\ should be followed by /, ? or &")
            c = pat[i]
            if c == "c":
                flag = "i"
            elif c == "C":
                flag = "I"
            elif c == "<":
                out.append("\\b(?=\\w)")
            elif c == ">":
                out.append("\\b(?<=\\w)")
            elif c == "(":
                out.append("(")
                at_start = True
                i += 1
                continue
            elif c == "%" and pat[i + 1:i + 2] == "(":
                out.append("(?:")
                at_start = True
                i += 2
                continue
            elif c == ")":
                out.append(")")
            elif c == "|":
                out.append("|")
                at_start = True
                i += 1
                continue
            elif c in "+?":
                out.append(c)
            elif c == "=":
                out.append("?")
            elif c == "{":
                j = pat.find("}", i)
                if j < 0:
                    raise CmdError("E554: Syntax error in \\{...}")
                body = pat[i + 1:j].rstrip("\\")
                lazy = body.startswith("-")
                body = body[1:] if lazy else body
                if body == "":
                    q = "*"
                elif "," in body:
                    lo, hi = body.split(",", 1)
                    q = "{%s,%s}" % (lo or "0", hi)
                else:
                    q = "{%s}" % body
                out.append(q + ("?" if lazy else ""))
                i = j
            elif c in CLASSES:
                out.append(CLASSES[c])
            elif c in ESCAPES:
                out.append(ESCAPES[c])
            elif c.isdigit() and c != "0":
                out.append("\\" + c)
            elif c == "n" or c in "zvVmM%@_":
                raise CmdError("E486: Pattern uses an unsupported item: \\" + c)
            else:
                out.append(re.escape(c))
            at_start = False
        elif c == "[":
            j = _collection_end(pat, i)
            if j < 0:
                out.append("\\[")
            else:
                out.append(_collection(pat[i + 1:j]))
                i = j
            at_start = False
        elif c == ".":
            out.append(".")
            at_start = False
        elif c == "*":
            out.append("\\*" if at_start else "*")
        elif c == "^":
            out.append("^" if at_start else "\\^")
        elif c == "$":
            rest = pat[i + 1:]
            out.append("$" if (rest == "" or rest.startswith("\\)") or rest.startswith("\\|")) else "\\$")
            at_start = False
        else:
            out.append(re.escape(c))
            at_start = False
        if c != "^" and not (c == "*" and at_start):
            at_start = False
        i += 1
    return "".join(out), flag


def _collection_end(pat, i):
    """The index of the ] that closes the [ at ``i``, or -1 (then the [ is an ordinary character)."""
    j = i + 1
    if j < len(pat) and pat[j] == "^":
        j += 1
    if j < len(pat) and pat[j] == "]":
        j += 1
    while j < len(pat):
        if pat[j] == "\\" and j + 1 < len(pat):
            j += 2
            continue
        if pat[j] == "[" and pat[j + 1:j + 2] == ":":
            k = pat.find(":]", j + 2)
            if k >= 0:
                j = k + 2
                continue
        if pat[j] == "]":
            return j
        j += 1
    return -1


def _collection(body):
    neg = body.startswith("^")
    if neg:
        body = body[1:]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            d = body[i + 1]
            out.append(ESCAPES.get(d, re.escape(d)) if d in ESCAPES else ("\\\\" if d == "\\" else re.escape(d)))
            i += 2
        elif c == "[" and body[i + 1:i + 2] == ":":
            k = body.find(":]", i + 2)
            name = body[i + 2:k] if k >= 0 else ""
            if name in POSIX:
                out.append(POSIX[name])
                i = k + 2
            else:
                out.append("\\[")
                i += 1
        elif c in "[]^\\":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "[" + ("^" if neg else "") + "".join(out) + "]"


def compile_pattern(pat, ignorecase=False, smartcase=False, use_smartcase=True):
    """A compiled Python pattern for a vim pattern; raises CmdError for a pattern vim would not accept (or that needs more than this engine does)."""
    try:
        py, flag = translate(pat)
        if flag == "i":
            ic = True
        elif flag == "I":
            ic = False
        else:
            ic = ignorecase
            if ic and smartcase and use_smartcase and has_upper(pat):
                ic = False
        return re.compile(py, re.IGNORECASE if ic else 0)
    except re.error as exc:
        raise CmdError("E486: Pattern not found: %s" % pat) from exc


def has_upper(pat):
    """Smart case: an upper-case letter that is not part of a \\x escape."""
    i = 0
    while i < len(pat):
        if pat[i] == "\\":
            i += 2
            continue
        if pat[i].isupper():
            return True
        i += 1
    return False
