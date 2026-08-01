<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="icons/wordmark/png/dynotiq-wordmark-dark-w1200.png">
  <img src="icons/wordmark/png/dynotiq-wordmark-light-w1200.png" width="380" alt="dynotiq">
</picture>

**System diagnostics and tuning for Ubuntu**

One GTK4 application that finds what slows a machine down, explains every
finding in plain language and offers the matching fix.
Nothing runs without asking first.

[**Download v0.1 Beta**](https://github.com/simonlinuxcraft/dynotiq/releases/tag/v0.1)

</div>


## What it does

**System check** scans for outdated graphics drivers, thermal throttling, full
filesystems, a growing journal, failed units, stale autostart entries and
pending updates. Every finding says what is wrong, why it matters and what to
do about it.

**Incidents** reads the journal for audio dropouts, GPU driver errors,
out-of-memory kills and failed systemd units. Each entry records temperature,
clock and load at that moment, so a bare error message turns into a connection.

**Updates** brings apt, Snap, Flatpak and firmware together, with download
sizes, per-entry selection, a live log and an optional Timeshift snapshot
beforehand. Afterwards it verifies which entries actually went through.

**App check** takes an installed application apart: where its updates come
from, how much it occupies in your home directory and how much of that is pure
cache, unresolved libraries, disconnected Snap interfaces, missing Flatpak
permissions, crashes, journal errors. Technical terms get translated, so
`audio-record` reads as microphone. Where a fix exists, there is a button.


**Dyno** records temperature and clock over minutes under real load and answers
what a snapshot cannot: at which point does it start throttling.

**Benchmark** measures CPU, memory and disk against the median of your own
earlier runs. A number without a baseline says nothing.

Plus a live monitor, storage analysis with cleanup, autostart control including
slow boot services, and a history of every scan.

## Ubuntu for now

dynotiq is built and tested on Ubuntu 24.04 and newer. It leans on apt, dpkg,
snap and Ubuntu specifics such as the HWE kernel stack and `do-release-upgrade`,
so on other distributions parts of it will report nothing useful. Support for
further distributions is planned.

## Install

Download `dynotiq_0.1_all.deb` from the
[v0.1 Beta release](https://github.com/simonlinuxcraft/dynotiq/releases/tag/v0.1)
and install it:

    sudo dpkg -i dynotiq_0.1_all.deb

From the PPA once a version is published there, which also keeps it updated
through apt:

    sudo add-apt-repository ppa:simonlinuxcraft/dynotiq
    sudo apt install dynotiq

Build the package yourself:

    ./build-deb.sh
    sudo dpkg -i build/dynotiq_0.1_all.deb

Or run it from the source tree without installing:

    python3 dynotiq.py

## Updates

Installed from a `.deb` by hand, dynotiq gets no updates and says so in the
system check. Installed from the PPA, it updates through apt like any other
package. The system check also reports a new version on its own, with a button
that runs the apt install after asking for your password. Nothing is downloaded
or installed without that click.

To publish a new version to the PPA, bump `VERSION` in `dynotiq.py` and
`debian/changelog` to the same number, then:

    ./build-source.sh
    dput ppa:simonlinuxcraft/dynotiq build/ppa/dynotiq_0.1~ubuntu24.04.1_source.changes

`build-source.sh` prints the exact upload lines when it finishes. It builds and
signs one source package per Ubuntu series, it never uploads. It needs
`devscripts`, `dput`, `debhelper` and `gettext`, plus a GPG key registered on
Launchpad.

Versions carry the Ubuntu release rather than the series name, so
`0.1~ubuntu24.04.1` sorts below `0.1~ubuntu26.04.1`. Series names cycle back
through the alphabet, which would eventually make a newer Ubuntu look older to
apt.

## Requirements

`python3-gi`, `python3-gi-cairo` and `gir1.2-gtk-4.0`. Recommended:
`librsvg2-bin` for tray icons, `pkexec` to apply fixes, `fonts-inter` for the
interface font.

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

## Licence

GPL-3.0-or-later. Copyright 2026 simonlinuxcraft.
