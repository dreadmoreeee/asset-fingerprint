import json
import re

import pytest

from asset_fingerprint import Config, apply_plan, build_plan


def run(root, **kw):
    kw.setdefault("site_host", "example.com")
    plan = build_plan(Config(root=root, **kw))
    apply_plan(plan)
    return plan


def read(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def hashed(root, pattern):
    hits = [p.relative_to(root).as_posix() for p in root.rglob("*")
            if re.fullmatch(pattern, p.relative_to(root).as_posix())]
    assert len(hits) == 1, hits
    return hits[0]


def test_rename_mode_renames_files_and_rewrites_html(site):
    run(site)
    logo = hashed(site, r"img/logo\.[0-9a-f]{8}\.png")
    assert not (site / "img/logo.png").exists()
    html = read(site, "index.html")
    assert 'src="%s"' % logo.replace("img/", "img/", 1) in html
    assert 'href="/css/site.' in html and 'src="/js/app.' in html
    assert "/css/site.css" not in html
    # a plain download link is not an asset reference we manage
    assert '<a href="/img/logo.png">' in html


def test_query_mode_keeps_names_and_appends_v(site):
    run(site, mode="query")
    assert (site / "img/logo.png").exists()
    html = read(site, "index.html")
    assert re.search(r'href="/css/site\.css\?v=[0-9a-f]{8}"', html)
    assert re.search(r'src="img/logo\.png\?v=[0-9a-f]{8}"', html)
    assert re.search(r'src="/js/app\.js\?v=[0-9a-f]{8}"', html)


def test_srcset_every_candidate_rewritten(site):
    run(site, mode="query")
    html = read(site, "index.html")
    m = re.search(r'srcset="img/logo\.png\?v=([0-9a-f]{8}) 1x, '
                  r'img/logo@2x\.png\?v=([0-9a-f]{8}) 2x"', html)
    assert m and m.group(1) != m.group(2)
    assert re.search(r'srcset="/img/logo\.png\?v=[0-9a-f]{8} 480w, '
                     r'/img/logo@2x\.png\?v=[0-9a-f]{8} 960w"', html)


def test_css_url_and_import_relative_resolution(site):
    run(site, mode="query")
    css = read(site, "css/site.css")
    assert re.search(r'@import "base\.css\?v=[0-9a-f]{8}";', css)
    assert re.search(r"url\(\.\./img/logo\.png\?v=[0-9a-f]{8}\)", css)
    assert re.search(r"url\('/fonts/f\.woff2\?v=[0-9a-f]{8}'\)", css)
    assert "url(https://cdn.example.net/x.png)" in css


def test_css_rename_mode_import_and_url(site):
    run(site)
    css = read(site, hashed(site, r"css/site\.[0-9a-f]{8}\.css"))
    assert re.search(r'@import "base\.[0-9a-f]{8}\.css";', css)
    assert re.search(r"url\(\.\./img/logo\.[0-9a-f]{8}\.png\)", css)


def test_web_manifest_icons_rewritten_external_untouched(site):
    run(site)
    text = read(site, "site.webmanifest")
    assert re.search(r'"src": "img/logo\.[0-9a-f]{8}\.png"', text)
    assert "https://cdn.example.net/i.png" in text
    assert '"name": "Example"' in text


def test_og_image_same_host_rewritten_external_untouched(site):
    run(site)
    html = read(site, "index.html")
    assert re.search(r'og:image" content="https://example\.com/img/logo\.[0-9a-f]{8}\.png"', html)
    assert 'content="https://cdn.example.net/img/logo.png"' in html


def test_og_image_untouched_without_site_host(site):
    run(site, site_host=None)
    assert 'content="https://example.com/img/logo.png"' in read(site, "index.html")


def test_external_data_and_missing_untouched(site):
    run(site)
    html = read(site, "index.html")
    assert '<script src="https://cdn.example.net/lib.js"></script>' in html
    assert 'src="data:image/gif;base64,R0lGODlhAQABAAAAACw="' in html
    assert 'src="/img/missing.png"' in html


def test_css_hash_changes_when_its_image_changes(site, put):
    run(site, mode="query")
    first = read(site, "css/site.css")
    put(site, "img/logo.png", b"\x89PNG-different")
    run(site, mode="query")
    second = read(site, "css/site.css")
    assert first != second
    pick = lambda t: re.search(r"logo\.png\?v=([0-9a-f]{8})", t).group(1)
    assert pick(first) != pick(second)


def test_css_file_name_changes_when_its_image_changes_rename_mode(site, put):
    run(site)
    old_css = hashed(site, r"css/site\.[0-9a-f]{8}\.css")
    old_logo = hashed(site, r"img/logo\.[0-9a-f]{8}\.png")
    put(site, old_logo, b"\x89PNG-different")
    run(site)
    new_css = hashed(site, r"css/site\.[0-9a-f]{8}\.css")
    assert new_css != old_css


def test_content_change_replaces_hash_never_stacks(site, put):
    run(site)
    js = hashed(site, r"js/app\.[0-9a-f]{8}\.js")
    put(site, js, "console.log('changed');\n")
    run(site)
    new_js = hashed(site, r"js/app\.[0-9a-f]{8}\.js")
    assert new_js != js
    assert "/" + new_js in read(site, "index.html")
    assert "/" + js not in read(site, "index.html")


def test_stale_v_param_replaced_and_other_params_kept(site, put):
    put(site, "index.html",
        '<link rel="stylesheet" href="/css/base.css?v=old&amp;x=1#f">\n')
    run(site, mode="query")
    html = read(site, "index.html")
    assert re.fullmatch(
        r'<link rel="stylesheet" href="/css/base\.css\?v=[0-9a-f]{8}&amp;x=1#f">\n', html)


@pytest.mark.parametrize("mode", ["rename", "query"])
def test_idempotent_second_run_zero_diff(site, snap, mode):
    run(site, mode=mode, manifest_path=site / "assets-manifest.json")
    before = snap(site)
    plan = build_plan(Config(root=site, mode=mode, site_host="example.com",
                             manifest_path=site / "assets-manifest.json"))
    assert not plan.has_changes
    run(site, mode=mode, manifest_path=site / "assets-manifest.json")
    assert snap(site) == before


def test_hash_length_configurable_and_changing_it_does_not_stack(site):
    run(site, length=10)
    hashed(site, r"js/app\.[0-9a-f]{10}\.js")
    run(site, length=6)
    hashed(site, r"js/app\.[0-9a-f]{6}\.js")


def test_manifest_maps_original_to_fingerprinted(site):
    plan = run(site, manifest_path=site / "assets-manifest.json")
    doc = json.loads((site / "assets-manifest.json").read_text())
    assert doc["assets"]["/js/app.js"] == "/" + hashed(site, r"js/app\.[0-9a-f]{8}\.js")
    assert plan.assets == doc["assets"]


def test_unreferenced_asset_not_renamed_in_rename_mode(site, put):
    put(site, "favicon.ico", b"ico")
    run(site)
    assert (site / "favicon.ico").exists()


def test_exclude_glob(site):
    run(site, exclude=("js/*",))
    assert (site / "js/app.js").exists()
    assert 'src="/js/app.js"' in read(site, "index.html")


def test_circular_import_does_not_hang(site, put):
    put(site, "css/a.css", '@import "b.css";\n')
    put(site, "css/b.css", '@import "a.css";\n')
    put(site, "index.html", '<link rel="stylesheet" href="/css/a.css">\n')
    plan = run(site, mode="query")
    assert plan.warnings
    assert not build_plan(Config(root=site, mode="query")).has_changes


def test_bad_arguments(tmp_path):
    with pytest.raises(ValueError):
        build_plan(Config(root=tmp_path / "does-not-exist"))
    with pytest.raises(ValueError):
        build_plan(Config(root=tmp_path, length=2))
