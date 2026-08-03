#!/bin/bash
# Zieht po/dynotiq.pot aus dem Quelltext nach und mischt beide Kataloge dagegen.
# Uebersetzungen gehen dabei nicht verloren, neue Texte landen als leere
# Eintraege in po/en.po und muessen dort ausgefuellt werden.
#
# de.po spiegelt nur den Quelltext und entsteht komplett neu aus der Vorlage:
# ohne diese Datei faellt LANGUAGE=de_DE:en auf den englischen Katalog durch.
set -eu
cd "$(dirname "$0")"

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dynotiq.py)
HOLDER="Simon Gettkandt (simonlinuxcraft)"
BUGS="https://github.com/simonlinuxcraft/dynotiq/issues"

# Ohne diese Angaben traegt xgettext seine Vorlagenplatzhalter ein und die
# stehen dann im Repo: SOME DESCRIPTIVE TITLE, FIRST AUTHOR, LL@li.org.
xgettext --language=Python --keyword=_ --keyword=N_ --from-code=UTF-8 \
         --package-name=dynotiq --package-version="$VER" \
         --copyright-holder="$HOLDER" --msgid-bugs-address="$BUGS" \
         -o po/dynotiq.pot dynotiq.py
# xgettext laesst YEAR, FULL NAME und LL@li.org stehen und markiert den Kopf
# als fuzzy. Fuer ein Projekt mit einem Autor ist das nur unfertiger Text.
sed -i "1s|.*|# Translation template for dynotiq.|; \
        2s|.*|# Copyright (C) 2026 $HOLDER|; \
        4s|.*|# $HOLDER, 2026.|; \
        /^#, fuzzy$/d; \
        s|^\"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE|\"PO-Revision-Date: $(date '+%Y-%m-%d %H:%M%z')|; \
        s|^\"Last-Translator: FULL NAME <EMAIL@ADDRESS>|\"Last-Translator: simonlinuxcraft|; \
        s|^\"Language-Team: LANGUAGE <LL@li.org>|\"Language-Team: dynotiq|" po/dynotiq.pot

for lang in de en; do
  po="po/$lang.po"
  if [ "$lang" = de ]; then
    msgen -o "$po.new" po/dynotiq.pot
  else
    msgmerge -q --no-fuzzy-matching -o "$po.new" "$po" po/dynotiq.pot
  fi
  # msgen und msgmerge ersetzen den Kopf durch Vorlagentext. Der alte Kopf
  # traegt Sprache, Uebersetzer und bei de die Plural-Forms, deshalb kommt er
  # zurueck und nur die Zeitstempel wandern mit. Getrennt wird am ersten
  # Absatzende, das ist in einer po-Datei genau die Grenze zwischen Kopf und
  # erstem Eintrag.
  python3 - "$po" "$po.new" po/dynotiq.pot <<'PY'
import re, sys
po, new, pot = sys.argv[1:4]
stamp = re.search(r'POT-Creation-Date: ([^\\]+)', open(pot).read()).group(1)
head = open(po).read().split('\n\n', 1)[0]
for field in ('POT-Creation-Date', 'PO-Revision-Date'):
    head = re.sub(rf'{field}: [^\\]+', f'{field}: {stamp}', head)
open(po, 'w').write(head + '\n\n' + open(new).read().split('\n\n', 1)[1])
PY
  rm -f "$po.new"
  msgfmt --check --statistics "$po" -o "locale/$lang/LC_MESSAGES/dynotiq.mo"
done

n=$(msgattrib --untranslated --no-obsolete po/en.po | grep -c '^msgid "' || true)
[ "$n" -le 1 ] || { echo; echo "$((n - 1)) Texte in po/en.po sind noch leer:"; \
                    msgattrib --untranslated --no-obsolete po/en.po | grep '^msgid "' | tail -n +2; }
