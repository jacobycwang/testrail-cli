import re
from html.parser import HTMLParser

BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "tr", "ul", "ol", "table", "pre", "blockquote",
        "hr", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    }
)
CELL_TAGS = frozenset({"td", "th"})
VERBATIM_TAGS = frozenset({"pre", "code"})
DROPPED_TAGS = frozenset({"script", "style"})
TAG = re.compile(r"<\s*/?[a-zA-Z][^>]*>")
HSPACE = re.compile(r"[^\S\n]+")
NEWLINE_RUN = re.compile(r"[^\S\n]*\n[^\S\n]*")
BLANK_LINES = re.compile(r"\n{3,}")


def html_to_text(value: str | None) -> str:
    """Flatten a TestRail rich-text field into plain text; pass tag-free text through."""
    if not value:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if not TAG.search(text):
        return text
    parser = _Flattener()
    parser.feed(text)
    parser.close()
    return parser.text()


class _Flattener(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._at_line_start = True
        self._verbatim = 0
        self._dropped = 0
        self._anchor: tuple[str, int] | None = None

    def text(self) -> str:
        lines = [line.rstrip() for line in "".join(self._out).split("\n")]
        return BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROPPED_TAGS:
            self._dropped += 1
            return
        if tag in BLOCK_TAGS:
            self._break(hard=tag == "br")
        if tag == "li":
            self._out.append("- ")
        if tag in VERBATIM_TAGS:
            self._verbatim += 1
        if tag == "a":
            self._anchor = (dict(attrs).get("href") or "", len(self._out))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCK_TAGS:
            self._break(hard=tag == "br")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROPPED_TAGS:
            self._dropped = max(0, self._dropped - 1)
            return
        if tag in VERBATIM_TAGS:
            self._verbatim = max(0, self._verbatim - 1)
        if tag == "a":
            self._close_anchor()
        if tag in CELL_TAGS:
            self._space()
        if tag in BLOCK_TAGS and tag != "br":
            self._break()

    def handle_data(self, data: str) -> None:
        if self._dropped:
            return
        if self._verbatim:
            self._write(data)
            return
        text = NEWLINE_RUN.sub("\n", HSPACE.sub(" ", data.replace("\xa0", " ")))
        if not text.strip():
            self._break() if "\n" in text else self._space()
            return
        self._write(text)

    def _write(self, text: str) -> None:
        if not text:
            return
        self._out.append(text)
        self._at_line_start = text.endswith("\n")

    def _break(self, hard: bool = False) -> None:
        if self._at_line_start and not (hard and self._out):
            return
        self._out.append("\n")
        self._at_line_start = True

    def _space(self) -> None:
        if not self._at_line_start:
            self._out.append(" ")

    def _close_anchor(self) -> None:
        if self._anchor is None:
            return
        href, start = self._anchor
        self._anchor = None
        label = "".join(self._out[start:]).strip()
        if not href or href == label:
            return
        self._write(href if not label else f" ({href})")
