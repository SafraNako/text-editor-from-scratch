# text-editor-from-scratch

A modal terminal text editor in pure Python, written from scratch on raw terminal mode: a subset of **vim** (normal, insert, replace, visual and command-line modes; the motions, operators, text objects, registers, marks, undo, `.`, search and the common `:` commands) with no curses and no dependencies. The terminal is driven with `termios` and ANSI escape sequences only.

It is checked against real **vim** (the same keystrokes typed into both, files and cursor compared) and drawn through a real terminal emulator in a pseudo-terminal, instead of just against its own tests.

```
  1 def greet(name):
  2     """Say hello."""
  3     message = "Hello, " + name + "!"
  4     print(message)
  5
  6
  7 for who in ["world", "vim", "ked"]:
  8     greet(who)
~
 NORMAL  hello.py                         8,11  All
/who
```

```
$ pip install -e .
$ ked notes.txt              # open (or create) a file
$ ked +40 -c "set nu" main.py
$ ked -s keys.txt notes.txt  # type the keys of a file into it, no terminal needed (like vim -s)
```

Python 3.9+, POSIX (macOS, Linux). The editor is `kendi_editor` (`ked` on the command line); `Editor` can also be used without a terminal: `Editor(text).feed_keys(list("dwx"))`.

## What it does

| | |
|---|---|
| **Motions** | `h j k l`, arrows, `0 ^ $ \|`, `w W b B e E ge gE`, `f F t T ; ,`, `% { }`, `gg G`, `+ - _`, `H M L`, `/ ? n N * #` (with `/pat/e`, `/pat/+1`, `/pat/s-1` offsets), marks `` ma 'a `a ``, counts for everything |
| **Operators** | `d c y > < g~ gu gU` with any motion or text object, doubled (`dd cc yy >> << g~~ guu gUU`), `x X D C s S Y r R ~ J gJ p P gp`, registers (`"a`, `"A`, `"_`, `"0`, `"1`-`"9`, `"-`), `u` and `Ctrl-R` (with vim's idea of where the cursor goes), `.` (also after visual operators), `Ctrl-A` / `Ctrl-X` |
| **Text objects** | `iw aw iW aW ip ap`, `i" a" i' a' i\` a\``, `i( a( ib`, `i{ a{ iB`, `i[ a[`, `i< a<`, with counts and, in visual mode, extending the selection |
| **Insert mode** | `i a I A o O gI`, counts (`3ofoo`), `Backspace`, `Delete`, `Ctrl-W`, `Ctrl-U`, `Ctrl-V`, cursor keys (which start a new undo step), auto-indent, `expandtab`, bracketed paste |
| **Visual mode** | `v` and `V`, `o`, text objects, `d y c < > ~ u U J gJ r p P :`, `'<` and `'>` |
| **Command line** | ranges (`1,5`, `%`, `.,$`, `/pat/`, `'a,'b`, `'<,'>`, `;`, offsets), `:w :q :wq :x :e :r :d :y :pu :m :t :co :j :> :< :normal :g :v :sort :s :k :set :noh`, with `!`, `:s` with `&`, `\1`-`\9`, `\u \U \l \L \e`, `\r`, flags `g i I n e`, `:s` repeat (`&`, `:&&`) |
| **Search** | vim's "magic" patterns (`\< \> \( \) \| \+ \? \= \{n,m} \s \d \w \a \l \u \x`, `[[:alpha:]]`, `\c \C`, anchors that are only anchors where vim says so), `'ignorecase'`, `'smartcase'`, `'wrapscan'` |
| **Screen** | soft-wrapped lines, tabs, control characters (`^A`), undecodable bytes (`<ff>`), wide and combining characters, line numbers (`number`, `relativenumber`), `nowrap` with sideways scrolling, visual selection and `hlsearch` in colour, a status line (mode, file, `[+]`, `[RO]`, `row,col`, `All/Top/Bot/42%`), a message line, scrolling like vim's (a line at a time near the edge, centred on a long jump) |
| **Files** | UTF-8 with any other bytes kept as they are, `\r\n` files stay `\r\n`, a missing final newline is added like vim does, new files, permissions kept, symlinks written through, atomic replacement (no half-written file), a file that changed on disk is not overwritten without `!` |

## How it is built

```
bytes ──▶ keys.py ──▶ key ──▶ Editor (a generator per command) ──▶ buffer, registers, undo ──▶ screen.py ──▶ rows ──▶ terminal.py ──▶ bytes
          decoder      │         normal.py  insert.py  ex.py  search.py                          render()                diff of rows
```

| Module | Role |
|---|---|
| `terminal.py` | Raw mode (no echo, no line editing, no signals from keys, no flow control), the alternate screen, bracketed paste, window size and `SIGWINCH`, `SIGTERM`/`SIGHUP` handled so the terminal is always put back |
| `keys.py` | Bytes to keys: UTF-8 across reads, `CSI`/`SS3` sequences for the cursor keys, a lone `<Esc>` told from the start of a sequence by a 50 ms timeout, paste |
| `editor.py` | The buffer (a list of lines), cursor, registers, marks, options, file reading and atomic writing, and the undo log |
| `normal.py` | Normal and visual mode. **Each command is a generator** that asks for its next key with `yield`, so `"a3d2fx` is straight-line code and `.` replays the recorded keys |
| `motions.py` | vim's word motions ported step by step (they are the part with the most corner cases) |
| `insert.py`, `ex.py`, `search.py`, `vimregex.py` | Insert and replace mode; the `:` commands and ranges; searching; vim patterns translated to Python's `re` |
| `screen.py` | The window, status line and message line as rows of text with colours, plus the cursor position; only rows that changed are written |
| `cli.py` | `ked`, and the main loop |

**Undo** is a log of changes to the list of lines (row, lines taken out, lines put in) that costs what the change costs, not what the file weighs; the cursor goes where vim puts it (the first line touched; the column it had before if that is the same line).

## How it was checked

There are no mocks. The oracles are the real programs.

| Check | What | Result |
|---|---|---|
| **vim, live** (`test_vim_differential.py`) | The same keys are typed into vim 9 (in a pseudo-terminal, as a user would, with a pause after each `<Esc>`) and into this editor; the two files that come out are compared, and a mark inserted at the end shows where the cursor was. A table of 845 commands (every motion, operator with every motion and text object, edit, visual command, search and `:` command, on four texts at several cursor positions), then 800 random sessions of up to 10 commands each from a seeded generator | identical, apart from the known differences below |
| **vim, recorded** (`test_recorded.py`) | The 845 answers of vim are in `recorded_vim.json` (`python tests/record_vim.py` makes it): the same table checked without vim | identical |
| **A real terminal emulator** (`test_screen.py`, `test_terminal.py`) | Every frame is given to **pyte** and must show the text that was meant, with the cursor where it was meant; and the real program is started in a pty, fed raw bytes (cursor keys, a lone `<Esc>`, a paste, `Ctrl-C`, `Ctrl-S`), resized (`SIGWINCH`), signalled (`SIGTERM`, `SIGHUP`), and the terminal's modes are compared before and after | the screen is what was drawn; the terminal is always put back |
| **Hand-written expectations** | modes and what is shown for them, registers (what goes to `"0`, `"1`-`"9`, `"-`), marks that move with their lines, undo granularity and cursor, insert-mode keys, options, ranges, `:g`, error messages | |
| **Files** (`test_files.py`) | line endings, missing final newline, new and empty files, permissions, symlinks, external changes, read-only, non-UTF-8 bytes, `:r`, `:e`, `:w name` | |

125 tests, about 90 s locally and 35 s in CI (most of it vim); on Python 3.9, 3.12 and 3.13, against vim 9.0 (macOS) and 9.1 (CI, Ubuntu). `pytest -q`; the vim tests are skipped without vim and the terminal tests need `pyte`.

**What vim found in this editor** (each is now a test): `u` is not what a script file of keys does to vim (a `-s` script is one undo step: the oracle types its keys instead); the cursor after an undo is not the first changed line but where the change started, and "one line up" when it was an `o`; a deletion that ends in column 1 turns linewise; `cw` is `ce`; `dw` on the last word stops at the end of the line; `g~` over an empty region in column 1 swaps the whole line (vim backs the end up by one first); `{` in a one-line buffer goes to the end of the line; `:s` leaves the cursor on the first non-blank, `:g` after it on the last line it touched; a `J` after an empty line adds a space; `joinspaces`; searching backwards finds matches that do not overlap; `V` then `r` puts the cursor in column 0 while `V` then `Y` puts it where the backwards selection ended; the undo of `:normal` over a range is one step; `p` in visual mode splits or replaces lines depending on the register and the selection; and about thirty more, found by the random sessions and minimised by a script that removes commands until the difference remains.

**Known differences** (the random sessions differ from vim in about 1 of 200; the batches tolerate 3 in 100):

- Not implemented: sentences (`( ) is as`), tags (`it at`), `gq`, `=`, folds, windows, tabs, macros (`q`, `@`), block-wise visual mode, `gn`, the jump list, `:s` patterns that match a newline, `\v`, `Ctrl-X` completion, `:!`, syntax colours, a swap file or `viminfo`.
- `h` and `l` treat a combining character as a character of its own.
- A count together with backspace in the text of an insert (`3ia<BS>b`) repeats differently from vim.
- After `:>` or `:put` on a range vim can leave the cursor beyond the end of a short line; this editor keeps it on the line.
- Some corners of visual mode: `ip` after a charwise selection keeps vim's column, `.` after a visual `p`, a failing motion in visual mode.
- vim asks "Backwards range given, OK to swap (y/n)?"; this editor swaps.

## Numbers

Batch jobs on a file of 100 000 lines (4 MB), `ked -s script` against `vim -es`, an old MacBook, Python 3.13 (`python benchmarks/bench.py`):

| job | ked | vim | ratio |
|---|---|---|---|
| open and write | 0.18 s | 0.08 s | 2.1× |
| `:%s/line/LINE/g` | 0.58 s | 0.19 s | 3.1× |
| `:g/7/d` (40 000 lines) | 1.39 s | 0.16 s | 8.6× |
| `:sort!` | 0.20 s | 0.58 s | 0.3× |
| `:%normal A;` | 2.59 s | 0.73 s | 3.6× |
| `:%s/\(\w\+\) \(\w\+\)/\2 \1/` | 0.63 s | 0.22 s | 2.8× |
| `/number 77777`, `dd` | 0.19 s | 0.10 s | 1.9× |
| `:%j` | 0.68 s | 0.12 s | 5.7× |
| 2000 × `ddp` typed in a row | 0.31 s | | |
| 1000 × `cwXY<Esc>j` | 0.24 s | | |

(The results of both are the same file in every row.) `:g` stays linear because the rows it has to visit are followed through the changes as one lazy offset; a 300 000 line file opens in under a second.

## Limits

- One buffer, one window. Everything is in memory (the lines as Python strings).
- Not a vim: no scripting, no mappings, no plugins, no `.vimrc` (set options with `-c "set ..."`).
- The terminal must understand ANSI escape sequences (all that matter do) and a 50 ms pause after `<Esc>` is how a lone `<Esc>` is told from the start of a key sequence; over a slow link set it higher (`ESC_TIMEOUT` in `cli.py`).
- Not tried on Windows.

## Development

```
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q                    # needs vim for the live comparison; pyte for the terminal tests
python tests/record_vim.py             # record vim's answers again (the command table)
python benchmarks/bench.py [lines]
```

MIT licensed.
