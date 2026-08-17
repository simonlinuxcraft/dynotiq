#!/bin/bash
# Schiebt build/repo in den Branch gh-pages, aus dem GitHub Pages ausliefert.
#
# Der Branch traegt nur Artefakte, keine Quellen. Deshalb wird er jedes Mal neu
# angelegt und mit --force gesetzt: eine Historie aus alten Paketindizes waere
# nur Ballast, und der Quellstand liegt ohnehin in main.
#
# Einmalig noetig: im GitHub-Repo unter Settings > Pages die Quelle auf den
# Branch gh-pages stellen, Ordner /.
set -eu
cd "$(dirname "$0")"

OUT="build/repo"
[ -f "$OUT/InRelease" ] || { echo "$OUT fehlt oder ist unsigniert, erst ./build-repo.sh"; exit 1; }

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dynotiq.py)
REMOTE=$(git remote get-url origin)

# Die Adresse landet in einem oeffentlichen Branch. Sie kommt aus git config,
# und die Repo-Einstellung, die hier die Noreply-Adresse setzt, liegt in
# .git/config und wird nicht mitversioniert: auf einem frischen Klon gilt wieder
# die globale. Deshalb lieber abbrechen als die private Adresse pushen.
MAIL=$(git config user.email)
case "$MAIL" in
  *@users.noreply.github.com|*@pm.me) ;;
  *) echo "user.email ist $MAIL, das geht in einen oeffentlichen Branch."
     echo "Setzen mit: git config user.email 245174420+simonlinuxcraft@users.noreply.github.com"
     exit 1 ;;
esac

# Eigenes Repo im Wegwerfverzeichnis statt worktree: kein Zustand, der im
# Hauptbaum haengen bleibt, wenn das Skript zwischendrin abbricht.
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -r "$OUT/." "$TMP/"
# Ohne diese Datei laesst Pages Verzeichnisse mit Unterstrich weg und faehrt
# den Inhalt durch Jekyll. Hier soll nichts umgeschrieben werden.
touch "$TMP/.nojekyll"

git -C "$TMP" init -q -b gh-pages
git -C "$TMP" add -A
git -C "$TMP" -c user.name="$(git config user.name)" \
              -c user.email="$(git config user.email)" \
              commit -qm "dynotiq $VER"
git -C "$TMP" push -q --force "$REMOTE" gh-pages

echo "gh-pages gesetzt, dynotiq $VER"
echo "Sichtbar unter https://simonlinuxcraft.github.io/dynotiq/ (Pages braucht einen Moment)"
