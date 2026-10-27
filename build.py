#!/usr/bin/env python3
# Super Rimario Italiano
# Copyright (C) 2024 Nicolò Brigadoi Calamari
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Build the site in web/ for publication (README: "Compilazione per la pubblicazione").

Usage: ``python3 build.py [--upload-base URL]``. Needs Python 3.14 (stdlib only)
and ``esbuild`` 0.28 in PATH. ``build/`` is wiped and recreated on every run,
and removed again if anything fails, so it never holds a half-built site.

Outputs:

- ``build/web/``: the standalone site. Every file except ``index.html`` is
  named ``<stem>-<hash>.<ext>``, where ``<hash>`` is the first 10 hex digits of
  the sha256 of the published bytes, so browsers can cache it forever. The CSS
  is minified; ``js/app.js`` and its imports are bundled and minified into one
  ``js/app-<hash>.js``. ``index.html`` is ``web/index.html`` with only its
  asset references rewritten, the ``modulepreload`` links removed and
  ``data-dictionary-bytes`` set.
- ``build/wordpress.html``: the version for L'AvisioBlog, to paste into a
  Custom HTML block: the widget fragment with the CSS and JS inlined, the logo
  as a data URI, and the dictionary and attribution pointing at their upload
  URLs under ``--upload-base`` (default: this month's WordPress uploads folder).
  The CSS makes the properties the blog's theme forces important too
  (WORDPRESS_IMPORTANT).
- ``build/wordpress-uploads/``: the files to upload to WordPress, with the
  same hashed names. WordPress refuses ``.md`` uploads, so the attribution is
  uploaded as ``ATTRIBUTION-<hash>.txt``, with a UTF-8 BOM (hence its own hash).

Every rewrite is checked: each expected reference must occur exactly as many
times as expected, and the outputs must not reference missing files or leave
files unreferenced, so a change to ``web/`` that the build doesn't know about
fails here instead of producing a broken site.
"""

import argparse
import base64
import datetime
import hashlib
import html
import re
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
BUILD = ROOT / "build"
BUILD_WEB = BUILD / "web"
WORDPRESS_HTML = BUILD / "wordpress.html"
WORDPRESS_UPLOADS = BUILD / "wordpress-uploads"

HASH_LEN = 10
# The browsers in README.md, "Requisiti del browser".
TARGET = "chrome105,edge105,firefox110,safari16"
# The hashes depend on esbuild's output, so a different version changes them.
ESBUILD_SERIES = "0.28."

# Files in web/, relative to it.
INDEX = "index.html"
CSS = "rimario.css"
JS_ENTRY = "js/app.js"
FAVICON = "favicon.svg"
LOGO = "logo.svg"
DICTIONARY = "parole-accenti-frequenze.csv"
ATTRIBUTION = "ATTRIBUTION.md"

# The asset references web/index.html must contain, as (tag, attribute, value,
# expected count). Any other reference to a file in web/ is an error.
WEB_REFERENCES = (
    ("link", "href", FAVICON, 1),
    ("link", "href", CSS, 1),
    ("script", "src", JS_ENTRY, 1),
    ("img", "src", LOGO, 1),
    ("link", "href", DICTIONARY, 1),                     # the preload
    ("div", "data-dictionary-url", DICTIONARY, 1),
    ("div", "data-attribution-url", ATTRIBUTION, 1),
    ("a", "href", ATTRIBUTION, 1),                       # the footer link (no-JS fallback)
)
MODULEPRELOADS = 4                                       # one per imported module of app.js
URL_ATTRIBUTES = ("href", "src", "action", "poster", "data-dictionary-url", "data-attribution-url")

# WordPress version.
DEFAULT_UPLOAD_BASE = "https://www.lavisioblog.it/wp-content/uploads/{:%Y/%m}/"
TITLE_SUFFIX = "Super Rimario Italiano - L'Avisio Blog"
SEO_HEADING = "Rimario Italiano online. Trova rime, assonanze atone, assonanze semplici e consonanze."
BEGIN_MARKER = "<!-- rimario:begin -->"
END_MARKER = "<!-- rimario:end -->"
# WordPress core shortcodes: "[name" anywhere in the page could be expanded.
SHORTCODES = ("caption", "wp_caption", "gallery", "playlist", "audio", "video", "embed")
# The blog serves static files without a charset, so the .txt starts with a BOM.
UTF8_BOM = b"\xef\xbb\xbf"

# The properties the blog's theme forces with !important on the widget's
# elements, through the Elementor kit's button styles:
#   .elementor-kit-9 button, .elementor-kit-9 input[type=button], .elementor-kit-9 input[type=submit],
#   .elementor-kit-9 .elementor-button {color:#fff!important; text-transform:uppercase!important;
#   font-weight:400!important; font-size:18px!important; border-radius:4px!important}
# and then {color:transparent!important}. Important beats normal whatever the
# selector, so the WordPress CSS makes every declaration of these properties
# important: the #rimario selectors outrank the theme's again, and the widget's
# own cascade is unchanged. Each `all:` gets an important copy for them, so the
# reset still undoes the theme where no component rule sets them. The list has
# every property sharing longhands with a forced one (font resets the other
# font-* and line-height), so an important shorthand can't override a normal
# longhand; the build fails if rimario.css uses a related one missing here.
WORDPRESS_IMPORTANT = (
    "color",
    "text-transform",
    "font", "font-family", "font-size", "font-weight", "font-style", "font-stretch", "font-variant",
    "font-variant-caps", "font-variant-numeric", "font-variant-ligatures", "font-variant-east-asian",
    "font-variant-alternates", "font-variant-position", "font-feature-settings", "font-variation-settings",
    "font-kerning", "font-size-adjust", "font-optical-sizing", "line-height",
    "border-radius", "border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius",
    "border-bottom-left-radius", "border-start-start-radius", "border-start-end-radius",
    "border-end-start-radius", "border-end-end-radius",
)
WORDPRESS_IMPORTANT_RELATED = r"color|text-transform|font(-[a-z-]+)?|line-height|border(-[a-z]+)*-radius"


class BuildError(Exception):
    """A failed check; the message says what to fix."""


def fail(message: str) -> None:
    raise BuildError(message)


# --- Small helpers -----------------------------------------------------------

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:HASH_LEN]


def hashed_name(rel: str, data: bytes) -> str:
    """``js/app.js`` -> ``js/app-<hash>.js``; the directory is kept."""
    path = Path(rel)
    return path.with_name(f"{path.stem}-{digest(data)}{path.suffix}").as_posix()


def write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def is_relative_url(url: str) -> bool:
    """True for URLs resolved against the page (not ``#…``, ``//host``, ``scheme:``)."""
    return not (url.startswith(("#", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url))


def size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.1f} kB"


def licence_header(index_src: str) -> str:
    """The GPL notice in the comment right after ``<!doctype html>``."""
    match = re.match(r"<!doctype html>\s*<!--\n(.*?)\n-->", index_src, re.IGNORECASE | re.DOTALL)
    if not match:
        fail(f"web/{INDEX}: no licence comment right after <!doctype html>")
    header = match.group(1)
    if "--" in header or "*/" in header:
        fail(f"web/{INDEX}: the licence comment contains '--' or '*/'")
    return header


def upload_base(value: str) -> str:
    """argparse type of --upload-base: an http(s) folder URL, with a trailing slash."""
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or re.search(r"[\s\"'<>]", value):
        raise argparse.ArgumentTypeError(f"not an http(s):// URL: {value!r}")
    if parts.query or parts.fragment:
        raise argparse.ArgumentTypeError(f"the URL of a folder can't have a query or fragment: {value!r}")
    return value if value.endswith("/") else value + "/"


# --- esbuild -----------------------------------------------------------------

def find_esbuild() -> tuple[str, str]:
    """(path, version) of esbuild in PATH; warns when it isn't 0.28.x."""
    path = shutil.which("esbuild")
    if path is None:
        fail("esbuild not found in PATH (install esbuild 0.28)")
    version = subprocess.run([path, "--version"], capture_output=True, text=True).stdout.strip()
    if not version.startswith(ESBUILD_SERIES):
        print(f"build.py: warning: esbuild {version or '(unknown version)'} instead of "
              f"{ESBUILD_SERIES}x: the output and its hashes will differ from other builds",
              file=sys.stderr)
    return path, version


def run_esbuild(esbuild: str, args: list[str], stdin: str | None = None) -> str:
    """esbuild's stdout, building ``stdin`` if given. Runs from the repository
    root with relative paths, so the output doesn't depend on where the
    repository is checked out."""
    result = subprocess.run([esbuild, *args, "--log-level=warning"], cwd=ROOT, input=stdin,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        fail(f"esbuild {args[0]} failed (exit {result.returncode})")
    if result.stderr:
        sys.stderr.write(result.stderr)                  # warnings
    return result.stdout


# --- Tag-level HTML rewriting ------------------------------------------------

@dataclass
class Node:
    """A start tag, end tag or comment, at ``source[start:end]``."""
    kind: str                                            # "start", "end" or "comment"
    name: str
    start: int
    end: int
    attrs: list[list] = field(default_factory=list)      # [name, value or None], in source order
    self_closing: bool = False
    changed: bool = False

    def get(self, name: str) -> str | None:
        return next((value for key, value in self.attrs if key == name), None)

    def has(self, name: str) -> bool:
        return any(key == name for key, _ in self.attrs)

    def tokens(self, name: str) -> list[str]:
        return (self.get(name) or "").split()

    def set(self, name: str, value: str) -> None:
        for attr in self.attrs:
            if attr[0] == name:
                attr[1] = value
                break
        else:
            self.attrs.append([name, value])
        self.changed = True

    def render(self) -> str:
        parts = [self.name]
        for key, value in self.attrs:
            parts.append(key if value is None else f'{key}="{html.escape(value)}"')
        return f"<{' '.join(parts)}{' /' if self.self_closing else ''}>"


class _Scanner(HTMLParser):
    """Records every tag and comment of ``source`` with its absolute offsets."""

    def __init__(self, source: str, label: str):
        super().__init__(convert_charrefs=True)
        self.source, self.label = source, label
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.nodes: list[Node] = []

    def _offset(self, raw: str) -> int:
        """Offset of the current token, which must start with ``raw``."""
        line, column = self.getpos()
        start = self.line_starts[line - 1] + column
        if not self.source.startswith(raw, start):
            fail(f"{self.label}: can't locate {raw[:40]!r} at line {line}, column {column + 1}")
        return start

    def _start(self, tag, attrs, self_closing):
        raw = self.get_starttag_text()
        start = self._offset(raw)
        self.nodes.append(Node("start", tag, start, start + len(raw),
                               [list(a) for a in attrs], self_closing))

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def handle_endtag(self, tag):
        start = self._offset("</")
        self.nodes.append(Node("end", tag, start, self.source.index(">", start) + 1))

    def handle_comment(self, data):
        raw = f"<!--{data}-->"
        start = self._offset(raw)
        self.nodes.append(Node("comment", "", start, start + len(raw)))


class Html:
    """An HTML text edited tag by tag: changed tags are regenerated from their
    parsed attributes, everything else is kept byte for byte."""

    def __init__(self, source: str, label: str):
        self.source, self.label = source, label
        scanner = _Scanner(source, label)
        scanner.feed(source)
        scanner.close()
        self.nodes = scanner.nodes
        self.splices: list[tuple[int, int, str]] = []

    def find(self, description: str, count: int, predicate) -> list[Node]:
        """The nodes matching ``predicate``; fails unless there are exactly ``count``."""
        found = [node for node in self.nodes if predicate(node)]
        if len(found) != count:
            fail(f"{self.label}: expected {count} {description}, found {len(found)}")
        return found

    def tags(self, name: str | None = None):
        return (n for n in self.nodes if n.kind == "start" and (name is None or n.name == name))

    def url_references(self):
        """(node, attribute, value) of every URL-valued attribute."""
        for node in self.tags():
            for key, value in node.attrs:
                if key in URL_ATTRIBUTES and value is not None:
                    yield node, key, value

    def replace(self, node: Node, text: str) -> None:
        self.splices.append((node.start, node.end, text))

    def remove_line(self, node: Node) -> None:
        """Remove ``node`` with its line, which must hold nothing else."""
        line_start = self.source.rfind("\n", 0, node.start) + 1
        line_end = self.source.find("\n", node.end)
        line_end = len(self.source) if line_end < 0 else line_end + 1
        if self.source[line_start:node.start].strip() or self.source[node.end:line_end].strip():
            fail(f"{self.label}: {self.source[node.start:node.end]} is not alone on its line")
        self.splices.append((line_start, line_end, ""))

    def render(self) -> str:
        splices = self.splices + [(n.start, n.end, n.render()) for n in self.nodes if n.changed]
        splices.sort()
        for (_, end, _), (start, _, _) in zip(splices, splices[1:]):
            if end > start:
                fail(f"{self.label}: overlapping edits at offset {start}")
        out = self.source
        for start, end, text in reversed(splices):
            out = out[:start] + text + out[end:]
        return out


def describe(tag: str, **attrs: str) -> str:
    return f"<{tag}{''.join(f' {k.replace('_', '-')}={v}' for k, v in attrs.items())}>"


# --- build/web ---------------------------------------------------------------

def build_web(esbuild: str, index_src: str, banner: str) -> dict:
    """Write build/web/; returns the published name and bytes of each asset."""
    css_src = (WEB / CSS).read_text(encoding="utf-8")
    if re.search(r"url\(|@import", css_src, re.IGNORECASE):
        fail(f"web/{CSS} uses url() or @import: their targets would need hashing too")
    assets = {
        CSS: run_esbuild(esbuild, [f"web/{CSS}", "--minify", f"--target={TARGET}",
                                   "--legal-comments=none", f"--banner:css={banner}"]).encode(),
        JS_ENTRY: run_esbuild(esbuild, [f"web/{JS_ENTRY}", "--bundle", "--minify", "--format=esm",
                                        f"--target={TARGET}", "--legal-comments=none",
                                        f"--banner:js={banner}"]).encode(),
    }
    for path in sorted(WEB.rglob("*")):
        rel = path.relative_to(WEB).as_posix()
        if not path.is_file() or rel in (INDEX, CSS) or (path.parent == WEB / "js" and path.suffix == ".js"):
            continue
        if any(part.startswith(".") for part in Path(rel).parts):
            continue                                     # editor lock and swap files (.~lock.*#, .*.swp)
        assets[rel] = path.read_bytes()
    for rel in (FAVICON, LOGO, DICTIONARY, ATTRIBUTION):
        if rel not in assets:
            fail(f"web/{rel} is missing")
    names = {rel: hashed_name(rel, data) for rel, data in assets.items()}
    for rel, data in assets.items():
        write(BUILD_WEB / names[rel], data)

    doc = Html(index_src, f"web/{INDEX}")
    for node in doc.find("<link rel=modulepreload>", MODULEPRELOADS,
                         lambda n: n.kind == "start" and n.name == "link" and "modulepreload" in n.tokens("rel")):
        doc.remove_line(node)
    found: dict[tuple, int] = {}
    for node, key, value in doc.url_references():
        if value in names:
            found[node.name, key, value] = found.get((node.name, key, value), 0) + 1
            node.set(key, names[value])
    expected = {(tag, key, value): count for tag, key, value, count in WEB_REFERENCES}
    for ref in sorted(expected.keys() | found.keys()):
        if found.get(ref, 0) != expected.get(ref, 0):
            tag, key, value = ref
            fail(f"web/{INDEX}: expected {expected.get(ref, 0)} <{tag} {key}={value}>, "
                 f"found {found.get(ref, 0)}")
    [root] = doc.find("<div id=rimario>", 1, lambda n: n.kind == "start" and n.name == "div"
                      and n.get("id") == "rimario")
    root.set("data-dictionary-bytes", str(len(assets[DICTIONARY])))
    index_out = doc.render()
    write(BUILD_WEB / INDEX, index_out)
    check_web(index_out)
    return {rel: (names[rel], data) for rel, data in assets.items()}


def check_web(index_out: str) -> None:
    """Every relative URL of build/web/index.html exists, and every file is referenced."""
    doc = Html(index_out, f"build/web/{INDEX}")
    if any("modulepreload" in n.tokens("rel") for n in doc.tags("link")):
        fail(f"build/web/{INDEX}: a modulepreload link is left")
    web_root = BUILD_WEB.resolve()
    referenced = set()
    for _, key, url in doc.url_references():
        if not is_relative_url(url) or url == "./":
            continue
        target = (web_root / urllib.parse.unquote(urllib.parse.urlsplit(url).path)).resolve()
        if web_root not in target.parents or not target.is_file():
            fail(f"build/web/{INDEX}: {key}={url} doesn't exist in build/web/")
        referenced.add(target.relative_to(web_root).as_posix())
    files = {p.relative_to(web_root).as_posix() for p in web_root.rglob("*") if p.is_file()}
    orphans = sorted(files - referenced - {INDEX})
    if orphans:
        fail(f"build/web/ has files that index.html doesn't reference: {', '.join(orphans)} "
             f"(a new file in web/? add its reference to WEB_REFERENCES in build.py)")


# --- build/wordpress.html ----------------------------------------------------

# Comments and strings, which may contain any of the other tokens; braces; semicolons.
_CSS_TOKEN = re.compile(r"""/\*.*?\*/|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|[{};]""", re.DOTALL)
_CSS_DECLARATION = re.compile(r"\s*(-?[A-Za-z][\w-]*)\s*:")


def important_css(css: str, label: str) -> str:
    """``css`` with every declaration of WORDPRESS_IMPORTANT made ``!important``,
    and an important copy of them after each ``all:`` (see WORDPRESS_IMPORTANT)."""
    # The text between two of { } ;, with comments blanked out and strings
    # masked, is a declaration if a ; or } ends it inside a block and it starts
    # with "name:" ("--name:" custom properties don't match); a selector or an
    # at-rule prelude ends with {, and the text before a } after a nested rule is blank.
    masked = list(css)
    inserts: list[tuple[int, str]] = []
    depth, segment_start = 0, 0
    for match in _CSS_TOKEN.finditer(css):
        token = match.group()
        if len(token) > 1:                               # a comment or a string
            masked[match.start():match.end()] = (" " if token.startswith("/*") else "x") * len(token)
            continue
        segment = "".join(masked[segment_start:match.start()])
        declaration = _CSS_DECLARATION.match(segment)
        if token != "{" and depth > 0 and declaration:
            name, value = declaration.group(1).lower(), segment[declaration.end():]
            end = segment_start + len(segment.rstrip())
            if re.fullmatch(WORDPRESS_IMPORTANT_RELATED, name) and name not in WORDPRESS_IMPORTANT:
                fail(f"{label} uses {name}, which shares longhands with WORDPRESS_IMPORTANT: "
                     f"add it there in build.py")
            if re.search(r"!\s*important", value, re.IGNORECASE):
                pass
            elif name == "all":
                value = css[segment_start + declaration.end():end].strip()
                inserts.append((end, "".join(f";{p}:{value} !important" for p in WORDPRESS_IMPORTANT)))
            elif name in WORDPRESS_IMPORTANT:
                inserts.append((end, " !important"))
        depth += {"{": 1, "}": -1, ";": 0}[token]
        if depth < 0:
            fail(f"{label}: unbalanced '}}' at offset {match.start()}")
        segment_start = match.end()
    if depth != 0:
        fail(f"{label}: unbalanced '{{'")
    if not inserts:
        fail(f"{label}: no declaration of {', '.join(WORDPRESS_IMPORTANT[:3])}…: the CSS tokenizer is broken")
    for offset, text in reversed(inserts):
        css = css[:offset] + text + css[offset:]
    return css


def build_wordpress(esbuild: str, index_src: str, header: str, assets: dict, base: str) -> dict:
    """Write build/wordpress.html and build/wordpress-uploads/; returns the uploads."""
    csv_name, csv_bytes = assets[DICTIONARY]
    attribution_bytes = UTF8_BOM + assets[ATTRIBUTION][1].removeprefix(UTF8_BOM)
    attribution_name = hashed_name(Path(ATTRIBUTION).with_suffix(".txt").as_posix(), attribution_bytes)
    csv_url, attribution_url = base + csv_name, base + attribution_name

    # The widget fragment between the markers.
    if index_src.count(BEGIN_MARKER) != 1 or index_src.count(END_MARKER) != 1:
        fail(f"web/{INDEX}: expected {BEGIN_MARKER} and {END_MARKER} exactly once each")
    begin, end = index_src.index(BEGIN_MARKER) + len(BEGIN_MARKER), index_src.index(END_MARKER)
    if end < begin:
        fail(f"web/{INDEX}: {END_MARKER} comes before {BEGIN_MARKER}")
    fragment = index_src[begin:end].strip()
    lowered = fragment.lower()
    for tag in ("<script", "<style", "<pre", "<textarea"):
        if tag in lowered:
            fail(f"web/{INDEX}: the fragment contains {tag}>: collapsing whitespace would break it")

    doc = Html(fragment, f"web/{INDEX} (fragment)")
    for node in doc.nodes:
        if node.kind == "comment":
            doc.replace(node, "")

    def expect(node: Node, key: str, value: str) -> None:
        if node.get(key) != value:
            fail(f"web/{INDEX}: expected {key}={value!r} on <{node.name}>, found {node.get(key)!r}")

    [root] = doc.find(describe("div", id="rimario"), 1, lambda n: n.kind == "start" and n.name == "div"
                      and n.get("id") == "rimario")
    expect(root, "data-dictionary-url", DICTIONARY)
    expect(root, "data-attribution-url", ATTRIBUTION)
    root.set("data-dictionary-url", csv_url)
    root.set("data-attribution-url", attribution_url)
    root.set("data-dictionary-bytes", str(len(csv_bytes)))
    root.set("data-title-suffix", TITLE_SUFFIX)

    # A data URI rather than inline <svg>: the logo's ids would leak into the page.
    [logo] = doc.find(describe("img", class_="sri-logo"), 1, lambda n: n.kind == "start" and n.name == "img"
                      and "sri-logo" in n.tokens("class"))
    expect(logo, "src", LOGO)
    logo.set("src", "data:image/svg+xml;base64," + base64.b64encode((WEB / LOGO).read_bytes()).decode())

    [link] = doc.find("<a data-sri-attribution>", 1, lambda n: n.kind == "start"
                      and n.name == "a" and n.has("data-sri-attribution"))
    expect(link, "href", ATTRIBUTION)
    link.set("href", attribution_url)

    fragment = doc.render()
    rendered = Html(fragment, "build/wordpress.html")
    for _, key, url in rendered.url_references():
        if is_relative_url(url) and url != "./":
            fail(f"build/wordpress.html: relative URL {key}={url} left (it would resolve against the blog post)")
    for node in rendered.tags():
        for key, value in node.attrs:
            if value is not None and "\n" in value:
                fail(f"web/{INDEX}: <{node.name} {key}> has a multi-line value, "
                     f"which collapsing whitespace would change")
    fragment = re.sub(r"\s*\n\s*", " ", fragment)

    css_src = important_css((WEB / CSS).read_text(encoding="utf-8"), f"web/{CSS}")
    css = run_esbuild(esbuild, [f"--sourcefile=web/{CSS}", "--loader=css", "--minify", f"--target={TARGET}",
                                "--legal-comments=none"], stdin=css_src).removesuffix("\n")
    # No --minify-syntax: it turns "\n" strings into template literals with real newlines.
    js = run_esbuild(esbuild, [f"web/{JS_ENTRY}", "--bundle", "--minify-whitespace", "--minify-identifiers",
                               "--format=esm", f"--target={TARGET}", "--legal-comments=none"]).removesuffix("\n")
    if "\n" in js or "</script" in js.lower() or "<!--" in js:
        fail("bundled JS contains a newline, '</script' or '<!--': it can't be inlined in WordPress")
    if "\n" in css or "</style" in css.lower():
        fail("minified CSS contains a newline or '</style': it can't be inlined in WordPress")

    notice = "\n".join(line for line in header.split("\n") if line.strip())
    page = (f"<!--\n{notice}\n-->\n"
            f'<div id="main-body"><link rel="preload" href="{html.escape(csv_url)}" as="fetch" crossorigin>'
            f'<h2 id="descrizionerimario">{html.escape(SEO_HEADING)}</h2>'
            f"<style>#descrizionerimario{{display:none}}{css}</style>"
            f'{fragment}<script type="module">{js}</script></div>\n')
    if any(not line.strip() for line in page.split("\n")[:-1]):
        fail("build/wordpress.html has a blank line: WordPress would split the block there")
    for name in SHORTCODES:
        if "[" + name in page:
            fail(f"build/wordpress.html contains '[{name}': WordPress would run it as a shortcode")
    write(WORDPRESS_HTML, page)

    uploads = {csv_name: (csv_bytes, csv_url), attribution_name: (attribution_bytes, attribution_url)}
    for name, (data, _) in uploads.items():
        write(WORDPRESS_UPLOADS / name, data)
    return uploads


# --- Main --------------------------------------------------------------------

def build(base: str) -> None:
    esbuild, version = find_esbuild()
    if BUILD != ROOT / "build":                          # guard for the rmtree below
        fail(f"unexpected build directory {BUILD}")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    index_src = (WEB / INDEX).read_text(encoding="utf-8")
    header = licence_header(index_src)
    assets = build_web(esbuild, index_src, f"/*\n{header}\n*/")
    uploads = build_wordpress(esbuild, index_src, header, assets, base)

    web_files = sorted(p for p in BUILD_WEB.rglob("*") if p.is_file())
    print(f"Built {BUILD.relative_to(ROOT)}/ with esbuild {version}:")
    print(f"  build/web/ ({len(web_files)} files, {size(sum(p.stat().st_size for p in web_files))})")
    for path in web_files:
        print(f"    {path.relative_to(BUILD_WEB).as_posix():44} {size(path.stat().st_size):>9}")
    print(f"  build/wordpress.html{'':30} {size(WORDPRESS_HTML.stat().st_size):>9}")
    print("  build/wordpress-uploads/")
    for name, (data, _) in uploads.items():
        print(f"    {name:44} {size(len(data)):>9}")
    print()
    print("To publish on WordPress:")
    print("1. Upload these files from Media > Add New (not from inside the page editor: WordPress files")
    print("   an upload under the month of the post it's attached to, which would change its URL):")
    for name, (data, url) in uploads.items():
        print(f"     build/wordpress-uploads/{name} ({len(data):,} bytes)")
        print(f"       -> {url}")
    print("2. Check that each attachment's URL is exactly the one above; if it isn't, rerun with")
    print("   --upload-base set to the folder WordPress used.")
    print("3. Paste build/wordpress.html into a Custom HTML block of the page.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build.py", description="Build web/ into build/ for publication (standalone site and WordPress).")
    parser.add_argument("--upload-base", metavar="URL", type=upload_base,
                        default=DEFAULT_UPLOAD_BASE.format(datetime.date.today()),
                        help="URL of the WordPress uploads folder the files will be uploaded to "
                             "(default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        build(args.upload_base)
    except BuildError as error:
        shutil.rmtree(BUILD, ignore_errors=True)
        print(f"build.py: error: {error}", file=sys.stderr)
        return 1
    except BaseException:
        shutil.rmtree(BUILD, ignore_errors=True)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
