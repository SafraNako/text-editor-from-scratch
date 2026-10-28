"""What is drawn: the window, the status line, the message line and where the cursor is. Every frame is also given to pyte, an independent terminal emulator, to see that the
escape sequences produce the text that was meant."""
import unicodedata

import pyte

from kendi_editor import Editor
from kendi_editor.screen import render

ESC = "\x1b"


def draw(text, keys="", rows=8, cols=30, **opts):
    e = Editor(text, "notes.txt", (rows, cols))
    e.opts.update(opts)
    frame = render(e, rows, cols)
    for key in keys:                                    # drawn after every key, as the editor does
        e.feed(key)
        frame = render(e, rows, cols)
    # what an independent terminal makes of the rows
    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    for i, row in enumerate(frame.rows):
        stream.feed("\x1b[%d;1H%s" % (i + 1, row))
    stream.feed("\x1b[%d;%dH" % (frame.cursor[0] + 1, frame.cursor[1] + 1))
    shown = [unicodedata.normalize("NFC", line.rstrip()) for line in screen.display]        # (pyte composes e + combining accent)
    assert shown == [unicodedata.normalize("NFC", line) for line in frame.plain], "pyte shows something else than the frame says"
    assert (screen.cursor.y, screen.cursor.x) == frame.cursor
    return e, frame


def test_a_short_file():
    e, f = draw("one\ntwo\n", rows=6)
    assert f.plain[:4] == ["one", "two", "~", "~"]
    assert f.plain[4].startswith(" NORMAL  notes.txt") and f.plain[4].endswith("1,1  All")
    assert f.cursor == (0, 0)


def test_the_cursor_follows():
    e, f = draw("one\ntwo\n", "jl")
    assert f.cursor == (1, 1) and "2,2" in f.plain[6]
    e, f = draw("one two\n", "$")
    assert f.cursor == (0, 6)


def test_long_lines_wrap():
    e, f = draw("a" * 25 + "bcdef" + "XYZ\nnext\n", cols=10, rows=8)
    assert f.plain[:5] == ["a" * 10, "a" * 10, "a" * 5 + "bcdef", "XYZ", "next"]
    e, f = draw("a" * 25 + "bcdef" + "XYZ\nnext\n", "$", cols=10, rows=8)
    assert f.cursor == (3, 2)
    e, f = draw("a" * 25 + "bcdef" + "XYZ\nnext\n", "30l", cols=10, rows=8)
    assert f.cursor == (3, 0)
    e, f = draw("a" * 25 + "bcdef" + "XYZ\nnext\n", "j", cols=10, rows=8)
    assert f.cursor[0] == 4


def test_a_line_that_does_not_fit_at_the_bottom_shows_at_signs():
    e, f = draw("one\n" + "x" * 50 + "\n", rows=5, cols=10)
    assert f.plain[:3] == ["one", "@", "@"]


def test_tabs_and_the_cursor_on_them():
    e, f = draw("a\tb\n", rows=4, cols=20)
    assert f.plain[0] == "a       b"
    e, f = draw("a\tb\n", "l", rows=4, cols=20)
    assert f.cursor == (0, 7)                           # normal mode: the cursor is at the end of the tab
    e, f = draw("a\tb\n", "li", rows=4, cols=20)
    assert f.cursor == (0, 1)                           # insert mode: at the start
    e, f = draw("a\tb\n", "ll", rows=4, cols=20)
    assert f.cursor == (0, 8)
    e, f = draw("a\tb\n", ":set ts=4\r", rows=4, cols=20)
    assert f.plain[0] == "a   b"


def test_control_characters_and_undecodable_bytes():
    e, f = draw("a\x01b\x7fc\n", rows=4, cols=20)
    assert f.plain[0] == "a^Ab^?c"
    e, f = draw("x\udcffy\n", rows=4, cols=20)
    assert f.plain[0] == "x<ff>y"
    e, f = draw("a\x01b\n", "ll", rows=4, cols=20)
    assert f.cursor == (0, 3)                           # a, then ^A in two cells, then b


def test_wide_and_combining_characters():
    e, f = draw("日本語x\n", rows=4, cols=20)
    assert f.plain[0] == "日本語x"
    e, f = draw("日本語x\n", "l", rows=4, cols=20)
    assert f.cursor == (0, 2)                                              # on the first cell of a wide character
    e, f = draw("日本語x\n", "$", rows=4, cols=20)
    assert f.cursor == (0, 6)
    e, f = draw("éx\n", rows=4, cols=20)
    assert f.plain[0] == "éx"


def test_line_numbers():
    e, f = draw("one\ntwo\nthree\n", rows=6, cols=20, number=True)
    assert f.plain[:3] == ["  1 one", "  2 two", "  3 three"]
    assert f.cursor == (0, 4)
    e, f = draw("one\ntwo\nthree\n", "j", rows=6, cols=20, number=True, relativenumber=True)
    assert f.plain[:3] == ["  1 one", "2   two", "  1 three"]
    e, f = draw("one\ntwo\nthree\n", "j", rows=6, cols=20, relativenumber=True)
    assert f.plain[:3] == ["  1 one", "  0 two", "  1 three"]
    e, f = draw("\n".join(str(i) for i in range(1, 1200)) + "\n", rows=6, cols=20, number=True)
    assert f.plain[0] == "   1 1" and f.cursor == (0, 5)


def test_scrolling():
    text = "\n".join("line %d" % i for i in range(1, 101)) + "\n"
    e, f = draw(text, rows=7, cols=20)
    assert f.plain[0] == "line 1" and f.plain[4] == "line 5"
    e, f = draw(text, "4j", rows=7, cols=20)
    assert f.plain[0] == "line 1" and f.cursor == (4, 0)
    e, f = draw(text, "G", rows=7, cols=20)
    assert f.plain[4] == "line 100" and f.cursor == (4, 0)
    e, f = draw(text, "50G", rows=7, cols=20)
    assert f.plain[:5] == ["line 48", "line 49", "line 50", "line 51", "line 52"] and f.cursor == (2, 0)           # a long jump puts the line in the middle
    e, f = draw(text, "50Ggg", rows=7, cols=20)
    assert f.plain[0] == "line 1"
    e, f = draw(text, "50Gk", rows=7, cols=20)
    assert f.plain[:5] == ["line 48", "line 49", "line 50", "line 51", "line 52"] and f.cursor == (1, 0)
    e, f = draw(text, "5j", rows=7, cols=20)
    e.feed_keys(list("5k"))
    f2 = render(e, 7, 20)
    assert f2.plain[0] == "line 1"


def test_scrolling_by_one_line_when_the_cursor_walks_off():
    text = "\n".join("line %d" % i for i in range(1, 30)) + "\n"
    e, f = draw(text, "5j", rows=7, cols=20)
    assert f.plain[0] == "line 2" and f.cursor == (4, 0)
    e.feed("j")
    assert render(e, 7, 20).plain[0] == "line 3"


def test_visual_selection_is_shown_in_reverse():
    e, f = draw("one two\nthree\n", "vl", rows=5, cols=20)
    assert "\x1b[0;7mon\x1b[0m" in f.rows[0]
    e, f = draw("one two\nthree\n", "Vj", rows=5, cols=20)
    assert "\x1b[0;7mone two" in f.rows[0] and "\x1b[0;7mthree" in f.rows[1]
    e, f = draw("one two\nthree\n", "v$", rows=5, cols=20)
    assert f.rows[0].startswith("\x1b[0;7mone two ")


def test_search_matches_are_highlighted_when_asked():
    e, f = draw("one two one\n", "/one\r", rows=5, cols=20, hlsearch=True)
    assert f.rows[0].count("\x1b[0;30;43m") == 2
    e, f = draw("one two one\n", "/one\r", rows=5, cols=20)
    assert "\x1b[0;30;43m" not in f.rows[0]


def test_no_wrap_scrolls_sideways():
    e, f = draw("0123456789abcdefghij\n", "$", rows=4, cols=10, wrap=False)
    assert f.plain[0] == "abcdefghij" and f.cursor == (0, 9)
    e, f = draw("0123456789abcdefghij\n", "$0", rows=4, cols=10, wrap=False)
    assert f.plain[0] == "0123456789"


def test_the_status_line():
    e, f = draw("one\n" * 10, "", rows=5, cols=40)
    assert f.plain[3] == " NORMAL  notes.txt" + " " * 13 + "1,1  Top"
    e, f = draw("one\n" * 10, "x", rows=5, cols=40)
    assert " [+]" in f.plain[3]
    e, f = draw("one\n" * 10, "G", rows=5, cols=40)
    assert f.plain[3].endswith("10,1  Bot")
    e, f = draw("one\n" * 10, "5G", rows=5, cols=40)
    assert f.plain[3].endswith("5,1  42%")
    e, f = draw("a\tb\n", "$", rows=5, cols=40)
    assert f.plain[3].endswith("1,3-9  All")
    e, f = draw("one\n", "i", rows=5, cols=40)
    assert " INSERT " in f.plain[3]
    e, f = draw("one\n", "v", rows=5, cols=40)
    assert " VISUAL " in f.plain[3]
    e, f = draw("one\n", "V", rows=5, cols=40)
    assert " V-LINE " in f.plain[3]
    e, f = draw("one\n", "R", rows=5, cols=40)
    assert " REPLACE " in f.plain[3]
    e = Editor("one\n", "/a/very/long/path/to/some/deeply/nested/directory/file.txt", (5, 40))
    f = render(e, 5, 40)
    assert f.plain[3].endswith("1,1  All") and "<" in f.plain[3] and f.plain[3].count("file.txt") == 1
    e = Editor("one\n", None, (5, 40))
    assert "[No Name]" in render(e, 5, 40).plain[3]


def test_the_message_line():
    e, f = draw("one\n", "i", rows=5, cols=40)
    assert f.plain[4] == "-- INSERT --"
    e, f = draw("one\n", "v", rows=5, cols=40)
    assert f.plain[4] == "-- VISUAL --"
    e, f = draw("one\n", "/zz\r", rows=5, cols=40)
    assert f.plain[4] == "E486: Pattern not found: zz" and "\x1b[0;97;41m" in f.rows[4]
    e, f = draw("one\n", ":set ts?\r", rows=5, cols=40)
    assert f.plain[4] == "tabstop=8" and "\x1b[0;97;41m" not in f.rows[4]
    e, f = draw("one\n", ":s/o", rows=5, cols=40)
    assert f.plain[4] == ":s/o" and f.cursor == (4, 4)
    e, f = draw("one\n", "/ne", rows=5, cols=40)
    assert f.plain[4] == "/ne" and f.cursor == (4, 3)
    e, f = draw("one\n", "2d", rows=5, cols=40)
    assert f.plain[4].strip() == "2d"
    e, f = draw("one\n", ":" + "x" * 80, rows=5, cols=40)
    assert len(f.plain[4]) == 39


def test_tiny_windows_do_not_crash():
    for rows, cols in [(1, 1), (1, 10), (2, 10), (3, 5), (24, 1), (2, 2)]:
        e = Editor("a long line of text\nsecond\n", "f", (rows, cols))
        e.feed_keys(list("$jx"))
        f = render(e, rows, cols)
        assert len(f.rows) == rows and len(f.plain) == rows


def test_every_row_is_cleared_to_the_end():
    e, f = draw("one\n", rows=4, cols=20)
    assert all(row.endswith("\x1b[K") for row in f.rows)


def test_a_big_file_is_drawn_from_the_top_only():
    text = "x\n" * 200000
    e = Editor(text, "big", (24, 80))
    f = render(e, 24, 80)
    assert f.plain[0] == "x" and len(f.rows) == 24
