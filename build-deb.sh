#!/bin/bash
# Baut dynolab_<version>_all.deb. Ohne debhelper: das Paket ist reines Python,
# der Rest sind Icons und ein Starter.
set -eu
cd "$(dirname "$0")"

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dynolab.py)
[ -n "$VER" ] || { echo "Version nicht gefunden"; exit 1; }
PKG="build/dynolab_${VER}_all"

rm -rf build
mkdir -p "$PKG/DEBIAN" "$PKG/usr/lib/dynolab" "$PKG/usr/bin"

install -m644 dynolab.py "$PKG/usr/lib/dynolab/dynolab.py"
cp -r icons "$PKG/usr/lib/dynolab/"

# Icons ins Systemtheme, damit der Menueintrag schon vor dem ersten Start stimmt
for s in 16 24 32 48 64 128 256 512; do
  install -Dm644 "icons/png/app/dynolab-app-dark-$s.png" \
    "$PKG/usr/share/icons/hicolor/${s}x${s}/apps/dynolab.png"
done
install -Dm644 icons/svg/dynolab-app-dark.svg \
  "$PKG/usr/share/icons/hicolor/scalable/apps/dynolab.svg"
install -Dm644 icons/svg/dynolab-icon-mono-white.svg \
  "$PKG/usr/share/icons/hicolor/scalable/apps/dynolab-tray.svg"

cat > "$PKG/usr/bin/dynolab" <<'EOF'
#!/bin/sh
exec python3 /usr/lib/dynolab/dynolab.py "$@"
EOF
chmod 755 "$PKG/usr/bin/dynolab"

# StartupWMClass muss zum prgname der App passen, sonst bleibt das Dock-Icon generisch
install -Dm644 /dev/stdin "$PKG/usr/share/applications/dynolab.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Dynolab
Comment=Systemdiagnose und Optimierung
Comment[en]=System diagnostics and tuning
Exec=dynolab
Icon=dynolab
Terminal=false
Categories=System;Settings;Monitor;
StartupNotify=true
StartupWMClass=dynolab
EOF

install -Dm644 /dev/stdin "$PKG/usr/share/doc/dynolab/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: dynolab
Source: https://github.com/simonlinuxcraft/dynolab

Files: *
Copyright: 2026 simonlinuxcraft
License: GPL-3+
 This program is free software: you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation, either version 3 of the License, or (at your option) any later
 version.
 .
 On Debian systems the full text of the GNU General Public License version 3
 can be found in /usr/share/common-licenses/GPL-3.
EOF

cat > "$PKG/DEBIAN/control" <<EOF
Package: dynolab
Version: $VER
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0
Recommends: librsvg2-bin, pkexec, fonts-inter
Suggests: fwupd, flatpak
Maintainer: simonlinuxcraft <245174420+simonlinuxcraft@users.noreply.github.com>
Description: System diagnostics and tuning for Ubuntu
 Scans the machine for what slows it down: outdated graphics drivers,
 thermal throttling, full filesystems, a growing journal, failed units
 and stale autostart entries. Reads the journal for audio dropouts, GPU
 driver errors and out-of-memory kills, and explains each one with
 concrete steps.
 .
 Shows pending updates from apt, snap, flatpak and fwupd and installs the
 selected ones, monitors CPU, GPU, RAM and disk live, and benchmarks the
 machine.
EOF

# cp erbt die Rechte aus dem Arbeitsbaum, dpkg will 755/644
find "$PKG" -type d -exec chmod 755 {} +
find "$PKG" -type f -exec chmod 644 {} +
chmod 755 "$PKG/usr/bin/dynolab"

dpkg-deb --root-owner-group --build "$PKG" > /dev/null
DEB="build/dynolab_${VER}_all.deb"
mv "$PKG.deb" "$DEB" 2>/dev/null || true
ls -lh "$DEB"
dpkg-deb -I "$DEB" | sed -n '2,12p'
