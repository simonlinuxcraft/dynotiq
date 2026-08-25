#!/bin/bash
# Legt den Installationsbaum unter $1 an. Eine Quelle fuer beide Wege:
# build-deb.sh baut daraus das lokale .deb, debian/rules das PPA-Paket.
set -eu
cd "$(dirname "$0")"
DEST="${1:?Zielverzeichnis fehlt}"

install -Dm644 dynotiq.py "$DEST/usr/lib/dynotiq/dynotiq.py"

# Nur die Dateien, die die App zur Laufzeit oeffnet. icons/ enthaelt daneben
# das Designmaterial in Groessen und Varianten, die nie geladen werden.
for f in app-icon/svg/dynotiq-app-dark.svg \
         app-icon/svg/dynotiq-icon-mono-white.svg \
         app-icon/svg/dynotiq-icon-light.svg \
         wordmark/png/dynotiq-wordmark-dark-w1200.png \
         wordmark/png/dynotiq-wordmark-light-w1200.png; do
  install -Dm644 "icons/$f" "$DEST/usr/lib/dynotiq/icons/$f"
done

# Die Symbole der Navigation. Der hicolor-Zwischenschritt muss bleiben, sonst
# erkennt GTK sie nicht als symbolisch und faerbt sie nicht mit ein.
for f in icons/ui/hicolor/scalable/actions/*.svg; do
  install -Dm644 "$f" "$DEST/usr/lib/dynotiq/$f"
done
for s in 16 24 32 48 64 128 256 512; do
  install -Dm644 "icons/app-icon/png/dynotiq-app-dark-$s.png" \
    "$DEST/usr/lib/dynotiq/icons/app-icon/png/dynotiq-app-dark-$s.png"
done

install -Dm755 /dev/stdin "$DEST/usr/bin/dynotiq" <<'EOF'
#!/bin/sh
exec python3 /usr/lib/dynotiq/dynotiq.py "$@"
EOF

# Icons ins Systemtheme, damit der Menueintrag schon vor dem ersten Start stimmt
for s in 16 24 32 48 64 128 256 512; do
  install -Dm644 "icons/app-icon/png/dynotiq-app-dark-$s.png" \
    "$DEST/usr/share/icons/hicolor/${s}x${s}/apps/dynotiq.png"
done
install -Dm644 icons/app-icon/svg/dynotiq-app-dark.svg \
  "$DEST/usr/share/icons/hicolor/scalable/apps/dynotiq.svg"
install -Dm644 icons/app-icon/svg/dynotiq-icon-mono-white.svg \
  "$DEST/usr/share/icons/hicolor/scalable/apps/dynotiq-tray.svg"

install -Dm644 dynotiq.desktop "$DEST/usr/share/applications/dynotiq.desktop"

# Paketquelle und Schluessel gehoeren ins Paket, sonst bekommt niemand Updates,
# der das .deb von Hand eingespielt hat. Flaches Repo: Suite "./", keine
# Komponenten. Signed-By zeigt auf genau diesen Schluessel und auf keinen
# anderen, damit die Quelle nichts ausserhalb von dynotiq signieren kann.
install -Dm644 packaging/dynotiq.gpg "$DEST/usr/share/keyrings/dynotiq.gpg"
install -Dm644 /dev/stdin "$DEST/etc/apt/sources.list.d/dynotiq.sources" <<'EOF'
Types: deb
URIs: https://simonlinuxcraft.github.io/dynotiq
Suites: ./
Signed-By: /usr/share/keyrings/dynotiq.gpg
EOF

# Sprachkataloge. de spiegelt nur den Quelltext, ohne ihn faellt
# LANGUAGE=de_DE:en auf den englischen Katalog durch.
command -v msgfmt > /dev/null || { echo "msgfmt fehlt: apt install gettext" >&2; exit 1; }
for po in po/*.po; do
  lang=$(basename "$po" .po)
  install -d "$DEST/usr/share/locale/$lang/LC_MESSAGES"
  msgfmt --check "$po" -o "$DEST/usr/share/locale/$lang/LC_MESSAGES/dynotiq.mo"
done
