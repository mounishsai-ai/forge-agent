r"""A small INI-like config format: parse() + Document.dumps() must round-trip
exactly (dumps(parse(text)) == text) for any text that already follows the
canonical form below -- this module both reads *and* writes the format, and
the two must agree byte-for-byte.

Canonical grammar (each line is one of, split on "\n"; no trailing newline
at end of file):

  blank line
      An empty line ("").

  comment line
      Starts with ';' or '#' as the very first character. Everything after
      that single marker character is the comment text, preserved exactly
      (including on round-trip -- ';' comments stay ';' comments, '#' stay
      '#', and the text after the marker is not stripped or altered).

  section header
      "[" + name + "]" with no surrounding whitespace, e.g. "[server]".
      A section may be reopened later in the file (its keys accumulate);
      reopening is not an error by itself.

  key/value line
      "key = value" -- exactly one space on each side of '='. `key` matches
      [A-Za-z0-9_.-]+. Before the first section header, keys belong to the
      root section, whose name is "" (empty string).

      `value` is one of:
        - unquoted: the rest of the line, taken completely literally (no
          stripping, no escape processing).
        - quoted: begins with '"' and ends with an unescaped '"' that is the
          last character on the line. Inside, '\"' means a literal '"' and
          '\\' means a literal '\'. Any other backslash escape is a parse
          error: raise IniError("invalid escape sequence at line N"). A
          quoted value with no closing '"' on the line is a parse error:
          raise IniError("unterminated quoted value at line N").

  continuation line
      A line that starts with exactly two spaces "  " immediately following
      a key/value line (or another continuation line for the same key).
      Everything after the two-space prefix is appended to that key's value
      literally (no escape processing, even if the key's value was quoted),
      joined to the previous content with a single "\n". This is the *only*
      way a value can contain a newline -- quoted values are always a
      single physical line.

  Anything else (e.g. a key line with the wrong spacing around '=', a
  continuation line with no preceding key) is a parse error: raise
  IniError("invalid line at line N").

Duplicate keys: if the same key appears twice *within the same section*
(counting all reopenings of that section together), raise
IniError("duplicate key 'KEY' in section 'NAME' at line N") where N is the
line number (1-indexed) of the second (duplicate) occurrence, and NAME is
"" for the root section.

Document.get(section, key) returns the fully-resolved value (continuation
lines already joined with "\n", quoting/escapes already removed) or raises
KeyError if the section or key doesn't exist.

Document.dumps() must reproduce the exact source text for any Document that
came from parse() on canonically-formatted input -- comments, blank lines,
section order, key order, quoting style, and continuation formatting all
preserved.
"""
from __future__ import annotations


class IniError(Exception):
    pass


class Document:
    """In-memory representation of a parsed INI-like file.

    Store whatever internal structure you like, but you need enough of it to
    (a) answer get(section, key) and (b) reproduce the original text byte
    for byte from dumps(). In particular, remember for each key/value line
    whether the value was originally quoted, since that affects how dumps()
    must write it back out.
    """

    def __init__(self) -> None:
        raise NotImplementedError

    def sections(self) -> list[str]:
        """Return section names in the order they first appeared (root
        section "" is not included unless it has at least one key)."""
        raise NotImplementedError

    def get(self, section: str, key: str):
        raise NotImplementedError

    def dumps(self) -> str:
        raise NotImplementedError


def parse(text: str) -> Document:
    raise NotImplementedError
