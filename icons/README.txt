dynotiq — App-Icon (2a)

Farben
  Ink                #12161B
  Akzent Gelb        #F5C242
  Akzent auf Dunkel  #F5C242  (identisch)

APP-ICONS — deckend, mit Hintergrund (das hier installierst du)
  png/app/dynotiq-app-<größe>.png        weiße Kachel, 16–1024 px
  png/app/dynotiq-app-dark-<größe>.png   dunkle Kachel, 16–1024 px
  svg/dynotiq-app.svg / -dark.svg        dieselben als Vektor, Eckradius 30 %
  svg/dynotiq-app-square*.svg            ohne Rundung (falls die Umgebung selbst maskiert)

TRANSPARENT — für Leisten, Doks mit eigener Maske, Web
  svg/dynotiq-icon.svg          Hauptmarke auf hellem Grund
  svg/dynotiq-icon-light.svg    auf dunklem Grund
  svg/dynotiq-icon-mono*.svg    einfarbig: Top-Bar / Tray / Favicon
  png/dynotiq-<größe>.png       16–512 px

Installation unter Ubuntu (App-Icon)
  for s in 16 24 32 48 64 128 256 512; do
    sudo install -Dm644 png/app/dynotiq-app-$s.png \
      /usr/share/icons/hicolor/${s}x${s}/apps/dynotiq.png
  done
  sudo install -Dm644 svg/dynotiq-app.svg /usr/share/icons/hicolor/scalable/apps/dynotiq.svg
  sudo gtk-update-icon-cache /usr/share/icons/hicolor

In der .desktop-Datei:  Icon=dynotiq

Glyph steht auf 80 % der Kachelkante — der Rest ist Schutzraum.
Ab 16 px farbig nicht mehr lesbar: dort dynotiq-icon-mono verwenden.
