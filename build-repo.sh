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

# Binaerer Keyring, genau die Form, die apt hinter signed-by erwartet. Der
# Abgleich faengt den Schluesselwechsel ab: sonst baut das Skript kommentarlos
# ein Paket, das seine eigene Quelle nicht verifizieren kann.
gpg --export "$KEY" > "$OUT/dynotiq.gpg"
cmp -s "$OUT/dynotiq.gpg" packaging/dynotiq.gpg || {
  echo "packaging/dynotiq.gpg passt nicht zu $KEY"; exit 1; }

cp packaging/screenshot.jpg "$OUT/screenshot.jpg"

# Die Seite ist das Erste, was jemand von dynotiq sieht. Sie traegt deshalb
# dieselbe Schrift, dieselben Toene und dieselbe Ampel wie die App, und sie
# kann hell wie dunkel. Kein Framework: sie besteht aus einer Datei.
cat > "$OUT/index.html" <<HTML
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>dynotiq apt repository</title>
<meta name="description" content="System diagnostics and tuning for Ubuntu.">
<style>
:root{
  --bg:#0E1116; --card:#161A20; --raised:#1B2027; --text:#F2F3F5;
  --dim:#9AA1AA; --faint:#767C85; --line:rgba(255,255,255,.09);
  --acc:#F5C242; --acctext:#F5C242; --ok:#2ED27A; --warn:#FF8A3D; --crit:#FF4747;
  --shadow:0 18px 50px rgba(0,0,0,.45);
}
@media (prefers-color-scheme:light){
  :root{
    --bg:#F4F1EC; --card:#FFFDFA; --raised:#F5F2ED; --text:#12161B;
    --dim:#5E656E; --faint:#767C85; --line:rgba(0,0,0,.10);
    --acctext:#AB872E; --ok:#177544; --warn:#9C5800; --crit:#C4362A;
    --shadow:0 18px 50px rgba(0,0,0,.10);
  }
}
*{box-sizing:border-box}
body{
  margin:0; padding:0 20px 72px;
  background:var(--bg); color:var(--text);
  font:16px/1.65 Arial,"Liberation Sans",Helvetica,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:52rem; margin:0 auto}
header{padding:72px 0 34px; text-align:center}
.mark{display:flex; align-items:center; justify-content:center; gap:14px}
.mark svg{width:52px; height:52px; flex:none}
h1{margin:0; font-size:44px; font-weight:700; letter-spacing:-.02em}
.lede{margin:18px auto 0; max-width:34rem; font-size:18px; color:var(--dim)}
.ver{
  display:inline-block; margin-top:20px; padding:5px 13px; border-radius:999px;
  border:1px solid var(--line); color:var(--faint);
  font:700 12px/1 Arial,"Liberation Sans",sans-serif; letter-spacing:.04em;
}
.shot{
  margin:38px 0 8px; border-radius:12px; overflow:hidden;
  border:1px solid var(--line); box-shadow:var(--shadow); line-height:0;
}
.shot img{width:100%; height:auto; display:block}
h2{
  margin:52px 0 6px; font-size:13px; font-weight:700; letter-spacing:.1em;
  text-transform:uppercase; color:var(--acctext);
}
h2+p{margin-top:0; color:var(--dim)}
.card{
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:6px 18px 18px; margin-top:14px;
}
.head{
  display:flex; align-items:center; justify-content:space-between;
  gap:12px; padding:10px 0 8px;
}
.head span{font-size:13px; color:var(--faint)}
pre{
  margin:0; padding:15px 16px; border-radius:9px;
  background:var(--raised); border:1px solid var(--line);
  font:13.5px/1.75 "Liberation Mono","Courier New",monospace; color:var(--text);
  /* Umbrechen statt seitwaerts schieben. Der kopierte Text bleibt exakt, nur
     die Darstellung bricht um, und niemand muss quer scrollen. */
  white-space:pre-wrap; overflow-wrap:anywhere;
}
button{
  border:1px solid var(--line); background:transparent; color:var(--dim);
  border-radius:7px; padding:6px 12px; cursor:pointer;
  font:700 12px Arial,"Liberation Sans",sans-serif;
}
button:hover{color:var(--text); border-color:var(--faint)}
ul{margin:14px 0 0; padding:0; list-style:none}
li{display:flex; gap:11px; align-items:baseline; padding:5px 0; color:var(--dim)}
li i{width:7px; height:7px; border-radius:2px; flex:none; transform:translateY(-1px)}
.d-ok{background:var(--ok)} .d-warn{background:var(--warn)} .d-crit{background:var(--crit)}
footer{
  margin-top:56px; padding-top:22px; border-top:1px solid var(--line);
  color:var(--faint); font-size:14px; text-align:center;
}
a{color:var(--acctext)}
a:hover{text-decoration:none}
code{
  font:13px "Liberation Mono","Courier New",monospace;
  background:var(--raised); padding:2px 6px; border-radius:5px;
}
</style>
<div class="wrap">
<header>
  <div class="mark">
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <path d="M13.87 45.45A20 20 0 1 1 50.79 30.16" fill="none"
            stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
      <path d="M50.79 30.16A20 20 0 0 1 50.13 45.45" fill="none"
            stroke="var(--acc)" stroke-width="6" stroke-linecap="round"/>
      <path d="M32 37L41.58 28.97" fill="none" stroke="currentColor"
            stroke-width="5" stroke-linecap="round"/>
      <circle cx="32" cy="37" r="4" fill="currentColor"/>
    </svg>
    <h1>dynotiq</h1>
  </div>
  <p class="lede">System diagnostics and tuning for Ubuntu. It looks for what
    actually slows the machine down, says what it found in plain words, and
    puts a button next to the things it can fix.</p>
  <div class="ver">VERSION $VER</div>
</header>

<div class="shot"><img src="screenshot.jpg" alt="The dynotiq overview, with a
  system score and the current temperature, clock and free memory"
  width="1100" height="392" loading="lazy"></div>

<h2>Install</h2>
<p>Four lines. The last one installs it, the first three tell apt where to
  look and which key to trust.</p>
<div class="card">
  <div class="head"><span>Add the repository and install</span>
    <button data-copy="cmd">Copy</button></div>
<pre id="cmd">curl -fsSL $URL/dynotiq.gpg | sudo tee /usr/share/keyrings/dynotiq.gpg > /dev/null
printf 'Types: deb\nURIs: $URL\nSuites: ./\nSigned-By: /usr/share/keyrings/dynotiq.gpg\n' | sudo tee /etc/apt/sources.list.d/dynotiq.sources > /dev/null
sudo apt update
sudo apt install dynotiq</pre>
</div>
<p>Updates then arrive through <code>apt upgrade</code> like any other
  package. The repository is signed, and the key above is the only one apt
  will accept for it.</p>

<h2>What it looks at</h2>
<ul>
  <li><i class="d-crit"></i><span>Graphics drivers, failed services, GPU
    errors and out-of-memory kills in the journal</span></li>
  <li><i class="d-warn"></i><span>Filesystems running full, a journal growing
    out of hand, thermal throttling, stale autostart entries</span></li>
  <li><i class="d-ok"></i><span>Pending updates from apt, snap, flatpak and
    fwupd, and which Proton build each Steam game is set to</span></li>
</ul>

<footer>
  <a href="https://github.com/simonlinuxcraft/dynotiq">Source on GitHub</a>
  &middot;
  <a href="https://github.com/simonlinuxcraft/dynotiq/releases/latest">Releases</a>
  <br><br>
  Free software under the GNU General Public License v3 or later.
</footer>
</div>
<script>
document.querySelectorAll("button[data-copy]").forEach(function (b) {
  b.addEventListener("click", function () {
    var el = document.getElementById(b.getAttribute("data-copy"));
    navigator.clipboard.writeText(el.innerText).then(function () {
      b.textContent = "Copied";
      setTimeout(function () { b.textContent = "Copy"; }, 1500);
    });
  });
});
</script>
HTML

echo "Fertig: $OUT"
ls -1 "$OUT"
echo
echo "Veroeffentlichen mit:"
echo "  ./publish-repo.sh"
