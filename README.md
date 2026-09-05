<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="icons/wordmark/png/dynotiq-wordmark-dark-w1200.png">
  <img src="icons/wordmark/png/dynotiq-wordmark-light-w1200.png" width="380" alt="dynotiq">
</picture>

**System diagnostics and tuning for Ubuntu**

One GTK4 application that finds what slows a machine down, explains every
finding in plain language and offers the matching fix.
Nothing runs without asking first.

[**Download the latest release**](https://github.com/simonlinuxcraft/dynotiq/releases/latest)

[![selftest](https://github.com/simonlinuxcraft/dynotiq/actions/workflows/selftest.yml/badge.svg)](https://github.com/simonlinuxcraft/dynotiq/actions/workflows/selftest.yml)
[![licence: GPL-3.0-or-later](https://img.shields.io/badge/licence-GPL--3.0--or--later-blue.svg)](LICENSE)

</div>


## What it does

It scans the machine, explains each finding in plain language, and where it can
act, the finding carries the button that does it. Fourteen pages. Three of them
are the reason the rest exists.

**Proton.** A Windows game that stopped starting is the hardest thing on this
list to work out. Every Proton version from 5.13 on runs inside a container
Steam downloads separately, and when that container is missing or damaged, no
game on that version starts while Steam says nothing beyond "exited
unexpectedly". The page reads Steam's own files, names the cause and carries
the fix: fetch the runtime again, take out an assignment that breaks it, move a
version into the folder Steam actually reads, or switch a title to a Proton
version its Windows store fits. The same page covers the rest of what Proton
leans on: ntsync, Resizable BAR, the file descriptor limit, MangoHud. Shader
caches and prefixes left behind by games uninstalled long ago come up in the
system check.

**Incidents.** Audio dropouts, GPU driver errors, out-of-memory kills and
failed units, read out of the journal. Each one carries the temperature, clock
and load from the moment it happened, which is usually the part that turns an
error message into an explanation.

**Dyno.** Records temperature, clock and waiting times over minutes under real
load. It answers when the machine starts throttling, and whether it ever stood
still waiting for a free core, for memory or for the disk. Stutter without heat
is invisible in a temperature curve.

The other eleven pages are the ordinary work: pending updates from apt, Snap,
Flatpak and firmware in one list with sizes and an optional snapshot
beforehand, an app inspector that says where a program updates from and what it
occupies, drivers, a live monitor, storage with cleanup, a benchmark against
your own earlier runs, autostart including slow boot services, the history of
every scan, and settings.

## Ubuntu for now

dynotiq is built and tested on Ubuntu 24.04 and newer. It leans on apt, dpkg,
snap and Ubuntu specifics such as the HWE kernel stack and `do-release-upgrade`,
so on other distributions parts of it will report nothing useful. Support for
further distributions is planned.

## How it is built

One Python file, GTK4 through the GObject bindings, the standard library, and
nothing else. No framework, no package from pip, no build step. What it knows
it reads from the machine itself: `/proc`, `/sys`, apt, snap, flatpak, systemd,
fwupd and Steam's own files.

It carries 707 assertions in a built-in selftest that needs no display and no
network. CI runs it on every push in both languages, then builds the package
and checks the catalogues against the source, because a test that only passes
in German is half a test.

    python3 dynotiq.py --selftest

It is written with AI assistance. That is worth saying outright rather than
leaving to be guessed at. What it does not mean: nothing goes in unread or
untested. Every fix the app offers has been triggered on a real machine before
release, the selftest is the floor and not the ceiling, and everything that
touches the system with root rights is written out in
[SECURITY.md](SECURITY.md), line by line. If something in here reads as
generated and wrong, that is a bug, and the issue tracker is the right place
for it.

## Install

From the apt repository, which also keeps it updated:

    curl -fsSL https://simonlinuxcraft.github.io/dynotiq/dynotiq.gpg | sudo tee /usr/share/keyrings/dynotiq.gpg > /dev/null
    printf 'Types: deb\nURIs: https://simonlinuxcraft.github.io/dynotiq\nSuites: ./\nSigned-By: /usr/share/keyrings/dynotiq.gpg\n' | sudo tee /etc/apt/sources.list.d/dynotiq.sources > /dev/null
    sudo apt update
    sudo apt install dynotiq

Or download the `.deb` from the
[latest release](https://github.com/simonlinuxcraft/dynotiq/releases/latest)
and install it directly. The package carries the repository and its key, so
updates arrive through apt either way. GitHub replaces the tilde in the version
with a dot in the attachment name, the package itself is unaffected:

    sudo dpkg -i dynotiq_0.4.beta_all.deb

Build the package yourself:

    ./build-deb.sh
    sudo dpkg -i build/dynotiq_0.4~beta_all.deb

Or run it from the source tree without installing:

    python3 dynotiq.py

## Updates

The package carries its own apt source and signing key, so updates arrive
through `apt upgrade` like for any other package, however it was installed. The
system check also reports a new version on its own, with a button that runs the
apt install after asking for your password. Nothing is downloaded or installed
without that click. Remove the source and the check says so, with the commands
to put it back.

The repository is served from GitHub Pages and holds binary packages only. It
is flat, one package for every Ubuntu release, because dynotiq is
`Architecture: all` and pure Python.

To publish a new version, bump `VERSION` in `dynotiq.py` and `debian/changelog`
to the same number, then:

    ./build-repo.sh      # builds the .deb, indexes and signs the repository
    ./publish-repo.sh    # pushes build/repo to the gh-pages branch

The `dpkg -i` line under Install names the file attached to the release, so it
is bumped once that release exists, not before. Bumped earlier it points at a
download nobody can fetch.

`build-repo.sh` never publishes, that stays a separate step. It needs
`dpkg-dev`, `apt-utils` and `gettext`, plus the GPG key the repository is
signed with. `publish-repo.sh` replaces the `gh-pages` branch outright; it
carries build artefacts only, the sources live in `main`.

Versions carry the Ubuntu release rather than the series name, so
`0.4~beta~ubuntu24.04.1` sorts below `0.4~beta~ubuntu26.04.1`. Series names
cycle back through the alphabet, which would eventually make a newer Ubuntu look
older to apt. A tilde sorts below everything, which is what makes `0.4~beta`
an upgrade from `0.3` and still a downgrade from the final `0.4`. Git refuses a
tilde in tag names, so the matching tag is written `v0.4-beta`.

## Requirements

`python3-gi`, `python3-gi-cairo` and `gir1.2-gtk-4.0`. Recommended:
`librsvg2-bin` for tray icons, `pkexec` to apply fixes, `fonts-liberation` for
the interface font. The interface asks for Arial first and falls back to
Liberation Sans, which has the same metrics, so the layout does not shift.

## Languages

German and English. The interface follows your desktop language and falls back
to German. To force one:

    LANGUAGE=en dynotiq

Catalogues live in `po/`, `build-deb.sh` compiles them into the package.

## Command line

| Option | Effect |
| --- | --- |
| `dynotiq` | open the window |
| `dynotiq --page Updates` | open on a specific page |
| `dynotiq --watch` | background service, reports new incidents |
| `dynotiq --install` | place icons and a launcher for the current user |
| `dynotiq --selftest` | run the built-in checks |
| `dynotiq --version` | print the version and exit |

## Contributing

Pull requests are welcome. A few things make them easy to merge:

- **Open an issue first** for anything larger than a fix. It saves you from
  building something that does not fit, and it saves me from turning it down
  after the fact.
- **The selftest has to pass.** `python3 dynotiq.py --selftest` runs the whole
  suite in a few seconds, and CI runs it on every push. Logic that can break
  brings its own assertion along.
- **Match the surrounding code.** One file, plain GTK4, no new dependencies
  without a reason. Comments explain why, not what.
- **User-visible strings are translatable.** Wrap them in `_()`, then run
  `./update-po.sh` and fill in the English catalogue.

Bug reports and ideas are just as welcome as code. If you send a patch, you
send it under the same licence as the rest of the project.

## Licence

Copyright (C) 2026 Simon Gettkandt (simonlinuxcraft)

dynotiq is free software under the **GNU General Public License, version 3 or
later**. You may use, study, share and modify it, and the same freedoms travel
with every copy you pass on. The full text is in [LICENSE](LICENSE).

It comes with no warranty, to the extent permitted by law.
