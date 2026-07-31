<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.png">
  <img src="docs/banner-light.png" width="410" alt="Dynolab">
</picture>

**System diagnostics and tuning for Ubuntu**

One GTK4 application that finds what slows a machine down, explains every
finding in plain language and offers the matching fix.
Nothing runs without asking first.

</div>

![Overview](docs/overview.png)

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

**App check** takes an installed application apart: unresolved libraries,
disconnected Snap interfaces, missing Flatpak permissions, kernel-denied
access, crashes, journal errors. Where a fix exists, there is a button.

**Dyno** records temperature and clock over minutes under real load and answers
what a snapshot cannot: at which point does it start throttling.

**Benchmark** measures CPU, memory and disk against the median of your own
earlier runs. A number without a baseline says nothing.

Plus a live monitor, storage analysis with cleanup, autostart control including
slow boot services, and a history of every scan.

<p align="center">
  <img src="docs/updates.png" width="49%" alt="Updates">
  <img src="docs/welcome.png" width="33%" alt="Welcome">
</p>

## Install

    ./build-deb.sh
    sudo dpkg -i build/dynolab_0.1_all.deb

Or run it from the source tree without installing:

    python3 dynolab.py

## Requirements

Ubuntu 24.04 or newer with `python3-gi`, `python3-gi-cairo` and
`gir1.2-gtk-4.0`. Recommended: `librsvg2-bin` for tray icons, `pkexec` to apply
fixes, `fonts-inter` for the interface font.

## Command line

| Option | Effect |
| --- | --- |
| `dynolab` | open the window |
| `dynolab --page Updates` | open on a specific page |
| `dynolab --watch` | background service, reports new incidents |
| `dynolab --install` | place icons and a launcher for the current user |
| `dynolab --selftest` | run the built-in checks |

## Licence

GPL-3.0-or-later. Copyright 2026 simonlinuxcraft.
