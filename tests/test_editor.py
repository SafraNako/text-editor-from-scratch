"""The editor core: what the command table (test_recorded.py, test_vim_differential.py) cannot show: modes and what is displayed about them, the registers, marks that move with
their lines, undo and the cursor, the keys of insert mode that are not characters, options, error messages, pasting."""
from kendi_editor import Editor

ESC = "\x1b"
TEXT = "one two three\nfour five six\nseven eight nine\n"


def make(text=TEXT, keys="", **opts):
    e = Editor(text, "/tmp/ked-never-written.txt")
    e.opts.update(opts)
    e.feed_keys(list(keys))
    return e


def lines(text=TEXT, keys="", **opts):
    return make(text, keys, **opts).lines


def pos(text=TEXT, keys=""):
    e = make(text, keys)
    return e.row, e.col


# --- modes and what the screen says about them ---------------------------------------------------------------------------------------------------
def test_modes():
    e = make()
    assert e.mode == "n"
    e.feed("i")
    assert e.mode == "i"
    e.feed(ESC)
    assert e.mode == "n"
    e.feed("v")
    assert e.mode == "v"
    e.feed("V")
    assert e.mode == "V"
    e.feed("V")
    assert e.mode == "n"
    e.feed("R")
    assert e.mode == "r"
    e.feed("\x03")                                             # Ctrl-C leaves insert mode like Esc
    assert e.mode == "n"
    e.feed(":")
    assert e.mode == "c" and e.cmdline == (":", "")
    e.feed("s")
    assert e.cmdline == (":", "s")
    e.feed(ESC)
    assert e.mode == "n" and e.cmdline is None


def test_pending_command_keys_are_shown():
    e = make()
    for key, shown in [("2", "2"), ("d", "2d"), ("3", "2d3")]:
        e.feed(key)
        assert e.pending == shown
    e.feed("w")
    assert e.pending == ""
    e.feed('"')
    e.feed("a")
    assert e.pending == '"a'
    e.feed("y")
    assert e.pending == '"ay'


def test_escape_cancels_a_pending_command():
    e = make(keys="2d" + ESC)
    assert e.lines == TEXT.rstrip("\n").split("\n") and e.pending == ""
    e.feed("x")
    assert e.lines[0] == "ne two three"                          # the count was forgotten


def test_a_failing_command_leaves_a_message_and_the_text_alone():
    for keys in ("fz", "dfz", "cfz", "tz", "/zzz\r", "d/zzz\r", "Gj", "ggk", "'a", "\x12", "u"):
        e = make(keys=keys)
        assert e.lines == TEXT.rstrip("\n").split("\n"), keys
    assert make(keys="/zzz\r").msg == "E486: Pattern not found: zzz"
    assert make(keys="/zzz\r").msg_error
    assert make(keys="'a").msg.startswith("E20")
    assert make(keys="u").msg == "Already at oldest change"
    assert make(keys="\x12").msg == "Already at newest change"
    assert make(keys=":bogus\r").msg.startswith("E492: Not an editor command")
    assert make(keys=":set bogus\r").msg.startswith("E518")
    assert make(keys=":s/zzz/y/\r").msg.startswith("E486")
    assert make(keys=":s/\\(/y/\r").msg_error


def test_a_message_is_cleared_by_the_next_command():
    e = make(keys="/zzz\r")
    assert e.msg
    e.feed("l")
    assert e.msg == ""


def test_search_messages_and_wrapping():
    e = make(keys="/five\r")
    assert (e.row, e.col) == (1, 5) and e.msg == "/five" and not e.msg_error
    e.feed("n")
    assert (e.row, e.col) == (1, 5) and e.msg.startswith("search hit BOTTOM")
    e = make(keys="G?one\r")
    assert (e.row, e.col) == (0, 0)
    e = make(keys=":set nowrapscan\r/one\r")
    assert e.msg.startswith("E486") and (e.row, e.col) == (0, 0)


# --- registers --------------------------------------------------------------------------------------------------------------------------------------
def test_registers():
    e = make(keys='"qyw')
    assert e.regs["q"].lines == ["one "] and not e.regs["q"].linewise and e.regs['"'].lines == ["one "] and "0" not in e.regs     # (a named register leaves "0 alone)
    e = make("a\nb\nc\nd\n", keys="dddd")
    assert [e.regs[k].lines for k in "12"] == [["b"], ["a"]] and e.regs['"'].lines == ["b"] and e.regs["1"].linewise
    e = make(keys="dw")
    assert e.regs["-"].lines == ["one "] and "1" not in e.regs and e.regs['"'].lines == ["one "]
    e = make(keys="yy")
    assert e.regs["0"].linewise and e.regs["0"].lines == ["one two three"]
    e = make(keys="yyjdd")
    assert e.regs["0"].lines == ["one two three"] and e.regs["1"].lines == ["four five six"]
    e = make(keys='"_dd')
    assert "1" not in e.regs and '"' not in e.regs
    e = make(keys='"ayw"Ayw')
    assert e.regs["a"].lines == ["one one "]
    e = make(keys='"ayy"Ayw')
    assert e.regs["a"].linewise and e.regs["a"].lines == ["one two three", "one "]
    assert lines(keys='"ayyj"bddk"ap"bp') == ["one two three", "one two three", "four five six", "seven eight nine"]
    assert make(keys='"zp').msg.startswith("E353")


def test_put_variants():
    assert lines(keys="yyp") == ["one two three", "one two three", "four five six", "seven eight nine"]
    assert lines(keys="yyP") == ["one two three", "one two three", "four five six", "seven eight nine"]
    assert lines(keys="yw$p") == ["one two threeone ", "four five six", "seven eight nine"]
    assert lines(keys="ywP") == ["one one two three", "four five six", "seven eight nine"]
    assert lines(keys="3yyG2p")[-7:] == ["seven eight nine"] + ["one two three", "four five six", "seven eight nine"] * 2
    assert lines(keys="y2wgp") == ["oone two ne two three", "four five six", "seven eight nine"]
    assert pos(keys="yyp") == (1, 0)
    assert pos(keys="yw$p") == (0, 16)                              # the cursor is on the last character that was put
    assert pos(keys="yyjgp") == (3, 0)
    assert lines("a\n", keys="yy3p") == ["a", "a", "a", "a"]


# --- marks --------------------------------------------------------------------------------------------------------------------------------------------
def test_marks_move_with_their_lines():
    assert pos(keys="jmaggOnew" + ESC + "'a") == (2, 0)
    assert pos(keys="jmaggdd'a") == (0, 0)
    assert pos(keys="jwmaGgg`a") == (1, 5)
    e = make(keys="jmadd")
    assert "a" not in e.marks and make(keys="jmadd'a").msg.startswith("E20")
    assert lines(keys="jmaggd'a") == ["seven eight nine"]
    assert lines(keys="jmaG:'a,.d\r") == ["one two three"]
    assert make(keys="ma").marks == {"a": [0, 0]}


# --- undo -------------------------------------------------------------------------------------------------------------------------------------------
def test_undo_granularity():
    assert lines("a\n", "ione" + ESC + "itwo" + ESC + "u") == ["onea"]
    assert lines("a\nb\nc\nd\n", "3ddu") == ["a", "b", "c", "d"]
    assert lines("a b c d\n", "dwdwu") == ["b c d"]
    assert lines("a b c d\n", "dwdwuu") == ["a b c d"]
    assert lines("a b c d\n", "dwdwuu\x12") == ["b c d"]
    assert lines("a b c d\n", "dwdwdwuu") == ["b c d"] and lines("a b c d\n", "dwdwdw2u") == ["b c d"]
    assert lines("a b c d\n", "dwdwdwu3u") == ["a b c d"]
    assert lines("a b c d\n", "dw2u") == ["a b c d"]
    assert lines("x\n", ":s/x/y/\ru") == ["x"]
    assert lines("a\nb\nc\n", ":%s/./X/\ru") == ["a", "b", "c"]
    assert lines("a\nb\nc\n", ":g/./s/$/!/\ru") == ["a", "b", "c"]
    assert lines("a\nb\nc\n", ":%normal Ax\ru") == ["a", "b", "c"]
    assert lines("a\n", "ix" + ESC + "u\x12\x12") == ["xa"]
    assert lines("a\n", "ix" + ESC + "uu") == ["a"]
    # a redo is dropped when something new is done after an undo
    assert lines("a b c\n", "dwux\x12") == [" b c"]


def test_undo_puts_the_cursor_where_the_change_was():
    for text, keys, where in [
            ("one two three\nfour\n", "wdwu", (0, 4)),
            ("one\ntwo\nthree\n", "jddu", (1, 0)),
            ("one\ntwo\n", "ox" + ESC + "u", (0, 0)),
            ("one\ntwo\nthree\n", "jjddu", (2, 0)),
            ("one two\n", "wcwX" + ESC + "u", (0, 4)),
            ("a\nb\nc\nd\ne\n", "jjmaggdd'au", (0, 0)),
            ("  x\n", "wdd" + "u", (0, 2)),
    ]:
        assert pos(text, keys) == where, keys


def test_redo_of_the_dot_register_survives_undo():
    assert lines("a b c d e\n", "dwu.") == ["b c d e"]


# --- the keys of insert mode ----------------------------------------------------------------------------------------------------------------
def test_insert_mode_special_keys():
    e = make("abc\n", "i")
    for key, text in [("<Right>", "abc"), ("X", "aXbc"), ("<Home>", "aXbc"), ("Y", "YaXbc"), ("<End>", "YaXbc"), ("Z", "YaXbcZ"), ("<Delete>", "YaXbcZ"), ("<Left>", "YaXbcZ"), ("<Delete>", "YaXbc")]:
        e.feed(key)
        assert e.lines == [text], key
    e.feed("<Left>")
    e.feed("<Up>")
    assert e.mode == "i" and e.row == 0
    assert lines("ab\ncd\n", "ji\x7f" + ESC) == ["abcd"]                 # backspace joins lines
    assert lines("", "ifoo\x7f\x7fx" + ESC) == ["fx"]
    assert lines("", "ione two\x17three" + ESC) == ["one three"]            # Ctrl-W
    assert lines("", "ione two\x15three" + ESC) == ["three"]               # Ctrl-U
    assert lines("", "i\x16\x1bx" + ESC) == ["\x1bx"]                       # Ctrl-V inserts the next key as it is
    assert lines("", "ia\tb" + ESC) == ["a\tb"]
    assert lines("", "ia\tb" + ESC, expandtab=True) == ["a       b"]
    assert lines("", "ifoo\rbar" + ESC) == ["foo", "bar"]
    e = make("abc\n", "A")
    e.feed("<Left>")
    e.feed("<Left>")
    e.feed("X")
    assert e.lines == ["aXbc"]


def test_cursor_keys_in_normal_mode():
    e = make(keys="")
    for key, where in [("<Right>", (0, 1)), ("<Down>", (1, 1)), ("<Left>", (1, 0)), ("<Up>", (0, 0)), ("<End>", (0, 12)), ("<Home>", (0, 0))]:
        e.feed(key)
        assert (e.row, e.col) == where, key
    e.feed("<Delete>")
    assert e.lines[0] == "ne two three"


def test_insert_with_a_count_repeats_the_text():
    assert lines("a\n", "3ix" + ESC) == ["xxxa"]
    assert lines("a\n", "2Ab" + ESC) == ["abb"]
    assert lines("a\n", "3ox" + ESC) == ["a", "x", "x", "x"]
    assert lines("a\n", "2Ofoo\rbar" + ESC) == ["foo", "bar", "foo", "bar", "a"]
    assert lines("a\n", "3o" + ESC) == ["a", "", "", ""]
    assert lines("abc\n", "2Rxy" + ESC) == ["xyxy"]


def test_replace_mode():
    assert lines("abc\n", "Rxy" + ESC) == ["xyc"]
    assert lines("abc\n", "Rxyzw" + ESC) == ["xyzw"]
    assert lines("abc\n", "Rxy\x7f\x7f" + ESC) == ["abc"]
    assert lines("abc\n", "Rxy\x7f" + ESC) == ["xbc"]


def test_autoindent():
    assert lines("    foo\n", "obar" + ESC, autoindent=True) == ["    foo", "    bar"]
    assert lines("    foo\n", "o" + ESC, autoindent=True) == ["    foo", ""]
    assert lines("    foo\n", "A\rbar" + ESC, autoindent=True) == ["    foo", "    bar"]
    assert lines("    foo\n", "Obar" + ESC, autoindent=True) == ["    bar", "    foo"]
    assert lines("    foo\n", "ccbar" + ESC, autoindent=True) == ["    bar"]
    assert lines("    foo\n", "obar" + ESC) == ["    foo", "bar"]
    assert lines("\tfoo\n", "o\rx" + ESC, autoindent=True) == ["\tfoo", "", "\tx"]
    assert lines("  foo bar\n", "wi\r" + ESC, autoindent=True) == ["  foo ", "  bar"]


def test_pasting_text():
    e = make("ab\n")
    e.feed_paste("X\nY")
    assert e.lines == ["X", "Yab"] and e.mode == "n"
    e = make("ab\n", "A")
    e.feed_paste("1\r\n2")
    assert e.lines == ["ab1", "2"] and e.mode == "i"
    e = make("    ab\n", "A", autoindent=True)
    e.feed_paste("1\n2")
    assert e.lines == ["    ab1", "2"]                                   # no auto-indent while pasting
    e = make("ab\n")
    e.feed_paste("")
    assert e.lines == ["ab"]
    e = make("ab\n")
    e.feed_paste("xy")
    e.feed("u")
    assert e.lines == ["ab"]


# --- options and ex ---------------------------------------------------------------------------------------------------------------------------------
def test_options():
    assert make(keys=":set nu\r").opts["number"] is True
    assert make(keys=":set nu\r:set nonu\r").opts["number"] is False
    assert make(keys=":set invnu\r").opts["number"] is True
    assert make(keys=":set nu!\r").opts["number"] is True
    assert make(keys=":set ts=2 sw=2 et\r").opts["tabstop"] == 2
    assert make(keys=":set sw=2 et\r").opts["expandtab"] is True
    assert make(keys=":set ts?\r").msg == "tabstop=8"
    assert make(keys=":set ic?\r").msg == "noignorecase"
    assert make(keys=":set ts=0\r").msg.startswith("E487")
    assert make(keys=":set ts=abc\r").msg.startswith("E521")
    assert lines(keys=":set sw=4\r>>")[0] == "    one two three"
    assert lines(keys=":set sw=4 et\r>>>>")[0] == "        one two three"
    assert lines(keys=":set ts=4 sw=4\r>>")[0] == "\tone two three"
    assert lines(keys=":set ts=4 sw=4\r>>>>")[0] == "\t\tone two three"
    assert lines("a. b\nc\n", "J") == ["a. b c"]
    assert lines("a.\nb\n", "J") == ["a.  b"]
    assert lines("a.\nb\n", ":set nojs\rJ") == ["a. b"]


def test_ex_ranges():
    t = "1\n2\n3\n4\n5\n6\n"
    assert lines(t, ":2,4d\r") == ["1", "5", "6"]
    assert lines(t, ":2;+1d\r") == ["1", "4", "5", "6"]
    assert lines(t, ":.,+2d\r") == ["4", "5", "6"]
    assert lines(t, ":$d\r") == ["1", "2", "3", "4", "5"]
    assert lines(t, ":$-1,$d\r") == ["1", "2", "3", "4"]
    assert lines(t, ":/3/,/5/d\r") == ["1", "2", "6"]
    assert lines(t, "jjma:'a,'a+1d\r") == ["1", "2", "5", "6"]
    assert lines(t, "jVj:d\r") == ["1", "4", "5", "6"]
    assert lines(t, ":4\rdd") == ["1", "2", "3", "5", "6"]
    assert lines(t, ":%d\r") == [""]
    assert make(t, ":9d\r").msg.startswith("E16")
    assert make(t, ":2d3\r").lines == ["1", "5", "6"]
    assert lines(t, ":2d 2\r") == ["1", "4", "5", "6"]
    assert lines(t, ":2,3y a\r:$pu a\r") == ["1", "2", "3", "4", "5", "6", "2", "3"]


def test_global_and_normal():
    t = "a1\nb2\na3\nb4\n"
    assert lines(t, ":g/a/d\r") == ["b2", "b4"]
    assert lines(t, ":v/a/d\r") == ["a1", "a3"]
    assert lines(t, ":g/a/s/$/!/\r") == ["a1!", "b2", "a3!", "b4"]
    assert lines(t, ":g/a/normal Ax\r") == ["a1x", "b2", "a3x", "b4"]
    assert lines(t, ":g/./m0\r") == ["b4", "a3", "b2", "a1"]
    assert lines(t, ":g/a/t.\r") == ["a1", "a1", "b2", "a3", "a3", "b4"]
    assert lines(t, ":g/b/s/b/B/\r:g/A/d\r") == ["a1", "B2", "a3", "B4"]
    assert lines(t, ":%normal Ax\r") == ["a1x", "b2x", "a3x", "b4x"]
    assert lines(t, ":2,3normal I-\r") == ["a1", "-b2", "-a3", "b4"]
    assert lines(t, ":normal 2dd\r") == ["a3", "b4"]
    assert make(t, ":g/zzz/d\r").msg.startswith("E486")
