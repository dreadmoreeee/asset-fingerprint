# asset-fingerprint

Cache-busting for a **built static site**: hash every css, js, image and font, then rewrite **every reference** to it, in one pass, with no dependencies.

```
python -m asset_fingerprint dist --site-host example.com            # styles.css -> styles.1a2b3c4d.css
python -m asset_fingerprint dist --mode query --site-host example.com   # keep names, append ?v=1a2b3c4d
python -m asset_fingerprint dist --dry-run                          # unified diff + planned renames, writes nothing
```

Why another one: a hash on the stylesheet alone is easy. The hard part is the rest of the graph. If `logo.png` changes, `site.css` (which has `url(logo.png)`) must get a new hash too, and so must every page pointing at it.

- **Two modes.** `rename` writes `name.<hash>.ext`; `query` keeps the file names and appends `?v=<hash>`.
- **Rewrites what browsers actually load:** `<link href>`, `<script src>`, `<img src/srcset>`, `<source src/srcset>`, `<style>` blocks, CSS `url()` and `@import`, and `"src"` in web manifests (`icons`, `screenshots`). `og:image` and `twitter:image` are rewritten only when the URL is relative or on your `--site-host`.
- **Paths resolved like a browser:** root-relative, `../`, and relative to the referencing file. Query strings and `#fragments` are kept.
- **Never touches** external URLs, `data:` URIs, or anything that is not a local file that exists.
- **Dependencies in order.** CSS is hashed after its own `url()` references are rewritten, so a changed image changes the CSS hash. Circular `@import` chains are detected, warned about, and do not hang.
- **Idempotent.** A second run changes nothing. Already-fingerprinted names and existing `?v=` are recognised; when content changes the old hash is replaced, never stacked (also when you change `--length`).
- Writes an **assets manifest** (`assets-manifest.json`, original path to fingerprinted path) and prints **cache headers** with Caddy and nginx snippets.

## Measured result

The real build of my portfolio ([marvin.demarkstudio.ca](https://marvin.demarkstudio.ca)), copied into a scratch folder (the original is never touched). Its stylesheet is served through a CDN that cached it for a day: when I changed `styles.css`, visitors kept seeing the old design until the URL changed. Adding `?v=<hash>` by hand fixed it once, and then I forgot to bump it. This tool makes the hash follow the content.

```
$ python -m asset_fingerprint public --mode query --length 10 --site-host marvin.demarkstudio.ca --dry-run --no-headers
--- a/index.html
+++ b/index.html
@@ -15,3 +15,3 @@
 <meta property="og:url" content="https://marvin.demarkstudio.ca/">
-<meta property="og:image" content="https://marvin.demarkstudio.ca/og.png">
+<meta property="og:image" content="https://marvin.demarkstudio.ca/og.png?v=861cb9ce2f">
 <meta property="og:locale" content="en_CA">
@@ -21,5 +21,5 @@
 <meta name="theme-color" content="#0f1720">
-<link rel="icon" href="/favicon.svg" type="image/svg+xml">
-<link rel="apple-touch-icon" href="/apple-touch-icon.png">
-<link rel="preload" as="image" href="/img/marvin-200.webp">
+<link rel="icon" href="/favicon.svg?v=76af5798fb" type="image/svg+xml">
+<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=f8a00c540e">
+<link rel="preload" as="image" href="/img/marvin-200.webp?v=c21c566aa6">
 <link rel="stylesheet" href="/styles.css?v=aefb6f239a">
[... same kind of changes for the srcset of the five project images and the other pages ...]

52 references rewritten in 6 files, 0 files renamed (dry run, nothing written); manifest would be updated.

$ python -m asset_fingerprint public --mode query --length 10 --site-host marvin.demarkstudio.ca --no-headers
rewrote  es/index.html
rewrote  index.html
rewrote  work/auditing-my-own-sites/index.html
rewrote  work/demark-studio/index.html
rewrote  work/stopping-form-spam/index.html
rewrote  work/triple-a-woodworks/index.html
52 references rewritten in 6 files, 0 files renamed (written); manifest was updated.
Assets manifest: _demo_scratch\public\assets-manifest.json (16 assets)

$ python -m asset_fingerprint public --mode query --length 10 --site-host marvin.demarkstudio.ca --no-headers
Nothing to change: 16 assets already fingerprinted.
Assets manifest: _demo_scratch\public\assets-manifest.json (16 assets)

$ python -m pytest -q -p no:cacheprovider --import-mode=importlib
...........................
27 passed in 1.11s
```

What happened: 52 references in 6 pages (16 assets in total) went from a bare URL to `?v=<hash>`: favicon, apple-touch-icon, the `og:image` (absolute, on my own host), the portrait and every `src` and `srcset` candidate of the project screenshots. The `<link rel="stylesheet" href="/styles.css?v=aefb6f239a">` line did **not** change: the hash the tool computes for the current `styles.css` (sha256, first 10 characters) is the one I had already stamped by hand, which is a good sign that both agree. With the default `--length 8` it shortens it to `aefb6f23`. Run three: zero changes. JSON-LD URLs and `<a href>` links are not asset references and were left alone.

## Install and usage

Python 3.10+, standard library only.

```
pip install .                      # gives the `asset-fingerprint` command
python -m asset_fingerprint <build-folder> [options]
```

| Option | Meaning |
|---|---|
| `--mode rename\|query` | `name.<hash>.ext` (default) or `?v=<hash>` |
| `--length N` | hex characters of the sha256 to keep (default 8) |
| `--site-host HOST` | absolute URLs on this host count as local (og:image, canonical-style links); any other host is never touched |
| `--ext .css --ext .js ...` | replace the list of extensions to fingerprint (default: css js mjs png jpg jpeg gif webp avif svg ico woff woff2 ttf otf eot) |
| `--exclude GLOB` | leave an asset alone (repeatable, relative to the folder, e.g. `js/legacy/*`) |
| `--manifest FILE` / `--no-manifest` | where to write the assets manifest (default `<folder>/assets-manifest.json`) |
| `--dry-run` | unified diff of the rewrites plus planned renames; writes nothing |
| `--check` | like `--dry-run`, exit code 1 if anything would change (for CI) |
| `--no-headers` | skip the cache header snippets |

The folder is changed in place, so run it on the build output, not on your sources. In `rename` mode only assets that something references are renamed (so `favicon.ico`, which browsers request by convention, keeps its name unless a page links to it). The manifest looks like:

```json
{"assets": {"/styles.css": "/styles.1a2b3c4d.css"}, "hash_length": 8, "mode": "rename", "version": 1}
```

A CI example is in [examples/ci-github-actions.yml](examples/ci-github-actions.yml) and a tiny site to try it on in [examples/site](examples/site).

## Cache headers

Fingerprinted files can be cached forever because a change produces a new URL; HTML (and the web manifest) must be revalidated so it can point at the new URLs:

```
fingerprinted assets:   Cache-Control: public, max-age=31536000, immutable
HTML and web manifest:  Cache-Control: no-cache
```

The tool prints Caddy and nginx snippets for the mode you used (a hash-in-name regex for `rename`, a `v` query check for `query`). They are written from the server documentation and are **not** tested against a live server here; read them before pasting.

## Limitations

- References inside **JavaScript** (`fetch("/img/a.png")`, dynamic imports) are not rewritten. In `rename` mode that would break them: use `query` mode, or `--exclude` those files. The manifest gives you the mapping for templates.
- Server-side templates and `<base href>` are not understood; run it on plain HTML output.
- A name like `report.20240101.png` (a segment of 6 to 16 hex characters) is read as "already fingerprinted" in `rename` mode, and the segment is replaced by the hash.
- Files must be UTF-8 (others are skipped with a warning). No `style="..."` attribute or `<video poster>` handling.

## Author

Marvin Palencia, founder of [DeMark Studio](https://demarkstudio.ca), Miramichi, New Brunswick, Canada. Portfolio: [marvin.demarkstudio.ca](https://marvin.demarkstudio.ca)

MIT License.
