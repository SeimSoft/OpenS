"""Python syntax highlighter with a VS Code Dark+ inspired colour scheme."""

import re
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont


# ── VS Code Dark+ palette ───────────────────────────────────────────
_COLORS = {
    "keyword": "#569CD6",  # blue
    "builtin": "#4EC9B0",  # teal
    "string": "#CE9178",  # orange-brown
    "number": "#B5CEA8",  # light green
    "comment": "#6A9955",  # green
    "decorator": "#DCDCAA",  # yellow
    "self": "#9CDCFE",  # light blue
    "class_def": "#4EC9B0",  # teal
    "func_def": "#DCDCAA",  # yellow
    "operator": "#D4D4D4",  # light grey
    "fstring_brace": "#569CD6",  # blue (f-string {…})
    "default": "#D4D4D4",  # light grey
}


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class PythonHighlighter(QSyntaxHighlighter):
    """Regex-based Python highlighter (single-line patterns + multi-line strings)."""

    # Python keywords
    KEYWORDS = [
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    ]

    BUILTINS = [
        "abs",
        "all",
        "any",
        "bin",
        "bool",
        "bytes",
        "callable",
        "chr",
        "classmethod",
        "complex",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "eval",
        "exec",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "help",
        "hex",
        "id",
        "input",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "locals",
        "map",
        "max",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "open",
        "ord",
        "pow",
        "print",
        "property",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "setattr",
        "slice",
        "sorted",
        "staticmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "vars",
        "zip",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._rules: list[tuple[re.Pattern, QTextCharFormat, int]] = []

        # ── Build rules (order matters – first match wins for overlapping) ──

        # Decorator
        self._rules.append(
            (
                re.compile(r"@\w+"),
                _fmt(_COLORS["decorator"]),
                0,
            )
        )

        # class / def  followed by name
        self._rules.append(
            (
                re.compile(r"\bclass\s+(\w+)"),
                _fmt(_COLORS["class_def"], bold=True),
                1,
            )
        )
        self._rules.append(
            (
                re.compile(r"\bdef\s+(\w+)"),
                _fmt(_COLORS["func_def"]),
                1,
            )
        )

        # Keywords
        kw_pattern = r"\b(?:" + "|".join(self.KEYWORDS) + r")\b"
        self._rules.append(
            (
                re.compile(kw_pattern),
                _fmt(_COLORS["keyword"]),
                0,
            )
        )

        # self / cls
        self._rules.append(
            (
                re.compile(r"\bself\b|\bcls\b"),
                _fmt(_COLORS["self"], italic=True),
                0,
            )
        )

        # Builtins
        bi_pattern = r"\b(?:" + "|".join(self.BUILTINS) + r")\b"
        self._rules.append(
            (
                re.compile(bi_pattern),
                _fmt(_COLORS["builtin"]),
                0,
            )
        )

        # Numbers (int, float, hex, oct, bin, complex)
        self._rules.append(
            (
                re.compile(
                    r"\b0[xXoObB][\da-fA-F_]+\b|\b\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?j?\b"
                ),
                _fmt(_COLORS["number"]),
                0,
            )
        )

        # Comment – applied BEFORE strings so that string formatting
        # overwrites any false '#' matches inside quoted text.
        self._rules.append(
            (
                re.compile(r"#[^\n]*"),
                _fmt(_COLORS["comment"], italic=True),
                0,
            )
        )

        # Strings – single-line  (single/double, raw/f-strings)
        # Applied AFTER comments so they take priority over '#' inside strings.
        self._rules.append(
            (
                re.compile(r'''[brufBRUF]{0,2}"[^"\\]*(?:\\.[^"\\]*)*"'''),
                _fmt(_COLORS["string"]),
                0,
            )
        )
        self._rules.append(
            (
                re.compile(r"""[brufBRUF]{0,2}'[^'\\]*(?:\\.[^'\\]*)*'"""),
                _fmt(_COLORS["string"]),
                0,
            )
        )

        # Multi-line string delimiters (used in highlightBlock state machine)
        self._tri_double = re.compile(r'"""')
        self._tri_single = re.compile(r"'''")
        self._string_fmt = _fmt(_COLORS["string"])

    # ─────────────────────────────────────────────────────────────────
    def highlightBlock(self, text: str):
        # Pass 1: left-to-right scan to find string and comment spans.
        # This ensures '#' inside strings is never treated as a comment.
        protected: list[tuple[int, int]] = []  # (start, end) of strings/comments
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            # Check for string start (single or double quote, with optional prefix)
            if ch in ('"', "'") or (
                ch in "brufBRUF"
                and i + 1 < n
                and text[i + 1] in ("'", '"', "b", "r", "u", "f", "B", "R", "U", "F")
            ):
                # Consume optional prefix characters
                start = i
                while i < n and text[i] in "brufBRUF":
                    i += 1
                if i >= n or text[i] not in ("'", '"'):
                    i = start + 1
                    continue
                quote = text[i]
                i += 1
                # Consume until matching unescaped close quote
                while i < n:
                    if text[i] == "\\":
                        i += 2  # skip escaped char
                        continue
                    if text[i] == quote:
                        i += 1
                        break
                    i += 1
                end = i
                self.setFormat(start, end - start, self._string_fmt)
                protected.append((start, end))
            elif ch == "#":
                # Real comment – everything to end of line
                self.setFormat(i, n - i, _fmt(_COLORS["comment"], italic=True))
                protected.append((i, n))
                break
            else:
                i += 1

        # Pass 2: apply keyword / builtin / number / decorator rules
        # only outside protected (string/comment) spans.
        def is_protected(start, end):
            for ps, pe in protected:
                if start < pe and end > ps:  # overlap
                    return True
            return False

        for pattern, fmt, group in self._rules:
            for m in pattern.finditer(text):
                s = m.start(group)
                e = m.end(group)
                if not is_protected(s, e):
                    self.setFormat(s, e - s, fmt)

        # Pass 3: Multi-line strings (triple quotes)
        self._match_multiline(text, self._tri_double, 1)
        self._match_multiline(text, self._tri_single, 2)

    def _match_multiline(self, text: str, delimiter: re.Pattern, state_id: int):
        """Handle triple-quoted multi-line strings."""
        if self.previousBlockState() == state_id:
            # We are inside a multi-line string from a previous block
            start = 0
            add = 0
        else:
            # Look for the start of a triple-quote
            m = delimiter.search(text)
            if m is None:
                return
            start = m.start()
            add = 3  # length of the opening delimiter

        # From 'start + add', look for the closing delimiter
        while start >= 0:
            end_match = delimiter.search(text, start + add)
            if end_match:
                # Found the end in this block
                length = end_match.end() - start
                self.setFormat(start, length, self._string_fmt)
                self.setCurrentBlockState(0)
                # Continue searching for another triple-quote in this line
                start = end_match.end()
                add = 0
                m2 = delimiter.search(text, start)
                if m2:
                    start = m2.start()
                    add = 3
                else:
                    break
            else:
                # End not found – the rest of the block is inside the string
                self.setCurrentBlockState(state_id)
                self.setFormat(start, len(text) - start, self._string_fmt)
                break


def apply_dark_plus_theme(text_edit):
    """Apply Dark+ colours to a QTextEdit and attach the highlighter."""
    text_edit.setStyleSheet(
        """
        QTextEdit {
            background-color: #1E1E1E;
            color: #D4D4D4;
            selection-background-color: #264F78;
            selection-color: #D4D4D4;
            border: 1px solid #3C3C3C;
        }
    """
    )
    font = text_edit.font()
    font.setFamily("Menlo")  # macOS mono; falls back gracefully
    font.setPointSize(12)
    font.setFixedPitch(True)
    text_edit.setFont(font)

    text_edit.setTabStopDistance(text_edit.fontMetrics().horizontalAdvance("    "))

    highlighter = PythonHighlighter(text_edit.document())
    # Store a reference so it doesn't get garbage-collected
    text_edit._syntax_highlighter = highlighter
    return highlighter
