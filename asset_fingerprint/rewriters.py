"""Text rewriters for HTML, CSS and web manifests.

Each function takes the text and a ``mapper(ref) -> new_ref | None`` and
returns the new text. Only the reference itself is replaced; every other
byte of the file is preserved.
"""

import json
import re
from html.parser import HTMLParser

_CSS_TOKEN = re.compile(
    r"""/\*.*?\*/
    |@import\s+(?P<iq>["'])(?P<iu>.*?)(?P=iq)
    |url\(\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^)\s"']*))\s*\)""",
    re.S | re.I | re.X,
)


def rewrite_css(text, mapper):
    """Rewrite url(...) and @import "..." (comments are left alone)."""

    def sub(m):
        whole = m.group(0)
        if whole.startswith("/*"):
            return whole
        for name in ("iu", "dq", "sq", "bare"):
            if m.group(name) is not None:
                new = mapper(m.group(name))
                if new is None:
                    return whole
                a = m.start(name) - m.start(0)
                b = m.end(name) - m.start(0)
                return whole[:a] + new + whole[b:]
        return whole

    return _CSS_TOKEN.sub(sub, text)


_MANIFEST_SRC = re.compile(r'("src"\s*:\s*)"((?:[^"\\]|\\.)*)"')


def rewrite_manifest(text, mapper):
    """Rewrite every "src" string (icons, screenshots, shortcut icons)."""

    def sub(m):
        try:
            value = json.loads('"' + m.group(2) + '"')
        except ValueError:
            return m.group(0)
        new = mapper(value)
        if new is None:
            return m.group(0)
        return m.group(1) + json.dumps(new, ensure_ascii=False)

    return _MANIFEST_SRC.sub(sub, text)


_ATTR = re.compile(
    r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?"""
)
_URL_ATTRS = {
    ("link", "href"),
    ("script", "src"),
    ("img", "src"),
    ("source", "src"),
}
_SRCSET_ATTRS = {
    ("img", "srcset"),
    ("source", "srcset"),
    ("link", "imagesrcset"),
}
_META_IMAGE_KEYS = {
    "og:image",
    "og:image:url",
    "og:image:secure_url",
    "twitter:image",
    "twitter:image:src",
}


def _srcset_spans(value):
    """Yield (start, end) of each URL in a srcset value."""
    i, n = 0, len(value)
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        if i >= n:
            break
        start = i
        while i < n and not value[i].isspace():
            i += 1
        end = i
        while end > start and value[end - 1] == ",":
            end -= 1
        if end > start:
            yield start, end
        if end == i:
            while i < n and value[i] != ",":
                i += 1


class _Finder(HTMLParser):
    def __init__(self, text, mapper):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.mapper = mapper
        self.edits = []
        self._in_style = False
        self._lines = [0] + [m.end() for m in re.finditer("\n", text)]

    def _abs(self):
        line, col = self.getpos()
        return self._lines[line - 1] + col

    def _edit_value(self, start, value, srcset):
        if srcset:
            for a, b in _srcset_spans(value):
                new = self.mapper(value[a:b])
                if new is not None:
                    self.edits.append((start + a, start + b, new))
        else:
            new = self.mapper(value)
            if new is not None:
                self.edits.append((start, start + len(value), new))

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._in_style = True
        if tag not in ("link", "script", "img", "source", "meta"):
            return
        raw = self.get_starttag_text()
        pos = self._abs()
        if not raw or self.text[pos:pos + len(raw)] != raw:
            return
        found = []
        for m in _ATTR.finditer(raw, len(tag) + 1):
            for g in (2, 3, 4):
                if m.group(g) is not None:
                    found.append((m.group(1).lower(), m.group(g), pos + m.start(g)))
                    break
        names = {n: v for n, v, _ in found}
        is_meta_image = tag == "meta" and (
            names.get("property", "").lower() in _META_IMAGE_KEYS
            or names.get("name", "").lower() in _META_IMAGE_KEYS
        )
        for name, value, start in found:
            if (tag, name) in _URL_ATTRS or (is_meta_image and name == "content"):
                self._edit_value(start, value, False)
            elif (tag, name) in _SRCSET_ATTRS:
                self._edit_value(start, value, True)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if not self._in_style or not data:
            return
        pos = self._abs()
        if self.text[pos:pos + len(data)] != data:
            return
        new = rewrite_css(data, self.mapper)
        if new != data:
            self.edits.append((pos, pos + len(data), new))


def rewrite_html(text, mapper):
    """Rewrite link href, script src, img/source src+srcset, og/twitter
    image meta tags and the contents of <style> blocks."""
    finder = _Finder(text, mapper)
    finder.feed(text)
    finder.close()
    out = text
    for start, end, new in sorted(finder.edits, reverse=True):
        out = out[:start] + new + out[end:]
    return out
