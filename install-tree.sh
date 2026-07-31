#!/bin/bash
# Legt den Installationsbaum unter $1 an. Eine Quelle fuer beide Wege:
# build-deb.sh baut daraus das lokale .deb, debian/rules das PPA-Paket.
set -eu
cd "$(dirname "$0")"
DEST="${1:?Zielverzeichnis fehlt}"

install -Dm644 dynolab.py "$DEST/usr/lib/dynolab/dynolab.py"
mkdir -p "$DEST/usr/lib/dynolab/icons"
cp -r icons/. "$DEST/usr/lib/dynolab/icons/"

install -Dm755 /dev/stdin "$DEST/usr/bin/dynolab" <<'EOF'
#!/bin/sh
exec python3 /usr/lib/dynolab/dynolab.py "$@"
EOF

# Icons ins Systemtheme, damit der Menueintrag schon vor dem ersten Start stimmt
for s in 16 24 32 48 64 128 256 512; do
  install -Dm644 "icons/png/app/dynolab-app-dark-$s.png" \
    "$DEST/usr/share/icons/hicolor/${s}x${s}/apps/dynolab.png"
done
install -Dm644 icons/svg/dynolab-app-dark.svg \
  "$DEST/usr/share/icons/hicolor/scalable/apps/dynolab.svg"
install -Dm644 icons/svg/dynolab-icon-mono-white.svg \
  "$DEST/usr/share/icons/hicolor/scalable/apps/dynolab-tray.svg"

install -Dm644 dynolab.desktop "$DEST/usr/share/applications/dynolab.desktop"

# Sprachkataloge. de spiegelt nur den Quelltext, ohne ihn faellt
# LANGUAGE=de_DE:en auf den englischen Katalog durch.
command -v msgfmt > /dev/null || { echo "msgfmt fehlt: apt install gettext" >&2; exit 1; }
for po in po/*.po; do
  lang=$(basename "$po" .po)
  install -d "$DEST/usr/share/locale/$lang/LC_MESSAGES"
  msgfmt --check "$po" -o "$DEST/usr/share/locale/$lang/LC_MESSAGES/dynolab.mo"
done
