#!/bin/bash
# Baut dynolab_<version>_all.deb fuer den lokalen Test. Ohne debhelper: das
# Paket ist reines Python, der Rest sind Icons, Kataloge und ein Starter.
# Der Weg in die Distribution laeuft ueber build-source.sh und das PPA.
set -eu
cd "$(dirname "$0")"

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dynolab.py)
[ -n "$VER" ] || { echo "Version nicht gefunden"; exit 1; }
PKG="build/dynolab_${VER}_all"

# Nur den eigenen Baum wegraeumen. build/ppa gehoert build-source.sh und
# enthaelt signierte Quellpakete, die hier nichts verloren haben.
rm -rf "$PKG" "build/dynolab_${VER}_all.deb"
mkdir -p "$PKG/DEBIAN"
./install-tree.sh "$PKG"

# Zweitkopie im Arbeitsbaum, damit sich 'LANGUAGE=en python3 dynolab.py'
# ohne Installation testen laesst.
rm -rf locale
cp -r "$PKG/usr/share/locale" locale

install -Dm644 debian/copyright "$PKG/usr/share/doc/dynolab/copyright"

cat > "$PKG/DEBIAN/control" <<EOF
Package: dynolab
Version: $VER
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0
Recommends: librsvg2-bin, pkexec, fonts-inter
Suggests: fwupd, flatpak
Maintainer: simonlinuxcraft <simonlinuxcraft@pm.me>
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
