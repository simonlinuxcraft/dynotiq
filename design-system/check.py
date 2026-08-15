#!/usr/bin/env python3
"""Check the design system still describes the app.

Reads dynotiq.py without importing it (no gi on a CI box) and asserts that
every colour it paints with is written down in tokens.css, that the derived
accent values still match lighten/darken, and that each specimen carries its
@dsCard marker on line 1.
"""

import ast
import pathlib
import re
import sys
from html.parser import HTMLParser

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent / "dynotiq.py"
TOKENS = HERE / "tokens.css"
HEX = re.compile(r"#[0-9A-Fa-f]{6}")

# Painted by Cairo widgets or only reachable through a theme we override, so
# they never became a token.
NOT_TOKENS = {"#2A0F0F", "#E8EBEE"}


def app_values():
    """INK, ACCENTS, PALETTES and CSS_TEMPLATE straight out of the source."""
    tree = ast.parse(APP.read_text())
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
        if name in ("INK", "ACCENTS", "PALETTES", "CSS_TEMPLATE"):
            out[name] = ast.literal_eval(node.value)
    missing = {"INK", "ACCENTS", "PALETTES", "CSS_TEMPLATE"} - out.keys()
    assert not missing, f"not found in {APP.name}: {sorted(missing)}"
    return out


def lighten(hexcol, f=0.25):
    rgb = tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(min(255, int(c + (255 - c) * f)) for c in rgb)


def darken(hexcol, f=0.90):
    rgb = tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(int(c * (1 - f)) for c in rgb)


class Wellformed(HTMLParser):
    VOID = {"br", "hr", "img", "input", "meta", "link", "source", "path",
            "circle", "rect", "use", "stop", "area", "col"}

    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        assert self.stack, f"{self.path.name}: </{tag}> with nothing open"
        assert self.stack[-1] == tag, \
            f"{self.path.name}: </{tag}> closes <{self.stack[-1]}>"
        self.stack.pop()


def main():
    app = app_values()
    css = TOKENS.read_text()
    token_hex = {h.upper() for h in HEX.findall(css)}

    # Every colour the app paints with has a token.
    for hexcol in {h.upper() for h in HEX.findall(app["CSS_TEMPLATE"])} - NOT_TOKENS:
        assert hexcol in token_hex, f"{hexcol} is in CSS_TEMPLATE but not in tokens.css"

    assert app["INK"].upper() in token_hex, "INK missing from tokens.css"

    for accent in app["ACCENTS"]:
        assert accent.upper() in token_hex, f"accent {accent} missing from tokens.css"
        assert lighten(accent) in token_hex, f"hover for {accent} missing or stale"
        assert darken(accent) in token_hex, f"on-accent text for {accent} missing or stale"

    for name, palette in app["PALETTES"].items():
        for state, hexcol in palette.items():
            assert hexcol.upper() in token_hex, \
                f"palette {name}/{state} {hexcol} missing from tokens.css"

    # Specimens parse and are filed under a group.
    pages = sorted(HERE.glob("*/*.html"))
    assert pages, "no specimen pages found"
    for page in pages:
        text = page.read_text()
        first = text.splitlines()[0]
        assert "@dsCard" in first and 'group="' in first, \
            f"{page.name}: line 1 needs an @dsCard comment with a group"
        parser = Wellformed(page)
        parser.feed(text)
        assert not parser.stack, f"{page.name}: unclosed {parser.stack}"

    print(f"ok: {len(token_hex)} tokens, {len(pages)} specimens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
