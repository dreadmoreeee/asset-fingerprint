"""Command line interface."""

import argparse
import difflib
import sys
from pathlib import Path

from . import __version__
from .core import DEFAULT_EXTS, Config, apply_plan, build_plan
from .headers import report


def _parser():
    p = argparse.ArgumentParser(
        prog="asset-fingerprint",
        description="Fingerprint static assets in a build folder and rewrite "
                    "every reference to them.")
    p.add_argument("root", help="build folder to process (changed in place)")
    p.add_argument("--mode", choices=("rename", "query"), default="rename",
                   help="rename: name.<hash>.ext (default); query: keep names, append ?v=<hash>")
    p.add_argument("--length", type=int, default=8, help="hex chars of sha256 to keep (default 8)")
    p.add_argument("--site-host", help="host of the site (e.g. example.com); absolute URLs on "
                                       "this host are rewritten, other hosts never")
    p.add_argument("--ext", action="append", metavar="EXT",
                   help="asset extension to fingerprint (repeatable; replaces the default list)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="asset path (relative to root) to leave alone (repeatable)")
    p.add_argument("--manifest", metavar="FILE",
                   help="assets manifest to write (default: <root>/assets-manifest.json)")
    p.add_argument("--no-manifest", action="store_true", help="do not write an assets manifest")
    p.add_argument("--dry-run", action="store_true",
                   help="print a unified diff and the planned renames; write nothing")
    p.add_argument("--check", action="store_true",
                   help="exit 1 when anything would change (implies --dry-run)")
    p.add_argument("--no-headers", action="store_true", help="do not print cache header snippets")
    p.add_argument("--version", action="version", version="asset-fingerprint " + __version__)
    return p


def _diff(op):
    return difflib.unified_diff(
        op.old_text.splitlines(), op.new_text.splitlines(),
        "a/" + op.old_rel, "b/" + op.new_rel, n=1, lineterm="")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    root = Path(args.root)
    exts = tuple(e if e.startswith(".") else "." + e for e in args.ext) if args.ext \
        else DEFAULT_EXTS
    manifest = None
    if not args.no_manifest:
        manifest = Path(args.manifest) if args.manifest else root / "assets-manifest.json"
    cfg = Config(root=root, mode=args.mode, length=args.length, site_host=args.site_host,
                 exts=exts, exclude=tuple(args.exclude), manifest_path=manifest)
    try:
        plan = build_plan(cfg)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    dry = args.dry_run or args.check

    for w in plan.warnings:
        print("warning: " + w, file=sys.stderr)

    if dry:
        for op in plan.text_ops:
            for line in _diff(op):
                print(line)
        if plan.text_ops:
            print()
        if plan.renames:
            print("Planned renames:")
            for old, new in plan.renames:
                print("  %s -> %s" % (old, new))
            print()
    else:
        apply_plan(plan)
        for op in plan.text_ops:
            print("rewrote  " + op.new_rel)
        for old, new in plan.renames:
            print("renamed  %s -> %s" % (old, new))

    if not plan.has_changes:
        print("Nothing to change: %d assets already fingerprinted." % len(plan.assets))
    else:
        verb = "would be" if dry else "was"
        print("%d references rewritten in %d files, %d files renamed (%s)%s."
              % (plan.rewrites, len(plan.text_ops), len(plan.renames),
                 "dry run, nothing written" if dry else "written",
                 "" if not plan.manifest_changed else "; manifest %s updated" % verb))
    if manifest is not None and not dry:
        print("Assets manifest: %s (%d assets)" % (manifest, len(plan.assets)))
    if not args.no_headers:
        print()
        print(report(cfg.mode, cfg.length, cfg.exts))
    return 1 if args.check and plan.has_changes else 0
