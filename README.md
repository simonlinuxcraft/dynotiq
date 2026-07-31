# Dynolab

System diagnostics and tuning for Ubuntu. A single GTK4 application that finds
what slows a machine down, explains each finding in plain language and offers
the matching fix.

![Overview](icons/png/dynolab-512.png)

## What it does

**System check.** Scans for outdated graphics drivers, thermal throttling, full
filesystems, a growing journal, failed units, stale autostart entries and
pending updates. Every finding comes with the reason and the command that fixes
it. Nothing runs without asking first.

**Incidents.** Reads the journal for audio dropouts, GPU driver errors,
out-of-memory kills and failed systemd units, and records the temperature,
clock and load at that moment, so a bare error message becomes a connection.

**Updates.** apt, Snap, Flatpak and firmware in one place, with download sizes,
per-source selection, a live log and a Timeshift snapshot beforehand if wanted.
After the run it verifies which entries actually went through.

**App check.** Takes an installed application apart: unresolved libraries,
disconnected Snap interfaces, missing Flatpak permissions, kernel-denied
access, crashes and journal errors. Where a fix exists, there is a button.

**Dyno.** Records temperature and clock over minutes under real load and
answers the question a snapshot cannot: at which point does it start throttling.

**Benchmark.** CPU, memory and disk, compared against the median of your own
earlier runs. A number without a baseline says nothing.

Plus a live monitor, storage analysis with cleanup, autostart control including
slow boot services, and a history of every scan.

## Install

Build the Debian package and install it:

    ./build-deb.sh
    sudo dpkg -i build/dynolab_0.1_all.deb

Or run it straight from the source tree:

    python3 dynolab.py

## Requirements

python3, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0. Recommended:
librsvg2-bin for tray icons, pkexec to apply fixes, fonts-inter for the
interface font. Ubuntu 24.04 or newer.

## Options

    dynolab                 start the window
    dynolab --page Updates  start on a specific page
    dynolab --watch         background service, reports new incidents
    dynolab --install       place icons and a launcher for the current user
    dynolab --selftest      run the built-in checks

## Licence

GPL-3.0-or-later. Copyright 2026 simonlinuxcraft.
