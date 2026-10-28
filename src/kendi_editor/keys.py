"""From bytes read on the terminal to keys: printable characters (UTF-8), control characters, and the escape sequences of the cursor keys, as a small state machine that can
be fed in pieces. A lone <Esc> cannot be told from the start of a sequence until nothing more arrives: ``flush`` says "nothing more came"."""
from __future__ import annotations

import codecs

ESC = "\x1b"

CSI_FINAL = {"A": "<Up>", "B": "<Down>", "C": "<Right>", "D": "<Left>", "H": "<Home>", "F": "<End>"}
CSI_TILDE = {1: "<Home>", 2: "<Insert>", 3: "<Delete>", 4: "<End>", 5: "<PageUp>", 6: "<PageDown>", 7: "<Home>", 8: "<End>"}
SS3_FINAL = {"A": "<Up>", "B": "<Down>", "C": "<Right>", "D": "<Left>", "H": "<Home>", "F": "<End>"}


class Decoder:
    def __init__(self):
        self.utf8 = codecs.getincrementaldecoder("utf-8")("surrogateescape")
        self.buf = b""                       # an escape sequence that is not complete yet
        self.paste = None                    # the text of a bracketed paste in progress

    def feed(self, data):
        """Keys for the bytes just read (a list; the key "<Paste>" is followed by the pasted text in one item, see ``take_paste``)."""
        out = []
        for b in data:
            self._byte(b, out)
        return out

    def pending(self):
        return bool(self.buf)

    def flush(self):
        """No more bytes are coming: a lone <Esc> is <Esc>, an incomplete sequence is just its characters."""
        out = []
        if self.buf:
            for ch in self.buf.decode("latin-1"):
                out.append(ch)
            self.buf = b""
        return out

    def _byte(self, b, out):
        if self.buf:
            self.buf += bytes([b])
            self._sequence(out)
            return
        if b == 0x1B:
            self.buf = b"\x1b"
            return
        self._plain(b, out)

    def _plain(self, b, out):
        text = self.utf8.decode(bytes([b]))
        for ch in text:
            if self.paste is not None:
                self.paste.append(ch)
            else:
                out.append(ch)

    def _sequence(self, out):
        s = self.buf
        if len(s) == 2:
            c = s[1:2]
            if c in (b"[", b"O"):
                return                               # wait for the rest
            # Alt + key: vim sees <Esc> then the key
            self.buf = b""
            out.append(ESC)
            self._byte(s[1], out) if s[1] != 0x1B else self._start_esc()
            return
        kind = s[1:2]
        last = s[-1]
        if kind == b"O":
            self.buf = b""
            key = SS3_FINAL.get(chr(last))
            if key:
                out.append(key)
            return
        # CSI: parameters 0x30-0x3f, intermediates 0x20-0x2f, final 0x40-0x7e
        if 0x40 <= last <= 0x7E:
            self.buf = b""
            params = s[2:-1].decode("latin-1")
            self._csi(params, chr(last), out)
        elif len(s) > 32:
            self.buf = b""

    def _start_esc(self):
        self.buf = b"\x1b"

    def _csi(self, params, final, out):
        if final == "~":
            nums = [int(p) if p.isdigit() else 0 for p in params.split(";")]
            n = nums[0] if nums else 0
            if n == 200:
                self.paste = []
                return
            if n == 201:
                text = "".join(self.paste or [])
                self.paste = None
                out.append(("paste", text))
                return
            key = CSI_TILDE.get(n)
            if key and self.paste is None:
                out.append(key)
            return
        key = CSI_FINAL.get(final)
        if key and self.paste is None:
            out.append(key)                            # (modifiers such as 1;5C are ignored: Ctrl-Right is Right)


class ScriptDecoder:
    """Keys from a script file (like vim -s): every byte is a key, <Esc> is just <Esc>, no escape sequences."""

    def __init__(self):
        self.utf8 = codecs.getincrementaldecoder("utf-8")("surrogateescape")

    def feed(self, data):
        return list(self.utf8.decode(data, final=True))
