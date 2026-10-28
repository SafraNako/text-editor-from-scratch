"""``ked``: the command line and the main loop that joins the terminal, the key decoder, the editor and the screen."""
from __future__ import annotations

import os
import sys

from . import __version__
from .editor import Editor
from .errors import CmdError
from .keys import Decoder, ScriptDecoder
from .screen import render
from .terminal import Terminal

USAGE = """usage: ked [options] [+LINE] [file]

options:
  -R            read-only
  -c COMMAND    run an ex command after the file is loaded (may be given more than once)
  -s SCRIPT     read the keys to type from a file (like vim -s), no terminal needed
  --version     print the version
  -h, --help    print this help
"""
ESC_TIMEOUT = 0.05


def parse_args(argv):
    opts = {"readonly": False, "commands": [], "script": None, "file": None, "line": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            sys.stdout.write(USAGE)
            return None
        if a == "--version":
            sys.stdout.write("ked %s\n" % __version__)
            return None
        if a == "-R":
            opts["readonly"] = True
        elif a == "-c" and i + 1 < len(argv):
            opts["commands"].append(argv[i + 1])
            i += 1
        elif a == "-s" and i + 1 < len(argv):
            opts["script"] = argv[i + 1]
            i += 1
        elif a.startswith("+") and a[1:].isdigit():
            opts["line"] = int(a[1:])
        elif a == "--":
            i += 1
            if i < len(argv):
                opts["file"] = argv[i]
            break
        elif a.startswith("-") and len(a) > 1:
            sys.stderr.write("ked: unknown option %s\n%s" % (a, USAGE))
            return False
        else:
            if opts["file"] is not None:
                sys.stderr.write("ked: only one file can be edited\n")
                return False
            opts["file"] = a
        i += 1
    return opts


def open_editor(opts, size):
    ed = Editor.open(opts["file"], size) if opts["file"] else Editor("", None, size)
    if opts["readonly"]:
        ed.readonly = True
    if opts["line"]:
        ed.row = max(0, min(opts["line"] - 1, len(ed.lines) - 1))
        ed.col = ed.first_nonblank_col(ed.row)
        ed.set_curswant()
    for cmd in opts["commands"]:
        try:
            ed.run_ex(cmd)
        except CmdError as exc:
            ed.say(str(exc), True)
    return ed


def run_script(opts):
    """Type the keys of a script file into the editor, without a terminal."""
    with open(opts["script"], "rb") as f:
        data = f.read()
    ed = open_editor(opts, (24, 80))
    for key in ScriptDecoder().feed(data):
        if ed.quit:
            break
        ed.feed(key)
    return 0


def feed_keys(ed, keys):
    for key in keys:
        if isinstance(key, tuple):
            ed.feed_paste(key[1])
        else:
            ed.feed(key)


def run_terminal(opts):
    with Terminal() as term:
        ed = open_editor(opts, term.size())
        decoder = Decoder()
        previous = []
        force = True
        rows, cols = term.size()
        while not ed.quit:
            ed.size = (rows, cols)
            frame = render(ed, rows, cols)
            out = ["\x1b[?25l"]
            for i, row in enumerate(frame.rows):
                if force or i >= len(previous) or previous[i] != row:
                    out.append("\x1b[%d;1H%s" % (i + 1, row))
            previous = frame.rows
            force = False
            r, c = frame.cursor
            out.append("\x1b[%d;%dH\x1b[%s q\x1b[?25h" % (r + 1, c + 1, "6" if ed.mode == "i" else "2"))
            term.write("".join(out))
            data = term.read(ESC_TIMEOUT if decoder.pending() else None)
            if data is None:
                rows, cols = term.size()
                force = True
                continue
            if data == b"":
                keys = decoder.flush()
            else:
                keys = decoder.feed(data)
            feed_keys(ed, keys)
            if "\x0c" in keys:
                force = True
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = parse_args(argv)
    if opts is None:
        return 0
    if opts is False:
        return 2
    try:
        if opts["script"]:
            return run_script(opts)
        if not (os.isatty(0) and os.isatty(1)):
            sys.stderr.write("ked: input and output must be a terminal (use -s SCRIPT to run without one)\n")
            return 1
        return run_terminal(opts)
    except EOFError:
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":                                                  # pragma: no cover
    sys.exit(main())
