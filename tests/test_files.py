"""Reading and writing files: line endings, a missing final newline, new files, permissions, a file that changed on disk, atomic replacement, odd bytes."""
import os
import stat

import pytest

from kendi_editor import Editor
from kendi_editor.errors import CmdError


def edit(path, keys, size=(24, 80)):
    e = Editor.open(str(path), size)
    e.feed_keys(list(keys))
    return e


def test_reading_and_writing_back(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"one\ntwo\nthree\n")
    e = edit(p, "jddZZ")
    assert e.quit and p.read_bytes() == b"one\nthree\n"


def test_message_on_open_and_write(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"one\ntwo\n")
    e = Editor.open(str(p))
    assert e.msg == '"%s" 2L, 8B' % p
    e.feed_keys(list(":w\r"))
    assert e.msg == '"%s" 2L, 8B written' % p and not e.modified


def test_a_missing_final_newline_is_added_like_vim_does(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"one\ntwo")
    e = Editor.open(str(p))
    assert e.lines == ["one", "two"] and e.noeol and "[noeol]" in e.msg
    e.feed_keys(list(":w\r"))
    assert p.read_bytes() == b"one\ntwo\n"


def test_crlf_files_keep_their_line_endings(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"one\r\ntwo\r\n")
    e = Editor.open(str(p))
    assert e.fileformat == "dos" and e.lines == ["one", "two"]
    e.feed_keys(list("ox\x1b:w\r"))
    assert p.read_bytes() == b"one\r\nx\r\ntwo\r\n"
    p.write_bytes(b"one\r\ntwo\n")                                   # a mix is not converted
    e = Editor.open(str(p))
    assert e.fileformat == "unix" and e.lines == ["one\r", "two"]


def test_a_new_file(tmp_path):
    p = tmp_path / "new.txt"
    e = Editor.open(str(p))
    assert e.msg.endswith("[New]") and e.lines == [""] and e.no_lines and e.is_new
    e.feed_keys(list("ihello\x1b:wq\r"))
    assert p.read_bytes() == b"hello\n" and e.quit
    e = Editor.open(str(tmp_path / "empty.txt"))
    e.feed_keys(list(":w\r"))
    assert (tmp_path / "empty.txt").read_bytes() == b""                # an empty buffer is an empty file


def test_empty_file_and_emptied_buffer(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"")
    e = Editor.open(str(p))
    assert e.no_lines and e.msg == '"%s" 0L, 0B' % p
    p.write_bytes(b"a\nb\n")
    e = edit(p, "dG:w\r")
    assert p.read_bytes() == b""
    e = edit(p, "ix\x1b:w\r")
    assert p.read_bytes() == b"x\n"
    p.write_bytes(b"a\n")
    e = edit(p, "ddix\x08\x1b:w\r")
    assert p.read_bytes() == b"\n"


def test_permissions_are_kept(tmp_path):
    p = tmp_path / "f.sh"
    p.write_bytes(b"echo hi\n")
    os.chmod(p, 0o754)
    edit(p, "A!\x1b:w\r")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o754 and p.read_bytes() == b"echo hi!\n"


def test_symlinks_are_written_through(tmp_path):
    target = tmp_path / "real.txt"
    target.write_bytes(b"a\n")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    edit(link, "Ab\x1b:w\r")
    assert link.is_symlink() and target.read_bytes() == b"ab\n"


def test_no_temporary_files_are_left_behind(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"a\n")
    edit(p, "x:w\r")
    assert sorted(os.listdir(tmp_path)) == ["f.txt"]


def test_a_file_changed_on_disk_is_not_overwritten_without_bang(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"a\n")
    e = Editor.open(str(p))
    p.write_bytes(b"changed elsewhere\n")
    os.utime(p, (1, 1))
    e.feed_keys(list("x:w\r"))
    assert "changed since reading" in e.msg and p.read_bytes() == b"changed elsewhere\n"
    e.feed_keys(list(":w!\r"))
    assert p.read_bytes() == b"\n" and "written" in e.msg


def test_write_to_another_name_and_ranges(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"a\nb\nc\n")
    e = Editor.open(str(p))
    e.feed_keys(list(":w %s\r" % (tmp_path / "copy.txt")))
    assert (tmp_path / "copy.txt").read_bytes() == b"a\nb\nc\n" and e.filename == str(p)
    e.feed_keys(list(":2,3w %s\r" % (tmp_path / "part.txt")))
    assert (tmp_path / "part.txt").read_bytes() == b"b\nc\n"
    e.feed_keys(list(":w %s\r" % (tmp_path / "copy.txt")))
    assert "E13" in e.msg
    e.feed_keys(list(":w! %s\r" % (tmp_path / "copy.txt")))
    assert "written" in e.msg


def test_unwritable_places(tmp_path):
    e = Editor.open(str(tmp_path / "nodir" / "f.txt"))
    e.feed_keys(list("ix\x1b:w\r"))
    assert e.msg.startswith("E212") and e.modified
    e = Editor("text\n")
    e.feed_keys(list(":w\r"))
    assert e.msg == "E32: No file name"
    d = Editor.open(str(tmp_path))
    assert "is a directory" in d.msg


def test_readonly(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"a\n")
    e = Editor.open(str(p))
    e.readonly = True
    e.feed_keys(list("x:w\r"))
    assert e.msg.startswith("E45") and p.read_bytes() == b"a\n"
    e.feed_keys(list(":w!\r"))
    assert p.read_bytes() == b"\n"


def test_bytes_that_are_not_utf8_survive(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"caf\xe9 \xff\x00 end\n\xfe\n")
    edit(p, "jx:w\r")
    assert p.read_bytes() == b"caf\xe9 \xff\x00 end\n\n"
    p.write_bytes("héllo ∑ 日本\n".encode())
    edit(p, "A!\x1b:w\r")
    assert p.read_bytes() == "héllo ∑ 日本!\n".encode()


def test_edit_and_read_commands(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"A\n")
    b.write_bytes(b"B1\nB2\n")
    e = Editor.open(str(a))
    e.feed_keys(list(":r %s\r" % b))
    assert e.lines == ["A", "B1", "B2"] and e.row == 1
    e.feed_keys(list(":e %s\r" % b))
    assert e.msg.startswith("E37")
    e.feed_keys(list(":e! %s\r" % b))
    assert e.lines == ["B1", "B2"] and e.filename == str(b) and not e.modified
    e.feed_keys(list(":e %s\r" % (tmp_path / "missing.txt")))
    assert e.msg.endswith("[New]")


def test_wq_and_x(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"a\n")
    e = edit(p, "x:x\r")
    assert e.quit and p.read_bytes() == b"\n"
    p.write_bytes(b"a\n")
    e = edit(p, ":x\r")
    assert e.quit and p.read_bytes() == b"a\n"
    e = edit(p, "xZQ")
    assert e.quit and p.read_bytes() == b"a\n"
    e = edit(p, "xZZ")
    assert e.quit and p.read_bytes() == b"\n"


def test_cmderror_is_an_exception_with_the_message():
    with pytest.raises(CmdError, match="E32"):
        Editor("x\n").write()
