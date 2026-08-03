#!/bin/bash
# Baut das apt-Repo, das auf GitHub Pages liegt: ein .deb, ein signierter
# Index, der oeffentliche Schluessel. Veroeffentlicht wird bewusst nicht, das
# bleibt ein eigener Schritt.
#
# Ein flaches Repo ohne dists/-Baum. Das Paket ist Architecture: all und reines
# Python, es passt auf jede Ubuntu-Fassung. Getrennte Serien waeren nur beim
# PPA noetig, wo Launchpad je Serie eine eigene Versionsnummer verlangt.
#
# Einmalig noetig:
#   sudo apt install dpkg-dev apt-utils
#   GPG-Schluessel anlegen, Pages im GitHub-Repo auf den Branch gh-pages stellen
#
# KEY ueberschreibt den Signierschluessel, URL die Adresse des Repos.
set -eu
cd "$(dirname "$0")"

KEY="${KEY:-9D421A82D67E1656}"
URL="${URL:-https://simonlinuxcraft.github.io/dynotiq}"
OUT="build/repo"

for t in dpkg-scanpackages apt-ftparchive gpg gzip; do
  command -v "$t" > /dev/null || { echo "$t fehlt, siehe Kopf dieser Datei"; exit 1; }
done
gpg --list-secret-keys "$KEY" > /dev/null 2>&1 || { echo "Schluessel $KEY fehlt"; exit 1; }

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dynotiq.py)
[ -n "$VER" ] || { echo "Version nicht gefunden"; exit 1; }

./build-deb.sh > /dev/null
DEB="build/dynotiq_${VER}_all.deb"
[ -f "$DEB" ] || { echo "$DEB fehlt"; exit 1; }

# Nur die aktuelle Fassung. Wer eine aeltere braucht, holt sie aus den
# GitHub-Releases; ein Repo mit einer Version haelt den Index klein und macht
# jeden Bau reproduzierbar.
rm -rf "$OUT"
mkdir -p "$OUT"
cp "$DEB" "$OUT/"

( cd "$OUT"
  # /dev/null als override-Datei, sonst sucht dpkg-scanpackages eine.
  dpkg-scanpackages --multiversion . /dev/null 2> /dev/null > Packages
  gzip -9kf Packages
  # Ohne Suite und Components, das ist der flache Fall. Kein Valid-Until: ein
  # Repo, das von selbst ablaeuft, zwingt zum Nachsignieren ohne neue Version.
  # Erst daneben schreiben: eine offene Umleitung auf Release legt die Datei
  # an, bevor apt-ftparchive scannt, und sie listet sich dann selbst mit.
  apt-ftparchive -o APT::FTPArchive::Release::Origin=dynotiq \
                 -o APT::FTPArchive::Release::Label=dynotiq \
                 -o APT::FTPArchive::Release::Architectures=all \
                 release . > ../Release.tmp
  mv ../Release.tmp Release
  rm -f InRelease
  gpg --batch --yes --local-user "$KEY" --clearsign -o InRelease Release )

# Binaerer Keyring, genau die Form, die apt hinter signed-by erwartet.
gpg --export "$KEY" > "$OUT/dynotiq.gpg"

cat > "$OUT/index.html" <<HTML
<!doctype html>
<meta charset="utf-8">
<title>dynotiq apt repository</title>
<style>
 body{font:16px/1.6 system-ui,sans-serif;max-width:44rem;margin:3rem auto;padding:0 1rem;
      background:#12161B;color:#D7DCE3}
 h1{font-weight:600;letter-spacing:-.02em} code,pre{font-family:ui-monospace,monospace}
 pre{background:#1B2027;padding:1rem;border-radius:8px;overflow-x:auto;font-size:14px}
 a{color:#F5C242}
</style>
<h1>dynotiq</h1>
<p>System diagnostics and tuning for Ubuntu. Current version: <code>$VER</code></p>
<h2>Install</h2>
<pre>curl -fsSL $URL/dynotiq.gpg | sudo tee /usr/share/keyrings/dynotiq.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/dynotiq.gpg] $URL ./" | sudo tee /etc/apt/sources.list.d/dynotiq.list
sudo apt update
sudo apt install dynotiq</pre>
<p>Updates then arrive through <code>apt upgrade</code> like any other package.</p>
<p><a href="https://github.com/simonlinuxcraft/dynotiq">Source on GitHub</a>.
Proprietary software, all rights reserved. See the LICENSE file.</p>
HTML

echo "Fertig: $OUT"
ls -1 "$OUT"
echo
echo "Veroeffentlichen mit:"
echo "  ./publish-repo.sh"
