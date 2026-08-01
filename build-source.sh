#!/bin/bash
# Baut signierte Quellpakete fuer das PPA, eines je Ubuntu-Serie, und zeigt die
# dput-Zeilen. Hochgeladen wird bewusst nicht, das bleibt ein eigener Schritt.
#
# Einmalig noetig, siehe README:
#   sudo apt install devscripts dput debhelper gettext
#   GPG-Schluessel anlegen und auf launchpad.net hinterlegen
#   Ubuntu Code of Conduct signieren, dann das PPA anlegen
#
# KEY ueberschreibt den Signierschluessel, REV die Paketrevision:
#   KEY=A1B2C3D4 REV=2 ./build-source.sh
set -eu
cd "$(dirname "$0")"

PPA="${PPA:-ppa:simonlinuxcraft/dynotiq}"
SERIES="${SERIES:-noble resolute}"
# Eine hochgeladene Versionsnummer ist bei Launchpad fuer immer verbraucht, auch
# nach einem fehlgeschlagenen Bau. Beim naechsten Anlauf REV hochzaehlen.
REV="${REV:-1}"
# Fest verdrahtet, weil die UID des Schluessels ("Simon (Dynolab)", noch aus
# der Zeit vor der Umbenennung) nicht zum Namen im changelog passt und debuild
# ihn sonst nicht findet.
KEY="${KEY:-9D421A82D67E1656}"
# dch nimmt sonst irgendwas aus der Systemumgebung und setzt eine fremde
# Adresse in den changelog-Eintrag. Muss zum GPG-Schluessel passen.
export DEBEMAIL="${DEBEMAIL:-simonlinuxcraft@pm.me}"
export DEBFULLNAME="${DEBFULLNAME:-simonlinuxcraft}"

for t in debuild dpkg-parsechangelog msgfmt ubuntu-distro-info; do
  command -v "$t" > /dev/null || { echo "$t fehlt, siehe Kopf dieser Datei"; exit 1; }
done
gpg --list-secret-keys > /dev/null 2>&1 || { echo "kein GPG-Schluessel"; exit 1; }

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dynotiq.py)
[ -n "$VER" ] || { echo "Version nicht gefunden"; exit 1; }
DEB_VER=$(dpkg-parsechangelog -S Version)
case "$DEB_VER" in
  "$VER"|"$VER"~*) ;;
  *) echo "debian/changelog steht auf $DEB_VER, dynotiq.py auf $VER"; exit 1 ;;
esac

# Die Serienkennung im Versionsstring muss aufsteigend sortieren, sonst gilt
# das Paket der neueren Ubuntu-Fassung als aelter und apt aktualisiert nie.
# Serienname taugt dafuer nicht, die Namen laufen alphabetisch im Kreis.
suffix() {
  local v
  v=$(ubuntu-distro-info --series="$1" -r 2>/dev/null | cut -d' ' -f1)
  [ -n "$v" ] || { echo "Serie $1 unbekannt" >&2; exit 1; }
  echo "${VER}~ubuntu${v}.${REV}"
}

python3 dynotiq.py --selftest

rm -rf build/ppa
mkdir -p build/ppa
for s in $SERIES; do
  # Verzeichnisname landet als Praefix im Quell-Tarball, deshalb die uebliche
  # Form paket-version und nicht der Serienname.
  work="build/ppa/dynotiq-$(suffix "$s")"
  mkdir -p "$work"
  # Ein Quellbaum je Serie, weil Launchpad je Serie eine eigene Version braucht.
  # Ein natives Quellpaket nimmt alles mit, deshalb fliegt raus was nicht zum
  # Bau gehoert: Arbeitsdateien, Entwuerfe, das Ergebnis vorheriger Laeufe.
  tar --exclude=./build --exclude=./locale --exclude=./.git \
      --exclude='./__pycache__' --exclude='./dynotiq Logo Icon Design' \
      --exclude='./Pruefstand-Dashboard.html' \
      -cf - . | (cd "$work" && tar -xf -)
  ( cd "$work"
    dch --newversion "$(suffix "$s")" --distribution "$s" --force-bad-version \
        "Build for $s." > /dev/null
    # debuild legt .dsc und .changes eine Ebene ueber dem Quellbaum ab.
    if [ -n "$KEY" ]; then debuild -S -sa "-k$KEY"; else debuild -S -sa; fi )
done

echo
echo "Fertig. Hochladen mit:"
for s in $SERIES; do
  echo "  dput $PPA build/ppa/dynotiq_$(suffix "$s")_source.changes"
done
