"""Recommended cache headers and ready-to-paste server snippets."""

IMMUTABLE = "public, max-age=31536000, immutable"
HTML = "no-cache"


def _ext_alternation(exts):
    return "|".join(sorted(e.lstrip(".") for e in exts))


def caddy(mode, length, exts):
    alt = _ext_alternation(exts)
    if mode == "rename":
        matcher = "@fingerprinted path_regexp \\.[0-9a-f]{%d}\\.(%s)$" % (length, alt)
    else:
        matcher = "@fingerprinted {\n    path_regexp \\.(%s)$\n    query v=*\n}" % alt
    return (
        matcher + "\n"
        'header @fingerprinted Cache-Control "%s"\n'
        "@html path_regexp (^|/)$|\\.html?$\n"
        'header @html Cache-Control "%s"' % (IMMUTABLE, HTML)
    )


def nginx(mode, length, exts):
    alt = _ext_alternation(exts)
    if mode == "rename":
        return (
            "location / {\n"
            '    add_header Cache-Control "%s" always;\n'
            "}\n"
            'location ~* "\\.[0-9a-f]{%d}\\.(%s)$" {\n'
            '    add_header Cache-Control "%s" always;\n'
            "}" % (HTML, length, alt, IMMUTABLE)
        )
    return (
        "map $arg_v $asset_cache_control {\n"
        '    ""      "%s";\n'
        '    default "%s";\n'
        "}\n"
        "location / {\n"
        '    add_header Cache-Control "%s" always;\n'
        "}\n"
        'location ~* "\\.(%s)$" {\n'
        "    add_header Cache-Control $asset_cache_control always;\n"
        "}" % (HTML, IMMUTABLE, HTML, alt)
    )


def report(mode, length, exts):
    return (
        "Recommended Cache-Control\n"
        "  fingerprinted assets: %s\n"
        "  HTML and web manifest: %s\n\n"
        "Caddy:\n%s\n\nnginx:\n%s\n"
        % (IMMUTABLE, HTML, _indent(caddy(mode, length, exts)),
           _indent(nginx(mode, length, exts)))
    )


def _indent(text):
    return "\n".join("  " + line for line in text.splitlines())
