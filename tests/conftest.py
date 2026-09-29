import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-1"
INDEX = """<!doctype html>
<html><head>
<meta property="og:image" content="https://example.com/img/logo.png">
<meta name="twitter:image" content="https://cdn.example.net/img/logo.png">
<link rel="stylesheet" href="/css/site.css">
<link rel="manifest" href="/site.webmanifest">
<script src="/js/app.js"></script>
<script src="https://cdn.example.net/lib.js"></script>
</head><body>
<img src="img/logo.png" srcset="img/logo.png 1x, img/logo@2x.png 2x" alt="">
<picture><source srcset="/img/logo.png 480w, /img/logo@2x.png 960w"></picture>
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="">
<img src="/img/missing.png" alt="">
<a href="/img/logo.png">download</a>
</body></html>
"""
SITE_CSS = """@import "base.css";
body { background: url(../img/logo.png); }
.f { src: url('/fonts/f.woff2') format('woff2'); }
.x { background: url(https://cdn.example.net/x.png); }
"""


def write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_bytes(content.encode("utf-8"))
    else:
        p.write_bytes(content)


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    write(root, "index.html", INDEX)
    write(root, "css/site.css", SITE_CSS)
    write(root, "css/base.css", "html { margin: 0; }\n")
    write(root, "js/app.js", "console.log('hi');\n")
    write(root, "img/logo.png", PNG)
    write(root, "img/logo@2x.png", PNG + b"2x")
    write(root, "fonts/f.woff2", b"wOF2-fake")
    write(root, "site.webmanifest",
          '{\n  "name": "Example",\n  "icons": [\n'
          '    {"src": "img/logo.png", "sizes": "192x192"},\n'
          '    {"src": "https://cdn.example.net/i.png", "sizes": "512x512"}\n  ]\n}\n')
    return root


@pytest.fixture
def snap():
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file()}
    return snapshot


@pytest.fixture
def put():
    return write
