Dynolab — App-Icon (2a)

Farben
  Ink                #12161B
  Akzent Gelb        #F5C242
  Akzent auf Dunkel  #F5C242  (identisch)

APP-ICONS — deckend, mit Hintergrund (das hier installierst du)
  png/app/dynolab-app-<größe>.png        weiße Kachel, 16–1024 px
  png/app/dynolab-app-dark-<größe>.png   dunkle Kachel, 16–1024 px
  svg/dynolab-app.svg / -dark.svg        dieselben als Vektor, Eckradius 30 %
  svg/dynolab-app-square*.svg            ohne Rundung (falls die Umgebung selbst maskiert)

TRANSPARENT — für Leisten, Doks mit eigener Maske, Web
  svg/dynolab-icon.svg          Hauptmarke auf hellem Grund
  svg/dynolab-icon-light.svg    auf dunklem Grund
  svg/dynolab-icon-mono*.svg    einfarbig: Top-Bar / Tray / Favicon
  png/dynolab-<größe>.png       16–512 px

Installation unter Ubuntu (App-Icon)
  for s in 16 24 32 48 64 128 256 512; do
    sudo install -Dm644 png/app/dynolab-app-$s.png \
      /usr/share/icons/hicolor/${s}x${s}/apps/dynolab.png
  done
  sudo install -Dm644 svg/dynolab-app.svg /usr/share/icons/hicolor/scalable/apps/dynolab.svg
  sudo gtk-update-icon-cache /usr/share/icons/hicolor

In der .desktop-Datei:  Icon=dynolab

Glyph steht auf 80 % der Kachelkante — der Rest ist Schutzraum.
Ab 16 px farbig nicht mehr lesbar: dort dynolab-icon-mono verwenden.
