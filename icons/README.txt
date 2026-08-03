dynotiq: Wortmarke + App-Icon

Der Name wird immer kleingeschrieben: dynotiq.

FARBEN
  Ink      #12161B
  Akzent   #F5C242

SCHRIFT
  Space Grotesk Bold, Laufweite −0.03 em
  In den SVGs eingebettet, sieht überall gleich aus, auch ohne installierte Fonts.


wordmark/     Schriftzug
  Das „o“ ist der Tacho selbst, auf Versalhöhe gezogen (Strichstärke ×1.25),
  damit sein Strich genauso dick ist wie die Buchstabenstämme.

  png/dynotiq-wordmark-light-w600|1200|2400.png    dunkle Schrift, transparent
  png/dynotiq-wordmark-dark-…                      weiße Schrift, transparent
  png/…-light-bg-… / …-dark-bg-…                   mit Fläche (weiß bzw. #12161B)
  svg/…                                            Vektor

  w = Breite des Schriftzugs in Pixel.
  Mindestbreite 150 px, darunter läuft der Zeiger im Tacho zu.


app-icon/     App-Icon
  png/dynotiq-app-<größe>.png        deckend, weiße Kachel, 16-1024 px  ← installieren
  png/dynotiq-app-dark-<größe>.png   deckend, dunkle Kachel
  png/dynotiq-<größe>.png            transparent, 16-512 px
  svg/dynotiq-app.svg / -dark.svg    Kachel als Vektor, Eckradius 30 %
  svg/dynotiq-app-square*.svg        ohne Eckrundung (wenn die Umgebung selbst maskiert)
  svg/dynotiq-icon-mono*.svg         einfarbig: Top-Bar / Tray / Favicon

  Glyph steht auf 80 % der Kachelkante, der Rest ist Schutzraum.


BENENNUNG
  light = für helle Flächen · dark = für dunkle Flächen
  -bg   = mit deckender Fläche · ohne = transparent


INSTALLATION UNTER UBUNTU
  for s in 16 24 32 48 64 128 256 512; do
    sudo install -Dm644 app-icon/png/dynotiq-app-$s.png \
      /usr/share/icons/hicolor/${s}x${s}/apps/dynotiq.png
  done
  sudo install -Dm644 app-icon/svg/dynotiq-app.svg \
    /usr/share/icons/hicolor/scalable/apps/dynotiq.svg
  sudo gtk-update-icon-cache /usr/share/icons/hicolor

  In der .desktop-Datei:  Icon=dynotiq


REGELN
  Das „o“ nie durch ein normales o ersetzen.
  Tacho nie drehen, spiegeln, verzerren oder umfärben.
  Ab 24 px farbig nicht mehr verlässlich, dort dynotiq-icon-mono verwenden.
