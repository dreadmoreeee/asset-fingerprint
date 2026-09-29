"""Plan and apply asset fingerprinting for a build folder."""

import fnmatch
import hashlib
import json
import os
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from .rewriters import rewrite_css, rewrite_html, rewrite_manifest

DEFAULT_EXTS = (
    ".css", ".js", ".mjs",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
)
SKIP_DIRS = {".git", "node_modules"}
_HASHED_STEM = re.compile(r"\.[0-9a-f]{6,16}$")
_ABS_URL = re.compile(r"^(?:(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*):)?//(?P<host>[^/?#]*)")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass
class Config:
    root: Path
    mode: str = "rename"          # "rename" or "query"
    length: int = 8
    site_host: str | None = None
    exts: tuple = DEFAULT_EXTS
    exclude: tuple = ()
    manifest_path: Path | None = None


@dataclass
class Op:
    old_rel: str
    new_rel: str
    old_text: str | None = None
    new_text: str | None = None   # None: the file content is not modified


@dataclass
class Plan:
    cfg: Config
    ops: list = field(default_factory=list)
    assets: dict = field(default_factory=dict)      # "/styles.css" -> new URL
    manifest_text: str | None = None
    manifest_changed: bool = False
    warnings: list = field(default_factory=list)
    rewrites: int = 0

    @property
    def renames(self):
        return [(o.old_rel, o.new_rel) for o in self.ops if o.old_rel != o.new_rel]

    @property
    def text_ops(self):
        return [o for o in self.ops if o.new_text is not None]

    @property
    def has_changes(self):
        return bool(self.ops) or self.manifest_changed


def _host(value):
    value = value.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value).split("/")[0]
    return value.rsplit("@", 1)[-1].rsplit(":", 1)[0]


def strip_hash(rel):
    """'css/app.1a2b3c4d.css' -> 'css/app.css' (unchanged if no hash)."""
    head, name = posixpath.split(rel)
    stem, ext = posixpath.splitext(name)
    m = _HASHED_STEM.search(stem)
    if m and m.start() > 0:
        name = stem[:m.start()] + ext
    return posixpath.join(head, name)


def with_hash(rel, digest):
    head, name = posixpath.split(rel)
    stem, ext = posixpath.splitext(name)
    return posixpath.join(head, "%s.%s%s" % (stem, digest, ext))


def set_query_v(query, digest):
    """Replace the v= parameter in place (or append it)."""
    sep = "&amp;" if query and "&amp;" in query else "&"
    parts = re.split("&amp;|&", query) if query else []
    out, done = [], False
    for p in parts:
        if p.split("=")[0] == "v":
            if not done:
                out.append("v=" + digest)
                done = True
        elif p:
            out.append(p)
    if not done:
        out.append("v=" + digest)
    return sep.join(out)


def drop_query_v(query):
    if query is None:
        return None
    sep = "&amp;" if "&amp;" in query else "&"
    kept = [p for p in re.split("&amp;|&", query) if p and p.split("=")[0] != "v"]
    return sep.join(kept) or None


class _Engine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = Path(cfg.root)
        self.site_host = _host(cfg.site_host) if cfg.site_host else None
        self.exts = {e.lower() for e in cfg.exts}
        self.plan = Plan(cfg)
        self.assets = {}      # logical rel -> disk rel
        self.by_disk = {}     # disk rel -> logical rel
        self.texts = []       # (disk rel, kind)
        self.referenced = set()
        self._recs = {}
        self._busy = set()
        self._collect = True

    # -- scanning -----------------------------------------------------
    def logical(self, disk):
        return strip_hash(disk) if self.cfg.mode == "rename" else disk

    def scan(self):
        skip = None
        if self.cfg.manifest_path is not None:
            skip = Path(self.cfg.manifest_path).resolve()
        groups = {}
        for dirpath, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                full = Path(dirpath, f)
                if skip is not None and full.resolve() == skip:
                    continue
                rel = full.relative_to(self.root).as_posix()
                low = f.lower()
                ext = posixpath.splitext(low)[1]
                if ext in (".html", ".htm"):
                    self.texts.append((rel, "html"))
                elif low == "manifest.json" or low.endswith(".webmanifest"):
                    self.texts.append((rel, "manifest"))
                if ext in self.exts:
                    groups.setdefault(self.logical(rel), []).append(rel)
        for logical, disks in sorted(groups.items()):
            if any(fnmatch.fnmatch(logical, pat) for pat in self.cfg.exclude):
                continue
            if len(disks) > 1:
                if logical in disks:
                    stale = [d for d in disks if d != logical]
                    self.plan.warnings.append(
                        "stale fingerprinted copies of %s ignored: %s"
                        % (logical, ", ".join(stale)))
                    disks = [logical]
                else:
                    self.plan.warnings.append(
                        "several fingerprinted copies of %s (%s); skipped"
                        % (logical, ", ".join(disks)))
                    continue
            self.assets[logical] = disks[0]
            self.by_disk[disks[0]] = logical
        self.texts += [(d, "css") for d in self.by_disk if d.lower().endswith(".css")]
        self.texts.sort()

    # -- reference handling ---------------------------------------------
    def _split(self, ref):
        r = ref.strip()
        if not r or r.startswith("#"):
            return None
        m = _ABS_URL.match(r)
        if m:
            scheme = (m.group("scheme") or "").lower()
            if scheme not in ("", "http", "https"):
                return None
            if self.site_host is None or _host(m.group("host")) != self.site_host:
                return None
            prefix, rest = m.group(0), r[m.end():]
            if not rest.startswith("/"):
                return None
        elif _SCHEME.match(r):
            return None
        else:
            prefix, rest = "", r
        rest, hash_, frag = rest.partition("#")
        path, q, query = rest.partition("?")
        if not path or path.endswith("/"):
            return None
        return prefix, path, (query if q else None), (frag if hash_ else None)

    def _resolve(self, path, base_dir):
        p = unquote(path)
        joined = p if p.startswith("/") else posixpath.join(base_dir, p)
        norm = posixpath.normpath(joined).lstrip("/")
        if norm in ("", ".", "..") or norm.startswith("../"):
            return None
        if norm in self.by_disk:
            return self.by_disk[norm]
        if self.cfg.mode == "rename" and strip_hash(norm) in self.assets:
            return strip_hash(norm)
        return None

    def mapper(self, disk_rel):
        base_dir = posixpath.dirname(disk_rel)

        def fn(ref):
            parts = self._split(ref)
            if parts is None:
                return None
            prefix, path, query, frag = parts
            logical = self._resolve(path, base_dir)
            if logical is None:
                return None
            if self._collect:
                self.referenced.add(logical)
                return None
            rec = self.record(logical)
            if rec is None:
                return None
            if self.cfg.mode == "rename":
                head, sep, _ = path.rpartition("/")
                new_path = head + sep + quote(posixpath.basename(rec["new_disk"]))
                query = drop_query_v(query)
            else:
                new_path = path
                query = set_query_v(query, rec["hash"])
            new = prefix + new_path
            if query is not None:
                new += "?" + query
            if frag is not None:
                new += "#" + frag
            lead = ref[:len(ref) - len(ref.lstrip())]
            trail = ref[len(ref.rstrip()):]
            new = lead + new + trail
            if new != ref:
                self.plan.rewrites += 1
            return new

        return fn

    # -- records ----------------------------------------------------------
    def record(self, logical):
        if logical in self._recs:
            return self._recs[logical]
        if logical in self._busy:
            self.plan.warnings.append(
                "circular reference through %s; that reference was left as is" % logical)
            return None
        self._busy.add(logical)
        disk = self.assets[logical]
        data = (self.root / disk).read_bytes()
        old_text = new_text = None
        if disk.lower().endswith(".css"):
            try:
                old_text = data.decode("utf-8")
            except UnicodeDecodeError:
                self.plan.warnings.append("%s is not UTF-8; hashed without rewriting" % disk)
            if old_text is not None:
                rewritten = rewrite_css(old_text, self.mapper(disk))
                if rewritten != old_text:
                    new_text = rewritten
                    data = rewritten.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()[:self.cfg.length]
        managed = True
        new_disk = disk
        if self.cfg.mode == "rename":
            managed = logical in self.referenced or disk != logical
            if managed:
                new_disk = with_hash(logical, digest)
        rec = {"logical": logical, "disk": disk, "new_disk": new_disk, "hash": digest,
               "managed": managed, "old_text": old_text, "new_text": new_text}
        self._busy.discard(logical)
        self._recs[logical] = rec
        return rec

    # -- planning -----------------------------------------------------------
    def run(self):
        self.scan()
        kinds = {"html": rewrite_html, "manifest": rewrite_manifest, "css": rewrite_css}
        loaded = {}
        for disk, _kind in self.texts:
            try:
                loaded[disk] = (self.root / disk).read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                self.plan.warnings.append("%s is not UTF-8; skipped" % disk)
        # pass 1: find out which assets are referenced at all
        self._collect = True
        for disk, kind in self.texts:
            if disk in loaded:
                kinds[kind](loaded[disk], self.mapper(disk))
        # pass 2: hash in dependency order and rewrite
        self._collect = False
        for logical in sorted(self.assets):
            self.record(logical)
        for disk, kind in self.texts:
            if kind == "css" or disk not in loaded:
                continue
            old = loaded[disk]
            new = kinds[kind](old, self.mapper(disk))
            if new != old:
                self.plan.ops.append(Op(disk, disk, old, new))
        for logical in sorted(self.assets):
            rec = self._recs[logical]
            if rec["new_text"] is not None or rec["new_disk"] != rec["disk"]:
                self.plan.ops.append(Op(rec["disk"], rec["new_disk"],
                                        rec["old_text"], rec["new_text"]))
            if rec["managed"]:
                if self.cfg.mode == "rename":
                    url = "/" + rec["new_disk"]
                else:
                    url = "/%s?v=%s" % (logical, rec["hash"])
                self.plan.assets["/" + logical] = url
        self.plan.ops.sort(key=lambda o: (o.old_rel, o.new_rel))
        self._manifest()
        return self.plan

    def _manifest(self):
        path = self.cfg.manifest_path
        if path is None:
            return
        doc = {"version": 1, "mode": self.cfg.mode, "hash_length": self.cfg.length,
               "assets": dict(sorted(self.plan.assets.items()))}
        self.plan.manifest_text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        path = Path(path)
        old = path.read_text(encoding="utf-8") if path.is_file() else None
        self.plan.manifest_changed = old != self.plan.manifest_text


def build_plan(cfg):
    if cfg.mode not in ("rename", "query"):
        raise ValueError("mode must be 'rename' or 'query'")
    if not 4 <= cfg.length <= 64:
        raise ValueError("hash length must be between 4 and 64")
    if not Path(cfg.root).is_dir():
        raise ValueError("not a directory: %s" % cfg.root)
    return _Engine(cfg).run()


def apply_plan(plan):
    root = Path(plan.cfg.root)
    for op in plan.ops:
        old, new = root / op.old_rel, root / op.new_rel
        if op.new_text is not None:
            new.parent.mkdir(parents=True, exist_ok=True)
            new.write_bytes(op.new_text.encode("utf-8"))
            if op.old_rel != op.new_rel:
                old.unlink()
        else:
            os.replace(old, new)
    if plan.manifest_changed:
        path = Path(plan.cfg.manifest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.manifest_text, encoding="utf-8", newline="\n")
