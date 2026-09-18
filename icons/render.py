"""Renders the app icon and wordmark sets from the two master images."""
import os
import sys

import numpy as np
from PIL import Image

ICONS = sys.argv[1]
ICON_MASTER = f"{ICONS}/app-icon/dynotiq-app-dark-master.png"
WORD_MASTER = f"{ICONS}/wordmark/dynotiq-wordmark-dark-master.png"
INK, TILE, WHITE = (0x12, 0x16, 0x1B), (0x16, 0x1A, 0x20), (0xFF, 0xFF, 0xFF)


def scaled(img, w, h):
    # Premultiplied, otherwise the transparent black around the shapes
    # bleeds into the edges as a dark fringe.
    return img.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")


def parts(img):
    a = np.asarray(img).astype(float) / 255
    rgb, al = a[..., :3], a[..., 3:]
    lum = (rgb @ [0.2126, 0.7152, 0.0722])[..., None]
    # Das Gelb des Tachos samt Schein: rot deutlich ueber blau.
    warm = rgb[..., :1] > rgb[..., 2:3] + 0.15
    return rgb, al, lum, warm


def pack(rgb, al):
    out = np.concatenate([np.clip(rgb, 0, 1), al], -1)
    return Image.fromarray((out * 255).astype(np.uint8))


def dark_tile(img):
    """The navy tile of the master in the dark tone of the app.

    Everything except the gauge yellow loses its colour. Dark pixels take
    the tile tone with their brightness kept, so gloss and rim survive.
    """
    rgb, al, lum, warm = parts(img)
    dark = np.clip((0.55 - lum) / 0.25, 0, 1)
    # Aufgehellt wird gleichmaessig, sonst waechst der leichte Kuehlton
    # des Anthrazits im Glanz zu sichtbarem Blau.
    tone = np.array(TILE) / 255 + 0.9 * (lum - 0.12)
    grey = dark * tone + (1 - dark) * lum
    return pack(np.where(warm, rgb, grey), al)


def dark_letters(img):
    """The white letters in ink for light surfaces, gauge yellow untouched."""
    rgb, al, lum, warm = parts(img)
    t = np.clip((lum - 0.72) / 0.28, 0, 1)
    return pack(np.where(warm, rgb, np.array(INK) / 255 * (0.7 + 0.9 * t)), al)


def on(img, color):
    bg = Image.new("RGBA", img.size, color + (255,))
    bg.alpha_composite(img)
    return bg.convert("RGB")


icon = dark_tile(Image.open(ICON_MASTER).convert("RGBA"))
for s in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
    scaled(icon, s, s).save(f"{ICONS}/app-icon/png/dynotiq-app-dark-{s}.png",
                            optimize=True)

word = Image.open(WORD_MASTER).convert("RGBA")
alpha = np.asarray(word)[..., 3]
ys, xs = np.nonzero(alpha > 5)
pad = 6
box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0),
       min(xs.max() + pad + 1, word.width), min(ys.max() + pad + 1, word.height))
word = word.crop(box)
print("wordmark box", box, word.size)
variants = {"dark": word, "light": dark_letters(word)}
for w in (600, 1200):
    h = round(word.height * w / word.width)
    for name, img in variants.items():
        small = scaled(img, w, h)
        small.save(f"{ICONS}/wordmark/png/dynotiq-wordmark-{name}-w{w}.png",
                   optimize=True)
        on(small, INK if name == "dark" else WHITE).save(
            f"{ICONS}/wordmark/png/dynotiq-wordmark-{name}-bg-w{w}.png",
            optimize=True)
print("ok")
