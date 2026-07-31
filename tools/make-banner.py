#!/usr/bin/env python3
"""Rendert die README-Banner aus dem Icon plus Schriftzug.

Aufruf aus dem Projektverzeichnis: python3 tools/make-banner.py
Ergebnis: docs/banner-light.png und docs/banner-dark.png
Braucht rsvg-convert (librsvg2-bin) und die Schrift Inter (fonts-inter).
"""
import os
import subprocess
import sys

import cairo

W, H, ICON, GAP = 820, 200, 112, 28
OUT = "docs"


def build(out, icon_svg, fg, sub):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    # Ohne das setzt Cairo Subpixel-Glättung und der Schriftzug bekommt auf
    # transparentem Grund farbige Säume.
    opt = cairo.FontOptions()
    opt.set_antialias(cairo.ANTIALIAS_GRAY)
    cr.set_font_options(opt)

    cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(64)
    word = cr.text_extents("dynolab")
    cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(15)
    sub_text, spacing = "SYSTEMDIAGNOSE", 3.4
    sub_w = sum(cr.text_extents(c).x_advance + spacing for c in sub_text) - spacing

    x0 = (W - (ICON + GAP + max(word.width, sub_w))) / 2
    tmp = out.replace(".png", "-tmp.png")
    subprocess.run(["rsvg-convert", "-w", str(ICON), "-h", str(ICON),
                    "-o", tmp, icon_svg], check=True)
    cr.set_source_surface(cairo.ImageSurface.create_from_png(tmp),
                          x0, (H - ICON) / 2)
    cr.paint()
    os.unlink(tmp)

    tx = x0 + ICON + GAP
    cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(64)
    cr.set_source_rgb(*fg)
    cr.move_to(tx - word.x_bearing, H / 2 + 6)
    cr.show_text("dynolab")

    cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(15)
    cr.set_source_rgb(*sub)
    cr.move_to(tx + 2, H / 2 + 36)
    for ch in sub_text:
        cr.show_text(ch)
        cr.rel_move_to(spacing, 0)
    surf.write_to_png(out)
    print("geschrieben:", out)


if __name__ == "__main__":
    if not os.path.isdir("icons"):
        sys.exit("Bitte aus dem Projektverzeichnis aufrufen.")
    os.makedirs(OUT, exist_ok=True)
    # Hell heißt: für hellen Hintergrund, also dunkles Icon und dunkler Text.
    build(f"{OUT}/banner-light.png", "icons/svg/dynolab-icon.svg",
          (0.07, 0.086, 0.106), (0.42, 0.45, 0.49))
    build(f"{OUT}/banner-dark.png", "icons/svg/dynolab-icon-light.svg",
          (0.949, 0.953, 0.961), (0.55, 0.58, 0.62))
