"""What the editor looks like: the text window (with soft wrapping, tabs, control characters, wide characters, line numbers and the visual selection), a status line and the
message / command line, as a list of rows. A row is a string with ANSI colours (what is written to the terminal) and a plain version (for tests)."""
from __future__ import annotations

from . import text as T

NORMAL, REVERSE, TILDE, CONTROL, SELECT, SEARCH, ERROR, STATUS, NUMBER, CURNUMBER = range(10)
SGR = {NORMAL: "0", REVERSE: "0;7", TILDE: "0;34", CONTROL: "0;34", SELECT: "0;7", SEARCH: "0;30;43", ERROR: "0;97;41", STATUS: "0;7;1", NUMBER: "0;33", CURNUMBER: "0;1;33"}
MODE_NAMES = {"n": "NORMAL", "i": "INSERT", "v": "VISUAL", "V": "V-LINE", "r": "REPLACE", "c": "COMMAND"}


class Frame:
    def __init__(self, rows, plain, cursor):
        self.rows = rows            # ANSI strings, one per terminal row
        self.plain = plain          # the same without colours, trailing spaces removed
        self.cursor = cursor        # (row, col) on the screen, 0-based


def cells_of(line, ts, base_attr=NORMAL):
    """The screen cells of a line: a list of (character shown, attribute, buffer column); a wide character is followed by an empty cell."""
    out = []
    v = 0
    for i, ch in enumerate(line):
        if ch == "\t":
            n = ts - v % ts
            out.extend((" ", base_attr, i) for _ in range(n))
            v += n
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(("^", CONTROL, i))
            out.append((chr(ord(ch) ^ 64), CONTROL, i))
            v += 2
        elif 0x80 <= ord(ch) < 0xA0 or 0xDC80 <= ord(ch) <= 0xDCFF:
            code = ord(ch) if ord(ch) < 0x100 else ord(ch) - 0xDC00
            text = "<%02x>" % code
            out.extend((c, CONTROL, i) for c in text)
            v += 4
        else:
            w = T.char_cells(ch)
            if w == 0:
                if out:
                    prev = out[-1]
                    out[-1] = (prev[0] + ch, prev[1], prev[2]) if prev[0] != "" else prev
                continue
            out.append((ch, base_attr, i))
            if w == 2:
                out.append(("", base_attr, i))
            v += w
    return out


def row_to_ansi(cells):
    out = []
    attr = NORMAL
    plain = []
    for ch, a in cells:
        if a != attr:
            out.append("\x1b[%sm" % SGR[a])
            attr = a
        out.append(ch)
        plain.append(ch)
    if attr != NORMAL:
        out.append("\x1b[0m")
    return "".join(out) + "\x1b[K", "".join(plain).rstrip()


def render(ed, rows, cols):
    """Draw the editor into ``rows`` x ``cols`` and say where the cursor is."""
    ts = ed.opts["tabstop"]
    text_rows = max(rows - 2, 1) if rows >= 3 else max(rows - 1, 1)
    lines = ed.lines
    n = len(lines)
    number = ed.opts["number"] or ed.opts["relativenumber"]
    gutter = (max(3, len(str(n))) + 1) if number else 0
    avail = max(cols - gutter, 1)
    wrap = ed.opts["wrap"]

    def height(r):
        if not wrap:
            return 1
        w = T.line_cells(lines[r], ts)
        if ed.mode in ("i", "r", "v", "V") and r == ed.row:
            w += 1
        return max(1, -(-w // avail))

    ed.top = max(0, min(ed.top, n - 1))
    adjust_top(ed, text_rows, height)
    sel = selection_ranges(ed) if ed.mode in ("v", "V") else None
    hl_rx = search_pattern(ed) if ed.opts["hlsearch"] and ed.last_search and not ed.hl_off else None
    screen = []
    cursor = (0, 0)
    leftcol = 0
    r = ed.top
    cursor_cell = None
    last_shown = r
    while len(screen) < text_rows and r < n:
        line = lines[r]
        cl = cells_of(line, ts)
        attrs = [c[1] for c in cl]
        if sel is not None and r in sel:
            lo, hi = sel[r]
            for k, c in enumerate(cl):
                if lo <= c[2] <= hi:
                    attrs[k] = SELECT
            if hi >= len(line) and lo <= len(line) and line is not None:
                cl = cl + [(" ", SELECT, len(line))]
                attrs.append(SELECT)
        if hl_rx is not None and len(line) < 5000:
            for found in hl_rx.finditer(line):
                m0, m1 = found.start(), found.end()
                for k, c in enumerate(cl):
                    if m0 <= c[2] < max(m1, m0 + 1) and attrs[k] == NORMAL:
                        attrs[k] = SEARCH
        h = height(r)
        if r == ed.row:
            cur_v = cursor_vcol(ed, ts)
            cursor_cell = cur_v
        if not wrap and r == ed.row:
            leftcol = horizontal_scroll(ed, cur_v, avail, ed.leftcol if hasattr(ed, "leftcol") else 0)
            ed.leftcol = leftcol
        if number:
            label = line_label(ed, r, gutter)
        segments = []
        if wrap:
            for s in range(h):
                segments.append((s * avail, cl[s * avail:(s + 1) * avail], attrs[s * avail:(s + 1) * avail]))
        else:
            lc = ed.leftcol if r == ed.row else getattr(ed, "leftcol", 0)
            segments.append((lc, cl[lc:lc + avail], attrs[lc:lc + avail]))
        if len(screen) + len(segments) > text_rows and screen:
            # the last line does not fit: vim shows @ for the rows it would need
            while len(screen) < text_rows:
                screen.append([("@", TILDE)] + [])
            break
        for si, (start, seg, seg_attrs) in enumerate(segments):
            if len(screen) >= text_rows:
                break
            prefix = []
            if number:
                if si == 0:
                    prefix = [(c, CURNUMBER if r == ed.row else NUMBER) for c in label]
                else:
                    prefix = [(" ", NORMAL)] * gutter
            row_cells = prefix + [(c[0], a) for c, a in zip(seg, seg_attrs)]
            if r == ed.row and cursor_cell is not None:
                base = start if wrap else getattr(ed, "leftcol", 0)
                if base <= cursor_cell < base + avail or (wrap and si == len(segments) - 1 and cursor_cell >= base):
                    cursor = (len(screen), gutter + min(cursor_cell - base, avail - 1) if wrap else gutter + cursor_cell - base)
            screen.append(row_cells)
        last_shown = r
        r += 1
    while len(screen) < text_rows:
        screen.append([("~", TILDE)])
    ansi, plain = [], []
    for row in screen:
        a, p = row_to_ansi(row)
        ansi.append(a)
        plain.append(p)
    # the status line and the message line
    if rows >= 3:
        status = status_line(ed, cols, last_shown)
        a, p = row_to_ansi(status)
        ansi.append(a)
        plain.append(p)
    message, msg_cursor = message_line(ed, cols)
    a, p = row_to_ansi(message)
    ansi.append(a)
    plain.append(p)
    if ed.cmdline is not None:
        cursor = (rows - 1, msg_cursor)
    return Frame(ansi[:rows], plain[:rows], cursor)


def cursor_vcol(ed, ts):
    line = ed.lines[ed.row]
    if ed.mode in ("i", "r"):
        return T.vcol_start(line, ed.col, ts)
    return T.vcol_end(line, ed.col, ts) if ed.col < len(line) else T.vcol_start(line, ed.col, ts)


def adjust_top(ed, text_rows, height):
    """Scroll so that the cursor line is in the window: by as little as possible if it is just outside, to the middle if it jumped further than half a window."""
    n = len(ed.lines)
    row = ed.row
    half = text_rows // 2

    def rows_between(a, b):
        """The display rows of lines a .. b-1, counted only as far as the window is tall (more than that is all we need to know)."""
        total = 0
        for r in range(a, min(b, n)):
            total += height(r)
            if total > text_rows:
                break
        return total

    def centre():
        top, above = row, 0
        while top > 0 and above + height(top - 1) <= half:
            top -= 1
            above += height(top)
        while top > 0 and rows_between(top, n) < text_rows:        # no empty rows below the last line while there are lines above it to show instead
            top -= 1
        return top

    if row < ed.top:
        ed.top = row if ed.top - row <= half else centre()
        return
    if row - ed.top >= text_rows + half:                           # further off than the window can hold: a jump
        ed.top = centre()
        return
    used = rows_between(ed.top, row + 1)
    if used <= text_rows:
        return
    if used - text_rows <= half:
        while ed.top < row and rows_between(ed.top, row + 1) > text_rows:
            ed.top += 1
    else:
        ed.top = centre()


def horizontal_scroll(ed, vcol, avail, left):
    if vcol < left:
        left = vcol
    elif vcol >= left + avail:
        left = vcol - avail + 1
    return max(left, 0)


def line_label(ed, r, gutter):
    if ed.opts["relativenumber"]:
        if r == ed.row:
            n = r + 1 if ed.opts["number"] else 0
            return (str(n).ljust(gutter - 1) if ed.opts["number"] else "0".rjust(gutter - 1)) + " "
        return str(abs(r - ed.row)).rjust(gutter - 1) + " "
    return str(r + 1).rjust(gutter - 1) + " "


def selection_ranges(ed):
    """{row: (first column, last column)} of the visual selection."""
    if ed.vstart is None:
        return None
    a, b = ed.vstart, (ed.row, ed.col)
    if b < a:
        a, b = b, a
    out = {}
    for r in range(a[0], b[0] + 1):
        if ed.mode == "V":
            out[r] = (0, max(len(ed.lines[r]), 0))
        else:
            lo = a[1] if r == a[0] else 0
            hi = b[1] if r == b[0] else len(ed.lines[r])
            out[r] = (lo, hi)
    return out


def search_pattern(ed):
    try:
        return ed.compile(ed.last_search[0])
    except Exception:
        return None


def status_line(ed, cols, last_shown=0):
    """`` NORMAL  name [+]            row,col  pct``: the name is shortened from the left ("<ame") when the line is too narrow."""
    name = ed.filename or "[No Name]"
    flags = (" [+]" if ed.modified else "") + (" [RO]" if ed.readonly else "") + (" [New]" if ed.is_new and ed.filename else "")
    mode = MODE_NAMES.get(ed.mode, "NORMAL")
    n = len(ed.lines)
    above, below = ed.top, n - 1 - last_shown
    pct = "All" if above == 0 and below <= 0 else ("Top" if above == 0 else ("Bot" if below <= 0 else "%d%%" % (above * 100 // (above + below))))
    col = T.vcol_start(ed.lines[ed.row], ed.col, ed.opts["tabstop"]) + 1
    right = "%d,%s  %s " % (ed.row + 1, str(ed.col + 1) if col == ed.col + 1 else "%d-%d" % (ed.col + 1, col), pct)
    room = cols - len(right) - len(mode) - len(flags) - 5
    if len(name) > room:
        name = "<" + name[len(name) - max(room - 1, 1):] if room > 1 else name[:max(room, 0)]
    left = " %s  %s%s" % (mode, name, flags)
    pad = max(cols - len(left) - len(right), 1)
    text = (left + " " * pad + right)[:cols]
    return [(c, STATUS) for c in text.ljust(cols)]


def message_line(ed, cols):
    """The bottom line: the command being typed, else the message, else the mode in the style of vim; plus the keys of an unfinished command at the right."""
    if ed.cmdline is not None:
        prefix, text = ed.cmdline
        shown = (prefix + text)[-(cols - 1):]
        return [(c, NORMAL) for c in shown], min(len(shown), cols - 1)
    if ed.msg:
        first = ed.msg.split("\n")[0][:cols - 1]
        return [(c, ERROR if ed.msg_error else NORMAL) for c in first], 0
    if ed.mode == "i":
        text = "-- INSERT --"
    elif ed.mode == "r":
        text = "-- REPLACE --"
    elif ed.mode == "v":
        text = "-- VISUAL --"
    elif ed.mode == "V":
        text = "-- VISUAL LINE --"
    else:
        text = ""
    pend = ed.pending
    cells = [(c, NORMAL) for c in text]
    if pend:
        cells += [(" ", NORMAL)] * max(cols - len(cells) - len(pend) - 12, 1) + [(c, NORMAL) for c in pend]
    return cells, 0
