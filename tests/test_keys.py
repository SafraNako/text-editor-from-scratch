"""From bytes to keys."""
import pytest

from kendi_editor.keys import Decoder, ScriptDecoder


def decode(data, flush=True):
    d = Decoder()
    keys = d.feed(data)
    if flush:
        keys += d.flush()
    return keys


def test_plain_characters_and_utf8():
    assert decode(b"abc") == ["a", "b", "c"]
    assert decode("héllo ∑ 日本".encode()) == list("héllo ∑ 日本")
    assert decode(b"\r\t\x7f\x03\x04") == ["\r", "\t", "\x7f", "\x03", "\x04"]


def test_utf8_split_across_reads():
    d = Decoder()
    data = "é∑".encode()
    keys = []
    for b in data:
        keys += d.feed(bytes([b]))
    assert keys == ["é", "∑"]


def test_invalid_utf8_becomes_surrogate_escapes():
    assert decode(b"a\xffb") == ["a", "\udcff", "b"]


@pytest.mark.parametrize("data, key", [
    (b"\x1b[A", "<Up>"), (b"\x1b[B", "<Down>"), (b"\x1b[C", "<Right>"), (b"\x1b[D", "<Left>"), (b"\x1b[H", "<Home>"), (b"\x1b[F", "<End>"),
    (b"\x1bOA", "<Up>"), (b"\x1bOB", "<Down>"), (b"\x1bOC", "<Right>"), (b"\x1bOD", "<Left>"), (b"\x1bOH", "<Home>"), (b"\x1bOF", "<End>"),
    (b"\x1b[1~", "<Home>"), (b"\x1b[4~", "<End>"), (b"\x1b[3~", "<Delete>"), (b"\x1b[5~", "<PageUp>"), (b"\x1b[6~", "<PageDown>"), (b"\x1b[2~", "<Insert>"),
    (b"\x1b[1;5C", "<Right>"), (b"\x1b[1;2A", "<Up>"), (b"\x1b[3;5~", "<Delete>"),
])
def test_cursor_and_editing_keys(data, key):
    assert decode(data) == [key]


def test_a_lone_escape_needs_the_timeout():
    d = Decoder()
    assert d.feed(b"\x1b") == [] and d.pending()
    assert d.flush() == ["\x1b"] and not d.pending()


def test_escape_followed_by_a_key_is_two_keys():
    assert decode(b"\x1bx") == ["\x1b", "x"]
    assert decode(b"\x1b\x1b") == ["\x1b", "\x1b"]
    d = Decoder()
    assert d.feed(b"\x1b\x1b[A") == ["\x1b", "<Up>"] and not d.pending()


def test_a_sequence_split_across_reads():
    d = Decoder()
    keys = d.feed(b"\x1b") + d.feed(b"[") + d.feed(b"A")
    assert keys == ["<Up>"]
    keys = d.feed(b"\x1b[1;") + d.feed(b"5C")
    assert keys == ["<Right>"]


def test_bracketed_paste():
    d = Decoder()
    keys = d.feed(b"a\x1b[200~hello\nworld\x1b[201~b")
    assert keys == ["a", ("paste", "hello\nworld"), "b"]
    keys = d.feed(b"\x1b[200~caf\xc3") + d.feed(b"\xa9 \x1b[A\x1b[201~")
    assert keys == [("paste", "café ")]                                  # (cursor keys inside a paste are not keys)


def test_unknown_sequences_are_dropped():
    assert decode(b"\x1b[99z") == [] and decode(b"\x1b[?1;2cx") == ["x"]
    assert decode(b"\x1b[M") == []


def test_script_decoder_takes_every_byte_as_a_key():
    assert ScriptDecoder().feed(b"ix\x1b[A\x1b") == ["i", "x", "\x1b", "[", "A", "\x1b"]
    assert ScriptDecoder().feed("é".encode()) == ["é"]
