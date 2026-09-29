import json

from asset_fingerprint.cli import main


def test_dry_run_prints_diff_and_writes_nothing(site, snap, capsys):
    before = snap(site)
    code = main([str(site), "--dry-run", "--site-host", "example.com"])
    out = capsys.readouterr().out
    assert code == 0
    assert snap(site) == before
    assert not (site / "assets-manifest.json").exists()
    assert "--- a/index.html" in out and "+++ b/index.html" in out
    assert "Planned renames:" in out
    assert "css/site.css -> css/site." in out
    assert "dry run, nothing written" in out


def test_real_run_then_second_run_reports_nothing(site, snap, capsys):
    assert main([str(site), "--site-host", "example.com"]) == 0
    capsys.readouterr()
    after_first = snap(site)
    assert main([str(site), "--site-host", "example.com", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Nothing to change" in out
    assert "--- a/" not in out
    assert main([str(site), "--site-host", "example.com"]) == 0
    assert snap(site) == after_first


def test_manifest_written_and_headers_printed(site, capsys):
    main([str(site), "--mode", "query"])
    out = capsys.readouterr().out
    doc = json.loads((site / "assets-manifest.json").read_text())
    assert doc["mode"] == "query"
    assert doc["assets"]["/js/app.js"].startswith("/js/app.js?v=")
    assert "max-age=31536000, immutable" in out
    assert "no-cache" in out
    assert "Caddy:" in out and "nginx:" in out


def test_rename_headers_match_hash_length(site, capsys):
    main([str(site), "--length", "10"])
    assert "{10}" in capsys.readouterr().out


def test_check_exit_code(site, capsys):
    assert main([str(site), "--check", "--no-headers"]) == 1
    main([str(site), "--no-headers"])
    assert main([str(site), "--check", "--no-headers"]) == 0


def test_no_manifest_and_bad_root(site, tmp_path, capsys):
    main([str(site), "--no-manifest", "--no-headers"])
    assert not (site / "assets-manifest.json").exists()
    assert main([str(tmp_path / "nope")]) == 2
