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

# Die Marken aus dem Projekt, nicht nachgebaut: die Wortmarke in beiden
# Fassungen (die Datei heisst nach dem Grund, auf dem sie liegt) und das
# App-Zeichen als Favicon.
cp icons/wordmark/png/dynotiq-wordmark-dark-w600.png "$OUT/wordmark-dark.png"
cp icons/wordmark/png/dynotiq-wordmark-light-w600.png "$OUT/wordmark-light.png"
cp icons/app-icon/svg/dynotiq-app.svg "$OUT/icon.svg"

# Die Seite ist das Erste, was jemand von dynotiq sieht. Sie traegt deshalb
# dieselbe Schrift, dieselben Toene und dieselbe Ampel wie die App, und sie
# kann hell wie dunkel. Kein Bildschirmfoto: eines von dieser Maschine wuerde
# Pfade, Kontonamen und laufende Dienste mit ins Netz nehmen. Das Zifferblatt
# unten ist gezeichnet, kein Foto, und zeigt nichts als sich selbst.
cat > "$OUT/index.html" <<HTML
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>dynotiq apt repository</title>
<meta name="description" content="System diagnostics and tuning for Ubuntu.">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<style>
:root{
  --bg:#0E1116; --card:#161A20; --raised:#1B2027; --text:#F2F3F5;
  --dim:#9AA1AA; --faint:#767C85; --line:rgba(255,255,255,.09);
  --acc:#F5C242; --acctext:#F5C242; --ok:#2ED27A; --warn:#FF8A3D; --crit:#FF4747;
  --track:rgba(255,255,255,.09);
}
@media (prefers-color-scheme:light){
  :root{
    --bg:#F4F1EC; --card:#FFFDFA; --raised:#F5F2ED; --text:#12161B;
    --dim:#5E656E; --faint:#767C85; --line:rgba(0,0,0,.10);
    --acctext:#AB872E; --ok:#177544; --warn:#9C5800; --crit:#C4362A;
    --track:rgba(0,0,0,.10);
  }
}
*{box-sizing:border-box}
body{
  margin:0; padding:0 20px 80px; background:var(--bg); color:var(--text);
  font:16px/1.65 Arial,"Liberation Sans",Helvetica,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:50rem; margin:0 auto}
header{padding:86px 0 10px; text-align:center}
/* Die Wortmarke aus dem Projekt, nicht nachgesetzt. Zwei Fassungen, die
   Fassung fuer den dunklen Grund traegt helle Schrift. */
.wordmark{width:270px; max-width:78%; height:auto; display:block; margin:0 auto}
.wm-light{display:none}
@media (prefers-color-scheme:light){
  .wm-dark{display:none} .wm-light{display:block}
}
.lede{margin:20px auto 0; max-width:33rem; font-size:18px; color:var(--dim)}
.ver{
  display:inline-block; margin-top:22px; padding:5px 13px; border-radius:999px;
  border:1px solid var(--line); color:var(--faint);
  font:700 12px/1 Arial,"Liberation Sans",sans-serif; letter-spacing:.05em;
}
h2{
  margin:56px 0 6px; font-size:13px; font-weight:700; letter-spacing:.1em;
  text-transform:uppercase; color:var(--acctext);
}
h2+p{margin-top:0; color:var(--dim)}
.card{
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:6px 18px 18px; margin-top:16px;
}
.head{
  display:flex; align-items:center; justify-content:space-between;
  gap:12px; padding:11px 0 9px;
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
.rows{margin-top:16px; display:grid; gap:10px}
.row{
  display:flex; gap:13px; align-items:flex-start;
  background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:14px 16px;
}
.row i{width:3px; align-self:stretch; border-radius:2px; flex:none}
.row b{display:block; font-size:14.5px; margin-bottom:2px}
.row span{color:var(--dim); font-size:14px}
.b-crit{background:var(--crit)} .b-warn{background:var(--warn)}
.b-ok{background:var(--ok)}
footer{
  margin-top:60px; padding-top:24px; border-top:1px solid var(--line);
  color:var(--faint); font-size:14px; text-align:center;
}
a{color:var(--acctext)} a:hover{text-decoration:none}
code{
  font:13px "Liberation Mono","Courier New",monospace;
  background:var(--raised); padding:2px 6px; border-radius:5px;
}
</style>
<div class="wrap">
<header>
  <img class="wordmark wm-dark" src="wordmark-dark.png" alt="dynotiq"
       width="599" height="142">
  <img class="wordmark wm-light" src="wordmark-light.png" alt="dynotiq"
       width="599" height="142">
  <p class="lede">System diagnostics and tuning for Ubuntu. It looks for what
    actually slows the machine down, says what it found in plain words, and
    puts a button next to the things it can fix.</p>
  <div class="ver">VERSION $VER</div>
</header>

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

<h2>What it reports</h2>
<div class="rows">
  <div class="row"><i class="b-crit"></i><div>
    <b>Something is broken</b>
    <span>A graphics driver that is not loaded, a service that failed, GPU
    errors and out-of-memory kills read out of the journal.</span></div></div>
  <div class="row"><i class="b-warn"></i><div>
    <b>Something needs a decision</b>
    <span>A filesystem running full, a journal growing out of hand, thermal
    throttling under load, launchers pointing at programs that are gone.</span>
    </div></div>
  <div class="row"><i class="b-ok"></i><div>
    <b>Nothing to do, but worth knowing</b>
    <span>Pending updates from apt, snap, flatpak and fwupd, and which Proton
    build each installed Steam game is set to.</span></div></div>
</div>
<p>Every finding says which file it came from, and nothing is changed without
  asking first.</p>

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
