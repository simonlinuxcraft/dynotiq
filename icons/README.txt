dynotiq: wordmark and app icon

The name is always written in lower case: dynotiq.


MASTERS
  app-icon/dynotiq-app-dark-master.png     navy tile, 1254 px, transparent corners
                                           (rendered in the dark app tone #161A20,
                                           only the gauge yellow keeps its colour)
  wordmark/dynotiq-wordmark-dark-master.png  white letters for dark surfaces

  Everything under png/ is rendered from these two. After changing a master:
    python3 icons/render.py icons
  (needs python3-numpy and python3-pil, only for rendering, not at runtime)


wordmark/png/
  dynotiq-wordmark-dark-w600|w1200.png       white letters, transparent
  dynotiq-wordmark-light-w600|w1200.png      dark letters, transparent
  …-bg-…                                     on a solid surface (#12161B / white)

  dark = for dark surfaces, light = for light surfaces.
  The light version is derived: the white letters recoloured to ink #12161B,
  shading kept, the gauge yellow left as it is.
  w = width in pixels. The app loads the w1200 files.


app-icon/png/
  dynotiq-app-dark-<size>.png    16-1024 px, installed as the app icon

app-icon/svg/
  dynotiq-icon-mono-white.svg    single colour, tray and top bar
  dynotiq-icon-mono.svg          single colour, dark
  dynotiq-icon.svg / -light.svg  flat gauge without tile, for small print


ui/
  hicolor/scalable/actions/dq-*-symbolic.svg    line icons, 24 px grid

  Every element needs a class attribute, otherwise GTK 4.20 and later fills
  the outline and the symbol turns into a black blob:
    outline   class="transparent-fill foreground-stroke"
    area      class="foreground-fill"
  fill and stroke on the element are ignored by GTK for these files, they
  stay in for browsers and mockups. GTK sets the stroke width to 2 itself.


RULES
  Never replace the gauge "o" with a normal o.
  Never rotate, mirror, stretch or recolour the gauge.
  The tile stays readable down to 16 px. Where only one colour works (tray,
  top bar), use dynotiq-icon-mono-white.
