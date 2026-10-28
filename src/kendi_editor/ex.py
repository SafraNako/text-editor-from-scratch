"""The command line (:) of the editor: ranges and the commands :w :q :wq :x :e :d :y :s :> :< :j :m :t :pu :set :noh :normal :g and a few more."""
from __future__ import annotations

import re

from . import text as T
from .errors import CmdError
from .vimregex import compile_pattern

COMMANDS = [("write", 1), ("wq", 2), ("xit", 1), ("quit", 1), ("edit", 1), ("delete", 1), ("yank", 1), ("substitute", 1), ("set", 2), ("nohlsearch", 3), ("join", 1), ("move", 1),
            ("t", 1), ("copy", 2), ("put", 2), ("normal", 4), ("global", 1), ("vglobal", 1), ("undo", 1), ("redo", 3), ("read", 1), ("file", 1), ("registers", 3), ("display", 2),
            ("wall", 2), ("qall", 2), ("wqall", 3), ("xall", 2), ("help", 1), ("version", 2), ("mark", 2), ("k", 1), ("print", 1), ("number", 2), ("saveas", 3), ("update", 2),
            ("&", 1), ("&&", 2), ("~", 1), (">", 1), ("<", 1), ("=", 1), ("sort", 3), ("retab", 3), ("left", 2), ("right", 2), ("center", 2)]


class ExMixin:
    def run_ex(self, text):
        """Run one command line (without the colon). Errors are CmdError."""
        text = text.lstrip(" \t:")
        if text == "" or text.startswith('"'):
            return
        before = (self.row, self.col)
        try:
            self.run_ex_line(text)
        finally:
            if (self.row, self.col) != before:
                self.check_cursor()
                self.set_curswant()

    def run_ex_line(self, text):
        # several commands separated by | (not for :normal, :g, which take the rest of the line)
        pos = 0
        rng, pos = self.parse_range(text, 0)
        m = re.match(r"[a-zA-Z]+|[&~<>=!@*]+|", text[pos:])
        word = m.group(0) if m else ""
        if word and word[0] in "&~<>=" and word != "&&":
            word = word[0]
        rest = text[pos + len(word):]
        # 's' followed by a non-letter delimiter, 'g' too: the name is the letters only
        if len(word) == 2 and word[0] == "k" and word not in ("ke",):
            word, rest = "k", word[1] + rest                           # :ka is :k a
        name = self.resolve_command(word)
        bang = False
        if rest.startswith("!") and name in ("write", "quit", "wq", "xit", "edit", "undo", "global", "read", "join", "put", "wall", "qall", "wqall", "xall", "sort", "update"):
            bang = True
            rest = rest[1:]
        if name == "global" and word.startswith("g") and rest.startswith("!"):
            name, rest = "vglobal", rest[1:]
        args = rest
        if name in ("normal", "global", "vglobal", "substitute", "&", "&&", "~"):
            body = args
        else:
            parts = self.split_bar(args)
            body = parts[0]
            if len(parts) > 1:
                self.dispatch_ex(name, rng, bang, body)
                self.run_ex(args[len(body) + 1:])
                return
        self.dispatch_ex(name, rng, bang, body)

    @staticmethod
    def split_bar(args):
        out, cur, i = [], "", 0
        while i < len(args):
            if args[i] == "\\" and i + 1 < len(args):
                cur += args[i:i + 2]
                i += 2
                continue
            if args[i] == "|":
                out.append(cur)
                cur = ""
                i += 1
                continue
            cur += args[i]
            i += 1
        out.append(cur)
        if len(out) > 1:
            out = [out[0], "|".join(out[1:])]
        return out

    def resolve_command(self, word):
        if word == "":
            return "goto"
        if word in ("&", "&&", "~", ">", "<", "="):
            return word
        for full, mn in COMMANDS:
            if len(word) >= mn and full.startswith(word):
                return full
        if word == "s":
            return "substitute"
        if word[0] == "s" and len(word) > 1 and not word[1].isalpha():
            return "substitute"
        raise CmdError("E492: Not an editor command: %s" % word)

    # --- ranges ----------------------------------------------------------------------------------------------------------------------------------
    def parse_range(self, text, pos):
        """Parse ``1,5`` ``%`` ``.,$`` ``'<,'>`` ``/pat/;+2`` at ``pos``: returns ((start, end) as 0-based rows or None, new position)."""
        n = len(text)
        while pos < n and text[pos] in " \t":
            pos += 1
        if pos < n and text[pos] == "%":
            return (0, len(self.lines) - 1), pos + 1
        addrs = []
        cur_row = self.row
        while True:
            addr, pos = self.parse_address(text, pos, cur_row)
            while pos < n and text[pos] in " \t":
                pos += 1
            if pos < n and text[pos] in ",;":
                sep = text[pos]
                pos += 1
                if addr is None:
                    addr = cur_row
                addrs.append(addr)
                if sep == ";":
                    cur_row = addr
                continue
            if addr is not None:
                addrs.append(addr)
            break
        if not addrs:
            return None, pos
        if len(addrs) == 1:
            return (addrs[0], addrs[0]), pos
        a, b = addrs[-2], addrs[-1]
        return (a, b), pos

    def parse_address(self, text, pos, cur_row):
        n = len(text)
        while pos < n and text[pos] in " \t":
            pos += 1
        base = None
        if pos < n:
            c = text[pos]
            if c.isdigit():
                m = re.match(r"\d+", text[pos:])
                base = int(m.group()) - 1
                pos += len(m.group())
            elif c == ".":
                base = cur_row
                pos += 1
            elif c == "$":
                base = len(self.lines) - 1
                pos += 1
            elif c == "'":
                mark = text[pos + 1:pos + 2]
                if mark in ("<", ">"):
                    if self.last_visual is None:
                        raise CmdError("E20: Mark not set")
                    a, b = sorted((self.last_visual[1], self.last_visual[2]))
                    base = (a if mark == "<" else b)[0]
                else:
                    pm = self.get_mark(mark)
                    base = pm[0]
                pos += 2
            elif c in "/?":
                end = pos + 1
                while end < n and text[end] != c:
                    end += 2 if text[end] == "\\" else 1
                pat = text[pos + 1:end]
                rx = self.compile(pat or (self.last_search[0] if self.last_search else ""))
                if pat:
                    self.last_search = (pat, c == "/")
                found = self.find_match(rx, cur_row, 0 if c == "?" else 10 ** 9, c == "/")
                if found is None:
                    raise CmdError("E486: Pattern not found: %s" % pat)
                base = found[0]
                pos = end + 1
        # offsets
        while pos < n and text[pos] in "+-" or (pos < n and text[pos].isdigit() and base is not None):
            if text[pos].isdigit():
                m = re.match(r"\d+", text[pos:])
                base += int(m.group())
                pos += len(m.group())
                continue
            sign = 1 if text[pos] == "+" else -1
            pos += 1
            m = re.match(r"\d+", text[pos:])
            amount = int(m.group()) if m else 1
            pos += len(m.group()) if m else 0
            if base is None:
                base = cur_row
            base += sign * amount
        if base is not None:
            if base < -1 or base > len(self.lines) - 1:
                raise CmdError("E16: Invalid range")
            if base < 0:
                base = -1
        return base, pos

    def get_range(self, rng, default="cursor"):
        if rng is None:
            if default == "all":
                return 0, len(self.lines) - 1
            return self.row, self.row
        a, b = rng
        if a is not None and a < 0 and b < 0:
            return 0, 0
        a = max(a, 0)
        b = max(b, 0)
        if a > b:
            a, b = b, a
        return a, b

    # --- the commands ----------------------------------------------------------------------------------------------------------------------------
    def dispatch_ex(self, name, rng, bang, args):
        args_s = args.strip()
        if name == "goto":
            if rng is None:
                return
            r = rng[1]
            r = max(0, min(r, len(self.lines) - 1))
            self.row = r
            self.col = self.first_nonblank_col(r)
            self.set_curswant()
            return
        if name in ("write", "update", "saveas"):
            a, b = self.get_range(rng, "all")
            lines = None if rng is None else self.lines[a:b + 1]
            if name == "update" and not self.modified:
                return
            if args_s.startswith(">>"):
                raise CmdError("E494: Append is not supported")
            self.say(self.write(args_s or None, bang, lines))
            return
        if name == "wq" or name == "xit":
            if name == "xit" and not self.modified and self.filename is not None and not self.is_new:
                self.quit = True
                return
            msg = self.write(args_s or None, bang)
            self.say(msg)
            self.quit = True
            return
        if name == "quit":
            if self.modified and not bang:
                raise CmdError("E37: No write since last change (add ! to override)")
            self.quit = True
            return
        if name in ("wall", "qall", "wqall", "xall"):
            if name in ("wall", "wqall", "xall") and self.modified:
                self.say(self.write(None, bang))
            if name != "wall":
                if name == "qall" and self.modified and not bang:
                    raise CmdError("E37: No write since last change (add ! to override)")
                self.quit = True
            return
        if name == "edit":
            self.edit_file(args_s, bang)
            return
        if name == "read":
            self.read_file(args_s, rng)
            return
        if name == "file":
            self.say(self.file_info())
            return
        if name in ("undo",):
            self.undo(1)
            return
        if name == "redo":
            self.redo_change(1)
            return
        if name == "set":
            self.set_options(args_s)
            return
        if name == "nohlsearch":
            self.hl_off = True
            return
        if name in ("help", "version"):
            self.say("ked: a small vim-like editor. Normal mode: hjkl w b e 0 $ gg G f t / ? n N, d c y p u . x J r ~ v V i a o, :w :q :wq. See the README.")
            return
        if name in ("registers", "display", "print", "number", "="):
            if name == "=":
                self.say(str(len(self.lines) if rng is None else rng[1] + 1))
            elif name in ("print", "number"):
                a, b = self.get_range(rng)
                self.row = b
                self.say("\n".join(self.lines[a:b + 1]))
            return
        if name == "delete":
            self.ex_delete(rng, args_s)
            return
        if name == "yank":
            self.ex_yank(rng, args_s)
            return
        if name in (">", "<"):
            a, b = self.get_range(rng)
            amount = 1
            rest = args
            while rest.startswith(name):
                amount += 1
                rest = rest[1:]
            self.op_shift(name, a, b, amount)
            self.row = b
            self.col = self.first_nonblank_col(b)
            return
        if name == "join":
            a, b = self.get_range(rng)
            count_arg = re.match(r"\s*(\d+)", args)
            if count_arg:
                a = b
                b = min(a + int(count_arg.group(1)) - 1, len(self.lines) - 1)
            elif rng is None or a == b:
                b = min(a + 1, len(self.lines) - 1)
            self.row = a
            if b <= a:
                raise CmdError("")
            self.join_lines(b - a + 1, not bang)
            self.col = self.first_nonblank_col(self.row)
            return
        if name in ("move", "t", "copy"):
            self.ex_move_copy(name, rng, args_s)
            return
        if name == "put":
            reg = args_s[:1] if args_s else None
            if rng is not None and rng[1] >= 0:
                self.row = min(rng[1], len(self.lines) - 1)           # (the cursor is on the range's last line even if the put then fails)
            register = self.get_register(reg or '"')
            r = self.row if rng is None else max(rng[1], -1)
            above = bang
            if r < 0:
                r = 0
                above = True
            at = r if above else r + 1
            text_lines = register.lines
            self.ins_lines(at, list(text_lines))
            self.row = at + len(text_lines) - 1
            self.col = self.first_nonblank_col(self.row)
            self.set_curswant()
            return
        if name in ("mark", "k"):
            self.set_mark(args_s[:1], self.get_range(rng)[1])
            return
        if name == "normal":
            self.ex_normal(rng, args)
            return
        if name in ("global", "vglobal"):
            self.ex_global(rng, args, name == "vglobal" or bang)
            return
        if name == "substitute":
            self.ex_substitute(rng, args)
            return
        if name in ("&", "&&"):
            self.ex_substitute(rng, self.repeat_sub_args(args))
            return
        if name == "~":
            self.ex_substitute(rng, self.repeat_sub_args(args, use_search=True))
            return
        if name == "sort":
            self.ex_sort(rng, args_s, bang)
            return
        if name == "retab":
            self.ex_retab(rng, args_s)
            return
        if name in ("left", "right", "center"):
            self.ex_align(name, rng, args_s)
            return
        raise CmdError("E492: Not an editor command: %s" % name)

    def repeat_sub_args(self, args, use_search=False):
        if self.last_sub is None:
            raise CmdError("E35: No previous regular expression")
        pat, rep = self.last_sub
        if use_search and self.last_search:
            pat = self.last_search[0]
        return "/%s/%s/%s" % (pat.replace("/", "\\/"), rep.replace("/", "\\/"), args.lstrip("&") if args.startswith("&") else args)

    def ex_delete(self, rng, args):
        from .editor_types import Register
        a, b = self.get_range(rng)
        reg = None
        m = re.match(r"\s*([a-zA-Z\"_-])?\s*(\d+)?", args)
        reg = m.group(1)
        if m.group(2):
            a = b
            b = min(a + int(m.group(2)) - 1, len(self.lines) - 1)
        self.store_deleted(reg, Register(self.lines[a:b + 1], True), True)
        self.del_lines(a, b - a + 1)
        self.row = min(a, len(self.lines) - 1)
        self.col = self.first_nonblank_col(self.row)
        self.set_curswant()

    def ex_yank(self, rng, args):
        from .editor_types import Register
        a, b = self.get_range(rng)
        m = re.match(r"\s*([a-zA-Z\"_-])?\s*(\d+)?", args)
        reg = m.group(1)
        if m.group(2):
            a = b
            b = min(a + int(m.group(2)) - 1, len(self.lines) - 1)
        self.set_register(reg, Register(self.lines[a:b + 1], True))

    def ex_move_copy(self, name, rng, args):
        a, b = self.get_range(rng)
        dest, _ = self.parse_address(args, 0, self.row)
        if dest is None:
            raise CmdError("E14: Invalid address")
        block = self.lines[a:b + 1]
        if name == "move":
            if a <= dest < b:
                raise CmdError("E134: Cannot move a range of lines into itself")
            if dest >= b:
                self.ins_lines(dest + 1, list(block))
                self.del_lines(a, b - a + 1)
                self.row = dest
            elif dest < a:
                self.ins_lines(dest + 1, list(block))
                self.del_lines(a + len(block), b - a + 1)
                self.row = dest + len(block)
            else:
                self.row = b
        else:
            self.ins_lines(dest + 1, list(block))
            self.row = dest + len(block)
        self.col = self.first_nonblank_col(self.row)
        self.set_curswant()

    def ex_normal(self, rng, args):
        keys = args.lstrip(" ") if not args.startswith("!") else args[1:].lstrip(" ")
        if not keys:
            raise CmdError("E471: Argument required")
        rows = None
        if rng is not None:
            a, b = self.get_range(rng)
            rows = list(range(a, b + 1))
        parsed = self.parse_key_string(keys)
        if rows is None:
            self.run_keys_nested(parsed)
            return
        tracker = self.track(rows)
        try:
            while True:
                r = tracker.next()
                if r is None:
                    break
                self.row, self.col = r, 0
                self.run_keys_nested(parsed)
        finally:
            self.untrack(tracker)

    @staticmethod
    def parse_key_string(s):
        out = []
        i = 0
        while i < len(s):
            if s[i] == "<":
                j = s.find(">", i)
                if j > 0 and s[i:j + 1] in ("<Esc>", "<CR>", "<BS>", "<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>", "<Delete>", "<Tab>", "<C-R>", "<C-V>", "<C-W>", "<C-U>"):
                    out.append({"<Esc>": "\x1b", "<CR>": "\r", "<BS>": "\x7f", "<Tab>": "\t", "<C-R>": "\x12", "<C-V>": "\x16", "<C-W>": "\x17", "<C-U>": "\x15"}.get(s[i:j + 1], s[i:j + 1]))
                    i = j + 1
                    continue
            out.append(s[i])
            i += 1
        return out

    def run_keys_nested(self, keys):
        """Run keys as normal-mode commands to the end (an unfinished command is cancelled with <Esc>, like :normal)."""
        gen = self.normal_command()
        next(gen)
        done = False
        self.nested += 1
        try:
            for k in keys:
                try:
                    gen.send(k)
                except StopIteration:
                    gen = self.normal_command()
                    next(gen)
                    gen.send(k)
            # finish a command that is still waiting for keys
            for _ in range(3):
                try:
                    gen.send("\x1b")
                except StopIteration:
                    done = True
                    break
        except CmdError:
            pass
        finally:
            self.nested -= 1
        if self.mode in ("i", "r"):
            self.mode = "n"
        if self.mode in ("v", "V"):
            self.end_visual()
        self.ins = None
        self.check_cursor()
        return done

    def ex_global(self, rng, args, invert):
        a, b = self.get_range(rng, "all")
        if not args:
            raise CmdError("E35: No previous regular expression")
        delim = args[0]
        i = 1
        while i < len(args) and args[i] != delim:
            i += 2 if args[i] == "\\" else 1
        pat = args[1:i]
        cmd = args[i + 1:] or "p"
        rx = self.compile(pat or (self.last_search[0] if self.last_search else ""))
        if pat:
            self.last_search = (pat, self.last_search[1] if self.last_search else True)
        rows = [r for r in range(a, b + 1) if bool(rx.search(self.lines[r])) != invert]
        if not rows:
            raise CmdError("E486: Pattern not found: %s" % pat)
        tracker = self.track(rows)
        self.global_busy += 1
        self.global_need_beginline = False
        try:
            while True:
                r = tracker.next()
                if r is None:
                    break
                self.row, self.col = r, 0
                try:
                    self.run_ex(cmd)
                except CmdError:
                    pass                               # an error in one line does not stop :g
        finally:
            self.global_busy -= 1
            self.untrack(tracker)
        if self.global_need_beginline:
            self.col = self.first_nonblank_col(self.row)
        self.check_cursor()
        self.set_curswant()

    # --- :s --------------------------------------------------------------------------------------------------------------------------------------
    def ex_substitute(self, rng, args):
        a, b = self.get_range(rng)
        if not args or args[0].isalnum() or args[0] in " \t\"|":
            if args.strip() == "" or args[0] in "&cgiInpl#r123456789" or args[0].isalnum():
                if self.last_sub is None:
                    raise CmdError("E35: No previous regular expression")
                pat, rep = self.last_sub
                flags = args.strip()
            else:
                raise CmdError("E146: Regular expressions can't be delimited by letters")
        else:
            delim = args[0]
            i = 1
            pat_chars = []
            while i < len(args) and args[i] != delim:
                if args[i] == "\\" and i + 1 < len(args):
                    pat_chars.append(args[i:i + 2] if args[i + 1] != delim else delim)
                    i += 2
                    continue
                pat_chars.append(args[i])
                i += 1
            pat = "".join(pat_chars)
            i += 1
            rep_chars = []
            while i < len(args) and args[i] != delim:
                if args[i] == "\\" and i + 1 < len(args):
                    rep_chars.append(args[i:i + 2] if args[i + 1] != delim else delim)
                    i += 2
                    continue
                rep_chars.append(args[i])
                i += 1
            rep = "".join(rep_chars)
            flags = args[i + 1:].strip()
            if pat == "":
                pat = self.last_search[0] if self.last_search else ""
                if not pat:
                    raise CmdError("E35: No previous regular expression")
            self.last_sub = (pat, rep)
            self.last_search = (pat, self.last_search[1] if self.last_search else True)
        m = re.match(r"([&cegiInp#lr]*)\s*(\d+)?", flags)
        fl = m.group(1)
        if m.group(2):
            a = b
            b = min(a + int(m.group(2)) - 1, len(self.lines) - 1)
        global_flag = "g" in fl
        ic = None
        if "i" in fl:
            ic = True
        if "I" in fl:
            ic = False
        rx = compile_pattern(pat, self.opts["ignorecase"] if ic is None else ic, self.opts["smartcase"] if ic is None else False)
        count_only = "n" in fl
        total = 0
        lines_changed = 0
        last_row = None
        r = a
        end = b
        while r <= end:
            line = self.lines[r]
            pieces, n_sub = self.substitute_line(rx, line, rep, global_flag)
            if n_sub:
                total += n_sub
                lines_changed += 1
                if not count_only:
                    new_lines = pieces
                    if not self.touched:
                        self.row, self.col = r, 0                  # (where the cursor was when the first line changed: undo goes back to it)
                    self.set_line(r, new_lines[0])
                    if len(new_lines) > 1:
                        self.ins_lines(r + 1, new_lines[1:])
                        r += len(new_lines) - 1
                        end += len(new_lines) - 1
                    last_row = r
            r += 1
        if total == 0:
            if "e" in fl:
                return
            raise CmdError("E486: Pattern not found: %s" % pat)
        if count_only:
            self.say("%d match%s on %d line%s" % (total, "" if total == 1 else "es", lines_changed, "" if lines_changed == 1 else "s"))
            return
        self.row = last_row if last_row is not None else self.row
        if self.global_busy:
            self.global_need_beginline = True
        else:
            self.col = self.first_nonblank_col(self.row)
        self.set_curswant()
        if total > 2:
            self.say("%d substitution%s on %d line%s" % (total, "s" if total != 1 else "", lines_changed, "s" if lines_changed != 1 else ""))

    def substitute_line(self, rx, line, rep, global_flag):
        """The line after substituting (as a list of lines: ``\\r`` in the replacement breaks it) and how many matches were replaced."""
        out = []
        pos = 0
        n = 0
        copied = 0
        prev_end = -1
        while pos <= len(line):
            m = rx.search(line, pos)
            if m is None:
                break
            if m.end() == m.start() and m.start() == prev_end:
                pos = m.start() + 1
                continue
            out.append(line[copied:m.start()])
            out.append(self.expand_replacement(rep, m))
            n += 1
            copied = m.end()
            prev_end = m.end()
            if not global_flag:
                break
            if m.end() == m.start():
                if m.start() < len(line):
                    out.append(line[m.start():m.start() + 1])
                    copied = m.start() + 1
                pos = m.start() + 1
            else:
                pos = m.end()
        if n == 0:
            return [line], 0
        out.append(line[copied:])
        return "".join(out).split("\r"), n

    @staticmethod
    def expand_replacement(rep, m):
        out = []
        case_next = None
        case_all = None
        i = 0

        def emit(s):
            nonlocal case_next
            for ch in s:
                if case_next:
                    ch = ch.upper() if case_next == "u" else ch.lower()
                    case_next = None
                elif case_all:
                    ch = ch.upper() if case_all == "U" else ch.lower()
                out.append(ch)
        while i < len(rep):
            c = rep[i]
            if c == "&":
                emit(m.group(0))
            elif c == "\\" and i + 1 < len(rep):
                i += 1
                d = rep[i]
                if d == "&":
                    emit("&")
                elif d.isdigit():
                    emit(m.group(int(d)) or "" if int(d) <= (m.re.groups) else "")
                elif d == "n":
                    out.append("\0")
                elif d == "r":
                    out.append("\r")
                elif d == "t":
                    emit("\t")
                elif d in "ul":
                    case_next = d
                elif d in "UL":
                    case_all = d
                elif d in "eE":
                    case_all = None
                    case_next = None
                else:
                    emit(d)
            elif c == "\r":
                out.append("\r")
            else:
                emit(c)
            i += 1
        return "".join(out)

    # --- the other commands ----------------------------------------------------------------------------------------------------------------------
    def set_options(self, args):
        from .editor import OPTION_ALIASES
        for item in args.split():
            val = None
            query = item.endswith("?")
            item = item.rstrip("?")
            if "=" in item:
                item, val = item.split("=", 1)
            toggle = item.endswith("!")
            item = item.rstrip("!")
            invert = item.startswith("no") and (item[2:] in self.opts or item[2:] in OPTION_ALIASES)
            inv = item.startswith("inv") and (item[3:] in self.opts or item[3:] in OPTION_ALIASES)
            name = item[2:] if invert else item[3:] if inv else item
            name = OPTION_ALIASES.get(name, name)
            if name not in self.opts:
                raise CmdError("E518: Unknown option: %s" % name)
            cur = self.opts[name]
            if query:
                self.say(("%s=%s" % (name, cur)) if not isinstance(cur, bool) else (name if cur else "no" + name))
                continue
            if val is not None:
                if isinstance(cur, bool):
                    raise CmdError("E474: Invalid argument: %s" % item)
                try:
                    self.opts[name] = int(val)
                except ValueError:
                    raise CmdError("E521: Number required after =: %s" % item) from None
                if name == "tabstop" and self.opts[name] < 1:
                    self.opts[name] = cur
                    raise CmdError("E487: Argument must be positive: %s" % item)
            elif isinstance(cur, bool):
                self.opts[name] = (not cur) if (toggle or inv) else (not invert)
            else:
                self.say("%s=%s" % (name, cur))

    def edit_file(self, path, bang):
        from .editor import Editor
        if not path:
            if self.filename is None:
                raise CmdError("E32: No file name")
            path = self.filename
        if self.modified and not bang:
            raise CmdError("E37: No write since last change (add ! to override)")
        fresh = Editor.open(path, self.size)
        self.adopt(fresh)

    def adopt(self, other):
        for attr in ("filename", "lines", "no_lines", "fileformat", "noeol", "readonly", "mtime", "is_new", "msg", "msg_error", "modified", "undo_list", "undo_pos"):
            setattr(self, attr, getattr(other, attr))
        self.row = self.col = 0
        self.top = 0
        self.set_curswant()

    def read_file(self, path, rng):
        if not path:
            raise CmdError("E32: No file name")
        try:
            with open(path, "rb") as f:
                data = f.read().decode("utf-8", "surrogateescape")
        except OSError:
            raise CmdError("E484: Can't open file %s" % path) from None
        new = data.replace("\r\n", "\n").split("\n")
        if new and new[-1] == "":
            new.pop()
        r = self.row if rng is None else rng[1]
        self.ins_lines(r + 1, new)
        self.row = r + 1
        self.col = self.first_nonblank_col(self.row)

    def ex_sort(self, rng, args, reverse):
        a, b = self.get_range(rng, "all")
        block = self.lines[a:b + 1]
        numeric = "n" in args
        ic = "i" in args
        def key(s):
            if numeric:
                m = re.search(r"-?\d+", s)
                return (0, int(m.group())) if m else (-1, 0)
            return s.lower() if ic else s
        if len(block) <= 1:
            return
        out = sorted(block, key=key, reverse=reverse)
        if "u" in args:
            seen, uniq = set(), []
            for s in out:
                k = key(s)
                if k not in seen:
                    seen.add(k)
                    uniq.append(s)
            out = uniq
        self.replace_lines(a, b, out)
        self.row = a
        self.col = self.first_nonblank_col(a)
        self.set_curswant()

    def ex_retab(self, rng, args):
        a, b = self.get_range(rng, "all")
        ts = self.opts["tabstop"]
        for r in range(a, b + 1):
            line = self.lines[r]
            if "\t" in line:
                out, v = [], 0
                for ch in line:
                    if ch == "\t":
                        w = ts - v % ts
                        out.append(" " * w if self.opts["expandtab"] else "\t")
                        v += w
                    else:
                        out.append(ch)
                        v += T.char_cells(ch)
                self.set_line(r, "".join(out))

    def ex_align(self, name, rng, args):
        a, b = self.get_range(rng)
        width = int(args) if args.isdigit() else (78 if name != "left" else 0)
        for r in range(a, b + 1):
            body = self.lines[r].strip(" \t")
            if name == "left":
                self.set_line(r, " " * (int(args) if args.isdigit() else 0) + body)
            elif name == "right":
                self.set_line(r, " " * max(width - len(body), 0) + body)
            else:
                self.set_line(r, " " * max((width - len(body)) // 2, 0) + body)
