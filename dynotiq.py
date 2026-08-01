#!/usr/bin/env python3
"""dynotiq - Systemdiagnose und Optimierung für Ubuntu.

Copyright 2026 simonlinuxcraft

Dieses Programm ist freie Software: Sie können es unter den Bedingungen
der GNU General Public License, Version 3 oder später, weitergeben und
verändern. Der Lizenztext liegt der Datei als LICENSE bei.
"""

import fcntl
import gettext
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

VERSION = "0.1"
APP_ID = "de.dynotiq.dynotiq"
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Die Texte im Quelltext sind deutsch, der Katalog uebersetzt sie bei Bedarf.
# Ohne passenden Katalog bleibt es beim deutschen Original.
LOCALE_DIRS = [os.path.join(APP_DIR, "locale"), "/usr/share/locale",
               os.path.expanduser("~/.local/share/locale")]
_ = gettext.translation("dynotiq", next((d for d in LOCALE_DIRS
                                         if os.path.isdir(d)), None),
                        fallback=True).gettext


def N_(text):
    """Nur für den Katalog markieren, nicht übersetzen.

    Für Texte, die als Schlüssel weiterleben: Vorfallstitel landen in
    incidents.jsonl und in classify(), Seitennamen in Dicts. Die bleiben
    deutsch, übersetzt wird erst bei der Anzeige mit _().
    """
    return text


CONFIG_DIR = os.path.expanduser("~/.config/dynotiq")
DATA_DIR = os.path.expanduser("~/.local/share/dynotiq")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")
INCIDENTS_FILE = os.path.join(DATA_DIR, "incidents.jsonl")
WATCH_UNIT = os.path.expanduser("~/.config/systemd/user/dynotiq-watch.service")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
HICOLOR = os.path.expanduser("~/.local/share/icons/hicolor")
DESKTOP_FILE = os.path.expanduser("~/.local/share/applications/dynotiq.desktop")
TRAY_ICON_DIR = os.path.join(DATA_DIR, "icons")
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
SIDEBAR_WIDTH = 208
# Updates laufen ueber apt aus dieser Quelle, nicht ueber einen eigenen Downloader.
PPA = "ppa:simonlinuxcraft/dynotiq"

# Aus dem Logo: Ink als Basis, Gelb als Marke. Warn liegt bewusst im Orange,
# sonst wäre es vom Akzent nicht zu unterscheiden.
INK = "#12161B"
ACCENTS = ["#F5C242", "#E95420", "#58C6E8", "#A78BFA"]
PALETTES = {
    "Ampel": {"ok": "#2ED27A", "warn": "#FF8A3D", "crit": "#FF4747"},
    "Warm": {"ok": "#9BD44F", "warn": "#FF9F1C", "crit": "#FF4D3D"},
    "Mono": {"ok": "#9EA4AC", "warn": "#D8DDE3", "crit": "#FFFFFF"},
}
DEFAULTS = {"accent": ACCENTS[0], "palette": "Ampel", "interval": 2, "tray": True,
            "firmware": True, "snapshot": False}

# Von build_css und den Cairo-Widgets gelesen, wechselt mit der Einstellung.
COLORS = {"acc": ACCENTS[0], **PALETTES["Ampel"]}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if cfg["accent"] not in ACCENTS:
        cfg["accent"] = DEFAULTS["accent"]
    if cfg["palette"] not in PALETTES:
        cfg["palette"] = DEFAULTS["palette"]
    return cfg


def save_config(cfg):
    """Erst in eine Nebendatei, dann umbenennen. Sonst steht bei voller Platte
    eine leere config.json da und alle Einstellungen sind beim Start zurück."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_FILE)
    except OSError as e:
        print(f"Einstellungen nicht speicherbar: {e}", file=sys.stderr)


def apply_colors(cfg):
    COLORS.update(PALETTES[cfg["palette"]])
    COLORS["acc"] = cfg["accent"]
    if cfg["palette"] == "Mono":
        COLORS["warn"] = cfg["accent"]


HISTORY_MAX = 4000
BENCH_KEYS = ("cpu1", "cpun", "ram", "disk")


def median(values):
    v = sorted(values)
    if not v:
        return 0.0
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def bench_baseline(runs, key, ignore_last=True):
    """Mittelwert früherer Läufe. Median statt Durchschnitt, damit ein einzelner
    Ausreißer (Rechner gerade unter Last) die Basislinie nicht verschiebt."""
    vals = [r[key] for r in runs if r.get(key)]
    if ignore_last:
        vals = vals[:-1]
    return median(vals[-8:])


def bench_drop(runs, key, tolerance=0.2):
    """Abweichung des letzten Laufs zur Basislinie, negativ heißt langsamer.
    None, wenn es zu wenig Läufe gibt oder alles im Rahmen liegt."""
    vals = [r[key] for r in runs if r.get(key)]
    if len(vals) < 4:
        return None
    base = bench_baseline(runs, key)
    if not base:
        return None
    delta = (vals[-1] - base) / base
    return delta if abs(delta) >= tolerance else None


def history_append(entry):
    """Schreibt einen Verlaufseintrag. Fehler dürfen den Aufrufer nicht killen,
    sonst hängt die Oberfläche bei voller Platte für immer im Ladezustand."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if os.path.getsize(HISTORY_FILE) > HISTORY_MAX * 200:
            lines = open(HISTORY_FILE).readlines()[-HISTORY_MAX:]
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w") as f:
                f.writelines(lines)
            os.replace(tmp, HISTORY_FILE)
    except OSError as e:
        print(f"Verlauf nicht schreibbar: {e}", file=sys.stderr)


def ensure_icons():
    """Legt Icons dort ab, wo Shell, Dock und Tray sie ohne Root finden.

    App-Icon ist die deckende Kachel, sonst verschwindet der Ink-Bogen auf
    dunklen Panels. Für den Tray die einfarbige Variante, so wie im Icon-README.
    """
    icon = os.path.join(APP_DIR, "icons", "app-icon")
    png, svg = os.path.join(icon, "png"), os.path.join(icon, "svg")
    jobs = [(f"{png}/dynotiq-app-dark-{s}.png", f"{HICOLOR}/{s}x{s}/apps/dynotiq.png")
            for s in ICON_SIZES]
    jobs.append((f"{svg}/dynotiq-app-dark.svg", f"{HICOLOR}/scalable/apps/dynotiq.svg"))
    mono = f"{svg}/dynotiq-icon-mono-white.svg"
    jobs.append((mono, f"{HICOLOR}/scalable/apps/dynotiq-tray.svg"))
    jobs.append((mono, f"{TRAY_ICON_DIR}/dynotiq-tray.svg"))
    jobs.append((f"{png}/dynotiq-app-dark-256.png", f"{TRAY_ICON_DIR}/dynotiq.png"))
    changed = False
    for src, dst in jobs:
        if not os.path.exists(src):
            continue
        if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        changed = True
    # Die Shell nimmt für die Leiste lieber Raster, sonst bleibt der Platz leer.
    for size in (16, 22, 24, 32, 48):
        dst = f"{HICOLOR}/{size}x{size}/apps/dynotiq-tray.png"
        if os.path.exists(mono) and not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if sh(["rsvg-convert", "-w", str(size), "-h", str(size), "-o", dst, mono]) == "" \
                    and not os.path.exists(dst):
                continue
            changed = True
    if changed:
        sh(["gtk-update-icon-cache", "-f", "-t", HICOLOR], timeout=20)
    return changed


def ensure_desktop():
    """StartupWMClass muss zur WM_CLASS passen, sonst bleibt das Dock-Icon generisch.

    Aus einem Systempfad gestartet gehört der Starter zum Paket. Ein zweiter im
    Home würde ihn überdecken und nach dem Deinstallieren liegenbleiben.
    """
    if APP_DIR.startswith(("/usr/", "/opt/")):
        return False
    entry = ("[Desktop Entry]\n"
             "Type=Application\n"
             "Name=dynotiq\n"
             "Comment=Systemdiagnose und Optimierung\n"
             f"Exec={sys.executable} {os.path.join(APP_DIR, 'dynotiq.py')}\n"
             "Icon=dynotiq\n"
             "Terminal=false\n"
             "Categories=System;Settings;Monitor;\n"
             "StartupNotify=true\n"
             "StartupWMClass=dynotiq\n")
    if read(DESKTOP_FILE) == entry.strip():
        return False
    os.makedirs(os.path.dirname(DESKTOP_FILE), exist_ok=True)
    with open(DESKTOP_FILE, "w") as f:
        f.write(entry)
    sh(["update-desktop-database", os.path.dirname(DESKTOP_FILE)], timeout=20)
    return True


def history_read(limit=200, kind=None):
    """Die letzten Einträge, optional nur einer Sorte. Ohne den kind-Filter vor
    dem Abschneiden verschwindet ein alter Benchmark hinter 200 Scans."""
    out = []
    try:
        with open(HISTORY_FILE) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if kind is None or e.get("kind") == kind:
                    out.append(e)
    except OSError:
        return []
    return out[-limit:]


# Datenquellen

def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def sh_rc(args, timeout=15):
    """(rc, stdout). rc None heißt: gar nicht gelaufen, also fehlt das Programm
    oder es lief in den Timeout. Wer zwischen leer und kaputt unterscheiden
    muss, nimmt das hier statt sh()."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL,
                           env={**os.environ, "LC_ALL": "C"})
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ""


def sh(args, timeout=15):
    rc, out = sh_rc(args, timeout)
    return out if rc == 0 else ""


def cpu_times(per_core=False):
    out = []
    for line in open("/proc/stat"):
        if not line.startswith("cpu"):
            break
        vals = [int(x) for x in line.split()[1:]]
        out.append((sum(vals), vals[3] + vals[4]))
    return out if per_core else out[0]


def busy_percent(prev, now):
    dt, di = now[0] - prev[0], now[1] - prev[1]
    return 100.0 * (dt - di) / dt if dt > 0 else 0.0


def meminfo():
    d = {}
    for line in open("/proc/meminfo"):
        k, _, v = line.partition(":")
        d[k] = int(v.split()[0])
    return d["MemTotal"] / 1048576, d["MemAvailable"] / 1048576


def swapinfo():
    d = {}
    for line in open("/proc/meminfo"):
        k, _, v = line.partition(":")
        d[k] = int(v.split()[0])
    return d.get("SwapTotal", 0) / 1048576, d.get("SwapFree", 0) / 1048576


def hwmon_temp(chips, labels=None):
    for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if read(f"{d}/name") not in chips:
            continue
        for inp in sorted(glob.glob(f"{d}/temp*_input")):
            if labels and (read(inp.replace("_input", "_label")) or "") not in labels:
                continue
            v = read(inp)
            if v:
                return int(v) / 1000
    return None


def cpu_temp():
    return (hwmon_temp({"k10temp", "zenpower"}, {"Tctl", "Tdie"})
            or hwmon_temp({"coretemp"}, {"Package id 0"})
            or hwmon_temp({"k10temp", "coretemp", "acpitz"}))


def nvme_temp():
    return hwmon_temp({"nvme"}, {"Composite"}) or hwmon_temp({"nvme"})


# NVML-Bits, die echtes Throttling bedeuten (Power-Cap, HW-Slowdown, thermisch).
THROTTLE_MASK = 0x4 | 0x8 | 0x20 | 0x40 | 0x80


def gpu():
    out = sh(["nvidia-smi", "--format=csv,noheader,nounits",
              "--query-gpu=name,driver_version,utilization.gpu,clocks.sm,temperature.gpu,"
              "memory.used,memory.total,power.draw"])
    if out.strip():
        f = [x.strip() for x in out.strip().splitlines()[0].split(",")]
        g = {"vendor": "nvidia", "name": f[0], "driver": f[1], "util": _f(f[2]),
             "clock": _f(f[3]), "temp": _f(f[4]), "mem_used": _f(f[5]),
             "mem_total": _f(f[6]), "power": _f(f[7])}
        for q in ("clocks_event_reasons.active", "clocks_throttle_reasons.active"):
            r = sh(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader"]).strip()
            # Nicht jede Karte liefert die Bits, dann steht dort [N/A] statt 0x...
            if r.startswith("0x"):
                g["throttled"] = bool(int(r.splitlines()[0], 16) & THROTTLE_MASK)
                break
        return g
    for card in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        dev = os.path.dirname(card)
        return {"vendor": "amd", "name": "AMD GPU", "driver": "amdgpu",
                "util": _f(read(card)), "clock": _amd_clock(dev),
                "temp": hwmon_temp({"amdgpu"}, {"edge"}) or 0.0,
                "mem_used": 0.0, "mem_total": 0.0, "power": 0.0}
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _amd_clock(dev):
    for line in (read(f"{dev}/pp_dpm_sclk") or "").splitlines():
        if line.endswith("*"):
            m = re.search(r"(\d+)\s*Mhz", line, re.I)
            if m:
                return float(m.group(1))
    return 0.0


def cpu_model():
    for line in open("/proc/cpuinfo"):
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "Unbekannte CPU"


def parse_lspci(text):
    devs = []
    for block in filter(str.strip, re.split(r"\n(?=\S)", text.strip())):
        head, *rest = block.splitlines()
        m = re.match(r"(\S+) ([^:]+): (.+?)(?: \(rev [^)]+\))?$", head)
        if not m:
            continue
        d = {"slot": m.group(1), "class": m.group(2), "name": m.group(3),
             "driver": None, "modules": []}
        for line in rest:
            line = line.strip()
            if line.startswith("Kernel driver in use:"):
                d["driver"] = line.split(":", 1)[1].strip()
            elif line.startswith("Kernel modules:"):
                d["modules"] = [x.strip() for x in line.split(":", 1)[1].split(",")]
        devs.append(d)
    return devs


DEVICE_CLASSES = ("VGA compatible controller", "3D controller", "Display controller",
                  "Audio device", "Ethernet controller", "Network controller",
                  "Non-Volatile memory controller", "SATA controller",
                  "USB controller", "Multimedia audio controller")


def devices():
    return [d for d in parse_lspci(sh(["lspci", "-k"])) if d["class"] in DEVICE_CLASSES]


def parse_desktop(text):
    d = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
            continue
        if section != "[Desktop Entry]" or "=" not in line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        d[k.strip()] = v.strip()
    return d


def parse_blame(text):
    """systemd-analyze blame: '11h 26min 16.414s foo.service'. Ohne Stunden- und
    Minutenteil fällt genau die langsamste Unit aus der Liste."""
    units = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:(\d+)h\s+)?(?:(\d+)min\s+)?([\d.]+)(m?s)\s+(\S+)", line)
        if m:
            secs = (3600 * int(m.group(1) or 0) + 60 * int(m.group(2) or 0)
                    + float(m.group(3)) / (1000 if m.group(4) == "ms" else 1))
            units.append((secs, m.group(5)))
    return sorted(units, reverse=True)


def unit_scope(unit):
    """('--user',) wenn es eine Nutzer-Unit ist, sonst () für die Systemebene."""
    if sh(["systemctl", "--user", "cat", unit], timeout=20).strip():
        return ("--user",)
    return ()


def unit_info(unit, scope=()):
    """Beschreibung und was sonst noch von der Unit abhängt."""
    args = ["systemctl", *scope]
    desc = sh(args + ["show", "-p", "Description", "--value", unit], timeout=20).strip()
    needed = [line.strip() for line in
              sh(args + ["list-dependencies", "--reverse", "--plain", "--no-pager",
                         unit], timeout=30).splitlines()[1:] if line.strip()]
    return desc, sorted(set(needed))[:8]


def unit_disable_cmd(unit, scope=()):
    """Abschaltbefehl. Nutzer-Units brauchen kein root, Systemdienste schon."""
    if scope:
        return ["systemctl", "--user", "disable", "--now", unit]
    return ["pkexec", "systemctl", "disable", "--now", unit]


def autostart_entries():
    entries = {}
    for base, scope in (("/etc/xdg/autostart", "system"), (AUTOSTART_DIR, "user")):
        for path in sorted(glob.glob(f"{base}/*.desktop")):
            e = parse_desktop(read(path) or "")
            if not e:
                continue
            name = os.path.basename(path)
            entries[name] = {
                "file": name, "path": path, "scope": scope,
                "name": e.get("Name[de]") or e.get("Name") or name,
                "exec": e.get("Exec", ""),
                "enabled": (e.get("Hidden", "false").lower() != "true"
                            and e.get("X-GNOME-Autostart-enabled", "true").lower() != "false"),
            }
    return sorted(entries.values(), key=lambda e: e["name"].lower())


def autostart_set(entry, enabled):
    """Schaltet über eine Nutzer-Kopie, Systemdateien bleiben unangetastet."""
    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    target = os.path.join(AUTOSTART_DIR, entry["file"])
    text = read(target) if os.path.exists(target) else read(entry["path"])
    lines = [ln for ln in (text or "[Desktop Entry]").splitlines()
             if not ln.strip().lower().startswith(("hidden=", "x-gnome-autostart-enabled="))]
    if not enabled:
        lines.append("Hidden=true")
    with open(target, "w") as f:
        f.write("\n".join(lines) + "\n")
    entry["path"], entry["scope"], entry["enabled"] = target, "user", enabled


def mounts():
    keep = {"ext4", "ext3", "btrfs", "xfs", "vfat", "exfat", "ntfs3", "ntfs", "f2fs"}
    out = []
    for line in open("/proc/mounts"):
        src, target, fstype = line.split()[:3]
        if fstype not in keep or not src.startswith("/dev/"):
            continue
        target = target.replace("\\040", " ")
        try:
            s = os.statvfs(target)
        except OSError:
            continue
        total = s.f_blocks * s.f_frsize
        free = s.f_bavail * s.f_frsize
        if total == 0:
            continue
        out.append({"target": target, "src": src, "fs": fstype,
                    "total": total, "free": free, "used": total - free})
    return sorted(out, key=lambda m: m["target"])


def dir_size(path, timeout=20):
    # du endet mit 1, sobald ein Unterverzeichnis nicht lesbar ist, und liefert
    # die Summe trotzdem. /var/cache/apt/archives/partial gehört root, deshalb
    # trifft das jede Ubuntu-Installation.
    _rc, out = sh_rc(["du", "-sb", path], timeout=timeout)
    try:
        return int(out.split()[0])
    except (IndexError, ValueError):
        return 0


def net_bytes():
    rx = tx = 0
    for line in open("/proc/net/dev").readlines()[2:]:
        iface, _, rest = line.partition(":")
        if iface.strip() == "lo":
            continue
        f = rest.split()
        rx += int(f[0])
        tx += int(f[8])
    return rx, tx


DISK_RE = re.compile(r"^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+|mmcblk\d+)$")


def disk_bytes():
    rd = wr = 0
    for line in open("/proc/diskstats"):
        f = line.split()
        if not DISK_RE.match(f[2]):
            continue
        rd += int(f[5]) * 512
        wr += int(f[9]) * 512
    return rd, wr


def processes():
    out = []
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(f"{d}/stat") as f:
                stat = f.read()
            name = stat[stat.index("(") + 1:stat.rindex(")")]
            f = stat[stat.rindex(")") + 2:].split()
            out.append({"pid": int(os.path.basename(d)), "name": name,
                        "cpu": int(f[11]) + int(f[12]), "rss": int(f[21]) * 4096})
        except (OSError, ValueError):
            continue
    return out


# Updates. Portiert aus allinone-updater, ohne dessen Root-Helfer: pkexec ruft
# apt-get und snap direkt, das spart die Installation nach /usr/lib und die
# eigene Polkit-Regel. Namen gehen als eigene Argumente raus, nie als Shell.

UPDATE_SOURCES = {"apt": "APT-Pakete", "snap": "Snaps",
                  "flatpak": "Flatpaks", "fwupd": "Firmware"}
# Wie im Helfer von allinone-updater: erstes Zeichen alphanumerisch, damit
# keine Option durchrutscht, und kein '-' am Ende, das hieße für apt entfernen.
PKG_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.+:/_-]*", re.ASCII)


def valid_pkg(name):
    return bool(PKG_NAME.fullmatch(name)) and not name.endswith("-")


def parse_size(text):
    """'50.2MB', '149.4 MB', '1.2 GB' in Byte. Unbekannt ist 0.

    Flatpak trennt Zahl und Einheit mit einem schmalen Leerzeichen, das unter
    LC_ALL=C als '?' ankommt. Deshalb hier alles außer Wortzeichen dazwischen.
    """
    m = re.search(r"([\d.]+)[^\w]*([kMGT])?i?B", text.replace(",", "."))
    if not m:
        return 0
    return int(float(m.group(1)) * 1000 ** " kMGT".index(m.group(2) or " "))


def parse_apt_sizes(text):
    """Byte je Paketname aus 'apt-get --print-uris': 'url' name_ver_arch.deb SIZE ..."""
    sizes = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0].startswith("'") and f[1].endswith(".deb"):
            parts = f[1][:-4].split("_")
            if len(parts) >= 3:
                try:
                    sizes[parts[0]] = int(f[2])
                except ValueError:
                    pass
    return sizes


def parse_apt_updates(text, uris=""):
    """Inst-Zeilen der apt-Simulation: 'Inst name[:arch] [alt] (neu quelle [arch])'.

    Phased Updates stehen dort nicht drin, es bleibt also genau das übrig,
    was apt jetzt wirklich zöge. Die ID behält :arch, sonst trifft der
    Installationsbefehl auf Multi-Arch-Systemen das falsche Paket.
    """
    sizes = parse_apt_sizes(uris)
    return [(m[0], m[0].split(":")[0], m[1], m[2], sizes.get(m[0].split(":")[0], 0))
            for m in re.findall(r"^Inst (\S+) \[([^\]]+)\] \(([^\s)]+)", text, re.M)]


def parse_snap_updates(text, installed=""):
    have = {f[0]: (f[1], f[2]) for f in (line.split() for line in installed.splitlines()[1:])
            if len(f) >= 3}
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Name"):
        return []                      # "All snaps up to date."
    out = []
    for f in (line.split() for line in lines[1:]):
        if len(f) < 4:
            continue
        old, old_rev = have.get(f[0], ("", ""))
        new, new_rev = f[1], f[2]
        # Viele Snaps heben nur die Revision an, dann sagt die Version nichts aus
        if old == new:
            old = _("Rev {rev}").format(rev=old_rev)
            new = _("Rev {rev}").format(rev=new_rev)
        out.append((f[0], f[0], old, new, parse_size(f[3])))
    return out


def parse_flatpak_updates(text, installed=""):
    def norm(ref):                     # 'list' liefert appid/arch/branch,
        p = ref.split("/")             # 'remote-ls' app/appid/arch/branch
        return "/".join(p[1:]) if len(p) == 4 and p[0] in ("app", "runtime") else ref

    have = {norm(f[0]): (f[1], f[2])
            for f in (line.split("\t") for line in installed.splitlines()) if len(f) >= 3}
    out = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 4:
            continue
        ref = norm(f[1])
        old, old_c = have.get(ref, ("", ""))
        new, new_c = f[2], f[3]
        # Runtimes behalten die Version und wechseln nur den Build. Viele Refs
        # tragen gar keine Version, dann bleibt nur der Build als Unterschied.
        if old == new:
            old = (_("Build {id}").format(id=old_c[:8]) if old_c
                   else _("neu"))
            new = _("Build {id}").format(id=new_c[:8])
        out.append((ref, f[0] or ref.split("/")[0], old, new,
                    parse_size(f[4]) if len(f) > 4 else 0))
    return out


def parse_fwupd_updates(text):
    try:
        devices = json.loads(text).get("Devices", [])
    except (ValueError, AttributeError):
        return []
    out = []
    for d in devices:
        rel = (d.get("Releases") or [None])[0]
        if not rel:
            continue
        try:
            size = int(rel.get("Size", 0))
        except (TypeError, ValueError):
            size = 0
        out.append((d.get("DeviceId", ""), d.get("Name", "Firmware"),
                    d.get("Version", ""), rel.get("Version", ""), size))
    return out


def updates_scan(include_firmware=True):
    """{quelle: {"items": [(id, name, alt, neu, byte)], "error": str|None}}.

    Der Fehlerzustand muss mit, sonst sieht eine kaputte Paketliste genauso aus
    wie ein aktuelles System.
    """
    out = {}

    def run(src, cmd, timeout, parse, *extra):
        rc, text = sh_rc(cmd, timeout=timeout)
        if rc is None:
            out[src] = {"items": [],
                        "error": _("{tool} antwortet nicht").format(
                            tool=cmd[0])}
        elif rc != 0:
            out[src] = {"items": [],
                        "error": _("{tool} endete mit Code {rc}").format(
                            tool=cmd[0], rc=rc)}
        else:
            out[src] = {"items": parse(text, *extra), "error": None}

    if shutil.which("apt-get"):
        # dist-upgrade statt upgrade, sonst fehlen zurueckgehaltene Updates wie
        # ein Kernel mit neuer ABI, der ein zusaetzliches Paket braucht.
        uris = sh(["apt-get", "-y", "--print-uris", "-o", "Debug::NoLocking=1",
                   "dist-upgrade"], timeout=90)
        run("apt", ["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], 60,
            parse_apt_updates, uris)
    if shutil.which("snap"):
        run("snap", ["snap", "refresh", "--list"], 60, parse_snap_updates,
            sh(["snap", "list"], timeout=30))
    if shutil.which("flatpak"):
        run("flatpak", ["flatpak", "remote-ls", "--updates",
                        "--columns=name,ref,version,commit,download-size"], 90,
            parse_flatpak_updates,
            sh(["flatpak", "list", "--columns=ref,version,active"], timeout=30))
    if include_firmware and shutil.which("fwupdmgr"):
        # Liest nur die gecachten Metadaten, kein Netzabruf beim Öffnen der Seite.
        rc, text = sh_rc(["fwupdmgr", "get-updates", "--json"], timeout=45)
        # 2 heißt "nichts gefunden", das ist kein Fehler
        out["fwupd"] = {"items": parse_fwupd_updates(text) if rc in (0, 2) else [],
                        "error": None if rc in (0, 2) else _("fwupdmgr nicht erreichbar")}
    return out


SNAPSHOT_CMD = ["pkexec", "timeshift", "--create", "--comments", "dynotiq"]
# Zeilen, an denen sich ablesen lässt, welches Paket gerade drankommt. Die
# Dateivariante steht getrennt, weil dort der Name im Dateinamen steckt.
PROGRESS_LINE = re.compile(
    r"^(?:Setting up|Unpacking|Installing|Updating|Refreshing|Refresh)\s+(\S+)")
PROGRESS_FILE = re.compile(r"^Preparing to unpack .*?/([^/_]+)_")


def progress_name(line):
    """Paketname aus einer Fortschrittszeile von apt, snap oder flatpak."""
    line = line.strip()
    for pat in (PROGRESS_LINE, PROGRESS_FILE):
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


def cmd_steps(cmd):
    """Eine Liste von Argumentlisten läuft nacheinander, eine einzelne
    Argumentliste ist ein Schritt. So kommt apt-get update vor die Installation,
    ohne dass eine Shell die beiden verknüpfen muss."""
    return cmd if cmd and isinstance(cmd[0], list) else [cmd]


def desktop_icon(text):
    """Icon-Name aus einer .desktop-Datei. Der Paketname taugt selten als
    Icon-Name, der Eintrag in der Startdatei dagegen fast immer."""
    m = re.search(r"^Icon=(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def update_icon(src, uid, name):
    """Icon-Name oder Pfad für eine Update-Zeile, leer wenn nichts passt."""
    if src == "snap":
        for p in sorted(glob.glob(f"/snap/{uid}/current/meta/gui/*.png")):
            return p
        return ""
    if src == "flatpak":
        return uid.split("/")[0]        # Flatpak exportiert unter der App-ID
    if src == "fwupd":
        return "application-x-firmware"
    pkg = uid.split(":")[0]
    for path in (f"/usr/share/applications/{pkg}.desktop",
                 f"/var/lib/flatpak/exports/share/applications/{pkg}.desktop"):
        text = read(path)
        if text:
            return desktop_icon(text)
    return ""


def update_cmd(src, ids):
    """Kommando, das die gewählten Updates einspielt. Ohne Shell, ohne Helfer."""
    if src == "apt":
        # pkexec setzt die Umgebung des Kindes auf ein Minimum zurueck, deshalb
        # muss DEBIAN_FRONTEND ueber env gesetzt werden statt ueber Popen(env=).
        return ["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                "apt-get", "-y",
                "-o", "Dpkg::Options::=--force-confdef",
                "-o", "Dpkg::Options::=--force-confold",
                "install", "--only-upgrade", "--", *ids]
    if src == "snap":
        return ["pkexec", "snap", "refresh", "--", *ids]
    if src == "flatpak":
        return ["flatpak", "update", "-y", "--noninteractive", *ids]
    return ["fwupdmgr", "update", "-y", *ids]


# App-Prüfung. Nimmt eine installierte Anwendung und sieht nach, woran sie
# auf diesem System scheitern könnte: fehlende Bibliotheken, abgeschnittene
# Sandbox-Rechte, blockierte Zugriffe, Abstürze.

DESKTOP_DIRS = ["/usr/share/applications",
                "/var/lib/flatpak/exports/share/applications",
                "/var/lib/snapd/desktop/applications",
                os.path.expanduser("~/.local/share/applications"),
                os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]


def exec_binary(exec_line):
    """Das eigentliche Programm aus einer Exec-Zeile.

    Startzeilen tragen oft eine env-Vorhut: Zuweisungen, aber auch Optionen mit
    eigenem Wert wie 'env -u GIO_MODULE_DIR'. Wer nur Zuweisungen überspringt,
    hält am Ende '-u' für das Programm.
    """
    try:
        toks = shlex.split(exec_line)      # respektiert Anführungszeichen
    except ValueError:
        toks = exec_line.split()
    toks = [t for t in toks if not t.startswith("%")]
    while toks:
        t = toks[0]
        if t in ("env", "/usr/bin/env"):
            toks.pop(0)
        elif t in ("-u", "--unset", "-C", "--chdir", "-S") and len(toks) > 1:
            del toks[:2]                   # Option samt zugehörigem Wert
        elif t.startswith("-") or "=" in t:
            toks.pop(0)
        else:
            break
    if not toks:
        return ""
    # 'sh -c "programm ..."': sonst gilt die Shell als das Programm und die
    # Herkunft landet bei dash statt bei dem, was wirklich startet.
    if os.path.basename(toks[0]) in ("sh", "bash", "dash", "zsh") \
            and len(toks) > 2 and toks[1] == "-c":
        try:
            inner = shlex.split(toks[2])
        except ValueError:
            inner = toks[2].split()
        if inner:
            return inner[0]
    return toks[0]


def app_source(entry):
    """(Art, Kennung) einer Anwendung: snap, flatpak, deb, lokal oder unbekannt."""
    ex = entry.get("Exec", "")
    if "flatpak run" in ex:
        ids = [t for t in ex.split() if t.count(".") >= 2 and not t.startswith("-")]
        return ("flatpak", ids[-1] if ids else "")
    binary = exec_binary(ex)
    if binary.startswith("/snap/bin/") or "/snap/" in binary:
        return ("snap", binary.rsplit("/", 1)[-1])
    if binary.endswith(".AppImage"):
        return ("appimage", binary)
    if binary:
        owner = sh(["dpkg", "-S", shutil.which(binary) or binary], timeout=20)
        if ":" in owner:
            return ("deb", owner.split(":")[0])
    return ("lokal", binary)


def desktop_apps():
    """{Anzeigename: Eintrag} aller sichtbaren Anwendungen."""
    apps = {}
    for d in DESKTOP_DIRS:
        for path in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            text = read(path)
            if not text:
                continue
            e = parse_desktop(text)
            if e.get("NoDisplay") == "true" or e.get("Hidden") == "true":
                continue
            name = e.get("Name") or os.path.basename(path)
            if e.get("Exec"):
                e["Path"] = path
                apps[name] = e
    return apps


def missing_libs(binary):
    """Bibliotheken, die der Binder nicht auflösen kann."""
    path = shutil.which(binary) or binary
    if not os.path.exists(path):
        return []
    return sorted({line.split()[0].strip() for line in
                   sh(["ldd", path], timeout=30).splitlines() if "not found" in line})


def parse_snap_connections(text, name):
    """Interfaces eines Snaps, die auf keinen Slot zeigen."""
    gaps = []
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) >= 3 and f[1].startswith(f"{name}:") and f[2] == "-":
            gaps.append(f[1].split(":", 1)[1])
    return sorted(set(gaps))


def parse_flatpak_perms(text):
    """Die Berechtigungen, deren Fehlen man tatsächlich merkt."""
    have = {}
    for key, label in (("devices", "Grafikbeschleunigung"), ("sockets", "Anzeige"),
                       ("filesystems", "Dateizugriff"), ("shared", "Netzwerk")):
        m = re.search(rf"^{key}=(.*)$", text, re.M)
        have[label] = [v for v in (m.group(1) if m else "").split(";") if v]
    return have


def parse_denials(text, label):
    """Blockierte Zugriffe eines Programms samt Beispiel."""
    hits = [line for line in text.splitlines()
            if 'apparmor="DENIED"' in line and f'label="{label}' in line]
    ops = sorted({m.group(1) for line in hits
                  if (m := re.search(r'operation="([^"]+)"', line))})
    return len(hits), ops


APP_KIND_LABEL = {"snap": "Snap", "flatpak": "Flatpak", "deb": _("Paket"),
                  "lokal": _("manuell installiert"), "appimage": "AppImage"}

# Snap-Schnittstellen in Alltagssprache. Die Namen sind Fachbegriffe, und ob
# eine fehlende Freigabe stört, hängt davon ab, was man mit der App macht.
SNAP_IFACE = {
    "audio-record": (_("Mikrofon"), _("Die App kann nichts aufnehmen. Nötig für "
                     "Spracheingabe oder Anrufe.")),
    "audio-playback": (_("Tonwiedergabe"), _("Die App bleibt stumm.")),
    "camera": (_("Kamera"), _("Video und Fotos gehen nicht.")),
    "removable-media": (_("USB-Sticks und externe Laufwerke"), _("Die App sieht nur "
                        "dein Home-Verzeichnis, nichts unter /media.")),
    "home": (_("Eigene Dateien"), _("Die App kommt nicht an dein Home-Verzeichnis.")),
    "network": (_("Internet"), _("Die App kann nicht ins Netz.")),
    "network-manager": (_("Netzwerkeinstellungen"), _("Nur nötig, wenn die App "
                        "Verbindungen selbst einrichten soll.")),
    "cups-control": (_("Drucken"), _("Druckaufträge gehen nicht raus.")),
    "bluetooth-control": (_("Bluetooth"), _("Geräte lassen sich nicht koppeln.")),
    "bluez": (_("Bluetooth"), _("Geräte lassen sich nicht koppeln.")),
    "location-observe": (_("Standort"), _("Ortsbezogene Funktionen bleiben leer.")),
    "password-manager-service": (_("Schlüsselbund"), _("Gespeicherte Passwörter sind "
                                 "nicht erreichbar, Anmeldungen fragen jedes Mal neu.")),
    "screen-inhibit-control": (_("Bildschirmschoner unterdrücken"), _("Der Bildschirm "
                               "schaltet auch während Wiedergabe oder Präsentation ab.")),
    "system-observe": (_("Systemprozesse ansehen"), _("Nur für Werkzeuge nötig, die "
                       "andere Programme überwachen.")),
    "process-control": (_("Prozesse steuern"), _("Nur für Systemwerkzeuge nötig.")),
    "hardware-observe": (_("Hardware auslesen"), _("Angaben zu Geräten bleiben leer.")),
    "mount-observe": (_("Laufwerke sehen"),
                      _("Eingehängte Datenträger bleiben unsichtbar.")),
    "raw-usb": (_("USB-Geräte direkt"), _("Nötig für Programmiergeräte, Scanner "
                "und Ähnliches.")),
    "optical-drive": (_("CD- und DVD-Laufwerk"), _("Discs werden nicht gelesen.")),
    "joystick": (_("Gamecontroller"), _("Controller werden nicht erkannt.")),
    "gpg-keys": (_("GPG-Schlüssel"), _("Signieren und Entschlüsseln geht nicht.")),
    "kerberos-tickets": (_("Firmenanmeldung"),
                         _("Nur in Firmennetzen mit Kerberos nötig.")),
    "avahi-observe": (_("Geräte im lokalen Netz finden"), _("Drucker und Freigaben "
                      "tauchen nicht von selbst auf.")),
    "pcscd": (_("Chipkartenleser"), _("Signaturkarten werden nicht erkannt.")),
    "u2f-devices": (_("Sicherheitsschlüssel"), _("YubiKey und ähnliche Sticks werden "
                    "nicht erkannt.")),
    "desktop-launch": (_("Andere Programme starten"), _("Links öffnen sich "
                       "möglicherweise nicht im Browser.")),
    "personal-files": (_("Bestimmte eigene Dateien"), _("Zugriff auf einzelne Ordner "
                       "im Home.")),
    "system-files": (_("Bestimmte Systemdateien"),
                     _("Zugriff auf einzelne Systemordner.")),
    "shared-memory": (_("Gemeinsamer Speicher"), _("Nötig für manche Fenster- und "
                      "Videofunktionen.")),
    "hostname-control": (_("Rechnername ändern"), _("Nur für Systemwerkzeuge nötig.")),
    "dvb": (_("TV-Karte"), _("Fernsehempfang geht nicht.")),
    "raw-input": (_("Eingabegeräte direkt"), _("Nötig für manche Tastatur- und "
                  "Controllerfunktionen.")),
}


def iface_text(name):
    """(Klarname, Erklärung) zu einer Snap-Schnittstelle."""
    known = SNAP_IFACE.get(name)
    if known:
        return known
    return (name.replace("-", " "),
            _("Was genau dahinter steckt, sagt die Beschreibung des Snaps."))


def entry_icon(entry):
    """Icon-Angabe einer Startdatei: absoluter Pfad oder Name aus dem Theme."""
    icon = entry.get("Icon", "").strip()
    if icon.startswith("/"):
        return icon if os.path.exists(icon) else ""
    return icon


def parse_apt_policy(text):
    """(installiert, verfügbar, kommt aus einer Paketquelle).

    Steht in der Versionstabelle nur der dpkg-Status, wurde das Paket von Hand
    installiert. Dann kommt dort nie ein Update an, egal wie alt es ist.
    """
    inst = re.search(r"Installed:\s*(\S+)", text)
    cand = re.search(r"Candidate:\s*(\S+)", text)
    from_repo = bool(re.search(r"^\s+\d+\s+\S+://", text, re.M))
    return (inst.group(1) if inst else "", cand.group(1) if cand else "", from_repo)


def app_dirs(names):
    """[(Pfad, Bytes)] der Ordner, die eine Anwendung im Home anlegt."""
    out = []
    for base in (".config", ".local/share", ".cache", ".var/app", "snap"):
        for n in filter(None, dict.fromkeys(names)):
            p = os.path.expanduser(f"~/{base}/{n}")
            if os.path.isdir(p):
                out.append((p, dir_size(p, 25)))
    return sorted(out, key=lambda x: -x[1])


def cache_dirs(path):
    """Unterordner mit reinem Zwischenspeicher. Die lassen sich gefahrlos
    leeren, die Anwendung legt sie beim nächsten Start neu an."""
    seen = {}
    for pat in ("*Cache*", "*cache*"):
        for p in glob.glob(os.path.join(path, pat)):
            if os.path.isdir(p) and p not in seen:
                seen[p] = dir_size(p, 15)
    return sorted(seen.items(), key=lambda x: -x[1])


def fuse2_missing():
    """AppImages der ersten Generation brauchen libfuse2. Auf Ubuntu 24.04 ist
    die nicht mehr vorinstalliert, das ist der häufigste Startfehler."""
    return not glob.glob("/usr/lib/*/libfuse.so.2*")


def app_check(entry):
    """[(sev, Titel, Detail, Fix)] zu einer Anwendung.

    sev ist ok, warn oder crit. Fix ist None oder (Knopfbeschriftung, argv),
    also eine Lösung, die die App selbst ausführen kann. Strukturiert statt
    Fließtext, damit die Oberfläche Punkte, Farben und Knöpfe setzen kann.
    """
    kind, ident = app_source(entry)
    binary = exec_binary(entry.get("Exec", ""))
    origin = {
        "snap": _("Läuft abgeschottet in einer Sandbox. Zugriffe auf Mikrofon, "
                "Kamera oder externe Laufwerke müssen einzeln freigegeben werden."),
        "flatpak": _("Läuft abgeschottet in einer Sandbox mit eigenen Bibliotheken, "
                   "unabhängig vom Rest des Systems."),
        "deb": _("Über die Paketverwaltung eingetragen, dpkg kennt es."),
        "lokal": _("Von Hand installiert, ohne Paketquelle. Updates musst du selbst "
                 "einspielen."),
        "appimage": _("Einzelne Programmdatei, die alles mitbringt. Updates musst "
                    "du selbst einspielen."),
    }.get(kind, "")
    out = [("ok", APP_KIND_LABEL.get(kind, kind) + (f" · {ident}" if ident else ""),
            origin, None)]

    if kind == "appimage":
        if not os.path.exists(binary):
            out.append(("crit", _("AppImage nicht gefunden"),
                        _("{path} liegt nicht mehr dort. Der Starter zeigt "
                          "ins Leere und lässt sich löschen.").format(path=binary),
                        None))
        else:
            if not os.access(binary, os.X_OK):
                out.append(("crit", _("Nicht ausführbar"),
                            _("Der Datei fehlt das Ausführungsrecht, ohne das "
                            "startet sie nicht."),
                            (_("Recht setzen"), ["chmod", "+x", binary])))
            else:
                out.append(("ok", _("Datei"),
                            _("{size}, ausführbar").format(
                                size=fmt_bytes(os.path.getsize(binary))), None))
            if fuse2_missing():
                out.append(("warn", _("libfuse2 fehlt"),
                            _("AppImages der ersten Generation brauchen sie zum "
                            "Entpacken. Ohne sie bricht der Start mit "
                            "'dlopen(): error loading libfuse.so.2' ab."),
                            (_("libfuse2 installieren"),
                             [["pkexec", "apt-get", "update"],
                              ["pkexec", "/usr/bin/env",
                               "DEBIAN_FRONTEND=noninteractive", "apt-get",
                               "install", "-y", "libfuse2t64"]])))
    elif kind in ("deb", "lokal") and binary:
        apt_fix = ["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                   "apt-get", "install", "-f", "-y"]
        if kind == "deb":
            status = sh(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", ident],
                        timeout=20).strip()
            if status and not status.startswith("ii"):
                out.append(("crit", _("Paket nicht sauber installiert"),
                            _("dpkg meldet den Status '{status}'. So bleibt ein "
                              "abgebrochener Installationslauf liegen, das Programm "
                              "ist unvollständig.").format(status=status),
                            (_("Installation reparieren"), apt_fix)))
        if kind == "deb" and ident:
            inst, cand, from_repo = parse_apt_policy(
                sh(["apt-cache", "policy", ident], timeout=30))
            when = ""
            listing = f"/var/lib/dpkg/info/{ident}.list"
            if os.path.exists(listing):
                when = time.strftime("%d.%m.%Y",
                                     time.localtime(os.path.getmtime(listing)))
            if not from_repo:
                out.append(("warn",
                            _("Version {v} bekommt keine Updates").format(v=inst),
                            (_("Installiert am {date}. ").format(date=when)
                             if when else "")
                            + _("Das Paket steht in keiner Paketquelle, es wurde "
                                "von Hand eingespielt. Die Systemaktualisierung "
                                "übergeht es, neue Versionen musst du selbst holen."),
                            None))
            elif cand and cand != inst:
                out.append(("warn", _("Version {v}, verfügbar wäre {avail}").format(
                                v=inst, avail=cand),
                            _("Die Systemaktualisierung hat das noch nicht "
                            "eingespielt."), (_("Jetzt aktualisieren"),
                                             [["pkexec", "apt-get", "update"],
                                              ["pkexec", "/usr/bin/env",
                                               "DEBIAN_FRONTEND=noninteractive",
                                               "apt-get", "install", "-y", ident]])))
            else:
                out.append(("ok", _("Version {v}").format(v=inst),
                            (_("Installiert am {date}, ").format(date=when)
                             if when else "")
                            + _("aktuell laut Paketquelle."), None))
        if shutil.which(binary) or os.path.exists(binary):
            missing = missing_libs(binary)
            if missing:
                out.append(("crit", _("Fehlende Bibliotheken"),
                            _("Das Programm startet so nicht: ") + ", ".join(missing),
                            (_("Abhängigkeiten nachziehen"), apt_fix)))
            else:
                out.append(("ok", _("Bibliotheken"), _("alle auflösbar"), None))
        else:
            fix = None
            if kind == "deb" and ident:
                fix = (_("Paket neu installieren"),
                       [["pkexec", "apt-get", "update"],
                        ["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                         "apt-get", "install", "--reinstall", "-y", ident]])
            out.append(("crit", _("Programm nicht gefunden"),
                        _("{path} liegt nicht (mehr) dort.").format(path=binary),
                        fix))

    if kind == "snap":
        gaps = parse_snap_connections(sh(["snap", "connections", ident], timeout=30),
                                      ident)
        for gap in gaps:
            label, why = iface_text(gap)
            # Bewusst nur ein Hinweis, kein Mangel: eine nicht freigegebene
            # Schnittstelle ist erstmal Sicherheit. Handeln muss man nur, wenn
            # einem die Funktion fehlt.
            out.append(("info", _("{iface} nicht freigegeben").format(iface=label),
                        _("{why} Brauchst du das nicht, kannst du es so lassen. "
                          "Fachbegriff: {name}.").format(why=why, name=gap),
                        (_("Freigeben"), ["pkexec", "snap", "connect",
                                          f"{ident}:{gap}"])))
        if not gaps:
            out.append(("ok", _("Freigaben"), _("Die App hat alles, was sie "
                        "angefordert hat."), None))

    if kind == "flatpak":
        perms = parse_flatpak_perms(sh(["flatpak", "info", "--show-permissions", ident],
                                       timeout=30))
        if not perms.get("Grafikbeschleunigung"):
            out.append(("warn", _("Keine Grafikbeschleunigung"),
                        _("devices=dri fehlt, das Programm rendert in Software "
                        "und ruckelt."),
                        (_("Freigeben"), ["flatpak", "override", "--user",
                                          "--device=dri", ident])))
        else:
            out.append(("ok", _("Grafikbeschleunigung"), _("vorhanden"), None))
        if not perms.get("Anzeige"):
            out.append(("crit", _("Kein Zugriff auf die Anzeige"),
                        _("Weder X11 noch Wayland freigegeben, das Fenster kann "
                        "nicht erscheinen."),
                        (_("Freigeben"), ["flatpak", "override", "--user",
                                          "--socket=wayland",
                                          "--socket=fallback-x11", ident])))
        if perms.get("Dateizugriff"):
            out.append(("ok", _("Dateizugriff"),
                        ", ".join(perms["Dateizugriff"])[:80], None))

    label = {"snap": f"snap.{ident}", "flatpak": ident}.get(kind, "")
    if label:
        count, ops = parse_denials(
            sh(["journalctl", "-k", "--since", "-24h", "--no-pager"], timeout=60), label)
        if count:
            what = {"dbus_method_call": _("mit einem Systemdienst sprechen"),
                    "dbus_signal": _("auf Systemmeldungen hören"),
                    "open": _("eine Datei öffnen"), "file_inherit": _("eine Datei "
                    "weiterreichen"), "exec": _("ein anderes Programm starten"),
                    "connect": _("eine Verbindung aufbauen"),
                    "capable": _("eine Systemberechtigung nutzen")}
            tried = [what.get(o, o) for o in ops[:3]]
            out.append(("info",
                        _("{n} mal von der Sandbox gebremst").format(n=count),
                        _("Die App wollte ") + _(" und ").join(tried)
                        + _(", durfte aber nicht. Das ist der Normalfall bei Snaps "
                            "und meist harmlos. Nur wenn etwas in der App wirklich "
                            "nicht geht, lohnt ein Blick auf die Freigaben darüber."),
                        None))

    if shutil.which("coredumpctl") and binary:
        base = os.path.basename(binary)
        dumps = sh(["coredumpctl", "list", "--no-pager", base], timeout=30)
        n = len([x for x in dumps.splitlines() if "/" in x or "core" in x.lower()]) - 1
        if n > 0:
            out.append(("crit", _("{n} Abstürze aufgezeichnet").format(n=n),
                        _("Der Bericht zeigt, woran es lag."),
                        (_("Bericht ansehen"), ["coredumpctl", "info", base])))

    if binary:
        errs = [x for x in sh(["journalctl", "--user", "--since", "-24h", "-p", "err",
                               "--no-pager", "-t", os.path.basename(binary)],
                              timeout=45).splitlines()
                if x and not x.startswith("--")]
        if errs:
            out.append(("warn",
                        _("{n} Fehlermeldungen im Journal").format(n=len(errs)),
                        strip_prefix(errs[-1])[:140],
                        (_("Alle anzeigen"),
                         ["journalctl", "--user", "--since", "-24h", "-p", "err",
                          "--no-pager", "-t", os.path.basename(binary)])))

    # Platzbedarf im Home. Bei Electron-Programmen liegen dort schnell
    # Gigabytes an Zwischenspeicher, ohne dass es jemand merkt.
    base = os.path.basename(binary).removesuffix(".AppImage") if binary else ""
    dirs = app_dirs([ident, base, entry.get("Name", "").lower()])
    if dirs:
        biggest, size = dirs[0]
        total = sum(s for _, s in dirs)
        where = biggest.replace(os.path.expanduser("~"), "~")
        out.append(("ok", _("Belegt {size} im Home").format(size=fmt_bytes(total)),
                    _("Größter Posten: {path} mit {size}.").format(
                        path=where, size=fmt_bytes(size))
                    + (_(" Dazu {n} weitere Ordner.").format(n=len(dirs) - 1)
                       if len(dirs) > 1 else ""), None))
        caches = [(p, s) for p, s in cache_dirs(biggest) if s > 50 * 2**20]
        if caches:
            csum = sum(s for _, s in caches)
            names = ", ".join(os.path.basename(p) for p, _ in caches[:3])
            out.append(("warn", _("{size} davon nur Zwischenspeicher").format(
                            size=fmt_bytes(csum)),
                        _("In {dirs}. Die Anwendung legt das beim nächsten Start "
                          "neu an, deine Anmeldung und Einstellungen bleiben."
                          ).format(dirs=names),
                        (_("Zwischenspeicher leeren"),
                         [["find", p, "-mindepth", "1", "-delete"]
                          for p, _ in caches])))

    auto = next((a for a in autostart_entries()
                 if base and base in a.get("exec", "")), None)
    if auto:
        out.append(("ok" if auto["enabled"] else "info",
                    _("Startet automatisch mit der Anmeldung") if auto["enabled"]
                    else _("Autostart-Eintrag vorhanden, aber abgeschaltet"),
                    _("Eintrag {file}. Ändern lässt sich das unter Autostart."
                      ).format(file=auto["file"]),
                    None))

    if binary:
        running = [p for p in processes() if p["name"] == os.path.basename(binary)[:15]]
        if running:
            out.append(("ok", _("Läuft gerade"),
                        _("{n} Prozess(e), {size} Speicher").format(
                            n=len(running),
                            size=fmt_bytes(sum(p["rss"] for p in running))), None))

    # Gilt für jede Art: zeigt der Starter ins Leere und liegt er im eigenen
    # Home, lässt er sich gefahrlos entfernen. Systemweite gehören einem Paket.
    path = entry.get("Path", "")
    gone = {_("AppImage nicht gefunden"), _("Programm nicht gefunden")}
    dead = any(sev == "crit" and title in gone for sev, title, _d, _f in out)
    if dead and path.startswith(os.path.expanduser("~")):
        out.append(("warn", _("Verwaister Starter"),
                    _("{path} zeigt auf ein Programm, das es nicht mehr gibt. "
                      "Der Eintrag im Menü bleibt sonst für immer stehen."
                      ).format(path=path),
                    (_("Starter entfernen"), ["rm", "--", path])))

    if not any(sev != "ok" for sev, _t, _d, _f in out):
        out.append(("ok", _("Keine Auffälligkeiten"),
                    _("Bibliotheken, Rechte und Journal sind sauber."), None))
    return out


def app_check_text(name, results):
    """Das Ergebnis als kopierbarer Text, etwa für einen Fehlerbericht."""
    lines = [_("App-Check: {app}").format(app=name), ""]
    for sev, title, detail, _fix in results:
        mark = {"ok": "  ", "info": "· ", "warn": "! ", "crit": "!!"}[sev]
        lines.append(f"{mark} {title}: {detail}")
    return "\n".join(lines)


# Was beim ersten Start und nach einem Update gezeigt wird. Pro Version ein
# Titel und die Punkte, die den Unterschied machen.

INTRO = [
    (_("Systemcheck"), _("Findet, was den Rechner ausbremst: veraltete Treiber, "
     "Wärmedrosselung, volle Dateisysteme, ein wucherndes Journal. Jeder Befund "
     "erklärt sich und bringt den passenden Befehl mit.")),
    (_("Vorfälle"), _("Liest das Journal nach Audio-Aussetzern, GPU-Treiberfehlern und "
     "abgeschossenen Prozessen und schreibt dazu, wie warm es zu dem Zeitpunkt war.")),
    (_("Updates"), _("apt, Snap, Flatpak und Firmware an einer Stelle, mit Größenangabe "
     "und Protokoll. Auf Wunsch mit Timeshift-Sicherung davor.")),
    (_("App-Check"), _("Nimmt eine installierte Anwendung auseinander: fehlende "
     "Bibliotheken, abgeschnittene Sandbox-Rechte, Abstürze. Wo es eine Lösung "
     "gibt, steht ein Knopf daneben.")),
    (_("Prüfstand"), _("Zeichnet Temperatur und Takt über Minuten auf und sagt dir, "
     "ab wann unter Dauerlast gedrosselt wird.")),
]

RELEASE_NOTES = {
    "0.1": (_("Erste Ausgabe"), [
        _("Systemcheck mit Punktzahl und erklärten Befunden"),
        _("Vorfallserkennung aus dem Journal, auf Wunsch im Hintergrund"),
        _("Updates für apt, Snap, Flatpak und Firmware"),
        _("App-Check, Prüfstand, Benchmark mit eigener Basislinie"),
    ]),
}


# Prüfstand: Messwerte über einen längeren Zeitraum aufzeichnen. Ein
# Momentwert sagt nichts darüber, was nach zehn Minuten Last passiert.

def record_sample(prev_cpu):
    """Ein Messpunkt. prev_cpu ist der Stand von cpu_times() beim letzten Punkt."""
    cur = cpu_times()
    total, avail = meminfo()
    g = gpu()
    s = {"t": time.time(), "cpu": round(busy_percent(prev_cpu, cur), 1),
         "ram": round(100 * (total - avail) / total, 1) if total else 0.0}
    t = cpu_temp()
    if t:
        s["cpu_temp"] = round(t, 1)
    if g:
        s["gpu"] = round(g["util"], 1)
        s["gpu_temp"] = round(g["temp"], 1)
        s["gpu_clock"] = round(g["clock"])
        s["throttled"] = bool(g.get("throttled"))
    n = nvme_temp()
    if n:
        s["nvme_temp"] = round(n, 1)
    return s, cur


def record_summary(samples):
    """Aus den Messpunkten das, was man hinterher wissen will: wie heiß wurde
    es, wie tief fiel der Takt, wie lange wurde gedrosselt."""
    if not samples:
        return {}
    out = {"n": len(samples),
           "secs": round(samples[-1]["t"] - samples[0]["t"])}
    for key in ("cpu", "ram", "cpu_temp", "gpu", "gpu_temp", "gpu_clock", "nvme_temp"):
        vals = [s[key] for s in samples if key in s]
        if vals:
            out[key] = {"min": min(vals), "max": max(vals),
                        "med": round(median(vals), 1)}
    thr = [s for s in samples if s.get("throttled")]
    if thr:
        out["throttle_share"] = round(100 * len(thr) / len(samples))
        out["throttle_from"] = round(thr[0]["t"] - samples[0]["t"])
    return out


RECORD_LABEL = {"cpu": (_("CPU-Last"), "%"), "ram": (_("Arbeitsspeicher"), "%"),
                "cpu_temp": (_("CPU-Temperatur"), "°C"), "gpu": (_("GPU-Last"), "%"),
                "gpu_temp": (_("GPU-Temperatur"), "°C"),
                "gpu_clock": (_("GPU-Takt"), "MHz"), "nvme_temp": ("NVMe", "°C")}


def format_summary(summary):
    """Die Auswertung als Text, kopierbar für Forum oder Bugreport."""
    if not summary:
        return _("Keine Messpunkte aufgezeichnet.")
    secs = summary["secs"]
    lines = [_("Aufzeichnung über {mins}:{secs:02d} min ({n} Messpunkte)").format(
        mins=secs // 60, secs=secs % 60, n=summary["n"]), ""]
    # Aus dem f-String gezogen, xgettext findet _() darin nicht.
    lo, mid, hi = _("niedrigster"), _("üblich"), _("höchster")
    lines.append(f"{'':<18}{lo:>13}{mid:>10}{hi:>11}")
    for key, (label, unit) in RECORD_LABEL.items():
        v = summary.get(key)
        if v:
            lines.append(f"{label:<18}{v['min']:>10.0f} {unit:<2}"
                         f"{v['med']:>8.0f} {unit:<2}{v['max']:>8.0f} {unit}")
    if "throttle_share" in summary:
        t = summary["throttle_from"]
        lines += ["", _("Die Grafikkarte drosselte in {pct} % der Messpunkte, "
                        "erstmals nach {mins}:{secs:02d} min.").format(
                            pct=summary["throttle_share"], mins=t // 60, secs=t % 60),
                  _("Das ist der Punkt, an dem die Leistung unter Dauerlast einbricht.")]
    elif summary.get("gpu_temp"):
        lines += ["", _("Keine Drosselung aufgezeichnet.")]
    return "\n".join(lines)


# Befunde

class Finding:
    def __init__(self, sev, title, detail, badge="", badge_ok=False, cmd=None,
                 argv=None, warn=None, report=None):
        self.sev, self.title, self.detail = sev, title, detail
        self.badge, self.badge_ok, self.cmd = badge, badge_ok, cmd
        # argv ist die ausführbare Fassung von cmd als Argumentliste. Nur wo sie
        # gesetzt ist, darf die App den Befehl selbst starten, nie durch eine
        # Shell und nie aus einem zusammengesetzten String.
        self.argv, self.warn = argv, warn
        # Funktion ohne Argumente, die einen längeren Text liefert. Läuft in
        # einem Thread, darf also ins Netz und auf die Platte.
        self.report = report


def parse_driver_branches(text):
    """Alle NVIDIA-Branches, die es fuer diesen Rechner gibt, absteigend.

    Liest sowohl 'ubuntu-drivers list' als auch 'ubuntu-drivers devices'.
    """
    return sorted({int(m) for m in re.findall(r"nvidia-driver-(\d+)", text)},
                  reverse=True)


DRIVER_RECOMMENDED = re.compile(
    r"^driver\s*:\s*(nvidia-driver-(\d+)(?:-[a-z]+)*)\s+-[^\n]*\brecommended\b", re.M)


def parse_recommended_driver(text):
    """(Paketname, Branch) des von Ubuntu empfohlenen Treibers, sonst (None, 0).

    Bewusst nicht der hoechste Branch. 'ubuntu-drivers devices' markiert den,
    den Ubuntu fuer genau diese Karte getestet hat. Der neueste ist oft nicht
    der, der laeuft, und ein Treiberwechsel ins Blaue kostet den Grafikstack.
    """
    m = DRIVER_RECOMMENDED.search(text)
    return (m.group(1), int(m.group(2))) if m else (None, 0)


def check_gpu_driver(ctx):
    g = ctx.get("gpu")
    if not g or g["vendor"] != "nvidia":
        return None
    cur = int(g["driver"].split(".")[0])
    pkg, avail = parse_recommended_driver(
        sh(["ubuntu-drivers", "devices"], timeout=60))
    if not pkg or avail <= cur:
        return None
    return Finding("crit",
                   _("GPU-Treiber veraltet - nvidia-driver-{v}").format(v=cur),
                   _("Ubuntu empfiehlt für diese Karte {pkg}.").format(pkg=pkg),
                   _("{v} empfohlen").format(v=avail), True,
                   f"sudo apt install {pkg}",
                   argv=[["pkexec", "apt-get", "update"],
                         ["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                          "apt-get", "install", "-y", pkg]],
                   warn=_("Der Treiber wird neu gebaut. Bis zum Neustart kann die "
                          "Grafik unvollständig sein, deshalb vorher alles sichern."))


def check_missing_driver(ctx):
    bad = [d for d in ctx.get("devices", [])
           if not d["driver"] and d["class"] != "USB controller"]
    if not bad:
        return None
    return Finding("crit",
                   _("{n} Gerät(e) ohne Kernel-Treiber").format(n=len(bad)),
                   ", ".join(d["name"][:40] for d in bad[:3]),
                   _("kein Treiber"), False)


def nvidia_loaded_version(text=None):
    """Version des geladenen Kernelmoduls aus /proc/driver/nvidia/version."""
    src = read("/proc/driver/nvidia/version") if text is None else text
    m = re.search(r"NVRM version:.*?\s(\d+\.\d+(?:\.\d+)?)\s", src or "")
    return m.group(1) if m else ""


def parse_nvml_mismatch(text):
    """Bibliotheksversion aus der Mismatch-Meldung von nvidia-smi, sonst leer."""
    if "version mismatch" not in text.lower():
        return ""
    m = re.search(r"NVML library version:\s*([\d.]+)", text)
    return m.group(1) if m else "?"


def branch_of(version):
    """Serie aus einer Treiberversion, 0 wenn dort keine Zahl steht."""
    head = version.split(".")[0]
    return int(head) if head.isdigit() else 0


def check_driver_mismatch(ctx):
    """Nach einem Treiberwechsel läuft noch das alte Kernelmodul, während die
    Bibliotheken schon neu sind. Bis zum Neustart geht gar nichts über die GPU,
    und Ubuntu setzt dafür nicht einmal /run/reboot-required.

    Zwei Lagen, zwei Antworten: stimmt die installierte Serie mit der von
    Ubuntu empfohlenen überein, fehlt nur der Neustart. Steht dort eine
    andere Serie, hilft ein Neustart womöglich gar nicht, weil das Modul
    dieser Serie für diese Karte nicht gebaut oder nicht geladen wird.
    """
    if ctx.get("gpu") or not shutil.which("nvidia-smi"):
        return None
    lib = parse_nvml_mismatch(sh_rc(["nvidia-smi"], timeout=20)[1])
    if not lib:
        return None
    loaded = nvidia_loaded_version()
    detail = _("Geladen ist noch Modul {mod}, installiert sind die "
               "Bibliotheken {lib}. Solange das so ist, läuft die Karte "
               "ohne Beschleunigung und keine GPU-Anzeige stimmt.").format(
                   mod=loaded or _("unbekannt"), lib=lib)
    have = branch_of(lib)
    pkg, rec = parse_recommended_driver(
        sh(["ubuntu-drivers", "devices"], timeout=60))
    if pkg and rec and have and have != rec:
        return Finding("crit", _("Grafiktreiber passt nicht zu dieser Karte"),
                       detail + " "
                       + _("Installiert ist Serie {have}, empfohlen für diese "
                           "Karte ist {pkg}.").format(have=have, pkg=pkg),
                       _("{v} empfohlen").format(v=rec), True,
                       f"sudo apt install {pkg}",
                       argv=[["pkexec", "apt-get", "update"],
                             ["pkexec", "/usr/bin/env",
                              "DEBIAN_FRONTEND=noninteractive",
                              "apt-get", "install", "-y", pkg]],
                       warn=_("Der Treiber wird neu gebaut, danach ist ein "
                              "Neustart nötig."))
    return Finding("crit", _("Grafiktreiber wartet auf einen Neustart"), detail,
                   _("Neustart"), False, "sudo reboot",
                   warn=_("Alles speichern, der Rechner startet sofort neu."),
                   argv=["pkexec", "systemctl", "reboot"])


def check_governor(ctx):
    govs = {read(p) for p in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor")}
    govs.discard(None)
    if not govs or govs == {"performance"}:
        return None
    return Finding("warn", _("CPU-Governor steht auf {gov}").format(
                       gov="/".join(sorted(govs))),
                   _("Unter Last kostet das Takt. performance hält die Kerne oben."),
                   _("Takt"), False,
                   "echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor")


def check_cpu_temp(ctx):
    t = ctx.get("cpu_temp")
    if not t or t < 85:
        return None
    return Finding("crit", _("CPU läuft mit {temp:.0f} °C heiß").format(temp=t),
                   _("Ab etwa 90 °C drosselt der Takt. Lüfterkurve und Kühler prüfen."),
                   f"{t:.0f} °C", False)


def check_gpu_throttle(ctx):
    g = ctx.get("gpu")
    if not g or not g.get("throttled"):
        return None
    return Finding("warn", _("GPU drosselt gerade"),
                   _("Takt {mhz:.0f} MHz bei {temp:.0f} °C. Power-Limit oder "
                     "Kühlung prüfen.").format(mhz=g["clock"], temp=g["temp"]),
                   _("gedrosselt"), False)


def check_filesystems(ctx):
    full = [m for m in ctx.get("mounts", []) if m["total"] and
            100 * m["used"] / m["total"] >= 85]
    if not full:
        return None
    worst = max(full, key=lambda m: m["used"] / m["total"])
    pct = 100 * worst["used"] / worst["total"]
    sev = "crit" if pct >= 90 else "warn"
    detail = (_("{free:.1f} GB von {total:.0f} GB frei").format(
                  free=worst["free"] / 2**30, total=worst["total"] / 2**30)
              + (_(", {n} weitere Partition(en) knapp").format(n=len(full) - 1)
                 if len(full) > 1 else ""))
    title = _("{mount} zu {pct:.0f} % voll").format(mount=worst["target"], pct=pct)
    badge = _("{free:.0f} GB frei").format(free=worst["free"] / 2**30)
    if worst["target"] != "/":
        # Auf einer Datenpartition liegt kein einziges Paket. Ein apt-Befehl
        # wuerde dort nichts freiraeumen, also nur melden statt etwas anzubieten.
        return Finding(sev, title,
                       detail + _(". Hier liegen deine eigenen Daten, aufräumen "
                       "musst du von Hand. Was am meisten belegt, steht unter "
                       "Speicher."),
                       badge, False)
    return Finding(sev, title, detail, badge, False,
                   "sudo apt autoremove --purge && sudo apt clean",
                   argv=["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                         "apt-get", "autoremove", "--purge", "-y"],
                   warn=_("Entfernt Pakete, die kein anderes Paket mehr braucht. "
                          "Die Liste steht vor dem Löschen im Protokoll."))


def os_release(key):
    m = re.search(rf'^{key}="?([^"\n]+)"?$', read("/etc/os-release") or "", re.M)
    return m.group(1) if m else ""


def parse_release_upgrade(text):
    """Version aus der Ausgabe von 'do-release-upgrade -c', sonst leer."""
    m = re.search(r"New release '([^']+)' available", text)
    return m.group(1) if m else ""


# Erst gefunden, dann in dieser Reihenfolge probiert. Der Nachsatz ist das,
# was vor das eigentliche Kommando gehoert.
TERMINALS = [("kitty", []), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
             ("xfce4-terminal", ["-x"]), ("x-terminal-emulator", ["-e"]),
             ("xterm", ["-e"])]


def terminal_cmd(argv):
    """argv in einem sichtbaren Terminal starten. Leer, wenn keins da ist."""
    for name, prefix in TERMINALS:
        if shutil.which(name):
            return [name] + prefix + argv
    return []


META_RELEASE = "https://changelogs.ubuntu.com/meta-release"


def parse_meta_release(text):
    """Ubuntus Releaseliste zu [(Version, Codename, unterstützt)]."""
    out = []
    for block in text.split("\n\n"):
        f = dict(re.findall(r"^([\w-]+): (.+)$", block, re.M))
        if f.get("Version"):
            out.append((f["Version"].strip(), f.get("Dist", "").strip(),
                        f.get("Supported", "0").strip() == "1"))
    return out


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:2])


def newer_release(current, releases):
    """Höchstes unterstütztes Release oberhalb der laufenden Version."""
    cur = version_tuple(current)
    newer = [r for r in releases if r[2] and version_tuple(r[0]) > cur]
    return max(newer, key=lambda r: version_tuple(r[0])) if newer else None


def fetch_releases(url=META_RELEASE, timeout=20):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse_meta_release(r.read().decode("utf-8", "replace"))
    except Exception as e:                       # Netz aus, DNS weg, Proxy
        print(f"Releaseliste nicht erreichbar: {e}", file=sys.stderr)
        return []


UBUNTU_HOSTS = ("archive.ubuntu.com", "security.ubuntu.com", "ports.ubuntu.com",
                "extras.ubuntu.com", "changelogs.ubuntu.com", "esm.ubuntu.com")


def parse_apt_source(text):
    """[(uri, suite)] aus einer sources.list-Zeile oder einer deb822-Datei."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("deb ") or line.startswith("deb-src "):
            toks = re.sub(r"\[[^\]]*\]", " ", line).split()
            if len(toks) >= 3:
                out.append((toks[1], toks[2]))
            elif len(toks) == 2:               # 'deb uri ./' ohne Suite
                out.append((toks[1], "./"))
    uris = re.findall(r"^URIs:\s*(.+)$", text, re.M)
    suites = re.findall(r"^Suites:\s*(.+)$", text, re.M)
    for uri, suite in zip(uris, suites):
        for u in uri.split():
            for s in suite.split():
                out.append((u, s))
    return out


def third_party_sources():
    """Fremdquellen als [(Name, uri, suite)]. Ubuntus eigene bleiben draußen."""
    out = []
    files = (glob.glob("/etc/apt/sources.list.d/*.list")
             + glob.glob("/etc/apt/sources.list.d/*.sources")
             + ["/etc/apt/sources.list"])
    for path in sorted(files):
        text = read(path)
        if not text:
            continue
        name = os.path.basename(path).rsplit(".", 1)[0]
        for uri, suite in parse_apt_source(text):
            if any(h in uri for h in UBUNTU_HOSTS):
                continue
            if (name, uri, suite) not in out:
                out.append((name, uri, suite))
    return out


def source_ready(uri, codename, timeout=8):
    """Hat die Quelle schon eine Paketliste für das neue Release?"""
    url = uri.rstrip("/") + f"/dists/{codename}/Release"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def local_packages():
    """Selbst installierte .deb-Pakete ohne Quelle im Archiv."""
    out = []
    for line in sh(["apt", "list", "--installed"], timeout=60).splitlines():
        if ",local]" in line or "[installed,local]" in line:
            out.append(line.split("/")[0])
    return sorted(out)


def dkms_modules():
    return sorted({line.split("/")[0] for line in
                   sh(["dkms", "status"], timeout=30).splitlines() if "/" in line})


def flatpak_index():
    """{kleingeschriebener letzter Teil der App-ID: App-ID} über alle Remotes.

    Ein Aufruf für alle, statt pro Programm einmal zu suchen. Bei rund 5000
    angebotenen Refs ist der Abgleich danach kostenlos.
    """
    index = {}
    for line in sh(["flatpak", "remote-ls", "--columns=application"],
                   timeout=90).splitlines():
        app = line.strip()
        if app and "." in app:
            index.setdefault(app.rsplit(".", 1)[-1].lower(), app)
    return index


def ppa_program(name):
    """Programmname aus einem PPA-Dateinamen: owner-ubuntu-PROGRAMM-codename."""
    m = re.match(r"^.+?-ubuntu-(.+)-[a-z]+$", name)
    return m.group(1) if m else name


def upgrade_report(codename="", version=""):
    """Was ein Release-Wechsel auf diesem Rechner konkret bedeutet.

    Bewusst am echten System ermittelt statt allgemein erklärt: welche Quelle
    das neue Release schon kennt, sieht man nur, wenn man nachsieht.
    """
    lines = []
    snaps = len([x for x in sh(["snap", "list"], timeout=30).splitlines()[1:] if x]) \
        if shutil.which("snap") else 0
    flat = len(sh(["flatpak", "list", "--columns=ref"], timeout=30).splitlines()) \
        if shutil.which("flatpak") else 0
    local = local_packages()
    dkms = dkms_modules()

    lines.append(_("BLEIBT ERHALTEN"))
    lines.append(_("  Home-Verzeichnis, Einstellungen und Dokumente"))
    if snaps or flat:
        lines.append(_("  {snaps} Snaps und {flatpaks} Flatpaks, sie bringen ihre "
                       "Bibliotheken selbst mit").format(snaps=snaps, flatpaks=flat))
    flatpaks = flatpak_index() if shutil.which("flatpak") else {}
    if local:
        lines.append(_("  {n} selbst installierte Pakete bleiben liegen, bekommen "
                       "aber weiterhin keine Updates:").format(n=len(local)))
        lines.append("    " + ", ".join(local[:12])
                     + (" …" if len(local) > 12 else ""))
        alt = [(p, flatpaks[p.lower()]) for p in local if p.lower() in flatpaks]
        if alt:
            lines.append(_("  Davon gibt es als Flatpak, der Upgrades unbeschadet "
                           "übersteht und Updates bekommt:"))
            for pkg, app in alt:
                lines.append(f"    {pkg} → flatpak install {app}")
    lines.append(_("  Autostart-Einträge und eigene systemd-Dienste"))

    if dkms:
        lines.append("")
        lines.append(_("WIRD NEU GEBAUT"))
        for m in dkms:
            lines.append(_("  {module} über DKMS").format(module=m))
        lines.append(_("  Scheitert der Bau, startet das System ohne dieses Modul. "
                       "Bei Grafiktreibern heißt das: Anmeldung ohne "
                       "Beschleunigung."))

    sources = third_party_sources()
    if sources and codename:
        ready, waiting = [], []
        for name, uri, suite in sources:
            # Nur Quellen, die den Codenamen fest eingetragen haben, sind
            # ueberhaupt betroffen. 'stable' oder './' laufen einfach weiter.
            if suite not in (os_release("VERSION_CODENAME"), ""):
                ready.append((name, suite))
            elif source_ready(uri, codename):
                ready.append((name, codename))
            else:
                waiting.append((name, uri))
        if waiting:
            lines.append("")
            lines.append(_("WIRD ABGESCHALTET, solange es kein {codename} gibt"
                           ).format(codename=codename))
            for name, uri in waiting:
                lines.append(f"  {name}  ({uri.split('/')[2] if '/' in uri else uri})")
            lines.append(_("  Diese Programme bleiben installiert, bekommen aber "
                           "keine Updates mehr, bis der Anbieter nachzieht. Ob er "
                           "das tut, hängt am Anbieter, nicht am Point-Release "
                           "von Ubuntu."))
            alt = [(n, flatpaks[ppa_program(n).lower()]) for n, _u in waiting
                   if ppa_program(n).lower() in flatpaks]
            if alt:
                lines.append(_("  Vom Anbieter unabhängig macht dich der Flatpak:"))
                for name, app in alt:
                    lines.append(f"    {ppa_program(name)} → flatpak install {app}")
        if ready:
            lines.append("")
            lines.append(_("LÄUFT WEITER"))
            lines.append("  " + ", ".join(n for n, _s in ready[:14])
                         + (" …" if len(ready) > 14 else ""))

    lines.append("")
    lines.append(_("VORBEREITUNG"))
    try:
        s = os.statvfs("/")
        free = s.f_bavail * s.f_frsize / 2**30
        lines.append(_("  {free:.0f} GB frei auf /, ").format(free=free)
                     + (_("das reicht") if free >= 10
                        else _("mindestens 10 GB wären nötig")))
    except OSError:
        pass
    lines.append(_("  Snapshot anlegen: ")
                 + (_("Timeshift ist da") if shutil.which("timeshift")
                    else _("Timeshift ist nicht installiert")))
    lines.append(_("  Das Upgrade läuft in einem eigenen Terminal und dauert eine halbe "
                 "bis anderthalb Stunden."))
    return "\n".join(lines)


def check_release_upgrade(ctx):
    """Neues Ubuntu-Release.

    Zwei Quellen, weil sie Verschiedenes wissen: do-release-upgrade sagt, was
    Ubuntu dir offiziell anbietet, die Releaseliste sagt, was es überhaupt gibt.
    Auf LTS klafft dazwischen ein halbes Jahr, weil die Freigabe erst mit dem
    ersten Point-Release kommt. Beides geht ins Netz, also höchstens einmal am Tag.
    """
    current = os_release("VERSION_ID")
    if not current:
        return None
    state = state_read()
    if time.time() - state.get("release_checked", 0) < 24 * 3600:
        offered = state.get("release_offered", "")
        exists = state.get("release_exists", "")
        codename = state.get("release_dist", "")
    else:
        offered = (parse_release_upgrade(sh(["do-release-upgrade", "-c"], timeout=90))
                   if shutil.which("do-release-upgrade") else "")
        found = newer_release(current, fetch_releases())
        exists, codename = (found[0], found[1]) if found else ("", "")
        state_write({**state_read(), "release_checked": time.time(),
                     "release_offered": offered, "release_exists": exists,
                     "release_dist": codename})

    def report():
        return upgrade_report(codename, exists or offered)

    if offered:
        return Finding("warn", _("Ubuntu {v} steht bereit").format(v=offered),
                       _("Aktuell läuft {v}. Der Wechsel dauert je nach Anschluss "
                         "eine halbe bis anderthalb Stunden.").format(v=current),
                       offered, True, "sudo do-release-upgrade",
                       argv=terminal_cmd(["sudo", "do-release-upgrade"]) or None,
                       warn=_("Läuft bewusst in einem eigenen Terminal, nicht in "
                            "diesem Fenster: das Upgrade tauscht Python und GTK "
                            "aus, unter denen dynotiq selbst läuft. Das "
                            "Terminalfenster bis zum Ende offen lassen, sonst "
                            "bricht das Upgrade mittendrin ab. Vorher einen "
                            "Timeshift-Snapshot anlegen."),
                       report=report)
    if exists:
        # Bewusst ohne ausführbaren Befehl: das ändert Systemkonfiguration und
        # nimmt eine Freigabe vorweg, die Ubuntu aus gutem Grund noch nicht gibt.
        return Finding("info", _("Ubuntu {v} ist erschienen").format(v=exists),
                       _("Angeboten wird der Wechsel von {v} aus erst mit dem "
                         "ersten Point-Release, meist im August. Bis dahin wird der "
                         "Upgrade-Weg selbst getestet, und Fremdquellen wie PPAs "
                         "haben oft noch keine Pakete für das neue Release, das "
                         "Upgrade schaltet sie dann ab. Sicherheitsupdates gibt es "
                         "hier noch jahrelang, Warten kostet also nichts. Wer "
                         "trotzdem früher wechseln will, setzt Prompt=normal und "
                         "startet selbst.").format(v=current),
                       exists, True,
                       "sudo sed -i 's/^Prompt=.*/Prompt=normal/' "
                       "/etc/update-manager/release-upgrades && "
                       "sudo do-release-upgrade",
                       report=report)
    return None


def check_hwe_kernel(ctx):
    """Auf LTS bringt der HWE-Stack neueren Kernel und Grafiktreiber."""
    ver = os_release("VERSION_ID")
    if not ver or not shutil.which("apt-cache"):
        return None
    pkg = f"linux-generic-hwe-{ver}"
    policy = sh(["apt-cache", "policy", pkg], timeout=30)
    if not policy.strip() or "Installed: (none)" not in policy:
        return None
    return Finding("warn", _("Neuerer Kernel verfügbar"),
                   _("{pkg} bringt den aktuellen Kernel samt Grafikstack. "
                     "Nach der Installation ist ein Neustart nötig.").format(pkg=pkg),
                   "HWE", True, f"sudo apt install --install-recommends {pkg}",
                   argv=[["pkexec", "apt-get", "update"],
                         ["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                          "apt-get", "install", "-y", "--install-recommends", pkg]],
                   warn=_("Wechselt die Kernel-Serie. Fremde Kernelmodule wie "
                        "VirtualBox oder NVIDIA werden neu gebaut."))


BENCH_LABEL = {"cpu1": _("Ein CPU-Kern"), "cpun": _("Alle CPU-Kerne"),
               "ram": _("Speicherdurchsatz"), "disk": _("Schreibrate der Platte")}


def check_bench_drop(ctx):
    """Ein Messwert allein sagt nichts. Verglichen mit den eigenen früheren
    Läufen wird daraus ein Befund: gedrosselte CPU, alternde SSD, volles
    Dateisystem."""
    runs = history_read(20, kind="bench")
    worst = None
    for key in BENCH_KEYS:
        d = bench_drop(runs, key)
        if d is not None and d < 0 and (worst is None or d < worst[1]):
            worst = (key, d)
    if not worst:
        return None
    key, delta = worst
    base = bench_baseline(runs, key)
    now = [r[key] for r in runs if r.get(key)][-1]
    return Finding("warn", _("{what} {pct:.0f} % langsamer als sonst").format(
                       what=BENCH_LABEL[key], pct=abs(delta) * 100),
                   _("Zuletzt {now:.0f} statt der üblichen {base:.0f}. Typische "
                     "Gründe: Wärmedrosselung, ein volles Dateisystem oder ein "
                     "Hintergrundprozess, der gerade mitläuft.").format(
                         now=now, base=base),
                   f"-{abs(delta) * 100:.0f} %", False)


def check_journal(ctx):
    m = re.search(r"take up ([\d.]+)([KMG]) ", sh(["journalctl", "--disk-usage"]))
    if not m:
        return None
    gb = float(m.group(1)) * {"K": 1 / 2**20, "M": 1 / 1024, "G": 1}[m.group(2)]
    if gb < 2:
        return None
    return Finding("warn", _("Systemjournal belegt {gb:.1f} GB").format(gb=gb),
                   _("Alte Logs lassen sich gefahrlos auf 500 MB eindampfen."),
                   _("{gb:.1f} GB frei").format(gb=gb - 0.5), True,
                   "sudo journalctl --vacuum-size=500M",
                   argv=["pkexec", "journalctl", "--vacuum-size=500M"])


def parse_disabled_snaps(text):
    out = []
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) >= 6 and "disabled" in f[-1]:
            out.append((f[0], f[2]))
    return out


def check_old_snaps(ctx):
    old = parse_disabled_snaps(sh(["snap", "list", "--all"]))
    if not old:
        return None
    return Finding("warn",
                   _("{n} alte Snap-Revisionen liegen herum").format(n=len(old)),
                   ", ".join(sorted({n for n, _r in old})[:6]),
                   _("{n} Pakete").format(n=len(old)), False,
                   "snap list --all | awk '/disabled/{print $1, $3}' | "
                   "while read s r; do sudo snap remove \"$s\" --revision=\"$r\"; done")


def check_autostart(ctx):
    user = [e for e in ctx.get("autostart", []) if e["scope"] == "user" and e["enabled"]]
    if len(user) <= 6:
        return None
    return Finding("warn",
                   _("{n} eigene Autostart-Einträge beim Login").format(n=len(user)),
                   ", ".join(e["name"] for e in user[:5]),
                   _("{n} Einträge").format(n=len(user)), False)


def check_swap(ctx):
    total, free = swapinfo()
    if total == 0 or (total - free) / total < 0.5:
        return None
    return Finding("warn", _("Swap zu {pct:.0f} % belegt").format(
                       pct=100 * (total - free) / total),
                   _("Das System lagert aus. Mehr RAM oder weniger offene Programme."),
                   f"{total - free:.1f} GB", False)


def check_incidents(ctx):
    recent = [i for i in incidents_read()
              if i["sev"] == "crit" and time.time() - i["t"] < 86400]
    if not recent:
        return None
    kinds = sorted({_(i["title"]) for i in recent})
    return Finding("crit", _("{n} kritische Vorfälle in den letzten 24 Stunden"
                             ).format(n=len(recent)),
                   ", ".join(kinds),
                   _("{n} Ereignisse").format(n=len(recent)), False)


def check_journal_rate(ctx):
    """Fünf-Minuten-Stichprobe, ein Vollscan des Journals wäre zu teuer."""
    lines = sh(["journalctl", "--user", "--since", "-5min", "--no-pager", "-o", "cat"],
               timeout=30).count("\n")
    rate = lines / 5
    if rate < 400:
        return None
    top = sh(["bash", "-c", "journalctl --user --since -5min --no-pager -o json "
              "--output-fields=_COMM | sed -n 's/.*\"_COMM\":\"\\([^\"]*\\)\".*/\\1/p' "
              "| sort | uniq -c | sort -rn | head -1"], timeout=30).split()
    who = _(", überwiegend {prog}").format(prog=top[1]) if len(top) > 1 else ""
    return Finding("crit" if rate > 2000 else "warn",
                   _("Journal wächst mit {rate:.0f} Zeilen pro Minute"
                     ).format(rate=rate),
                   _("Hochgerechnet {k:.0f} Tausend Zeilen pro Tag{who}. Das füllt "
                     "die Platte und macht jede Journalsuche langsam.").format(
                         k=rate * 1440 / 1000, who=who),
                   f"{rate:.0f}/min", False,
                   "journalctl --user --since -5min -o json --output-fields=_COMM | "
                   "jq -r ._COMM | sort | uniq -c | sort -rn | head")


def check_updates(ctx):
    out = sh(["apt-get", "-s", "-o", "Debug::NoLocking=1", "upgrade"], timeout=40)
    n = len(re.findall(r"^Inst ", out, re.M))
    if n < 20:
        return None
    return Finding("warn", _("{n} Paket-Updates stehen aus").format(n=n),
                   _("Sicherheits- und Treiber-Updates bleiben sonst liegen."),
                   _("{n} Pakete").format(n=n), False,
                   "sudo apt update && sudo apt upgrade")


def check_self_update(ctx):
    """Neue dynotiq-Version aus dem PPA.

    Bewusst ueber apt statt ueber einen eigenen Downloader: dieselbe Quelle,
    dieselbe Signaturpruefung und derselbe Passwortdialog wie bei jedem anderen
    Paket. Aus dem Quellbaum gestartet gibt es kein installiertes Paket, dann
    meldet sich der Check gar nicht.
    """
    if not shutil.which("apt-cache"):
        return None
    inst, cand, from_repo = parse_apt_policy(
        sh(["apt-cache", "policy", "dynotiq"], timeout=30))
    if not inst or inst == "(none)":
        return None
    if not from_repo:
        # Von Hand eingespielt: es gibt keine Quelle, aus der etwas kaeme.
        # Genau der Mangel, den dynotiq bei fremden Paketen auch anzeigt.
        return Finding("info", _("dynotiq bekommt keine Updates"),
                       _("Version {v} wurde von Hand installiert und steht in "
                         "keiner Paketquelle. Aus dem PPA holt apt neue "
                         "Fassungen von selbst.").format(v=inst),
                       _("von Hand"), False,
                       f"sudo add-apt-repository -y {PPA} && "
                       "sudo apt install dynotiq",
                       argv=[["pkexec", "add-apt-repository", "-y", PPA],
                             ["pkexec", "/usr/bin/env",
                              "DEBIAN_FRONTEND=noninteractive",
                              "apt-get", "install", "-y", "dynotiq"]],
                       warn=_("Trägt die Paketquelle ein und ersetzt die "
                              "Installation durch die aus dem PPA."))
    if not cand or cand == inst:
        return None
    return Finding("info", _("dynotiq {v} ist verfügbar").format(v=cand),
                   _("Installiert ist {v}. Das Update kommt aus der Paketquelle "
                     "und läuft wie jedes andere Paket über apt.").format(v=inst),
                   cand, True, "sudo apt update && sudo apt install dynotiq",
                   argv=[["pkexec", "apt-get", "update"],
                         ["pkexec", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                          "apt-get", "install", "-y", "dynotiq"]],
                   warn=_("Dieses Fenster läuft bis zum Schließen mit der alten "
                          "Fassung weiter."))


CHECKS = [check_gpu_driver, check_incidents, check_journal_rate, check_missing_driver,
          check_cpu_temp,
          check_filesystems, check_gpu_throttle, check_governor, check_journal,
          check_old_snaps, check_autostart, check_swap, check_updates,
          check_hwe_kernel, check_release_upgrade, check_driver_mismatch,
          check_bench_drop, check_self_update]

# info kostet keine Punkte: es ist eine Mitteilung, kein Mangel.
WEIGHT = {"crit": 12, "warn": 4, "info": 0}


def scan(progress=None):
    """progress(erledigt, gesamt) wird nach jedem Schritt gerufen, damit die
    Oberfläche zeigen kann, dass wirklich etwas läuft."""
    total = len(CHECKS) + 2
    if progress:
        progress(0, total)
    incidents_sync()
    if progress:
        progress(1, total)
    ctx = {"gpu": gpu(), "cpu_temp": cpu_temp(), "devices": devices(),
           "mounts": mounts(), "autostart": autostart_entries()}
    findings = []
    for i, fn in enumerate(CHECKS):
        if progress:
            progress(i + 2, total)
        try:
            f = fn(ctx)
        except Exception as e:            # ein kaputter Check darf den Scan nicht killen
            print(f"check {fn.__name__}: {e}", file=sys.stderr)
            continue
        if f:
            findings.append(f)
    if progress:
        progress(total, total)
    findings.sort(key=lambda f: ("crit", "warn", "info").index(f.sev))
    # Grobe Abzüge, bis der Benchmark echte Zahlen liefert.
    score = max(0, 100 - sum(WEIGHT[f.sev] for f in findings))
    return score, findings, ctx


# Vorfälle
#
# Übernommen aus Sentinel Linux-Diagnose: dieselben Muster, dieselben Titel.
# Statt eines Daemons mit SQLite liest der Scan das Journal rückwirkend, denn
# journald hat die Ereignisse ohnehin schon.

AUDIO_UNITS = ["pipewire", "pipewire-pulse", "wireplumber", "pulseaudio",
               "pipewire-media-session", "jackdbus", "jackd"]

INCIDENT_DETECTORS = [
    {"cat": "Audio", "sev": "warn", "title": N_("Audio-Aussetzer erkannt"),
     "scope": ["--user"] + [a for u in AUDIO_UNITS for a in ("-u", u)],
     "pattern": re.compile(r"xrun|underrun|buffer[- ]?underflow", re.I)},
    {"cat": "GPU", "sev": "crit", "title": N_("GPU-Treiberfehler erkannt"),
     "scope": ["-k"],
     "pattern": re.compile(r"gpu has fallen off the bus|gpu reset|gpu hang"
                           r"|display engine.*error", re.I)},
    {"cat": "Speicher", "sev": "crit", "title": N_("OOM-Killer aktiv"), "scope": ["-k"],
     "pattern": re.compile(r"out of memory: killed process|oom-killer", re.I)},
]

# Kategorie-Schluessel bleiben deutsch, sie stehen so in incidents.jsonl. Die
# Anzeige laeuft ueber CAT_LABEL, weil "Speicher" schon die Seite mit den
# Datentraegern heisst und ein msgid nur eine Uebersetzung haben kann.
INCIDENT_CATS = ["Audio", "GPU", "Speicher", "Systemd"]
CAT_LABEL = {"Audio": N_("Audio"), "GPU": N_("GPU"),
             "Speicher": N_("Arbeitsspeicher"), "Systemd": N_("Systemd"),
             "Alle": N_("Alle")}

JOURNAL_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def journal_time(line):
    m = JOURNAL_TS.match(line)
    if not m:
        return time.time()
    return time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))


def strip_prefix(line):
    """Zeitstempel, Host und Unit weg, es bleibt die eigentliche Meldung."""
    parts = line.split(": ", 1)
    return parts[1].strip() if len(parts) == 2 else line.strip()


def unit_episodes(previous, currently_failed, now=None):
    """{Unit: Beginn des aktuellen Ausfalls}.

    Wie known.retain in Sentinels systemd_units.rs: eine reparierte Unit fällt
    aus dem Satz, damit ein erneuter Ausfall wieder als eigener Vorfall zählt.
    Eine durchgehend kaputte Unit behält ihren Beginn und bleibt ein Zustand.
    """
    now = time.time() if now is None else now
    return {u: previous.get(u, now) for u in currently_failed}


def detect_incidents(since="-24h", episodes=None):
    found = []
    for d in INCIDENT_DETECTORS:
        text = sh(["journalctl"] + d["scope"] + ["--since", since, "--no-pager",
                                                 "-o", "short-iso"], timeout=60)
        for line in text.splitlines():
            if d["pattern"].search(line):
                found.append({"t": journal_time(line), "cat": d["cat"], "sev": d["sev"],
                              "title": d["title"], "detail": strip_prefix(line)})
    for unit, began in (episodes if episodes is not None else
                        unit_episodes({}, failed_units())).items():
        found.append({"t": began, "cat": "Systemd", "sev": "warn",
                      "title": N_("systemd-Unit fehlgeschlagen"), "detail": unit})
    found.sort(key=lambda i: i["t"])
    return found


def failed_units():
    out = sh(["systemctl", "--failed", "--no-legend", "--plain"])
    out += sh(["systemctl", "--user", "--failed", "--no-legend", "--plain"])
    return [line.split()[0] for line in out.splitlines() if line.split()]


def incident_key(i):
    # Der Zeitstempel einer Unit ist der Beginn ihres Ausfalls, nicht der
    # Zeitpunkt der Messung. Dadurch bleibt eine dauerhaft kaputte Unit ein
    # Eintrag, ein erneuter Ausfall nach Reparatur wird aber wieder gemeldet.
    if i["cat"] == "Systemd":
        return f"unit|{i['detail']}|{int(i['t'])}"
    return f"{int(i['t'])}|{i['title']}|{i['detail']}"


INCIDENTS_MAX = 3000
INCIDENTS_LOCK = os.path.join(DATA_DIR, "incidents.lock")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
# GUI-Threads und der watch-Dienst schreiben in dieselbe Datei. Der Lock deckt
# die Threads ab, die Lockdatei den zweiten Prozess.
_INC_LOCK = threading.Lock()


def state_read():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def state_write(state):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        print(f"Zustand nicht speicherbar: {e}", file=sys.stderr)


def scan_window(last_check, fallback="-24h", now=None):
    """Ab wann journalctl lesen soll. Seit dem letzten Lauf statt immer 24 h,
    das spart bei laufendem Dienst den Grossteil der Arbeit. Ist der letzte Lauf
    zu lange her oder unbekannt, bleibt es beim vollen Fenster."""
    now = time.time() if now is None else now
    if not last_check or not 0 < now - last_check < 24 * 3600:
        return fallback
    return f"@{int(last_check)}"


def system_snapshot():
    """Messwerte für den Moment, in dem ein Vorfall auftaucht. Ohne die steht
    im Protokoll nur die Fehlermeldung, aber nicht, ob die Karte gerade 87 Grad
    hatte oder der Speicher voll war."""
    snap = {}
    try:
        total, avail = meminfo()
        if total:
            snap["ram"] = round(100 * (total - avail) / total)
        t = cpu_temp()
        if t:
            snap["cpu_temp"] = round(t)
        g = gpu()
        if g:
            snap["gpu_temp"] = round(g["temp"])
            snap["gpu_clock"] = round(g["clock"])
            if g.get("throttled"):
                snap["gpu_throttled"] = True
        load = (read("/proc/loadavg") or "").split()
        if load:
            snap["load"] = float(load[0])
    except (OSError, ValueError, TypeError) as e:
        print(f"Messwerte nicht lesbar: {e}", file=sys.stderr)
    return snap


def format_snapshot(snap):
    """Die Messwerte eines Vorfalls als eine lesbare Zeile."""
    if not snap:
        return ""
    parts = []
    if "cpu_temp" in snap:
        parts.append(_("CPU {temp} °C").format(temp=snap["cpu_temp"]))
    if "gpu_temp" in snap:
        g = _("GPU {temp} °C").format(temp=snap["gpu_temp"])
        if snap.get("gpu_clock"):
            g += _(" bei {mhz} MHz").format(mhz=snap["gpu_clock"])
        if snap.get("gpu_throttled"):
            g += _(", gedrosselt")
        parts.append(g)
    if "ram" in snap:
        parts.append(_("RAM {pct} %").format(pct=snap["ram"]))
    if "load" in snap:
        parts.append(_("Last {load:.1f}").format(load=snap["load"]))
    return " · ".join(parts)


def incidents_sync(since="-24h"):
    """Neue Vorfälle anhängen, schon bekannte überspringen.

    Lesen, Erkennen und Schreiben müssen zusammen unter der Sperre liegen. Das
    Erkennen dauert Sekunden, und in der Zeit schreibt sonst der watch-Dienst
    dieselben Vorfälle ein zweites Mal.
    """
    with _INC_LOCK:
        lock = None
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            lock = open(INCIDENTS_LOCK, "w")
            fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError as e:
            print(f"Vorfallsperre nicht möglich: {e}", file=sys.stderr)
        try:
            state = state_read()
            episodes = unit_episodes(state.get("units", {}), failed_units())
            window = scan_window(state.get("last_check"), since)
            known = {incident_key(i) for i in incidents_read()}
            fresh = [i for i in detect_incidents(window, episodes)
                     if incident_key(i) not in known]
            if fresh:
                # Einmal messen für alle frischen Vorfälle dieses Laufs: sie
                # liegen ohnehin im selben Zeitfenster.
                snap = system_snapshot()
                if snap:
                    for i in fresh:
                        i["sys"] = snap
            state_write({**state, "last_check": time.time(), "units": episodes})
            if not fresh:
                return []
            with open(INCIDENTS_FILE, "a") as f:
                for i in fresh:
                    f.write(json.dumps(i) + "\n")
            if len(known) + len(fresh) > INCIDENTS_MAX:
                lines = open(INCIDENTS_FILE).readlines()[-INCIDENTS_MAX:]
                tmp = INCIDENTS_FILE + ".tmp"
                with open(tmp, "w") as f:
                    f.writelines(lines)
                os.replace(tmp, INCIDENTS_FILE)
            return fresh
        except OSError as e:
            print(f"Vorfälle nicht schreibbar: {e}", file=sys.stderr)
            return []
        finally:
            if lock:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()


def incidents_read(limit=None):
    """Alle Vorfälle, oder die letzten limit. Der Abgleich beim Anhängen braucht
    die ganze Datei, sonst kommen ältere Einträge erneut dazu."""
    out = []
    try:
        with open(INCIDENTS_FILE) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:] if limit else out


# Wissensbasis
#
# Portiert aus sentinel-knowledge. Kein Eintrag darf eine Anzeige blockieren,
# unbekannte Titel bekommen den Fallback.

XID_RE = re.compile(r"xid\s*(?:\([^)]*\))?\s*:?\s*(\d+)", re.I)

XID_KNOWLEDGE = {
    79: ("crit",
         _("Xid 79: GPU has fallen off the bus. Der PCIe-Bus antwortet nicht mehr, die GPU "
         "ist aus Systemsicht komplett verschwunden."),
         [_("Hardwareproblem auf der PCIe-Verbindung (Sitz der Karte, Stromversorgung)"),
          _("Überhitzung oder instabiles Power-Limit/Overclocking"),
          _("Fehlerhafter oder zu alter Treiber")],
         [_("System komplett neu starten (nicht nur die Anwendung), oft hilft nur ein Reboot, "
          "weil die GPU aus dem PCIe-Bus verschwunden ist"),
          _("Kartensitz, PCIe-Stromstecker und Kühlung prüfen"),
          _("Bei Overclocking: Takt und Spannung auf Standardwerte zurücksetzen"),
          _("GPU-Treiber aktualisieren (nvidia-smi -q prüfen)"),
          _("Wiederholt sich das häufig: Temperaturen unter Last beobachten "
          "(nvidia-smi -q -d TEMPERATURE), Netzteil-Kapazität prüfen")]),
    62: ("crit",
         _("Xid 62: interner Mikrocontroller der GPU (PMU) ist stehengeblieben."),
         [_("Instabiler Treiberzustand nach längerer Laufzeit"),
          _("Firmware- oder VBIOS-Problem, selten Hardwaredefekt")],
         [_("nvidia-smi --gpu-reset probieren, falls keine Prozesse mehr auf der GPU laufen, "
          "sonst System neu starten"),
          _("GPU-Treiber aktualisieren"),
          _("Tritt es wiederholt auf: VBIOS-Version prüfen, Hersteller-Support kontaktieren")]),
    43: ("info",
         _("Xid 43: GPU-Kanal wurde zurückgesetzt, die GPU bleibt laut NVIDIA dabei in einem "
         "gesunden Zustand."),
         [_("Meist ein Softwarefehler in der Anwendung, die die GPU genutzt hat")],
         [_("Nur relevant, wenn die betroffene Anwendung abgestürzt ist, dann dort nach einem "
          "Update suchen"),
          _("Tritt es isoliert auf und lief alles weiter: keine Aktion nötig")]),
    8: ("warn",
        _("Xid 8: GPU-Kanal ist wegen eines Timeouts gestoppt worden."),
        [_("Anwendung oder Spiel hat die GPU zu lange blockiert oder ist hängengeblieben")],
        [_("Betroffene Anwendung neu starten"),
         _("Tritt es nur bei einer bestimmten Anwendung auf: dort nach einem Update suchen")]),
    13: ("warn",
         _("Xid 13: Graphics Engine Exception, typischerweise ein Programmierfehler in der "
         "Anwendung, etwa ein Zugriff außerhalb eines Arrays auf der GPU."),
         [_("Bug in der Anwendung oder dem Spiel, das die GPU genutzt hat")],
         [_("Betroffene Anwendung aktualisieren"),
          _("Tritt es nur bei einer bestimmten Anwendung auf: das ist der beste Hinweis auf "
          "die Ursache, gegebenenfalls beim Hersteller melden")]),
    31: ("warn",
         _("Xid 31: GPU-Speicher-Seitenfehler (MMU-Fehler), meist ein Speicherzugriffsfehler "
         "in der Anwendung."),
         [_("Anwendung greift auf ungültigen GPU-Speicherbereich zu")],
         [_("Betroffene Anwendung oder Treiber aktualisieren"),
          _("Kein Hardwaredefekt, laut NVIDIA kein RMA-Grund, wenn es nur bei dieser einen "
          "Anwendung auftritt")]),
    32: ("warn",
         _("Xid 32: beschädigter Command-Buffer, meist ein PCIe-Qualitäts- oder "
         "Treiberproblem, kein direkter Anwendungsfehler."),
         [_("PCIe-Signalqualität (Sitz der Karte, Riser-Kabel)"),
          _("Treiber- oder Speicherkorruption auf Host-Seite")],
         [_("Kartensitz prüfen, bei PCIe-Riser-Kabel einmal ohne testen"),
          _("GPU-Treiber aktualisieren")]),
}


def classify(title, detail):
    """Titel plus Log-Zeile zu Einordnung, Ursachen und Schritten."""
    if title == "Audio-Aussetzer erkannt":
        return ("warn",
                _("Audio-Buffer-Underrun (Xrun): PipeWire oder PulseAudio konnte den Puffer "
                "nicht rechtzeitig füllen, hörbar als kurzes Knacken."),
                [_("Quantum oder Puffergröße zu niedrig für die aktuelle CPU-Last"),
                 _("CPU-Governor auf powersave, der Prozessor taktet nicht schnell genug hoch"),
                 _("Ein anderer Prozess blockiert kurzzeitig CPU oder I/O, etwa Kompilieren "
                 "oder ein Backup"),
                 _("USB-Audio-Gerät mit hoher Latenz oder instabilem Port")],
                [_("pw-top laufen lassen und beobachten, welcher Client die Xruns verursacht"),
                 _("Quantum probeweise erhöhen: "
                 "pw-metadata -n settings 0 clock.force-quantum 1024"),
                 _("Bessert sich das, schrittweise wieder runter (512, 256) bis die Xruns "
                 "zurückkommen, dann eine Stufe höher bleiben"),
                 _("cpupower frequency-info prüfen, Governor auf performance oder schedutil"),
                 _("Bei USB-Audio: anderen Port testen, USB-Autosuspend für das Gerät aus")])
    if title == "OOM-Killer aktiv":
        return ("crit",
                _("Der Kernel hat einen Prozess beendet, weil dem System der Arbeitsspeicher "
                "ausgegangen ist."),
                [_("Ein Prozess hat deutlich mehr Speicher belegt als erwartet, Leck oder "
                 "schlicht zu große Last wie viele Browser-Tabs oder eine RAM-hungrige VM"),
                 _("Zu wenig oder kein Swap bzw. zram als Puffer für Lastspitzen"),
                 _("Mehrere speicherhungrige Programme liefen gleichzeitig")],
                [_("journalctl -k --since \"-1 hour\" | grep -i 'killed process' für Details "
                 "zum getroffenen Prozess (Name, PID, RSS)"),
                 _("free -h ausführen, Speicher- und Swap-Stand prüfen"),
                 _("Falls kein Swap aktiv: zram über systemd-zram-generator oder eine "
                 "Swapdatei einrichten"),
                 _("Betroffenes Programm auf ein Speicherleck prüfen, etwa laufend in htop"),
                 _("Optional systemd-oomd oder earlyoom installieren, damit gezielt statt "
                 "zufällig der unwichtigste Prozess beendet wird")])
    if title == "systemd-Unit fehlgeschlagen":
        unit = detail.strip()
        if unit == "vboxdrv.service":
            return ("warn",
                    _("Das VirtualBox-Kernelmodul konnte nicht geladen werden. Sehr häufig "
                    "durch Secure Boot verursacht, das unsignierte Kernelmodule blockiert."),
                    [_("Secure Boot ist aktiv und das Modul ist nicht signiert oder die "
                     "Signatur liegt nicht im MOK"),
                     _("DKMS-Modul wurde nach einem Kernel-Update nicht neu gebaut")],
                    [_("dmesg | grep -i vbox für die genaue Fehlermeldung"),
                     _("sudo apt install --reinstall virtualbox-dkms baut das Modul neu"),
                     _("sudo modprobe vboxdrv danach erneut versuchen"),
                     _("Bei Secure Boot den MOK-Schlüssel beim nächsten Neustart im "
                     "MOK-Manager bestätigen, alternativ Secure Boot im UEFI abschalten")])
        return ("warn",
                _("Der systemd-Dienst {unit} ist in den failed-Zustand gewechselt."
                  ).format(unit=unit),
                [_("Fehlkonfiguration der Unit oder der Anwendung selbst"),
                 _("Fehlende Abhängigkeit beim Start, etwa Netzwerk oder ein Gerät"),
                 _("Anwendung ist beim Start abgestürzt oder mit Fehlercode beendet")],
                [_("systemctl status {unit} für den genauen Fehlerstatus"
                   ).format(unit=unit),
                 _("journalctl -u {unit} -e für die Logs rund um den Absturz"
                   ).format(unit=unit),
                 _("Nach Beheben der Ursache: systemctl restart {unit}"
                   ).format(unit=unit)])
    if title == "GPU-Treiberfehler erkannt":
        m = XID_RE.search(detail)
        if m and int(m.group(1)) in XID_KNOWLEDGE:
            return XID_KNOWLEDGE[int(m.group(1))]
        if m:
            return ("warn",
                    _("Xid {code}: GPU-Fehler, für diesen Code liegt noch kein "
                      "eigener Eintrag vor.").format(code=m.group(1)),
                    [_("Siehe NVIDIA Xid-Errors-Dokumentation für die Code-Details")],
                    [_("nvidia-bug-report.sh ausführen, falls der Fehler sich wiederholt"),
                     _("GPU-Treiber aktualisieren")])
        return ("warn",
                _("GPU- oder Display-Fehler ohne erkennbaren Xid-Code, etwa ein anderer "
                "Treiber als NVIDIA oder ein Compositor-Neustart."),
                [_("Compositor ist abgestürzt und neugestartet"),
                 _("Treiberfehler eines AMD- oder Intel-Treibers")],
                [_("journalctl -k --since \"-1 hour\" auf weitere Details rund um den "
                 "Zeitpunkt prüfen"),
                 _("Grafiktreiber aktualisieren")])
    return ("info", _("Für diesen Typ gibt es noch keinen Eintrag in der Wissensbasis."),
            [], [_("Journal-Auszug oben manuell prüfen.")])


def notify(title, body):
    sh(["notify-send", "-a", "dynotiq", "-i", "dynotiq", title, body], timeout=10)


def release_notify():
    """Meldet ein freigegebenes Release genau einmal. Die eigentliche Abfrage
    steckt im Check und ist dort schon auf einen Lauf pro Tag begrenzt."""
    f = check_release_upgrade({})
    # sev warn heißt: Ubuntu bietet den Wechsel wirklich an. Ein bloß
    # erschienenes Release ist info und keine Benachrichtigung wert.
    if not f or f.sev != "warn":
        return None
    state = state_read()
    if state.get("release_notified") == f.badge:
        return None
    state_write({**state, "release_notified": f.badge})
    notify(f.title, _("Der Wechsel wird jetzt offiziell angeboten."))
    return f.badge


def watch(interval=30):
    """Hintergrundmodus: Journal abfragen, neue Vorfälle melden."""
    print(f"dynotiq watch: Intervall {interval} s", flush=True)
    incidents_sync("-1h")
    last_release = 0.0
    while True:
        time.sleep(interval)
        if time.time() - last_release > 6 * 3600:
            last_release = time.time()
            try:
                release_notify()
            except Exception as e:
                print(f"watch release: {e}", file=sys.stderr, flush=True)
        try:
            fresh = incidents_sync(f"-{interval * 3}s")
        except Exception as e:
            print(f"watch: {e}", file=sys.stderr, flush=True)
            continue
        # Bewusst ohne den gematchten Text: der landet sonst über stdout wieder
        # im Journal und der nächste Durchlauf findet die eigene Ausgabe.
        if fresh:
            print(f"{len(fresh)} neue Vorfaelle: "
                  + ", ".join(sorted({i["title"] for i in fresh})), flush=True)
        crit = [i for i in fresh if i["sev"] == "crit"]
        if crit:
            notify(_(crit[0]["title"]),
                   crit[0]["detail"][:160].replace("\n", " "))
        elif fresh:
            notify(_("{n} neue Vorfälle").format(n=len(fresh)),
                   _(fresh[0]["title"]))


WATCH_UNIT_TEXT = """[Unit]
Description=dynotiq Hintergrunduberwachung
After=graphical-session.target

[Service]
Type=simple
ExecStart={python} {script} --watch
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def watch_enabled():
    return sh(["systemctl", "--user", "is-enabled", "dynotiq-watch.service"]).strip() \
        == "enabled"


def watch_set(enabled):
    if enabled:
        os.makedirs(os.path.dirname(WATCH_UNIT), exist_ok=True)
        with open(WATCH_UNIT, "w") as f:
            f.write(WATCH_UNIT_TEXT.format(python=sys.executable,
                                           script=os.path.join(APP_DIR, "dynotiq.py")))
        sh(["systemctl", "--user", "daemon-reload"])
        sh(["systemctl", "--user", "enable", "--now", "dynotiq-watch.service"])
    else:
        sh(["systemctl", "--user", "disable", "--now", "dynotiq-watch.service"])
    return watch_enabled()


# Benchmark

def bench_cpu(threads, seconds=2.0):
    """MiB/s SHA-256. hashlib gibt das GIL frei, darum skaliert das über Threads."""
    data = os.urandom(4 << 20)
    counts = [0] * threads
    stop = time.monotonic() + seconds

    def work(i):
        n = 0
        while time.monotonic() < stop:
            hashlib.sha256(data).digest()
            n += 1
        counts[i] = n

    ts = [threading.Thread(target=work, args=(i,)) for i in range(threads)]
    t0 = time.monotonic()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return sum(counts) * 4 / (time.monotonic() - t0)


def bench_ram(seconds=1.5):
    size = 64 << 20
    src, dst = memoryview(bytearray(size)), memoryview(bytearray(size))
    n = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        dst[:] = src
        n += 1
    return n * (size / 2**30) / (time.monotonic() - t0)


def bench_disk(mib=256):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "bench.tmp")
    # Eine Restdatei von einem abgebrochenen Lauf zaehlt beim Platzcheck mit
    if os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass
    # Eine vollgeschriebene Systempartition legt den Rechner lahm. Lieber gar
    # nicht messen als das Risiko eingehen.
    s = os.statvfs(DATA_DIR)
    free_mib = s.f_bavail * s.f_frsize / 2**20
    if free_mib < mib * 4:
        raise OSError(_("Zu wenig Platz für den Test: {free:.0f} MiB frei, "
                        "nötig sind {need:.0f} MiB").format(
                          free=free_mib, need=mib * 4))
    buf = os.urandom(8 << 20)
    try:
        t0 = time.monotonic()
        with open(path, "wb") as f:
            for _block in range(mib // 8):
                f.write(buf)
            f.flush()
            os.fsync(f.fileno())
        return mib / (time.monotonic() - t0)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# CSS

CSS_TEMPLATE = """
window, .page { background: #0E1116; }
headerbar { background-image: linear-gradient(#232932, #1A1F26); border: none;
            box-shadow: inset 0 -1px rgba(0,0,0,.6); min-height: 46px; padding: 0 8px; }
/* Systemthemes malen Buttons per background-image, das muss überall mit weg. */
headerbar windowcontrols button { background-color: #2C333D; background-image: none;
            border: none; box-shadow: none; border-radius: 50%; color: #B9BEC5;
            min-width: 22px; min-height: 22px; padding: 0; margin: 0 2px; }
headerbar windowcontrols button.close { background-color: #C0402B; color: #fff; }
.dot { min-width: 9px; min-height: 9px; border-radius: 2px; background: @ACC@; }
.hb-title { font: 600 12.5px @SANS@; color: #E6E8EA; }
.hb-sub { font: 11px @SANS@; color: #767C85; }

.sidebar { background: #12161B; box-shadow: inset -1px 0 rgba(255,255,255,.06);
           padding: 18px 12px 14px; }
.brand { font: 700 15px @SANS@; color: #EDEEF0; letter-spacing: -0.3px; }
.brandsub { font: 9.5px @SANS@; color: #6F757E; letter-spacing: 0.6px; }
.nav { font: 12.5px @SANS@; color: #9AA1AA; background-color: transparent;
       background-image: none; border: none; box-shadow: none; min-height: 0;
       border-radius: 7px; padding: 8px 10px 8px 22px; }
.nav:hover { background-color: rgba(255,255,255,.05); color: #D6DAE0; }
.nav.active { background-color: @ACC@; background-image: none; color: @ACCTXT@;
              font-weight: 600; box-shadow: none; }
.nav.active:hover { background-color: @ACCHI@; color: @ACCTXT@; }
.navgroup { font: 600 9.5px @SANS@; color: #5E656E; letter-spacing: 1px;
            padding: 14px 0 5px 12px; }
.navbadge { font: 600 10px @SANS@; background: @CRIT@; color: #2A0F0F;
            border-radius: 9px; padding: 2px 7px; }
.rig { background: #1B2027; border: 1px solid rgba(255,255,255,.06);
       border-radius: 9px; padding: 12px; }
.rig-key { font: 600 9.5px @SANS@; color: #6F757E; letter-spacing: 0.7px; }
.rig-val { font: 500 11px @SANS@; color: #C8CDD3; }
.rig-sub { font: 10px @SANS@; color: #6F757E; }

.card { background: #161A20; border: 1px solid rgba(255,255,255,.07); border-radius: 12px; }
.h1 { font: 600 22px @SANS@; color: #F2F3F5; }
.sub { font: 11px @SANS@; color: #767C85; }
.btn-ghost { font: 500 12px @SANS@; color: #C8CDD3; background-color: transparent;
             background-image: none; box-shadow: none; min-height: 0;
             border: 1px solid rgba(255,255,255,.12); border-radius: 8px; padding: 9px 14px; }
.btn-ghost:hover { background-color: rgba(255,255,255,.06); }
.btn-ghost:disabled { color: #5A6069; }
.btn-accent, .btn-fix { color: @ACCTXT@; background-color: @ACC@; background-image: none;
              border: none; box-shadow: none; min-height: 0; }
.btn-accent { font: 600 12px @SANS@; border-radius: 8px; padding: 9px 16px; }
.btn-fix { font: 600 11.5px @SANS@; border-radius: 7px; padding: 8px 14px; }
.btn-accent:hover, .btn-fix:hover { background-color: @ACCHI@; }
.btn-accent:disabled, .btn-fix:disabled { background-color: #272E38; color: #767C85; }
.swatch { border-radius: 8px; border: 1px solid rgba(255,255,255,.12);
          background-color: transparent; background-image: none; box-shadow: none;
          padding: 3px; min-height: 0; }
.swatch.active { border: 2px solid #F2F3F5; padding: 2px; }

.eyebrow { font: 600 10px @SANS@; color: @CRIT@; letter-spacing: 1px; }
.headline { font: 600 29px @SANS@; color: #F2F3F5; }
.lede { font: 12.5px @SANS@; color: #9AA1AA; }
.kpi { background: #1B2027; border-radius: 9px; padding: 11px 12px; }
.kpi-key { font: 9.5px @SANS@; color: #767C85; letter-spacing: 0.7px; }
.kpi-val { font: 700 21px @SANS@; color: #EDEEF0; }
.kpi-unit { font: 12px @SANS@; color: #767C85; }
.state-ok { color: @OK@; } .state-warn { color: @WARN@; } .state-crit { color: @CRIT@; }

.cardhead { font: 600 12.5px @SANS@; color: #E6E8EA; }
.rowsep { background: rgba(255,255,255,.05); min-height: 1px; }
.row-title { font: 500 13px @SANS@; color: #EDEEF0; }
.row-detail { font: 11.5px @SANS@; color: #767C85; }
.mono { font: 11.5px @SANS@; color: #9AA1AA; }
.mono-dim { font: 11px @SANS@; color: #6F757E; }
.pill { font: 600 11px @SANS@; border-radius: 6px; padding: 5px 9px;
        background: rgba(255,255,255,.07); color: #C8CDD3; }
.pill.ok { background: @OK12@; color: @OK@; }
.pill.warn { background: @WARN12@; color: @WARN@; }
.pill.crit { background: @CRIT12@; color: @CRIT@; }
.bullet-crit { min-width: 8px; min-height: 8px; border-radius: 50%; background: @CRIT@; }
.bullet-warn { min-width: 8px; min-height: 8px; border-radius: 50%; background: @WARN@; }
.bullet-ok { min-width: 8px; min-height: 8px; border-radius: 50%; background: @OK@; }
.bullet-info { min-width: 8px; min-height: 8px; border-radius: 50%; background: #6F757E; }
.tile-key { font: 500 10.5px @SANS@; color: #767C85; letter-spacing: 0.6px; }
.tile-val { font: 700 15px @SANS@; color: #EDEEF0; }
.big-val { font: 700 27px @SANS@; color: #EDEEF0; }
.empty { font: 13px @SANS@; color: #767C85; }
switch { background-color: #272E38; background-image: none; border: none;
         box-shadow: none; border-radius: 12px; }
switch:checked { background-color: @ACC@; background-image: none; }
switch > slider { background-color: #E8EBEE; background-image: none; border: none;
                  box-shadow: none; min-width: 18px; min-height: 18px;
                  border-radius: 50%; margin: 1px; }
dropdown > button { background-color: #1B2027; background-image: none; border: none;
                    box-shadow: none; color: #D6DAE0; border-radius: 7px; min-height: 0;
                    padding: 7px 10px; font: 12px @SANS@; }
popover contents { background-color: #1B2027; color: #D6DAE0; border-radius: 9px; }
scrollbar { background: transparent; }
scrollbar slider { background: rgba(255,255,255,.16); border-radius: 8px; min-width: 7px; }
tooltip { background: #1B2027; color: #D6DAE0; }
/* Gleich breite Ziffern, sonst zappeln die Live-Werte bei jeder Aktualisierung
   und Spalten stehen nicht untereinander. */
.kpi-val, .kpi-unit, .tile-val, .big-val, .mono, .mono-dim, .pill, .navbadge,
.rig-sub, .sub { font-feature-settings: "tnum" 1; }
textview { font-family: @MONO@; }
"""


def alpha(hexcol, a):
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{a})"


def lighten(hexcol, f=0.25):
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(min(255, int(c + (255 - c) * f)) for c in (r, g, b))


def darken(hexcol, f=0.90):
    """Schrift auf farbigem Grund. Aus der Farbe selbst abgeleitet statt fest
    dunkelgrau: das haelt den Farbton und traegt auf jedem Akzent weiter."""
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(int(c * (1 - f)) for c in (r, g, b))


# Inter ist die modernste freie Oberflaechenschrift, Ubuntu liegt auf dem
# Zielsystem immer bereit. Beide OFL beziehungsweise Ubuntu Font Licence.
SANS = "Inter, Ubuntu, 'Noto Sans', sans-serif"
MONO = "'JetBrains Mono', 'Ubuntu Mono', monospace"


def first_font(*names):
    """Der erste Name, den fontconfig wirklich liefert. Cairo nimmt keine
    Liste und zeichnet sonst stumm mit einer Ersatzschrift."""
    for name in names:
        got = sh(["fc-match", "-f", "%{family}", name], timeout=10)
        if got and name.lower() in got.lower():
            return name
    return "sans-serif"


CAIRO_SANS = first_font("Inter", "Ubuntu", "Noto Sans")


def build_css():
    css = CSS_TEMPLATE
    for token, value in (("@SANS@", SANS), ("@MONO@", MONO),
                         ("@ACC13@", alpha(COLORS["acc"], .13)),
                         ("@ACCHI@", lighten(COLORS["acc"])),
                         ("@ACCTXT@", darken(COLORS["acc"])),
                         ("@ACC@", COLORS["acc"]),
                         ("@OK12@", alpha(COLORS["ok"], .12)),
                         ("@OK@", COLORS["ok"]),
                         ("@WARN12@", alpha(COLORS["warn"], .12)),
                         ("@WARN@", COLORS["warn"]),
                         ("@CRIT12@", alpha(COLORS["crit"], .12)),
                         ("@CRIT@", COLORS["crit"])):
        css = css.replace(token, value)
    return css


# Widgets

# Die Seitennamen sind Schluessel: sie stehen in self.pages, im Builder-Dict
# und in --page auf der Kommandozeile. Uebersetzt wird erst bei der Anzeige.
NAV_GROUPS = [
    (_("DIAGNOSE"), [N_("Übersicht"), N_("Probleme"), N_("Vorfälle"),
                     N_("Treiber")]),
    (_("SYSTEM"), [N_("Updates"), N_("App-Check"), N_("Autostart"),
                   N_("Live-Monitor"), N_("Speicher")]),
    (_("DATEN"), [N_("Prüfstand"), N_("Benchmark"), N_("Verlauf"),
                  N_("Einstellungen")]),
]
NAV = [name for _g, names in NAV_GROUPS for name in names]


def lbl(text, css="", xalign=0.0, wrap=False, chars=52):
    w = Gtk.Label(label=text, xalign=xalign)
    if css:
        w.add_css_class(css)
    if wrap:
        w.set_wrap(True)
        w.set_max_width_chars(chars)
    return w


def box(horiz=False, spacing=0, **kw):
    o = Gtk.Orientation.HORIZONTAL if horiz else Gtk.Orientation.VERTICAL
    return Gtk.Box(orientation=o, spacing=spacing, **kw)


def card(child, pad=16):
    c = box()
    c.add_css_class("card")
    child.set_margin_top(pad)
    child.set_margin_bottom(pad)
    child.set_margin_start(pad)
    child.set_margin_end(pad)
    c.append(child)
    return c


def card_head(title, right=None):
    h = box(True, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18)
    h.append(lbl(title, "cardhead"))
    r = right if isinstance(right, Gtk.Widget) else lbl(right or "", "sub", xalign=1.0)
    r.set_hexpand(True)
    r.set_halign(Gtk.Align.END)
    h.append(r)
    return h


def sep():
    s = Gtk.Box()
    s.add_css_class("rowsep")
    return s


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def fmt_bytes(n):
    for unit, size in (("TB", 2**40), ("GB", 2**30), ("MB", 2**20), ("kB", 2**10)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} B"


def clear(widget):
    child = widget.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        widget.remove(child)
        child = nxt


class Ring(Gtk.DrawingArea):
    def __init__(self, size=186):
        super().__init__(content_width=size, content_height=size)
        self.value = 0
        self.busy = False
        self.angle = 0.0
        self.step = 0            # erledigte Prüfungen
        self.steps = 0           # Prüfungen gesamt
        self.timer = None
        self.set_draw_func(self._draw)

    def set_value(self, v):
        self.value = v
        self.queue_draw()

    def set_busy(self, busy, steps=0):
        """Während des Scans dreht ein Bogen, statt dass eine tote Zahl steht."""
        self.busy = busy
        self.step, self.steps = 0, steps
        if busy and not self.timer:
            self.timer = GLib.timeout_add(40, self._spin)
        elif not busy and self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.queue_draw()

    def set_step(self, done, total):
        self.step, self.steps = done, total
        self.queue_draw()

    def _spin(self):
        if not self.busy:
            self.timer = None
            return False
        self.angle = (self.angle + 0.16) % 6.2832
        self.queue_draw()
        return True

    def _neon(self, cr, cx, cy, r, start, end, hexcol, fade=1.0):
        """Bogen mit Leuchten: weiche breite Lagen aussen, harter Kern innen.

        Cairo kann nicht weichzeichnen, deshalb von Hand gestapelt. Die
        Radien sind so gewaehlt, dass das Leuchten innerhalb der Flaeche
        bleibt, sonst schneidet die DrawingArea es ab.
        """
        base = rgb(hexcol)
        cr.set_line_cap(1)
        for width, a in ((28, .06), (21, .10), (15, .16)):
            cr.set_line_width(width)
            cr.set_source_rgba(*base, a * fade)
            cr.arc(cx, cy, r, start, end)
            cr.stroke()
        cr.set_line_width(12)
        cr.set_source_rgba(*base, fade)
        cr.arc(cx, cy, r, start, end)
        cr.stroke()
        # Aufgehellter Kern, erst der macht aus dem Bogen eine Leuchtroehre.
        cr.set_line_width(3.5)
        cr.set_source_rgba(*rgb(lighten(hexcol, .6)), .85 * fade)
        cr.arc(cx, cy, r, start, end)
        cr.stroke()

    def _draw(self, _a, cr, w, h):
        cx, cy = w / 2, h / 2
        # Farbe aus der gewaehlten Palette, damit der Ring die Ampel bleibt.
        col = COLORS["ok"] if self.value >= 85 else COLORS["warn"] if self.value >= 60 \
            else COLORS["crit"]
        cr.set_source_rgba(1, 1, 1, .06)
        cr.set_line_width(1)
        cr.set_dash([1, 5])
        cr.arc(cx, cy, w / 2 - 11, 0, 6.2832)
        cr.stroke()
        cr.set_dash([])
        cr.set_line_width(12)
        cr.set_source_rgb(*rgb("#232830"))
        cr.arc(cx, cy, w / 2 - 22, 0, 6.2832)
        cr.stroke()
        r = w / 2 - 22
        if self.busy:
            # Gefüllter Teil ist der echte Fortschritt, der laufende Bogen zeigt,
            # dass gerade wirklich etwas passiert.
            if self.steps:
                self._neon(cr, cx, cy, r, -1.5708,
                           -1.5708 + 6.2832 * self.step / self.steps,
                           COLORS["acc"], .35)
            self._neon(cr, cx, cy, r, self.angle, self.angle + 1.1, COLORS["acc"])
        elif self.value > 0:
            self._neon(cr, cx, cy, r, -1.5708,
                       -1.5708 + 6.2832 * self.value / 100, col)
        cr.select_font_face(CAIRO_SANS, 0, 1)
        cr.set_source_rgb(*rgb("#F2F3F5"))
        cr.set_font_size(54)
        t = f"{self.step}/{self.steps}" if self.busy and self.steps else str(int(self.value))
        if self.busy and self.steps:
            cr.set_font_size(30)
        e = cr.text_extents(t)
        cr.move_to(cx - e.width / 2 - e.x_bearing, cy + 8)
        cr.show_text(t)
        cr.select_font_face(CAIRO_SANS, 0, 0)
        cr.set_source_rgb(*rgb("#767C85"))
        cr.set_font_size(11)
        t = "P R Ü F U N G E N" if self.busy and self.steps else "V O N  1 0 0"
        e = cr.text_extents(t)
        cr.move_to(cx - e.width / 2 - e.x_bearing, cy + 31)
        cr.show_text(t)


class Spark(Gtk.DrawingArea):
    def __init__(self, lo, hi, color_key="acc", points=13, height=26):
        super().__init__(content_height=height, hexpand=True)
        self.lo, self.hi, self.color_key = lo, hi, color_key
        self.vals = deque(maxlen=points)
        self.set_draw_func(self._draw)

    def push(self, v):
        self.vals.append(v)
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        if len(self.vals) < 2:
            return
        span = max(self.hi - self.lo, 1)
        step = w / (self.vals.maxlen - 1)
        cr.set_source_rgb(*rgb(COLORS[self.color_key]))
        cr.set_line_width(1.6)
        for i, v in enumerate(self.vals):
            y = h - 3 - (h - 6) * min(max((v - self.lo) / span, 0), 1)
            (cr.line_to if i else cr.move_to)(i * step, y)
        cr.stroke()


class Chart(Gtk.DrawingArea):
    """Mehrere Reihen über einer festen Fensterbreite, y-Achse optional automatisch."""

    def __init__(self, series, points=60, top=100, height=130, unit="%"):
        super().__init__(content_height=height, hexpand=True)
        self.series = series
        self.top, self.unit = top, unit
        self.data = {k: deque([0.0] * points, maxlen=points) for k, _ in series}
        self.set_draw_func(self._draw)

    def push(self, values):
        for k, v in values.items():
            if k in self.data:
                self.data[k].append(v)
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        top = self.top or max(1.0, max(max(d) for d in self.data.values()) * 1.2)
        cr.select_font_face(CAIRO_SANS, 0, 0)
        cr.set_font_size(9)
        for i in range(5):
            y = 6 + (h - 20) * i / 4
            cr.set_source_rgba(1, 1, 1, .05)
            cr.set_line_width(1)
            cr.move_to(34, y)
            cr.line_to(w, y)
            cr.stroke()
            cr.set_source_rgb(*rgb("#6F757E"))
            cr.move_to(2, y + 3)
            cr.show_text(f"{top * (4 - i) / 4:.0f}")
        for key, color_key in self.series:
            vals = self.data[key]
            step = (w - 36) / max(len(vals) - 1, 1)
            cr.set_source_rgb(*rgb(COLORS[color_key]))
            cr.set_line_width(1.8)
            for i, v in enumerate(vals):
                y = 6 + (h - 20) * (1 - min(max(v / top, 0), 1))
                (cr.line_to if i else cr.move_to)(34 + i * step, y)
            cr.stroke()


class Bar(Gtk.DrawingArea):
    def __init__(self, fraction=0.0, height=8, vertical=False):
        super().__init__(content_height=height, hexpand=True)
        self.fraction, self.vertical = fraction, vertical
        self.set_draw_func(self._draw)

    def set_fraction(self, f):
        self.fraction = f
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        col = COLORS["ok"] if self.fraction < .75 else COLORS["warn"] \
            if self.fraction < .9 else COLORS["crit"]
        f = min(max(self.fraction, 0), 1)
        cr.set_source_rgb(*rgb("#232830"))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgb(*rgb(col))
        if self.vertical:
            cr.rectangle(0, h * (1 - f), w, h * f)
        else:
            cr.rectangle(0, 0, w * f, h)
        cr.fill()


class Swatch(Gtk.DrawingArea):
    def __init__(self, color, size=26):
        super().__init__(content_width=size, content_height=size)
        self.color = color
        self.set_draw_func(self._draw)

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(*rgb(self.color))
        cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 6.2832)
        cr.fill()


# Tray läuft direkt über StatusNotifierItem: GTK4 hat kein StatusIcon und
# libayatana-appindicator ist gegen GTK3 gebaut, lässt sich also nicht laden.

SNI_XML = """<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/><arg name="dir" type="s" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>"""

MENU_XML = """<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/><arg type="i" name="parent"/>
    </signal>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updated"/><arg type="a(ias)" name="removed"/>
    </signal>
  </interface>
</node>"""


class Tray:
    def __init__(self, items, tooltip=_("Systemdiagnose"), on_ready=None):
        self.items = items                  # [(id, label, callback)], label None = Trenner
        self.tooltip = tooltip
        self.on_ready = on_ready
        self.bus = None
        self.ok = False
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
            menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
            self.bus.register_object("/StatusNotifierItem", sni, self._sni_call,
                                     self._sni_get, None)
            self.bus.register_object("/MenuBar", menu, self._menu_call, self._menu_get, None)
            self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
            Gio.bus_own_name_on_connection(self.bus, self.name,
                                           Gio.BusNameOwnerFlags.NONE, self._acquired, None)
            # Der Watcher kann später kommen (Autostart vor der Erweiterung) und
            # wieder verschwinden (Shell-Neustart). Beides muss ankommen, sonst
            # versteckt sich das Fenster in einen Tray, den es nicht mehr gibt.
            Gio.bus_watch_name_on_connection(
                self.bus, "org.kde.StatusNotifierWatcher",
                Gio.BusNameWatcherFlags.NONE, self._watcher_up, self._watcher_gone)
        except GLib.Error as e:
            print(f"tray: nicht verfügbar ({e.message})", file=sys.stderr)

    def _acquired(self, conn, name):
        self.owned = True
        self._register()

    def _watcher_up(self, _conn, _name, _owner):
        self._register()

    def _watcher_gone(self, _conn, _name):
        self.ok = False
        print("tray: StatusNotifierWatcher verschwunden", file=sys.stderr)

    def _register(self):
        """Beim Watcher anmelden. Läuft asynchron, sonst steht der Mainloop bis
        zum Timeout, wenn die Shell gerade ihre Erweiterungen lädt."""
        if self.ok or not self.bus or not getattr(self, "owned", False):
            return

        def done(conn, res):
            try:
                conn.call_finish(res)
            except GLib.Error as e:
                print(f"tray: kein StatusNotifierWatcher ({e.message})", file=sys.stderr)
                return
            self.ok = True
            if self.on_ready:
                GLib.idle_add(self.on_ready)

        self.bus.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                      "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self.name,)), None,
                      Gio.DBusCallFlags.NONE, 5000, None, done)

    def set_tooltip(self, text):
        self.tooltip = text
        if self.bus:
            try:
                self.bus.emit_signal(None, "/StatusNotifierItem",
                                     "org.kde.StatusNotifierItem", "NewToolTip", None)
            except GLib.Error:
                pass

    def _sni_get(self, _c, _s, _p, _i, prop):
        vals = {
            "Category": ("s", "SystemServices"), "Id": ("s", "dynotiq"),
            "Title": ("s", "dynotiq"), "Status": ("s", "Active"),
            "IconName": ("s", "dynotiq-tray"), "IconThemePath": ("s", TRAY_ICON_DIR),
            "AttentionIconName": ("s", ""), "OverlayIconName": ("s", ""),
            "ItemIsMenu": ("b", True), "Menu": ("o", "/MenuBar"),
            "WindowId": ("u", 0),
        }
        if prop == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("dynotiq-tray", [], "dynotiq", self.tooltip))
        sig, val = vals.get(prop, ("s", ""))
        return GLib.Variant(sig, val)

    def _sni_call(self, _c, _s, _p, _i, method, params, inv):
        # ContextMenu muss deklariert sein, sonst antwortet GDBus mit
        # UnknownMethod und der Rechtsklick tut bei Hosts ohne dbusmenu nichts.
        if method in ("Activate", "SecondaryActivate", "ContextMenu"):
            self._fire(self.items[0][0])
        inv.return_value(None)

    def _props(self, item):
        _id, label, _cb = item
        if label is None:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", label),
                "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True)}

    def _menu_get(self, _c, _s, _p, _i, prop):
        return {"Version": GLib.Variant("u", 2),
                "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"),
                "IconThemePath": GLib.Variant("as", [TRAY_ICON_DIR])}.get(
                    prop, GLib.Variant("s", ""))

    def _menu_call(self, _c, _s, _p, _i, method, params, inv):
        if method == "GetLayout":
            # Nur die Kinder dürfen fertige Variants sein, das Wurzel-Struct nicht:
            # PyGObject packt ein Variant an Struct-Stelle wieder aus und verliert
            # dabei die Typen in a{sv}.
            children = [GLib.Variant("(ia{sv}av)", (i[0], self._props(i), []))
                        for i in self.items]
            root = (0, {"children-display": GLib.Variant("s", "submenu")}, children)
            inv.return_value(GLib.Variant("(u(ia{sv}av))", (1, root)))
        elif method == "GetGroupProperties":
            inv.return_value(GLib.Variant("(a(ia{sv}))",
                                          ([(i[0], self._props(i)) for i in self.items],)))
        elif method == "GetProperty":
            item = next((i for i in self.items if i[0] == params[0]), None)
            val = self._props(item).get(params[1], GLib.Variant("s", "")) if item \
                else GLib.Variant("s", "")
            inv.return_value(GLib.Variant("(v)", (val,)))
        elif method == "Event":
            if params[1] == "clicked":
                self._fire(params[0])
            inv.return_value(None)
        elif method == "AboutToShow":
            inv.return_value(GLib.Variant("(b)", (False,)))
        else:
            inv.return_value(None)

    def _fire(self, item_id):
        for i, label, cb in self.items:
            if i == item_id and cb:
                GLib.idle_add(cb)
                return


class App(Gtk.Application):
    def __init__(self, start_page="Übersicht"):
        super().__init__(application_id=APP_ID)
        self.start_page = start_page
        self.cfg = load_config()
        apply_colors(self.cfg)
        self.prev_cpu = cpu_times()
        self.prev_cores = cpu_times(per_core=True)
        self.prev_net = net_bytes()
        self.prev_disk = disk_bytes()
        self.prev_procs = {p["pid"]: p["cpu"] for p in processes()}
        self.prev_t = time.monotonic()
        self.findings = []
        self.score = 0
        self.built = set()
        self.tick_id = None
        self.gpu_busy = False
        self.procs_busy = False
        self.dyno_id = None
        self.dyno_samples = []
        self.upd_running = False

    def do_activate(self):
        if self.win_exists():
            # Aus dem Tray zurückgeholt oder zweiter Start: Fenster wieder zeigen,
            # sonst passiert bei einem Klick im Menü sichtbar nichts.
            self.win.set_visible(True)
            self.win.present()
            self.restart_tick()
            return
        ensure_icons()
        ensure_desktop()
        self.provider = Gtk.CssProvider()
        # 900 > PRIORITY_USER (800): eigene Themes im Home dürfen das Design nicht kippen.
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),
                                                  self.provider, 900)
        self.apply_css()

        Gtk.Window.set_default_icon_name("dynotiq")
        self.win = Gtk.ApplicationWindow(application=self, default_width=1180,
                                         default_height=800, title="dynotiq",
                                         icon_name="dynotiq")
        hb = Gtk.HeaderBar(show_title_buttons=True)
        t = box(True, 10)
        t.append(self._logo(18))
        t.append(lbl("dynotiq", "hb-title"))
        t.append(lbl(self._distro(), "hb-sub"))
        hb.set_title_widget(Gtk.Box())
        hb.pack_start(t)
        self.win.set_titlebar(hb)

        root = box(True)
        root.append(self._sidebar())
        self.stack = Gtk.Stack(hexpand=True)
        self.stack.add_css_class("page")
        self.pages = {}
        for name in NAV:
            holder = box()
            self.pages[name] = holder
            self.stack.add_named(holder, name)
        root.append(self.stack)
        self.win.set_child(root)

        self._build("Übersicht")
        self.win.connect("close-request", self._on_close)
        self.win.present()
        # Erst wenn das Fenster steht, sonst hängt der Dialog vor dem Nichts.
        GLib.idle_add(self._maybe_intro)
        if self.start_page in NAV and self.start_page != "Übersicht":
            self._nav_clicked(self.nav_buttons[self.start_page], self.start_page)

        self.tray = Tray([(1, _("dynotiq öffnen"), self._tray_open),
                          (2, _("Neu scannen"), self._tray_rescan),
                          (3, None, None),
                          (4, _("Beenden"), self._tray_quit)], on_ready=self._tray_ready)
        self.rescan()
        self.restart_tick()

    def win_exists(self):
        return getattr(self, "win", None) is not None

    def work(self, fn, sub=None, *args):
        """Hintergrundarbeit starten. Stirbt sie, steht der Grund in der Seite,
        statt dass die Karte für immer auf 'wird gelesen' stehen bleibt."""
        def guarded():
            try:
                fn(*args)
            except Exception as e:
                traceback.print_exc()
                if sub is not None:
                    GLib.idle_add(sub.set_text, f"Fehlgeschlagen: {e}")
        threading.Thread(target=guarded, daemon=True).start()

    def _wordmark(self, width):
        """Wortmarke in der Fassung für dunkle Flächen, None wenn sie fehlt.

        Selbst gezeichnet, weil beide fertigen Widgets die Groesse verfehlen:
        Gtk.Picture nimmt immer die volle Breite des Elternelements, egal was
        halign, can_shrink oder set_size_request sagen. Gtk.Image passt den
        Inhalt in ein Quadrat der Kantenlaenge pixel_size ein, statt ihn auf
        die Zuteilung zu skalieren, eine breite Wortmarke bleibt darin winzig.
        set_content_width/height dagegen ist genau die natuerliche Groesse.

        Die Vorlage wird doppelt so gross geladen wie die Anzeige, damit sie
        auf Bildschirmen mit doppelter Aufloesung scharf bleibt.
        """
        path = os.path.join(APP_DIR, "icons", "wordmark", "png",
                            "dynotiq-wordmark-dark-w1200.png")
        if not os.path.exists(path):
            return None
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width * 2, -1, True)
        except GLib.Error:
            return None
        area = Gtk.DrawingArea()
        area.set_content_width(width)
        area.set_content_height(round(width * pix.get_height() / pix.get_width()))
        area.set_halign(Gtk.Align.CENTER)

        def draw(_area, cr, w, h):
            cr.scale(w / pix.get_width(), h / pix.get_height())
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint()

        area.set_draw_func(draw)
        return area

    def _logo(self, size):
        path = os.path.join(APP_DIR, "icons", "app-icon", "svg",
                            "dynotiq-icon-light.svg")
        img = (Gtk.Image.new_from_file(path) if os.path.exists(path)
               else Gtk.Image.new_from_icon_name("dynotiq"))
        img.set_pixel_size(size)
        img.set_valign(Gtk.Align.CENTER)
        return img

    def _on_close(self, win):
        """Im Tray weiterlaufen, aber nur wenn dort auch wirklich ein Icon hängt."""
        if self.cfg["tray"] and getattr(self, "tray", None) and self.tray.ok:
            win.set_visible(False)
            # Ohne das liest die App unsichtbar jede Sekunde weiter alle
            # Prozesse und startet nvidia-smi, endlos.
            if self.tick_id:
                GLib.source_remove(self.tick_id)
                self.tick_id = None
            return True
        return False

    def _tray_ready(self):
        row = getattr(self, "tray_switch", None)
        if row:
            row[0].set_sensitive(True)
            row[0].set_active(self.cfg["tray"])
            row[1].set_text(_("Statusicon aktiv"))
        return False

    def _tray_open(self):
        self.win.set_visible(True)
        self.win.present()
        self.restart_tick()
        return False

    def _tray_rescan(self):
        self.rescan()
        return False

    def _tray_quit(self):
        self.quit()
        return False

    def apply_css(self):
        try:
            self.provider.load_from_string(build_css())
        except AttributeError:
            self.provider.load_from_data(build_css().encode())

    def restart_tick(self):
        if self.tick_id:
            GLib.source_remove(self.tick_id)
        self.tick_id = GLib.timeout_add_seconds(self.cfg["interval"], self._tick)

    def _distro(self):
        m = re.search(r'PRETTY_NAME="(.+)"', read("/etc/os-release") or "")
        return m.group(1) if m else "Linux"

    # Sidebar

    def _sidebar(self):
        s = box(spacing=1)
        s.add_css_class("sidebar")
        head = box(spacing=8, margin_bottom=18, margin_start=8, margin_top=2)
        mark = self._wordmark(150)
        if mark:
            mark.set_halign(Gtk.Align.START)
            head.append(mark)
            sub = lbl(_("SYSTEMDIAGNOSE v{v}").format(v=VERSION), "brandsub")
            sub.set_margin_start(3)
            head.append(sub)
        else:                              # ohne Wortmarke der alte Aufbau
            row = box(True, 9)
            row.append(self._logo(30))
            txt = box()
            txt.append(lbl("dynotiq", "brand"))
            txt.append(lbl(f"SYSTEMDIAGNOSE v{VERSION}", "brandsub"))
            row.append(txt)
            head.append(row)
        s.append(head)
        self.nav_buttons = {}
        for group, names in NAV_GROUPS:
            s.append(lbl(group, "navgroup"))
            for name in names:
                b = Gtk.Button()
                b.add_css_class("nav")
                row = box(True, 8)
                row.append(Gtk.Label(label=_(name), xalign=0.0, hexpand=True))
                if name == "Probleme":
                    self.problem_badge = lbl("0", "navbadge")
                    self.problem_badge.set_valign(Gtk.Align.CENTER)
                    self.problem_badge.set_visible(False)
                    row.append(self.problem_badge)
                elif name == "Vorfälle":
                    self.incident_badge = lbl("0", "navbadge")
                    self.incident_badge.set_valign(Gtk.Align.CENTER)
                    self.incident_badge.set_visible(False)
                    row.append(self.incident_badge)
                b.set_child(row)
                if name == "Übersicht":
                    b.add_css_class("active")
                b.connect("clicked", self._nav_clicked, name)
                self.nav_buttons[name] = b
                s.append(b)

        s.append(Gtk.Box(vexpand=True))
        rig = box(spacing=5, margin_top=12)
        rig.add_css_class("rig")
        rig.append(lbl("RIG", "rig-key"))
        total, _avail = meminfo()
        # gpu() startet nvidia-smi. Genau bei einer hängenden Karte, also im
        # Diagnosefall, gäbe es sonst minutenlang gar kein Fenster.
        self.rig_val = lbl(_("{cpu}\nGrafik wird gelesen … · {gb:.0f} GB RAM"
                             ).format(cpu=cpu_model(), gb=total),
                           "rig-val", wrap=True, chars=26)
        rig.append(self.rig_val)
        rig.append(lbl(f"Kernel {os.uname().release} · {os.environ.get('XDG_SESSION_TYPE', '?')}",
                       "rig-sub"))
        s.append(rig)
        self.work(self._rig_worker, None, total)
        # Fest 208 px: das hexpand der Nav-Labels schlägt sonst nach oben durch
        # und die Sidebar wandert je nach Inhalt der rechten Seite.
        frame = Gtk.ScrolledWindow(child=s, hexpand=False, width_request=SIDEBAR_WIDTH,
                                   hscrollbar_policy=Gtk.PolicyType.NEVER)
        frame.set_size_request(SIDEBAR_WIDTH, -1)
        return frame

    def _maybe_intro(self):
        """Beim ersten Start das Willkommen, nach einem Update die Neuerungen.
        Danach nie wieder, gemerkt wird die zuletzt gesehene Version."""
        seen = state_read().get("seen_version")
        if seen == VERSION:
            return False
        state_write({**state_read(), "seen_version": VERSION})
        self._show_intro(first=seen is None)
        return False

    def _show_intro(self, first=True):
        win = Gtk.Window(transient_for=self.win, modal=True, default_width=560,
                         title="dynotiq")
        win.add_css_class("page")
        inner = box(spacing=0, margin_top=30, margin_bottom=24,
                    margin_start=32, margin_end=32)
        mark = self._wordmark(210)
        if mark:
            mark.set_halign(Gtk.Align.CENTER)
            mark.set_margin_bottom(10)
            inner.append(mark)
        else:
            logo = self._logo(56)
            logo.set_halign(Gtk.Align.CENTER)
            inner.append(logo)

        title = lbl(_("Willkommen") if first
                    else _("Neu in Version {v}").format(v=VERSION),
                    "h1", xalign=0.5)
        title.set_margin_top(10)
        inner.append(title)
        note = RELEASE_NOTES.get(VERSION, ("", []))
        sub = lbl(_("Systemdiagnose für Ubuntu. Ein kurzer Überblick, dann kann es "
                  "losgehen.") if first else note[0], "lede", xalign=0.5, wrap=True,
                  chars=60)
        sub.set_margin_top(6)
        sub.set_margin_bottom(22)
        inner.append(sub)

        if first:
            for name, text in INTRO:
                r = box(True, 14, margin_bottom=14)
                dot = Gtk.Box(valign=Gtk.Align.START)
                dot.add_css_class("bullet-ok")
                dot.set_margin_top(6)
                r.append(dot)
                t = box(spacing=3, hexpand=True)
                t.append(lbl(name, "row-title"))
                t.append(lbl(text, "row-detail", wrap=True, chars=64))
                r.append(t)
                inner.append(r)
            hint = lbl(_("Nichts davon greift von allein ein. Jeder Eingriff fragt "
                       "vorher nach und zeigt, was er ausführt."), "mono-dim",
                       xalign=0.5, wrap=True, chars=70)
            hint.set_margin_top(8)
            inner.append(hint)
        else:
            for line in note[1]:
                r = box(True, 14, margin_bottom=11)
                dot = Gtk.Box(valign=Gtk.Align.CENTER)
                dot.add_css_class("bullet-ok")
                r.append(dot)
                r.append(lbl(line, "row-detail", wrap=True, chars=64))
                inner.append(r)

        go = Gtk.Button(label=_("Los geht's") if first else _("Weiter"),
                        halign=Gtk.Align.CENTER)
        go.add_css_class("btn-accent")
        go.set_margin_top(26)
        go.connect("clicked", lambda *_: win.close())
        inner.append(go)
        win.set_child(inner)
        win.present()

    def _rig_worker(self, total):
        g = gpu()
        GLib.idle_add(self.rig_val.set_text,
                      _("{cpu}\n{gpu} · {gb:.0f} GB RAM").format(
                          cpu=cpu_model(), gb=total,
                          gpu=g["name"] if g else _("Keine dGPU")))

    def _nav_clicked(self, btn, name):
        for b in self.nav_buttons.values():
            b.remove_css_class("active")
        btn.add_css_class("active")
        self._build(name)
        self.stack.set_visible_child_name(name)

    def _build(self, name):
        if name in self.built:
            return
        self.built.add(name)
        builder = {"Übersicht": self._page_overview, "Probleme": self._page_problems,
                   "Vorfälle": self._page_incidents,
                   "Treiber": self._page_drivers, "Updates": self._page_updates,
                   "App-Check": self._page_appcheck,
                   "Autostart": self._page_autostart,
                   "Live-Monitor": self._page_monitor, "Speicher": self._page_storage,
                   "Prüfstand": self._page_dyno,
                   "Benchmark": self._page_bench, "Verlauf": self._page_history,
                   "Einstellungen": self._page_settings}[name]
        self.pages[name].append(builder())

    def _scroll(self, inner):
        inner.set_margin_top(22)
        inner.set_margin_bottom(22)
        inner.set_margin_start(26)
        inner.set_margin_end(26)
        return Gtk.ScrolledWindow(child=inner, hexpand=True, vexpand=True,
                                  hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _head(self, title, subtitle, *buttons):
        h = box(True, valign=Gtk.Align.END)
        left = box(spacing=2, hexpand=True)
        left.append(lbl(title, "h1"))
        sub = lbl(subtitle, "sub")
        left.append(sub)
        h.append(left)
        if buttons:
            bb = box(True, 9, valign=Gtk.Align.CENTER)
            for b in buttons:
                bb.append(b)
            h.append(bb)
        return h, sub

    # Übersicht

    def _page_overview(self):
        p = box(spacing=16)
        share = Gtk.Button(label=_("Bericht kopieren"))
        share.add_css_class("btn-ghost")
        share.connect("clicked", self._copy_report)
        rescan = Gtk.Button(label=_("Neu scannen"))
        rescan.add_css_class("btn-accent")
        rescan.connect("clicked", lambda *_: self.rescan())
        head, self.scan_info = self._head(_("Systemcheck"), _("Scan läuft …"), share, rescan)
        p.append(head)

        top = box(True, 16)
        inner = box(spacing=10, halign=Gtk.Align.CENTER)
        self.ring = Ring()
        inner.append(self.ring)
        self.score_title = lbl(_("Systemzustand"), "cardhead", xalign=0.5)
        self.score_sub = lbl(_("wird ermittelt"), "sub", xalign=0.5)
        inner.append(self.score_title)
        inner.append(self.score_sub)
        sc = card(inner, 18)
        sc.set_size_request(262, -1)
        top.append(sc)

        fi = box(spacing=0)
        self.eyebrow = lbl(_("BEFUND"), "eyebrow")
        fi.append(self.eyebrow)
        self.headline = lbl(_("Scan läuft …"), "headline", wrap=True, chars=30)
        self.headline.set_margin_top(7)
        fi.append(self.headline)
        self.lede = lbl("", "lede", wrap=True, chars=60)
        self.lede.set_margin_top(6)
        fi.append(self.lede)
        kpis = box(True, 10, homogeneous=True, margin_top=16, vexpand=True,
                   valign=Gtk.Align.END)
        self.kpi = {}
        for key, unit in (("CPU-TEMP", "°C"), ("GPU-TAKT", "MHz"), ("RAM FREI", "GB")):
            k = box(spacing=2)
            k.add_css_class("kpi")
            k.append(lbl(key, "kpi-key"))
            row = box(True, 4)
            v = lbl("-", "kpi-val")
            u = lbl(unit, "kpi-unit")
            u.set_valign(Gtk.Align.END)
            u.set_margin_bottom(3)
            row.append(v)
            row.append(u)
            k.append(row)
            self.kpi[key] = (v, u)
            kpis.append(k)
        fi.append(kpis)
        fc = card(fi, 20)
        fc.set_hexpand(True)
        top.append(fc)
        p.append(top)

        lc = box()
        lc.add_css_class("card")
        self.list_count = lbl("", "sub", xalign=1.0)
        lc.append(card_head(_("Was du zuerst angehen solltest"), self.list_count))
        self.list_box = box()
        lc.append(self.list_box)
        p.append(lc)

        tiles = box(True, 12, homogeneous=True)
        self.tiles = {}
        for key, lo, hi, ck in (("CPU", 0, 100, "acc"), ("GPU", 0, 100, "acc"),
                                ("RAM", 0, 100, "acc"), ("NVMe", 25, 85, "warn")):
            t = box(spacing=6)
            r = box(True)
            r.append(lbl(key, "tile-key"))
            v = lbl("-", "tile-val", xalign=1.0)
            v.set_hexpand(True)
            r.append(v)
            t.append(r)
            sp = Spark(lo, hi, ck)
            t.append(sp)
            self.tiles[key] = (v, sp)
            tiles.append(card(t, 13))
        p.append(tiles)
        return self._scroll(p)

    # Probleme

    def _page_problems(self):
        p = box(spacing=16)
        b = Gtk.Button(label=_("Neu scannen"))
        b.add_css_class("btn-accent")
        b.connect("clicked", lambda *_: self.rescan())
        head, self.prob_sub = self._head(_("Probleme"), "", b)
        p.append(head)
        self.prob_box = box(spacing=16)
        p.append(self.prob_box)
        self._fill_problems()
        return self._scroll(p)

    def _fill_problems(self):
        if not hasattr(self, "prob_box"):
            return
        clear(self.prob_box)
        crit = [f for f in self.findings if f.sev == "crit"]
        warn = [f for f in self.findings if f.sev == "warn"]
        info = [f for f in self.findings if f.sev == "info"]
        self.prob_sub.set_text(
            _("{crit} kritisch · {warn} Hinweise").format(
                crit=len(crit), warn=len(warn))
            + (_(" · {n} zur Kenntnis").format(n=len(info)) if info else ""))
        if not self.findings:
            e = box(spacing=6, halign=Gtk.Align.CENTER)
            e.append(lbl(_("Keine Befunde. Das System läuft sauber."), "empty"))
            self.prob_box.append(card(e, 40))
            return
        for title, group in ((_("Kritisch"), crit), (_("Hinweise"), warn),
                             (_("Zur Kenntnis"), info)):
            if not group:
                continue
            c = box()
            c.add_css_class("card")
            c.append(card_head(title, f"{len(group)}"))
            for f in group:
                c.append(self._finding_row(f))
            self.prob_box.append(c)

    def _finding_row(self, f):
        wrap = box()
        wrap.append(sep())
        r = box(True, 14, margin_top=14, margin_bottom=14, margin_start=18, margin_end=18)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class({"crit": "bullet-crit", "warn": "bullet-warn"}
                          .get(f.sev, "bullet-info"))
        r.append(dot)
        txt = box(spacing=2, hexpand=True)
        txt.append(lbl(f.title, "row-title"))
        txt.append(lbl(f.detail, "row-detail", wrap=True, chars=70))
        r.append(txt)
        if f.badge:
            pill = lbl(f.badge, "pill")
            if f.badge_ok:
                pill.add_css_class("ok")
            pill.set_valign(Gtk.Align.CENTER)
            r.append(pill)
        if f.report:
            rb = Gtk.Button(label=_("Was heißt das für mich?"), valign=Gtk.Align.CENTER)
            rb.add_css_class("btn-ghost")
            rb.connect("clicked", self._show_report, f)
            r.append(rb)
        b = Gtk.Button(label=_("Beheben") if f.cmd else _("Details"), valign=Gtk.Align.CENTER)
        b.add_css_class("btn-fix")
        b.connect("clicked", self._show_fix, f)
        r.append(b)
        wrap.append(r)
        return wrap

    def _show_report(self, _b, f):
        """Fenster mit einer Einschätzung, die erst beim Öffnen ermittelt wird."""
        win = Gtk.Window(title=f.title, transient_for=self.win, modal=True,
                         default_width=680, default_height=520)
        view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buf = view.get_buffer()
        buf.set_text(_("Wird für diesen Rechner geprüft …\n\n"
                     "Dabei werden auch die Paketquellen gefragt, ob sie das neue "
                     "Release schon kennen. Das dauert einen Moment."))
        close = Gtk.Button(label=_("Schließen"), halign=Gtk.Align.END, margin_top=10)
        close.connect("clicked", lambda *_: win.close())
        copy = Gtk.Button(label=_("Text kopieren"), halign=Gtk.Align.END, margin_top=10)
        row = box(True, 8, halign=Gtk.Align.END)
        row.append(copy)
        row.append(close)
        wrap = box(spacing=0, margin_top=14, margin_bottom=14,
                   margin_start=14, margin_end=14)
        wrap.append(Gtk.ScrolledWindow(child=view, vexpand=True))
        wrap.append(row)
        win.set_child(wrap)
        win.present()

        def fill(text):
            buf.set_text(text)
            copy.connect("clicked", lambda *_: Gdk.Display.get_default()
                         .get_clipboard().set(text))
            return False

        def worker():
            try:
                GLib.idle_add(fill, f.report())
            except Exception as e:
                traceback.print_exc()
                GLib.idle_add(fill, f"Die Prüfung ist fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    # Zeigt den Befehl, führt ihn nicht aus. pkexec kommt, wenn die Checks
    # länger im echten Betrieb gegengeprüft sind.
    def _show_fix(self, _b, f):
        d = Gtk.AlertDialog(modal=True)
        d.set_message(f.title)
        detail = f.detail + ("\n\n" + f.cmd if f.cmd else "")
        if f.argv and f.warn:
            detail += "\n\n" + f.warn
        d.set_detail(detail)
        if not f.cmd:
            d.set_buttons([_("Schließen")])
            d.show(self.win)
            return
        buttons = [_("Schließen"), _("Befehl kopieren")]
        if f.argv:
            buttons.append(_("Jetzt ausführen"))
        d.set_buttons(buttons)
        d.set_default_button(1)
        d.set_cancel_button(0)
        d.choose(self.win, None, lambda dlg, res: self._fix_response(dlg, res, f))

    def _fix_response(self, dlg, res, f):
        try:
            choice = dlg.choose_finish(res)
        except GLib.Error:
            return
        if choice == 1:
            Gdk.Display.get_default().get_clipboard().set(f.cmd)
        elif choice == 2 and f.argv:
            self._run_log(f.title, f.argv, self._after_fix)

    def _after_fix(self):
        """Nach einem Eingriff stimmen die alten Zahlen nicht mehr."""
        self.rescan()
        for page in ("Speicher", "Autostart"):
            self._build_reload(page)

    # Vorfälle

    def _page_incidents(self):
        p = box(spacing=16)
        self.inc_filter = Gtk.DropDown.new_from_strings(
            [_(CAT_LABEL[c]) for c in ["Alle"] + INCIDENT_CATS])
        self.inc_filter.set_valign(Gtk.Align.CENTER)
        self.inc_filter.connect("notify::selected", lambda *_: self._fill_incidents())
        reload_btn = Gtk.Button(label=_("Journal neu einlesen"))
        reload_btn.add_css_class("btn-accent")
        reload_btn.connect("clicked", lambda *_: self._incidents_reload())
        head, self.inc_sub = self._head(_("Vorfälle"), _("wird gelesen …"),
                                        self.inc_filter, reload_btn)
        p.append(head)
        note = lbl(_("Gelesen wird das Journal der letzten 24 Stunden. Erkannt werden "
                   "Audio-Aussetzer, GPU-Treiberfehler, OOM-Killer-Ereignisse und "
                   "fehlgeschlagene systemd-Units."), "lede", wrap=True, chars=95)
        p.append(card(note))
        self.inc_box = box(spacing=16)
        p.append(self.inc_box)
        self._incidents_reload()
        return self._scroll(p)

    def _incidents_reload(self):
        self.inc_sub.set_text(_("Journal wird gelesen …"))
        self.work(self._incidents_worker, self.inc_sub)

    def _incidents_worker(self):
        incidents_sync()
        GLib.idle_add(self._fill_incidents)

    def _fill_incidents(self):
        all_inc = list(reversed(incidents_read()))
        choice = (["Alle"] + INCIDENT_CATS)[self.inc_filter.get_selected()]
        shown = [i for i in all_inc if choice == "Alle" or i["cat"] == choice]
        crit = sum(1 for i in all_inc if i["sev"] == "crit")
        self.inc_sub.set_text(_("{n} Vorfälle · {crit} kritisch").format(
            n=len(all_inc), crit=crit))
        if hasattr(self, "incident_badge"):
            self.incident_badge.set_text(str(crit))
            self.incident_badge.set_visible(crit > 0)

        clear(self.inc_box)
        if not shown:
            e = box(halign=Gtk.Align.CENTER)
            e.append(lbl(_("Keine Vorfälle in diesem Zeitraum.") if choice == "Alle"
                         else _("Keine Vorfälle der Kategorie {cat}.").format(
                             cat=_(CAT_LABEL.get(choice, choice))), "empty"))
            self.inc_box.append(card(e, 40))
            return False
        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Erkannte Vorfälle"),
                           _("{n} angezeigt").format(n=len(shown))))
        for i in shown[:80]:
            c.append(self._incident_row(i))
        self.inc_box.append(c)
        return False

    def _incident_row(self, inc):
        w = box()
        w.append(sep())
        r = box(True, 12, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("bullet-crit" if inc["sev"] == "crit" else "bullet-warn")
        r.append(dot)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_(inc["title"]), "row-title"))
        t.append(lbl(inc["detail"][:110], "mono-dim"))
        ctx = format_snapshot(inc.get("sys"))
        if ctx:
            t.append(lbl(_("Zu dem Zeitpunkt: ") + ctx, "mono-dim"))
        r.append(t)
        stamp = lbl(time.strftime("%d.%m. %H:%M", time.localtime(inc["t"])), "mono",
                    xalign=1.0)
        stamp.set_valign(Gtk.Align.CENTER)
        r.append(stamp)
        pill = lbl(_(CAT_LABEL.get(inc["cat"], inc["cat"])), "pill")
        pill.set_valign(Gtk.Align.CENTER)
        r.append(pill)
        b = Gtk.Button(label=_("Diagnose"), valign=Gtk.Align.CENTER)
        b.add_css_class("btn-fix")
        b.connect("clicked", self._show_diagnosis, inc)
        r.append(b)
        w.append(r)
        return w

    def _show_diagnosis(self, _b, inc):
        fix, summary, causes, steps = classify(inc["title"], inc["detail"])
        rank = {"crit": _("Sollte behoben werden"), "warn": _("Lohnt sich zu beheben"),
                "info": _("Nur zur Information")}[fix]
        text = [summary, "", rank]
        if causes:
            text += ["", _("Mögliche Ursachen:")] + [f"  - {c}" for c in causes]
        if steps:
            text += ["", _("Schritte:")] + [f"  {n}. {s}" for n, s in enumerate(steps, 1)]
        ctx = format_snapshot(inc.get("sys"))
        if ctx:
            text += ["", _("Zustand des Rechners zu diesem Zeitpunkt:"), "  " + ctx]
        text += ["", _("Journal-Zeile:"), inc["detail"]]
        d = Gtk.AlertDialog(modal=True)
        d.set_message(_(inc["title"]))
        d.set_detail("\n".join(text))
        d.set_buttons([_("Schließen"), _("Schritte kopieren")])
        d.set_default_button(1)
        d.choose(self.win, None, lambda dlg, res: self._copy_steps(dlg, res, steps))

    def _copy_steps(self, dlg, res, steps):
        try:
            if dlg.choose_finish(res) == 1:
                Gdk.Display.get_default().get_clipboard().set(
                    "\n".join(f"{n}. {s}" for n, s in enumerate(steps, 1)))
        except GLib.Error:
            pass

    # Treiber

    def _page_drivers(self):
        p = box(spacing=16)
        head, self.drv_sub = self._head(_("Treiber"), _("wird gelesen …"))
        p.append(head)
        self.drv_box = box(spacing=16)
        p.append(self.drv_box)
        self.work(self._drivers_worker, self.drv_sub)
        return self._scroll(p)

    def _drivers_worker(self):
        # 'devices' statt 'list': nur dort steht, welchen Treiber Ubuntu fuer
        # diese Karte empfiehlt. Die Branch-Liste faellt dabei mit ab.
        data = {"devs": devices(),
                "avail": sh(["ubuntu-drivers", "devices"], timeout=60),
                "gpu": gpu(), "modules": sh(["lsmod"]).count("\n") - 1}
        GLib.idle_add(self._drivers_done, data)

    def _drivers_done(self, data):
        clear(self.drv_box)
        devs = data["devs"]
        without = [d for d in devs if not d["driver"]]
        self.drv_sub.set_text(
            _("{n} Geräte · {bad} ohne Treiber · {mods} Module geladen").format(
                n=len(devs), bad=len(without), mods=data["modules"]))

        g = data["gpu"]
        if g:
            info = box(spacing=8)
            row = box(True, 12)
            row.append(lbl(g["name"], "row-title"))
            branches = parse_driver_branches(data["avail"])
            pkg, rec = parse_recommended_driver(data["avail"])
            cur = int(g["driver"].split(".")[0]) if g["vendor"] == "nvidia" else 0
            pill = lbl(f"{g['driver']}", "pill")
            pill.add_css_class("warn" if rec > cur else "ok")
            pill.set_valign(Gtk.Align.CENTER)
            row.append(pill)
            info.append(row)
            if branches:
                info.append(lbl(_("Verfügbare Branches: ")
                                + ", ".join(str(b) for b in branches[:6]), "mono"))
                # Angeboten wird nur der empfohlene. Der hoechste Branch ist
                # nicht der, den Ubuntu fuer diese Karte getestet hat.
                if pkg:
                    info.append(lbl(_("Empfohlen: {pkg}").format(pkg=pkg), "mono-dim"))
                if pkg and rec > cur:
                    b = Gtk.Button(label=_("{pkg} installieren").format(pkg=pkg),
                                   halign=Gtk.Align.START)
                    b.add_css_class("btn-fix")
                    b.set_margin_top(4)
                    f = Finding("crit", pkg,
                                _("Wechsel der Treiber-Branch, danach Neustart nötig."),
                                cmd=f"sudo apt install {pkg}",
                                argv=[["pkexec", "apt-get", "update"],
                                      ["pkexec", "/usr/bin/env",
                                       "DEBIAN_FRONTEND=noninteractive", "apt-get",
                                       "install", "-y", pkg]],
                                warn=_("Der Treiber wird neu gebaut. Bis zum Neustart "
                                     "kann die Grafik unvollständig sein, deshalb "
                                     "vorher alles sichern."))
                    b.connect("clicked", self._show_fix, f)
                    info.append(b)
            c = box()
            c.add_css_class("card")
            c.append(card_head("Grafiktreiber"))
            info.set_margin_start(18)
            info.set_margin_end(18)
            info.set_margin_bottom(16)
            c.append(info)
            self.drv_box.append(c)

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Geräte"), f"{len(devs)}"))
        for d in devs:
            r = box(True, 12, margin_top=11, margin_bottom=11, margin_start=18, margin_end=18)
            dot = Gtk.Box(valign=Gtk.Align.CENTER)
            dot.add_css_class("bullet-ok" if d["driver"] else "bullet-crit")
            r.append(dot)
            txt = box(spacing=2, hexpand=True)
            txt.append(lbl(d["name"], "row-title", wrap=True, chars=64))
            txt.append(lbl(f"{d['class']} · {d['slot']}", "mono-dim"))
            r.append(txt)
            pill = lbl(d["driver"] or _("kein Treiber"), "pill")
            pill.add_css_class("ok" if d["driver"] else "crit")
            pill.set_valign(Gtk.Align.CENTER)
            r.append(pill)
            w = box()
            w.append(sep())
            w.append(r)
            c.append(w)
        self.drv_box.append(c)
        return False

    # Updates

    def _page_updates(self):
        p = box(spacing=16)
        rel = Gtk.Button(label=_("Neu einlesen"))
        rel.add_css_class("btn-accent")
        rel.connect("clicked", lambda *_: self._updates_reload())
        head, self.upd_sub = self._head(_("Updates"), _("wird gelesen …"), rel)
        p.append(head)
        self.upd_box = box(spacing=16)
        p.append(self.upd_box)
        self.upd_checks = {}
        self._updates_reload()
        return self._scroll(p)

    def _updates_reload(self):
        self.upd_sub.set_text(_("wird gelesen …"))
        self.work(self._updates_worker, self.upd_sub)

    def _updates_worker(self):
        GLib.idle_add(self._updates_done, updates_scan(self.cfg.get("firmware", True)))

    def _updates_done(self, data):
        clear(self.upd_box)
        self.upd_checks = {}
        parts = [f"{len(v['items'])} {UPDATE_SOURCES[k]}"
                 for k, v in data.items() if v["items"]]
        broken = [UPDATE_SOURCES[k] for k, v in data.items() if v["error"]]
        if broken:
            parts.append(_("ungeprüft: ") + ", ".join(broken))
        self.upd_sub.set_text(" · ".join(parts) if parts else _("alles aktuell"))

        for src, res in data.items():
            if res["error"]:
                c = box()
                c.add_css_class("card")
                c.append(card_head(UPDATE_SOURCES[src], _("nicht geprüft")))
                body = lbl(_("{err}. Ob hier Updates anstehen, ist unbekannt."
                             ).format(err=res["error"]),
                           "lede", wrap=True, chars=80)
                body.set_margin_start(18)
                body.set_margin_end(18)
                body.set_margin_bottom(16)
                c.append(body)
                self.upd_box.append(c)
        if not any(v["items"] for v in data.values()):
            if not broken:
                c = box()
                c.add_css_class("card")
                c.append(card_head(_("Nichts zu tun")))
                body = lbl(_("Alle Quellen sind auf dem aktuellen Stand."), "lede",
                           wrap=True, chars=80)
                body.set_margin_start(18)
                body.set_margin_end(18)
                body.set_margin_bottom(16)
                c.append(body)
                self.upd_box.append(c)
            return False

        for src, res in data.items():
            ups = res["items"]
            if not ups:
                continue
            c = box()
            c.add_css_class("card")
            btn = Gtk.Button(label=_("Installieren"), valign=Gtk.Align.CENTER)
            btn.add_css_class("btn-fix")
            btn.connect("clicked", self._updates_apply, src)
            total = sum(u[4] for u in ups)
            allbox = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER,
                                     tooltip_text=_("Alle in dieser Quelle"))
            right = box(True, 10)
            right.append(lbl(f"{len(ups)} · {fmt_bytes(total)}" if total
                             else str(len(ups)), "sub"))
            right.append(btn)
            head = card_head(UPDATE_SOURCES[src], right)
            head.prepend(allbox)
            c.append(head)
            checks = []
            for uid, name, old, new, size in ups:
                r = box(True, 12, margin_top=9, margin_bottom=9,
                        margin_start=18, margin_end=18)
                cb = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
                # Namen kommen zwar vom Paketmanager, gehen aber als Argument an
                # pkexec. Was dem Muster nicht entspricht, bleibt abwählbar liegen.
                if not valid_pkg(uid):
                    cb.set_active(False)
                    cb.set_sensitive(False)
                    cb.set_tooltip_text(_("Ungewöhnlicher Name, hier nicht ausführbar"))
                r.append(cb)
                checks.append((cb, uid))
                icon = update_icon(src, uid, name)
                img = (Gtk.Image.new_from_file(icon) if icon.startswith("/")
                       else Gtk.Image.new_from_icon_name(
                           icon or "package-x-generic-symbolic"))
                img.set_pixel_size(24)
                img.set_valign(Gtk.Align.CENTER)
                r.append(img)
                txt = box(spacing=2, hexpand=True)
                txt.append(lbl(name, "row-title", wrap=True, chars=50))
                txt.append(lbl(f"{old} → {new}" if old else new, "mono-dim"))
                r.append(txt)
                if size:
                    s = lbl(fmt_bytes(size), "mono-dim")
                    s.set_valign(Gtk.Align.CENTER)
                    r.append(s)
                w = box()
                w.append(sep())
                w.append(r)
                c.append(w)
            allbox.connect("toggled", self._updates_toggle_all, checks)
            self.upd_checks[src] = checks
            self.upd_box.append(c)
        return False

    def _updates_toggle_all(self, allbox, checks):
        for cb, _uid in checks:
            if cb.get_sensitive():
                cb.set_active(allbox.get_active())

    def _updates_apply(self, btn, src):
        if getattr(self, "upd_running", False):
            self._alert(_("Läuft bereits"), _("Warte, bis die laufende Installation fertig ist."))
            return
        ids = sorted({uid for cb, uid in self.upd_checks.get(src, ())
                      if cb.get_active() and valid_pkg(uid)})
        if not ids:
            self._alert(_("Nichts ausgewählt"),
                        _("Wähle mindestens einen Eintrag zum Aktualisieren."))
            return
        self.upd_running = True
        btn.set_sensitive(False)
        steps = cmd_steps(update_cmd(src, ids))
        if self.cfg["snapshot"] and shutil.which("timeshift"):
            # Erst sichern, dann installieren. Scheitert der Snapshot, bricht die
            # Kette ab und es wird nichts angefasst.
            steps = [SNAPSHOT_CMD] + steps

        def done():
            self.upd_running = False
            btn.set_sensitive(True)
            self.work(self._updates_verify, self.upd_sub, src, ids)

        self._run_log(f"{UPDATE_SOURCES[src]} aktualisieren", steps, done,
                      count=len(ids))

    def _updates_verify(self, src, ids):
        """Nach dem Lauf nachsehen, was wirklich weg ist. Der Sammel-Exitcode
        sagt nicht, welches Paket gescheitert ist."""
        data = updates_scan(self.cfg.get("firmware", True))
        left = {u[0] for u in data.get(src, {}).get("items", [])} & set(ids)
        GLib.idle_add(self._updates_done, data)
        if left:
            GLib.idle_add(self._alert,
                          _("{n} von {total} nicht aktualisiert").format(
                              n=len(left), total=len(ids)),
                          _("Diese Einträge stehen weiterhin an:\n\n")
                          + "\n".join(sorted(left)[:15])
                          + ("\n…" if len(left) > 15 else ""))

    def _run_log(self, title, cmd, done=None, count=0):
        """Führt cmd aus und zeigt die Ausgabe live. Kein Shell, cmd ist eine
        Liste von Argumenten oder eine Liste solcher Listen."""
        win = Gtk.Window(title=title, transient_for=self.win, modal=True,
                         default_width=780, default_height=460)
        view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buf = view.get_buffer()
        scroll = Gtk.ScrolledWindow(child=view, vexpand=True)
        bar = Gtk.ProgressBar(show_text=True, text=_("startet …"), margin_top=10,
                              pulse_step=0.06)
        stop = Gtk.Button(label=_("Abbrechen"), halign=Gtk.Align.END)
        close = Gtk.Button(label=_("Schließen"), halign=Gtk.Align.END, sensitive=False)
        close.connect("clicked", lambda *_: win.close())
        row = box(True, 8, margin_top=10, halign=Gtk.Align.END)
        row.append(stop)
        row.append(close)
        wrap = box(spacing=0, margin_top=14, margin_bottom=14,
                   margin_start=14, margin_end=14)
        wrap.append(scroll)
        wrap.append(bar)
        wrap.append(row)
        win.set_child(wrap)
        # Solange dpkg läuft, darf das Fenster nicht weg, sonst läuft der Lauf
        # unsichtbar als root weiter.
        win.connect("close-request", lambda *_: not close.get_sensitive())
        win.present()
        proc = {}

        seen = set()
        run = {"start": time.monotonic(), "last": time.monotonic(), "done": False,
               "step": ""}

        def append(line):
            buf.insert(buf.get_end_iter(), line + "\n")
            view.scroll_to_mark(buf.get_insert(), 0, False, 0, 1)
            buf.place_cursor(buf.get_end_iter())
            run["last"] = time.monotonic()
            name = progress_name(line)
            if name:
                seen.add(name)
                run["step"] = name
                if count:
                    bar.set_fraction(min(len(seen) / count, 1.0))
            return False

        def heartbeat():
            """Zeigt Laufzeit und wie lange das Programm schon still ist. Ein
            DKMS-Build schweigt minutenlang, ohne das sähe er aus wie ein Hänger."""
            if run["done"]:
                return False
            secs = int(time.monotonic() - run["start"])
            idle = int(time.monotonic() - run["last"])
            parts = [f"{secs // 60}:{secs % 60:02d}"]
            if count:
                parts.append(f"{len(seen)} von {count}")
            elif run["step"]:
                parts.append(run["step"])
            if idle >= 5:
                parts.append(_("seit {secs} s keine Ausgabe").format(secs=idle))
            bar.set_text(" · ".join(parts))
            if not count:
                bar.pulse()          # ohne Gesamtzahl bleibt nur die Bewegung
            return True

        GLib.timeout_add(250, heartbeat)

        def finish(msg):
            run["done"] = True
            append("\n" + msg)
            if os.path.exists("/run/reboot-required"):
                append(_("Ein Neustart ist nötig, damit die Updates wirksam werden."))
            secs = int(time.monotonic() - run["start"])
            bar.set_fraction(1.0)
            bar.set_text(f"{msg.rstrip('.')} nach {secs // 60}:{secs % 60:02d}")
            stop.set_sensitive(False)
            close.set_sensitive(True)
            if done:
                done()
            return False

        def do_cancel():
            pr = proc.get("p")
            if not pr or pr.poll() is not None:
                return
            append(_("Abbruch angefordert …"))
            try:
                pr.terminate()
                stop.set_sensitive(False)
            except PermissionError:
                # pkexec läuft als root, ein Signal von hier ist nicht erlaubt
                append(_("Der Lauf gehört root und lässt sich von hier nicht stoppen. "
                       "Im Terminal: sudo pkill -TERM apt-get"))
            except OSError as e:
                append(_("Abbruch nicht möglich: {err}").format(err=e))

        def cancel(_b):
            d = Gtk.AlertDialog(modal=True)
            d.set_message(_("Installation abbrechen?"))
            d.set_detail(_("Mitten im Entpacken abzubrechen kann halb installierte "
                         "Pakete hinterlassen. Danach hilft nur "
                         "'sudo dpkg --configure -a'."))
            d.set_buttons([_("Weiterlaufen lassen"), _("Abbrechen erzwingen")])
            d.set_default_button(0)
            d.set_cancel_button(0)
            d.choose(win, None, lambda dlg, res: dlg.choose_finish(res) == 1
                     and do_cancel())

        stop.connect("clicked", cancel)

        def worker():
            for step in steps:
                GLib.idle_add(append, "$ " + " ".join(step))
                try:
                    pr = subprocess.Popen(step, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL, text=True,
                                          errors="replace")
                except OSError as e:
                    GLib.idle_add(finish,
                              _("Start fehlgeschlagen: {err}").format(err=e))
                    return
                proc["p"] = pr
                for line in pr.stdout:
                    GLib.idle_add(append, line.rstrip())
                rc = pr.wait()
                if rc != 0:
                    # 126/127: pkexec-Dialog abgebrochen oder nicht startbar
                    GLib.idle_add(finish, _("Abgebrochen.")
                                  if rc in (126, 127) or rc < 0
                                  else _("Beendet mit Code {rc}.").format(rc=rc))
                    return
            GLib.idle_add(finish, _("Fertig."))

        steps = cmd_steps(cmd)
        threading.Thread(target=worker, daemon=True).start()

    def _unit_disable(self, _b, unit):
        """Fragt erst, was der Dienst überhaupt tut und wer ihn braucht."""
        self.work(self._unit_ask, self.auto_sub, unit)

    def _unit_ask(self, unit):
        scope = unit_scope(unit)
        desc, needed = unit_info(unit, scope)
        GLib.idle_add(self._unit_confirm, unit, scope, desc, needed)

    def _unit_confirm(self, unit, scope, desc, needed):
        detail = [desc or _("Keine Beschreibung hinterlegt."), ""]
        detail.append(_("Ebene: ") + (_("Nutzer-Dienst") if scope else _("Systemdienst")))
        if needed:
            detail += ["", _("Darauf bauen auf:")] + [f"  {n}" for n in needed]
            detail.append("")
            detail.append(_("Diese Dienste starten danach möglicherweise nicht mehr."))
        detail.append("")
        detail.append(_("Befehl: ") + " ".join(unit_disable_cmd(unit, scope)))
        d = Gtk.AlertDialog(modal=True)
        d.set_message(_("{unit} abschalten?").format(unit=unit))
        d.set_detail("\n".join(detail))
        d.set_buttons([_("Abbrechen"), _("Abschalten")])
        d.set_default_button(0)
        d.set_cancel_button(0)
        d.choose(self.win, None, lambda dlg, res: self._unit_response(dlg, res,
                                                                     unit, scope))
        return False

    def _unit_response(self, dlg, res, unit, scope):
        try:
            if dlg.choose_finish(res) != 1:
                return
        except GLib.Error:
            return
        self._run_log(f"{unit} abschalten", unit_disable_cmd(unit, scope),
                      lambda: self._build_reload("Autostart"))

    def _build_reload(self, page):
        """Seite neu aufbauen, damit die Änderung sichtbar wird."""
        if page in self.built:
            self.built.discard(page)
            clear(self.pages[page])
            self._build(page)

    # Prüfstand

    def _page_dyno(self):
        p = box(spacing=16)
        self.dyno_btn = Gtk.Button(label=_("Aufzeichnung starten"))
        self.dyno_btn.add_css_class("btn-accent")
        self.dyno_btn.connect("clicked", lambda *_: self._dyno_toggle())
        head, self.dyno_sub = self._head(_("Prüfstand"), "bereit", self.dyno_btn)
        p.append(head)
        p.append(card(lbl(_("Starte die Aufzeichnung, dann belaste den Rechner wie "
                          "im Alltag: spielen, rendern, kompilieren. Danach steht "
                          "hier, wie heiß es wurde, wie tief der Takt fiel und ab "
                          "wann gedrosselt wurde. Einzelne Momentwerte zeigen das "
                          "nicht, weil die Drosselung erst nach Minuten einsetzt."),
                          "lede", wrap=True, chars=95)))

        c = box()
        c.add_css_class("card")
        c.append(card_head("Verlauf", _("Temperatur und Takt")))
        self.dyno_chart = Chart([("cpu_temp", "warn"), ("gpu_temp", "crit")],
                                points=180, top=110, height=150, unit="°C")
        self.dyno_chart.set_margin_start(18)
        self.dyno_chart.set_margin_end(18)
        self.dyno_chart.set_margin_bottom(16)
        c.append(self.dyno_chart)
        p.append(c)

        self.dyno_view = Gtk.TextView(editable=False, monospace=True,
                                      cursor_visible=False)
        self.dyno_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        for m in ("top", "bottom", "start", "end"):
            getattr(self.dyno_view, f"set_margin_{m}")(18 if m in ("start", "end") else 14)
        self.dyno_view.get_buffer().set_text(
            "Noch keine Aufzeichnung.\n\n"
            "Empfehlung: mindestens zehn Minuten unter der Last, die dich "
            "interessiert. Kürzere Läufe zeigen die Drosselung oft noch nicht.")
        res = box()
        res.add_css_class("card")
        res.append(card_head(_("Auswertung")))
        res.append(self.dyno_view)
        p.append(res)
        self._fill_dyno_history(p)
        return self._scroll(p)

    def _fill_dyno_history(self, parent):
        runs = history_read(6, kind="run")
        if not runs:
            return
        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Frühere Läufe"), str(len(runs))))
        for r in reversed(runs):
            s = r.get("summary", {})
            row = box(True, 12, margin_top=9, margin_bottom=9,
                      margin_start=18, margin_end=18)
            row.append(lbl(time.strftime("%d.%m. %H:%M", time.localtime(r["t"])), "mono"))
            secs = s.get("secs", 0)
            row.append(lbl(f"{secs // 60}:{secs % 60:02d} min", "mono-dim"))
            for key in ("cpu_temp", "gpu_temp"):
                v = s.get(key, {}).get("max")
                t = lbl(f"{RECORD_LABEL[key][0]} max {v:.0f} °C" if v else "-",
                        "mono", xalign=1.0)
                t.set_hexpand(True)
                row.append(t)
            thr = s.get("throttle_share")
            row.append(lbl(f"{thr} % gedrosselt" if thr else _("ohne Drosselung"),
                           "mono-dim", xalign=1.0))
            w = box()
            w.append(sep())
            w.append(row)
            c.append(w)
        parent.append(c)

    def _dyno_toggle(self):
        if self.dyno_id:
            GLib.source_remove(self.dyno_id)
            self.dyno_id = None
            self.dyno_btn.set_label(_("Aufzeichnung starten"))
            summary = record_summary(self.dyno_samples)
            self.dyno_view.get_buffer().set_text(format_summary(summary))
            self.dyno_sub.set_text("fertig")
            if summary:
                history_append({"t": time.time(), "kind": "run", "summary": summary})
            return
        self.dyno_samples = []
        self.dyno_prev = cpu_times()
        self.dyno_t0 = time.monotonic()
        self.dyno_chart.data = {k: deque([0.0], maxlen=180)
                                for k in ("cpu_temp", "gpu_temp")}
        self.dyno_btn.set_label(_("Aufzeichnung beenden"))
        self.dyno_view.get_buffer().set_text(_("Läuft. Belaste den Rechner jetzt so, "
                                             "wie du ihn im Alltag belastest."))
        # Zwei Sekunden reichen: Temperaturen ändern sich langsamer als das.
        self.dyno_id = GLib.timeout_add_seconds(2, self._dyno_tick)
        self._dyno_tick()

    def _dyno_tick(self):
        self.work(self._dyno_worker)
        return True

    def _dyno_worker(self):
        s, cur = record_sample(self.dyno_prev)
        self.dyno_prev = cur
        GLib.idle_add(self._dyno_add, s)

    def _dyno_add(self, s):
        if not self.dyno_id:
            return False
        self.dyno_samples.append(s)
        self.dyno_chart.push({"cpu_temp": s.get("cpu_temp", 0),
                              "gpu_temp": s.get("gpu_temp", 0)})
        secs = int(time.monotonic() - self.dyno_t0)
        thr = _(" · gedrosselt") if s.get("throttled") else ""
        self.dyno_sub.set_text(
            _("läuft seit {mins}:{secs:02d} · {n} Messpunkte{thr}").format(
                mins=secs // 60, secs=secs % 60, thr=thr,
                n=len(self.dyno_samples)))
        return False

    # App-Check

    def _page_appcheck(self):
        p = box(spacing=16)
        head, self.app_sub = self._head(_("App-Check"), _("Anwendung wählen und prüfen"))
        p.append(head)
        self.apps = desktop_apps()
        names = sorted(self.apps, key=str.lower)
        self.app_pick = Gtk.DropDown.new_from_strings(names or [_("nichts gefunden")])
        self.app_pick.set_enable_search(True)
        self.app_pick.set_hexpand(True)
        self.app_pick.connect("notify::selected", lambda *_: self._appcheck_preview())
        btn = Gtk.Button(label=_("Prüfen"), valign=Gtk.Align.CENTER)
        btn.add_css_class("btn-accent")
        btn.connect("clicked", lambda *_: self._appcheck_run())

        self.app_icon = Gtk.Image()
        self.app_icon.set_pixel_size(44)
        self.app_icon.set_valign(Gtk.Align.CENTER)
        self.app_name = lbl("", "row-title")
        self.app_kind = lbl("", "mono-dim")
        who = box(spacing=2, hexpand=True)
        who.append(self.app_name)
        who.append(self.app_kind)
        row = box(True, 14, margin_top=16, margin_bottom=16,
                  margin_start=18, margin_end=18)
        row.append(self.app_icon)
        row.append(who)
        row.append(btn)
        c = box()
        c.add_css_class("card")
        c.append(row)
        c.append(sep())
        pick = box(True, 12, margin_top=12, margin_bottom=14,
                   margin_start=18, margin_end=18)
        pick.append(self.app_pick)
        c.append(pick)
        p.append(c)

        self.app_box = box(spacing=16)
        p.append(self.app_box)
        self._appcheck_hint(
            _("{n} Anwendungen gefunden. Gesucht wird nach fehlenden "
              "Bibliotheken, abgeschnittenen Rechten in der Sandbox, "
              "blockierten Zugriffen, Abstürzen und Fehlern im Journal. "
              "Wo es eine Lösung gibt, steht ein Knopf daneben."
              ).format(n=len(self.apps)))
        self._appcheck_preview()
        return self._scroll(p)

    def _appcheck_hint(self, text):
        clear(self.app_box)
        c = box()
        c.add_css_class("card")
        body = lbl(text, "lede", wrap=True, chars=95)
        for m in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{m}")(18 if m in ("start", "end") else 16)
        c.append(body)
        self.app_box.append(c)

    def _appcheck_entry(self):
        item = self.app_pick.get_selected_item()
        return self.apps.get(item.get_string()) if item else None

    def _appcheck_preview(self):
        """Logo und Herkunft der gewählten Anwendung, noch ohne Prüfung."""
        entry = self._appcheck_entry()
        if not entry:
            return
        icon = entry_icon(entry)
        if icon.startswith("/"):
            self.app_icon.set_from_file(icon)
        else:
            self.app_icon.set_from_icon_name(icon or "application-x-executable")
        kind, ident = app_source(entry)
        self.app_name.set_text(entry.get("Name", ""))
        self.app_kind.set_text(APP_KIND_LABEL.get(kind, kind)
                               + (f" · {ident}" if ident else ""))

    def _appcheck_run(self):
        entry = self._appcheck_entry()
        if not entry:
            return
        self.app_sub.set_text(_("{app} wird geprüft …").format(
            app=entry.get("Name", "")))
        self._appcheck_hint(_("Läuft. Journal und Paketverwaltung werden gefragt, "
                            "das dauert einen Moment."))
        self.work(self._appcheck_worker, self.app_sub, entry)

    def _appcheck_worker(self, entry):
        results = app_check(entry)
        GLib.idle_add(self._appcheck_done, entry.get("Name", ""), results)

    def _appcheck_done(self, name, results):
        clear(self.app_box)
        bad = [r for r in results if r[0] in ("warn", "crit")]
        hints = [r for r in results if r[0] == "info"]
        if bad:
            state = f"{len(bad)} Problem" + ("e" if len(bad) > 1 else "")
        elif hints:
            state = f"läuft, {len(hints)} Hinweis" + ("e" if len(hints) > 1 else "")
        else:
            state = _("alles in Ordnung")
        self.app_sub.set_text(f"{name}: {state}")
        c = box()
        c.add_css_class("card")
        copy = Gtk.Button(label=_("Bericht kopieren"), valign=Gtk.Align.CENTER)
        copy.add_css_class("btn-ghost")
        copy.connect("clicked", lambda *_: Gdk.Display.get_default().get_clipboard()
                     .set(app_check_text(name, results)))
        c.append(card_head(_("Ergebnis"), copy))
        for sev, title, detail, fix in results:
            r = box(True, 14, margin_top=13, margin_bottom=13,
                    margin_start=18, margin_end=18)
            dot = Gtk.Box(valign=Gtk.Align.CENTER)
            dot.add_css_class({"crit": "bullet-crit", "warn": "bullet-warn",
                               "info": "bullet-info"}.get(sev, "bullet-ok"))
            r.append(dot)
            t = box(spacing=2, hexpand=True)
            t.append(lbl(title, "row-title"))
            t.append(lbl(detail, "row-detail", wrap=True, chars=78))
            r.append(t)
            if fix:
                label, argv = fix
                b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
                b.add_css_class("btn-fix")
                b.connect("clicked", self._appcheck_fix, title, label, argv)
                r.append(b)
            w = box()
            w.append(sep())
            w.append(r)
            c.append(w)
        self.app_box.append(c)
        return False

    def _appcheck_fix(self, _b, title, label, argv):
        steps = cmd_steps(argv)
        d = Gtk.AlertDialog(modal=True)
        d.set_message(_("{action}?").format(action=label))
        d.set_detail(_("{title}\n\nAusgeführt wird:\n").format(title=title)
                     + "\n".join("  " + " ".join(s) for s in steps))
        d.set_buttons([_("Abbrechen"), label])
        d.set_default_button(1)
        d.set_cancel_button(0)
        d.choose(self.win, None, lambda dlg, res: self._appcheck_fix_run(
            dlg, res, title, argv))

    def _appcheck_fix_run(self, dlg, res, title, argv):
        try:
            if dlg.choose_finish(res) != 1:
                return
        except GLib.Error:
            return
        self._run_log(title, argv, self._appcheck_run)

    # Autostart

    def _page_autostart(self):
        p = box(spacing=16)
        head, self.auto_sub = self._head(_("Autostart"), _("wird gelesen …"))
        p.append(head)
        self.auto_box = box(spacing=16)
        p.append(self.auto_box)
        self.work(self._autostart_worker, self.auto_sub)
        return self._scroll(p)

    def _autostart_worker(self):
        GLib.idle_add(self._autostart_done, autostart_entries(),
                      sh(["systemd-analyze", "blame"], timeout=20))

    def _autostart_done(self, entries, blame):
        clear(self.auto_box)
        on = [e for e in entries if e["enabled"]]
        self.auto_sub.set_text(_("{n} Einträge · {on} aktiv").format(
            n=len(entries), on=len(on)))

        for scope, title in (("user", _("Eigene Einträge")), ("system", _("Systemweit"))):
            group = [e for e in entries if e["scope"] == scope]
            if not group:
                continue
            c = box()
            c.add_css_class("card")
            c.append(card_head(title, _("{on} von {total} aktiv").format(
                on=sum(1 for e in group if e["enabled"]), total=len(group))))
            for e in group:
                c.append(self._autostart_row(e))
            self.auto_box.append(c)

        units = parse_blame(blame)
        if units:
            c = box()
            c.add_css_class("card")
            c.append(card_head(_("Langsamste Dienste beim Boot"),
                               _("{n} Units").format(n=len(units))))
            for secs, unit in units[:8]:
                r = box(True, 12, margin_top=9, margin_bottom=9, margin_start=18, margin_end=18)
                r.append(lbl(unit, "mono"))
                v = lbl(f"{secs / 60:.0f} min" if secs >= 90 else f"{secs:.1f} s",
                        "mono", xalign=1.0)
                v.set_hexpand(True)
                r.append(v)
                # Bewusst ein Knopf mit Rückfrage statt eines Schalters: einen
                # Systemdienst abzuschalten kann den Rechner unbrauchbar machen.
                b = Gtk.Button(label=_("Abschalten"), valign=Gtk.Align.CENTER)
                b.add_css_class("btn-ghost")
                b.connect("clicked", self._unit_disable, unit)
                r.append(b)
                w = box()
                w.append(sep())
                w.append(r)
                c.append(w)
            self.auto_box.append(c)
        return False

    def _autostart_row(self, e):
        w = box()
        w.append(sep())
        r = box(True, 12, margin_top=10, margin_bottom=10, margin_start=18, margin_end=18)
        txt = box(spacing=2, hexpand=True)
        txt.append(lbl(e["name"], "row-title"))
        txt.append(lbl(e["exec"][:80] or e["file"], "mono-dim"))
        r.append(txt)
        sw = Gtk.Switch(active=e["enabled"], valign=Gtk.Align.CENTER)
        sw.connect("state-set", self._autostart_toggle, e)
        r.append(sw)
        w.append(r)
        return w

    def _autostart_toggle(self, _sw, state, entry):
        try:
            autostart_set(entry, state)
        except OSError as err:
            print(f"autostart: {err}", file=sys.stderr)
        return False

    # Live-Monitor

    def _page_monitor(self):
        p = box(spacing=16)
        head, self.mon_sub = self._head(
            _("Live-Monitor"),
            _("Aktualisierung alle {secs} s").format(secs=self.cfg["interval"]))
        p.append(head)

        grid = box(True, 16, homogeneous=True)
        self.charts = {}
        for key, title, series, top, unit in (
                ("cpu", "CPU", [("cpu", "acc")], 100, "%"),
                ("mem", _("Arbeitsspeicher"), [("mem", "acc"), ("swap", "warn")], 100, "%")):
            c = box(spacing=8)
            c.add_css_class("card")
            self.charts[key + "_val"] = lbl("-", "big-val")
            h = card_head(title, self.charts[key + "_val"])
            c.append(h)
            ch = Chart(series, top=top, unit=unit)
            ch.set_margin_start(14)
            ch.set_margin_end(14)
            ch.set_margin_bottom(14)
            self.charts[key] = ch
            c.append(ch)
            grid.append(c)
        p.append(grid)

        grid2 = box(True, 16, homogeneous=True)
        for key, title, series, top, unit in (
                ("gpu", "GPU", [("util", "acc"), ("temp", "warn")], 100, "%"),
                ("io", _("Netz und Datenträger"), [("net", "acc"), ("disk", "ok")], None, "MB/s")):
            c = box(spacing=8)
            c.add_css_class("card")
            self.charts[key + "_val"] = lbl("-", "big-val")
            c.append(card_head(title, self.charts[key + "_val"]))
            ch = Chart(series, top=top, unit=unit)
            ch.set_margin_start(14)
            ch.set_margin_end(14)
            ch.set_margin_bottom(14)
            self.charts[key] = ch
            c.append(ch)
            grid2.append(c)
        p.append(grid2)

        cores = box(spacing=8)
        cores.add_css_class("card")
        cores.append(card_head(_("Kerne"), f"{len(self.prev_cores) - 1} Threads"))
        cb = box(True, 4, margin_start=18, margin_end=18, margin_bottom=16)
        self.core_bars = []
        for _core in range(len(self.prev_cores) - 1):
            holder = box(spacing=3, hexpand=True)
            bar = Bar(0.0, height=34, vertical=True)
            holder.append(bar)
            self.core_bars.append(bar)
            cb.append(holder)
        cores.append(cb)
        p.append(cores)

        pc = box()
        pc.add_css_class("card")
        pc.append(card_head(_("Top-Prozesse"), _("nach CPU")))
        self.proc_box = box()
        pc.append(self.proc_box)
        p.append(pc)
        # Die Vergleichswerte laufen nur mit, solange diese Seite gebaut ist.
        # Ohne das teilt der erste Tick das seit dem Start aufgelaufene I/O
        # durch ein Intervall und die Kurve steht bei vierstelligen MB/s.
        self.prev_net = net_bytes()
        self.prev_disk = disk_bytes()
        self.prev_cores = cpu_times(per_core=True)
        self.prev_procs = {p["pid"]: p["cpu"] for p in processes()}
        self.prev_t = time.monotonic()
        return self._scroll(p)

    def _fill_procs(self, procs):
        """Sechs feste Zeilen, die nur ihren Text wechseln. Bei jedem Tick neue
        Widgets zu bauen kostet Layout und lässt die Liste flackern."""
        if not getattr(self, "proc_rows", None):
            self.proc_rows = []
            for _ in range(6):
                r = box(True, 12, margin_top=8, margin_bottom=8,
                        margin_start=18, margin_end=18)
                name = lbl("", "row-title")
                pid = lbl("", "mono-dim")
                cpu = lbl("", "mono", xalign=1.0)
                cpu.set_hexpand(True)
                rss = lbl("", "mono", xalign=1.0)
                for w in (name, pid, cpu, rss):
                    r.append(w)
                holder = box()
                holder.append(sep())
                holder.append(r)
                self.proc_box.append(holder)
                self.proc_rows.append((holder, name, pid, cpu, rss))
        for i, (holder, name, pid, cpu, rss) in enumerate(self.proc_rows):
            if i < len(procs):
                p = procs[i]
                name.set_text(p["name"][:38])
                pid.set_text(str(p["pid"]))
                cpu.set_text(f"{p['pct']:.0f} %")
                rss.set_text(fmt_bytes(p["rss"]))
                holder.set_visible(True)
            else:
                holder.set_visible(False)

    # Speicher

    def _page_storage(self):
        p = box(spacing=16)
        b = Gtk.Button(label=_("Neu berechnen"))
        b.add_css_class("btn-ghost")
        b.connect("clicked", lambda *_: self._storage_reload())
        head, self.sto_sub = self._head(_("Speicher"), _("wird berechnet …"), b)
        p.append(head)
        self.sto_box = box(spacing=16)
        p.append(self.sto_box)
        self._storage_reload()
        return self._scroll(p)

    def _storage_reload(self):
        self.work(self._storage_worker, self.sto_sub)

    def _storage_worker(self):
        """Aufräumbares samt ausführbarem Befehl. Nur wo das Löschen gefahrlos
        oder umkehrbar ist, gibt es eine Argumentliste, sonst bleibt es beim
        Befehl zum Kopieren."""
        eaters = []
        journal = re.search(r"take up ([\d.]+)([KMG])",
                            sh(["journalctl", "--disk-usage"]))
        if journal:
            size = float(journal.group(1)) * {"K": 2**10, "M": 2**20,
                                              "G": 2**30}[journal.group(2)]
            eaters.append((_("Systemjournal"), "/var/log/journal", int(size),
                           "sudo journalctl --vacuum-size=500M",
                           ["pkexec", "journalctl", "--vacuum-size=500M"],
                           _("Alte Logzeilen werden verworfen, die letzten 500 MB "
                           "bleiben.")))
        eaters.append((_("APT-Paketcache"), "/var/cache/apt/archives",
                       dir_size("/var/cache/apt/archives"), "sudo apt clean",
                       ["pkexec", "apt-get", "clean"],
                       _("Heruntergeladene Installationsdateien. Werden bei Bedarf "
                       "erneut geladen.")))
        old = parse_disabled_snaps(sh(["snap", "list", "--all"]))
        if old:
            eaters.append((_("Alte Snap-Revisionen ({n})").format(n=len(old)),
                           "/var/lib/snapd/snaps",
                           sum(dir_size(f"/var/lib/snapd/snaps/{n}_{r}.snap", 5)
                               for n, r in old),
                           "snap list --all | awk '/disabled/{print $1, $3}' | "
                           "while read s r; do sudo snap remove \"$s\" "
                           "--revision=\"$r\"; done",
                           [["pkexec", "snap", "remove", n, f"--revision={r}"]
                            for n, r in old],
                           _("Das sind die Vorgängerversionen, auf die snap "
                           "zurückrollen könnte. Danach geht das nicht mehr.")))
        trash = os.path.expanduser("~/.local/share/Trash")
        thumbs = os.path.expanduser("~/.cache/thumbnails")
        for title, path, cmd, argv, warn in (
                (_("Nutzer-Cache"), "~/.cache", "rm -rf ~/.cache/*", None,
                 None),
                (_("Papierkorb"), "~/.local/share/Trash", "gio trash --empty",
                 ["gio", "trash", "--empty"],
                 _("Deine gelöschten Dateien sind danach endgültig weg.")),
                (_("Thumbnails"), "~/.cache/thumbnails", "rm -rf ~/.cache/thumbnails/*",
                 ["find", thumbs, "-mindepth", "1", "-delete"],
                 _("Vorschaubilder des Dateimanagers, werden beim nächsten Öffnen "
                 "neu erzeugt."))):
            full = os.path.expanduser(path)
            if os.path.isdir(full):
                eaters.append((title, path, dir_size(full, 30), cmd, argv, warn))
        eaters = [e for e in eaters if e[2] > 0]
        eaters.sort(key=lambda e: -e[2])
        GLib.idle_add(self._storage_done, mounts(), eaters)

    def _storage_done(self, ms, eaters):
        clear(self.sto_box)
        total_free = sum(m["free"] for m in ms)
        self.sto_sub.set_text(
            _("{n} Dateisysteme · {free} frei · {clean} aufräumbar").format(
                n=len(ms), free=fmt_bytes(total_free),
                clean=fmt_bytes(sum(e[2] for e in eaters))))

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Dateisysteme"), f"{len(ms)}"))
        for m in ms:
            frac = m["used"] / m["total"]
            r = box(spacing=6, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18)
            top = box(True, 12)
            t = box(spacing=1, hexpand=True)
            t.append(lbl(m["target"], "row-title"))
            t.append(lbl(f"{m['src']} · {m['fs']}", "mono-dim"))
            top.append(t)
            v = lbl(f"{fmt_bytes(m['used'])} von {fmt_bytes(m['total'])}", "mono", xalign=1.0)
            top.append(v)
            pill = lbl(f"{100 * frac:.0f} %", "pill")
            pill.add_css_class("ok" if frac < .75 else "warn" if frac < .9 else "crit")
            pill.set_valign(Gtk.Align.CENTER)
            top.append(pill)
            r.append(top)
            r.append(Bar(frac))
            w = box()
            w.append(sep())
            w.append(r)
            c.append(w)
        self.sto_box.append(c)

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Aufräumbar"), fmt_bytes(sum(e[2] for e in eaters))))
        if not eaters:
            e = box(halign=Gtk.Align.CENTER)
            e.append(lbl(_("Nichts Nennenswertes gefunden."), "empty"))
            c.append(card(e, 26))
        for title, path, size, cmd, argv, warn in eaters:
            r = box(True, 12, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18)
            t = box(spacing=2, hexpand=True)
            t.append(lbl(title, "row-title"))
            t.append(lbl(path, "mono-dim"))
            r.append(t)
            r.append(lbl(fmt_bytes(size), "mono"))
            b = Gtk.Button(label=_("Aufräumen"), valign=Gtk.Align.CENTER)
            b.add_css_class("btn-fix")
            b.connect("clicked", self._show_fix,
                      Finding("warn", title,
                              _("{path} belegt {size}.").format(
                                  path=path, size=fmt_bytes(size)),
                              cmd=cmd, argv=argv, warn=warn))
            r.append(b)
            w = box()
            w.append(sep())
            w.append(r)
            c.append(w)
        self.sto_box.append(c)
        return False

    # Benchmark

    def _page_bench(self):
        p = box(spacing=16)
        self.bench_btn = Gtk.Button(label=_("Benchmark starten"))
        self.bench_btn.add_css_class("btn-accent")
        self.bench_btn.connect("clicked", lambda *_: self._bench_start())
        head, self.bench_sub = self._head(_("Benchmark"), _("noch nicht gelaufen"), self.bench_btn)
        p.append(head)

        note = box(spacing=4)
        note.append(lbl(_("Gemessen wird, was ohne Root messbar ist: SHA-256-Durchsatz "
                        "ein- und mehrfädig, Speicherkopie und Schreibrate auf die "
                        "Home-Partition."), "lede", wrap=True, chars=90))
        note.append(lbl(_("Der Lesewert fehlt bewusst, ohne Cache-Drop wäre er gelogen. "
                        "Die Zahlen taugen zum Vergleich mit dir selbst, nicht mit "
                        "fremden Rechnern."), "row-detail", wrap=True, chars=90))
        p.append(card(note))

        self.bench_tiles = {}
        grid = box(True, 12, homogeneous=True)
        for key, title, unit in (("cpu1", _("CPU einfädig"), "MiB/s"),
                                 ("cpun", _("CPU alle Kerne"), "MiB/s"),
                                 ("ram", _("Speicherkopie"), "GiB/s"),
                                 ("disk", _("Schreibrate"), "MiB/s")):
            t = box(spacing=4)
            t.append(lbl(title.upper(), "kpi-key"))
            v = lbl("-", "big-val")
            t.append(v)
            t.append(lbl(unit, "mono-dim"))
            self.bench_tiles[key] = v
            grid.append(card(t, 14))
        p.append(grid)

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Frühere Läufe")))
        self.bench_hist = box()
        c.append(self.bench_hist)
        p.append(c)
        self._fill_bench_history()
        return self._scroll(p)

    def _fill_bench_history(self):
        clear(self.bench_hist)
        runs = history_read(20, kind="bench")
        if not runs:
            e = box(halign=Gtk.Align.CENTER)
            e.append(lbl(_("Noch kein Lauf aufgezeichnet."), "empty"))
            self.bench_hist.append(card(e, 26))
            return
        # Ohne Vergleich sagt eine Zahl wie 3200 MiB/s nichts. Der Bezug ist
        # der eigene Rechner von frueher, nicht irgendeine fremde Hardware.
        base = {k: bench_baseline(runs, k, ignore_last=False) for k in BENCH_KEYS}
        if any(base.values()) and len(runs) >= 2:
            row = box(True, 12, margin_top=9, margin_bottom=9,
                      margin_start=18, margin_end=18)
            row.append(lbl(_("üblich"), "mono-dim"))
            for key, unit in (("cpu1", "MiB/s"), ("cpun", "MiB/s"),
                              ("ram", "GiB/s"), ("disk", "MiB/s")):
                last = runs[-1].get(key, 0)
                d = f"  {(last - base[key]) / base[key] * 100:+.0f} %" \
                    if base[key] and len(runs) >= 4 else ""
                v = lbl(f"{base[key]:.0f} {unit}{d}", "mono-dim", xalign=1.0)
                v.set_hexpand(True)
                row.append(v)
            w = box()
            w.append(sep())
            w.append(row)
            self.bench_hist.append(w)
        for r in reversed(runs[-8:]):
            row = box(True, 12, margin_top=9, margin_bottom=9, margin_start=18, margin_end=18)
            row.append(lbl(time.strftime("%d.%m. %H:%M", time.localtime(r["t"])), "mono"))
            for key, unit in (("cpu1", "MiB/s"), ("cpun", "MiB/s"),
                              ("ram", "GiB/s"), ("disk", "MiB/s")):
                v = lbl(f"{r.get(key, 0):.0f} {unit}", "mono", xalign=1.0)
                v.set_hexpand(True)
                row.append(v)
            w = box()
            w.append(sep())
            w.append(row)
            self.bench_hist.append(w)

    def _bench_start(self):
        self.bench_btn.set_sensitive(False)
        self.bench_sub.set_text(_("läuft, das dauert etwa 8 Sekunden …"))
        self.work(self._bench_worker, self.bench_sub)

    def _bench_worker(self):
        res = {"t": time.time(), "kind": "bench"}
        for key, fn in (("cpu1", lambda: bench_cpu(1)),
                        ("cpun", lambda: bench_cpu(os.cpu_count() or 4)),
                        ("ram", bench_ram), ("disk", bench_disk)):
            try:
                res[key] = fn()
            except Exception as e:
                print(f"bench {key}: {e}", file=sys.stderr)
                res[key] = 0.0
            GLib.idle_add(self._bench_partial, key, res[key])
        history_append(res)
        GLib.idle_add(self._bench_done)

    def _bench_partial(self, key, value):
        self.bench_tiles[key].set_text(f"{value:.0f}" if value >= 10 else f"{value:.1f}")
        return False

    def _bench_done(self):
        self.bench_btn.set_sensitive(True)
        self.bench_sub.set_text(_("fertig, Lauf im Verlauf gespeichert"))
        self._fill_bench_history()
        if "Verlauf" in self.built:
            self._fill_history()
        return False

    # Verlauf

    def _page_history(self):
        p = box(spacing=16)
        b = Gtk.Button(label=_("Verlauf löschen"))
        b.add_css_class("btn-ghost")
        b.connect("clicked", lambda *_: self._history_clear())
        head, self.hist_sub = self._head(_("Verlauf"), "", b)
        p.append(head)

        c = box(spacing=8)
        c.add_css_class("card")
        c.append(card_head(_("Systemzustand über die Zeit")))
        self.hist_chart = Chart([("score", "acc")], points=40, top=100, height=150)
        self.hist_chart.set_margin_start(14)
        self.hist_chart.set_margin_end(14)
        self.hist_chart.set_margin_bottom(14)
        c.append(self.hist_chart)
        p.append(c)

        lc = box()
        lc.add_css_class("card")
        lc.append(card_head(_("Aufzeichnungen")))
        self.hist_box = box()
        lc.append(self.hist_box)
        p.append(lc)
        self._fill_history()
        return self._scroll(p)

    def _fill_history(self):
        entries = history_read(HISTORY_MAX)
        scans = [e for e in entries if e.get("kind") == "scan"]
        benches = len([e for e in entries if e.get("kind") == "bench"])
        self.hist_sub.set_text(_("{scans} Scans · {benches} Benchmarks").format(
            scans=len(scans), benches=benches))
        self.hist_chart.data["score"] = deque(
            [float(e.get("score", 0)) for e in scans[-40:]] or [0.0], maxlen=40)
        self.hist_chart.queue_draw()

        clear(self.hist_box)
        if not entries:
            e = box(halign=Gtk.Align.CENTER)
            e.append(lbl(_("Noch nichts aufgezeichnet."), "empty"))
            self.hist_box.append(card(e, 30))
            return
        for e in reversed(entries[-20:]):
            r = box(True, 12, margin_top=9, margin_bottom=9, margin_start=18, margin_end=18)
            r.append(lbl(time.strftime("%d.%m.%Y %H:%M", time.localtime(e["t"])), "mono"))
            if e.get("kind") == "scan":
                txt = f"Scan · {e.get('crit', 0)} kritisch · {e.get('warn', 0)} Hinweise"
                pill = lbl(str(e.get("score", 0)), "pill")
                pill.add_css_class("ok" if e.get("score", 0) >= 85 else "warn"
                                   if e.get("score", 0) >= 60 else "crit")
            else:
                txt = (f"Benchmark · CPU {e.get('cpun', 0):.0f} MiB/s · "
                       f"RAM {e.get('ram', 0):.1f} GiB/s · Disk {e.get('disk', 0):.0f} MiB/s")
                pill = lbl("Bench", "pill")
            t = lbl(txt, "row-detail", xalign=0.0)
            t.set_hexpand(True)
            t.set_margin_start(8)
            r.append(t)
            pill.set_valign(Gtk.Align.CENTER)
            r.append(pill)
            w = box()
            w.append(sep())
            w.append(r)
            self.hist_box.append(w)

    def _history_clear(self):
        d = Gtk.AlertDialog(modal=True)
        d.set_message(_("Verlauf löschen?"))
        d.set_detail(_("Entfernt alle Aufzeichnungen aus {file}.").format(
            file=HISTORY_FILE))
        d.set_buttons([_("Abbrechen"), _("Löschen")])
        d.choose(self.win, None, self._history_clear_done)

    def _history_clear_done(self, dlg, res):
        try:
            if dlg.choose_finish(res) != 1:
                return
        except GLib.Error:
            return
        try:
            os.unlink(HISTORY_FILE)
        except OSError:
            pass
        self._fill_history()
        if "Benchmark" in self.built:
            self._fill_bench_history()

    # Einstellungen

    def _page_settings(self):
        p = box(spacing=16)
        head, _sub = self._head(_("Einstellungen"), f"dynotiq {VERSION}")
        p.append(head)

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Darstellung")))
        row = box(True, 12, margin_start=18, margin_end=18, margin_bottom=6)
        row.append(lbl(_("Akzentfarbe"), "row-title"))
        sw = box(True, 8, halign=Gtk.Align.END, hexpand=True)
        self.swatch_buttons = {}
        for col in ACCENTS:
            b = Gtk.Button()
            b.add_css_class("swatch")
            if col == self.cfg["accent"]:
                b.add_css_class("active")
            b.set_child(Swatch(col))
            b.connect("clicked", self._set_accent, col)
            self.swatch_buttons[col] = b
            sw.append(b)
        row.append(sw)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=12)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Statusfarben"), "row-title"))
        t.append(lbl(_("Farbschema für ok, Hinweis und kritisch"), "row-detail"))
        row.append(t)
        dd = Gtk.DropDown.new_from_strings(list(PALETTES))
        dd.set_selected(list(PALETTES).index(self.cfg["palette"]))
        dd.set_valign(Gtk.Align.CENTER)
        dd.connect("notify::selected", self._set_palette)
        row.append(dd)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=16)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Aktualisierungsintervall"), "row-title"))
        t.append(lbl(_("Wie oft Live-Werte neu gelesen werden"), "row-detail"))
        row.append(t)
        iv = Gtk.DropDown.new_from_strings(["1 s", "2 s", "5 s", "10 s"])
        opts = [1, 2, 5, 10]
        iv.set_selected(opts.index(self.cfg["interval"]) if self.cfg["interval"] in opts else 1)
        iv.set_valign(Gtk.Align.CENTER)
        iv.connect("notify::selected", self._set_interval, opts)
        row.append(iv)
        c.append(row)
        p.append(c)

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("System")))
        row = box(True, 12, margin_start=18, margin_end=18, margin_top=6, margin_bottom=12)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("dynotiq beim Login starten"), "row-title"))
        t.append(lbl(f"{AUTOSTART_DIR}/dynotiq.desktop", "mono-dim"))
        row.append(t)
        sw = Gtk.Switch(active=os.path.exists(f"{AUTOSTART_DIR}/dynotiq.desktop"),
                        valign=Gtk.Align.CENTER)
        sw.connect("state-set", self._set_own_autostart)
        row.append(sw)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=12)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Hintergrundüberwachung"), "row-title"))
        t.append(lbl(_("systemd-User-Dienst, prüft alle 30 s auf neue Vorfälle und "
                     "meldet kritische per Benachrichtigung"), "row-detail",
                     wrap=True, chars=64))
        row.append(t)
        sw = Gtk.Switch(active=watch_enabled(), valign=Gtk.Align.CENTER)
        sw.connect("state-set", self._set_watch)
        row.append(sw)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=12)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Beim Schließen im Tray weiterlaufen"), "row-title"))
        have_tray = bool(getattr(self, "tray", None) and self.tray.ok)
        hint = lbl(_("Statusicon aktiv") if have_tray
                   else _("Warte auf StatusNotifier …"), "row-detail")
        t.append(hint)
        row.append(t)
        sw = Gtk.Switch(active=self.cfg["tray"] and have_tray, valign=Gtk.Align.CENTER,
                        sensitive=have_tray)
        self.tray_switch = (sw, hint)
        sw.connect("state-set", self._set_tray)
        row.append(sw)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=12)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Firmware-Updates mitprüfen"), "row-title"))
        t.append(lbl(_("fwupd nach Geräte-Updates fragen") if shutil.which("fwupdmgr")
                     else _("fwupdmgr ist nicht installiert"), "row-detail"))
        row.append(t)
        sw = Gtk.Switch(active=self.cfg["firmware"], valign=Gtk.Align.CENTER,
                        sensitive=bool(shutil.which("fwupdmgr")))
        sw.connect("state-set", self._set_firmware)
        row.append(sw)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=12)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Vor Updates einen Snapshot anlegen"), "row-title"))
        t.append(lbl(_("Timeshift läuft vor der Installation, bricht sie ab wenn er "
                     "scheitert") if shutil.which("timeshift")
                     else _("timeshift ist nicht installiert"), "row-detail",
                     wrap=True, chars=64))
        row.append(t)
        sw = Gtk.Switch(active=self.cfg["snapshot"] and bool(shutil.which("timeshift")),
                        valign=Gtk.Align.CENTER, sensitive=bool(shutil.which("timeshift")))
        sw.connect("state-set", self._set_snapshot)
        row.append(sw)
        c.append(row)
        c.append(sep())

        row = box(True, 12, margin_start=18, margin_end=18, margin_top=12, margin_bottom=16)
        t = box(spacing=2, hexpand=True)
        t.append(lbl(_("Daten und Einstellungen"), "row-title"))
        t.append(lbl(f"{CONFIG_FILE}\n{HISTORY_FILE}", "mono-dim"))
        row.append(t)
        b = Gtk.Button(label=_("Ordner öffnen"), valign=Gtk.Align.CENTER)
        b.add_css_class("btn-ghost")
        b.connect("clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(
            "file://" + DATA_DIR, None))
        row.append(b)
        c.append(row)
        p.append(c)

        c = box()
        c.add_css_class("card")
        c.append(card_head(_("Über")))
        t = box(spacing=4, margin_start=18, margin_end=18, margin_bottom=16)
        t.append(lbl(f"dynotiq {VERSION} · GTK4 · PyGObject", "mono"))
        t.append(lbl(_("Analysiert von sich aus nur lesend. Was etwas ändert, also Updates "
                     "und Behebungen, läuft erst nach deinem Klick, zeigt vorher den "
                     "vollständigen Befehl und fragt per Systemdialog nach dem Passwort."),
                     "row-detail", wrap=True, chars=80))
        c.append(t)
        p.append(c)
        return self._scroll(p)

    def _set_accent(self, _b, col):
        self.cfg["accent"] = col
        save_config(self.cfg)
        apply_colors(self.cfg)
        self.apply_css()
        for c, b in self.swatch_buttons.items():
            b.remove_css_class("active")
        self.swatch_buttons[col].add_css_class("active")
        self.win.queue_draw()

    def _set_palette(self, dd, _p):
        self.cfg["palette"] = list(PALETTES)[dd.get_selected()]
        save_config(self.cfg)
        apply_colors(self.cfg)
        self.apply_css()
        self.win.queue_draw()

    def _set_interval(self, dd, _p, opts):
        self.cfg["interval"] = opts[dd.get_selected()]
        save_config(self.cfg)
        self.restart_tick()
        if hasattr(self, "mon_sub"):
            self.mon_sub.set_text(_("Aktualisierung alle {secs} s").format(
                secs=self.cfg["interval"]))

    def _set_watch(self, sw, state):
        if watch_set(state) != state:
            sw.set_active(not state)
            self._alert(_("Dienst nicht geschaltet"),
                        "systemctl --user hat den Zustand nicht übernommen. "
                        f"Unit liegt unter {WATCH_UNIT}.")
        return False

    def _alert(self, title, detail):
        d = Gtk.AlertDialog(modal=True)
        d.set_message(title)
        d.set_detail(detail)
        d.set_buttons([_("Schließen")])
        d.show(self.win)

    def _set_tray(self, _sw, state):
        self.cfg["tray"] = state
        save_config(self.cfg)
        return False

    def _set_firmware(self, _sw, state):
        self.cfg["firmware"] = state
        save_config(self.cfg)
        if "Updates" in self.built:
            self._updates_reload()
        return False

    def _set_snapshot(self, _sw, state):
        self.cfg["snapshot"] = state
        save_config(self.cfg)
        return False

    def _set_own_autostart(self, _sw, state):
        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        path = f"{AUTOSTART_DIR}/dynotiq.desktop"
        if state:
            with open(path, "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=dynotiq\n"
                        f"Exec={os.path.abspath(sys.argv[0])}\nTerminal=false\n")
        elif os.path.exists(path):
            os.unlink(path)
        return False

    # Scan

    def rescan(self):
        self.scan_info.set_text(_("Scan läuft …"))
        if getattr(self, "ring", None):
            self.ring.set_busy(True, len(CHECKS) + 2)
        self.work(self._scan_worker, self.scan_info)

    def _scan_progress(self, done, total):
        if getattr(self, "ring", None):
            self.ring.set_step(done, total)
        self.scan_info.set_text(_("Prüfung {done} von {total} läuft …").format(
            done=done, total=total))
        return False

    def _scan_worker(self):
        t0 = time.monotonic()
        score, findings, ctx = scan(
            lambda done, total: GLib.idle_add(self._scan_progress, done, total))
        GLib.idle_add(self._scan_done, score, findings, ctx, time.monotonic() - t0)

    def _scan_done(self, score, findings, ctx, secs):
        self.score, self.findings = score, findings
        crit = [f for f in findings if f.sev == "crit"]
        warn = [f for f in findings if f.sev == "warn"]
        history_append({"t": time.time(), "kind": "scan", "score": score,
                        "crit": len(crit), "warn": len(warn)})

        self.ring.set_busy(False)
        self.ring.set_value(score)
        state = (_("gut") if score >= 85
                 else _("mittelmäßig") if score >= 60 else _("schlecht"))
        self.score_title.set_text(_("Systemzustand: {state}").format(state=state))
        self.score_sub.set_text(_("{n} Befunde").format(n=len(findings)))
        self.scan_info.set_text(
            _("Letzter Scan: heute, {time} · Dauer {secs:.0f} s").format(
                time=time.strftime("%H:%M"), secs=secs))
        self.problem_badge.set_text(str(len(crit)))
        self.problem_badge.set_visible(bool(crit))
        self.list_count.set_text(_("{crit} kritisch · {warn} Hinweise").format(
            crit=len(crit), warn=len(warn)))

        if crit:
            n = {1: _("Eine Sache bremst"), 2: _("Zwei Dinge bremsen"),
                 3: _("Drei Dinge bremsen")}.get(
                     len(crit), _("{n} Dinge bremsen").format(n=len(crit)))
            self.headline.set_text(_("{what} deinen PC aus.").format(what=n))
            self.lede.set_text(_("Behebst du sie, läuft die Kiste wieder so, wie sie soll."))
        else:
            self.headline.set_text(_("Nichts Kritisches gefunden."))
            self.lede.set_text(_("Das System läuft im grünen Bereich."))

        clear(self.list_box)
        for f in findings[:4]:
            self.list_box.append(self._finding_row(f))
        rest = len(findings) - 4
        if rest > 0:
            more = box(True, 14, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18)
            more.set_opacity(.72)
            b = Gtk.Box(valign=Gtk.Align.CENTER)
            b.add_css_class("bullet-warn")
            more.append(b)
            more.append(lbl(_("{n} weitere Hinweise").format(n=rest),
                            "row-detail"))
            link = Gtk.Button(label=_("Alle anzeigen"), halign=Gtk.Align.END, hexpand=True)
            link.add_css_class("btn-ghost")
            link.connect("clicked", lambda *_: self._nav_clicked(
                self.nav_buttons["Probleme"], "Probleme"))
            more.append(link)
            self.list_box.append(more)

        self._fill_problems()
        if "Verlauf" in self.built:
            self._fill_history()
        if getattr(self, "tray", None):
            self.tray.set_tooltip(
                _("Systemzustand {score}/100 · {crit} kritisch").format(
                    score=score, crit=len(crit)))
        return False

    def _copy_report(self, btn):
        lines = [f"dynotiq - Systemcheck {time.strftime('%Y-%m-%d %H:%M')}",
                 f"{cpu_model()} · Kernel {os.uname().release}",
                 f"Score: {self.score}/100", ""]
        for f in self.findings:
            lines.append(f"[{f.sev.upper()}] {f.title}")
            lines.append(f"  {f.detail}")
            if f.cmd:
                lines.append(f"  $ {f.cmd}")
        Gdk.Display.get_default().get_clipboard().set("\n".join(lines))
        btn.set_label(_("Kopiert"))
        GLib.timeout_add_seconds(2, lambda: btn.set_label(_("Bericht kopieren")) or False)

    # Live-Werte

    def _tick(self):
        now = time.monotonic()
        dt = max(now - self.prev_t, 0.001)
        self.prev_t = now

        cur = cpu_times()
        pct = busy_percent(self.prev_cpu, cur)
        self.prev_cpu = cur
        total, avail = meminfo()
        ram_pct = 100 * (total - avail) / total
        sw_total, sw_free = swapinfo()
        swap_pct = 100 * (sw_total - sw_free) / sw_total if sw_total else 0.0

        self.tiles["CPU"][0].set_text(f"{pct:.0f} %")
        self.tiles["CPU"][1].push(pct)
        self.tiles["RAM"][0].set_text(f"{ram_pct:.0f} %")
        self.tiles["RAM"][1].push(ram_pct)
        nt = nvme_temp()
        if nt:
            self.tiles["NVMe"][0].set_text(f"{nt:.0f} °C")
            self.tiles["NVMe"][1].push(nt)
        ct = cpu_temp()
        if ct:
            v, _u = self.kpi["CPU-TEMP"]
            v.set_text(f"{ct:.0f}")
            self._state(v, ct < 75, ct < 88)
        v, _u = self.kpi["RAM FREI"]
        v.set_text(f"{avail:.1f}")
        self._state(v, avail > 4, avail > 2)

        # Nur die sichtbare Seite rechnet. Sonst laeuft die Monitor-Arbeit
        # samt Prozessliste für immer weiter, sobald sie einmal offen war.
        if self.stack.get_visible_child_name() == "Live-Monitor":
            self.charts["cpu"].push({"cpu": pct})
            self.charts["cpu_val"].set_text(f"{pct:.0f} %")
            self.charts["mem"].push({"mem": ram_pct, "swap": swap_pct})
            self.charts["mem_val"].set_text(f"{ram_pct:.0f} %")

            cores = cpu_times(per_core=True)
            for i, bar in enumerate(self.core_bars):
                if i + 1 < len(cores) and i + 1 < len(self.prev_cores):
                    bar.set_fraction(busy_percent(self.prev_cores[i + 1], cores[i + 1]) / 100)
            self.prev_cores = cores

            rx, tx = net_bytes()
            rd, wr = disk_bytes()
            net_mb = (rx - self.prev_net[0] + tx - self.prev_net[1]) / dt / 2**20
            disk_mb = (rd - self.prev_disk[0] + wr - self.prev_disk[1]) / dt / 2**20
            self.prev_net, self.prev_disk = (rx, tx), (rd, wr)
            self.charts["io"].push({"net": net_mb, "disk": disk_mb})
            self.charts["io_val"].set_text(f"{net_mb + disk_mb:.1f} MB/s")

            # 483 Prozesse einlesen kostet knapp 9 ms, das gehoert nicht in den
            # Zeichenthread. Immer nur einer gleichzeitig.
            if not self.procs_busy:
                self.procs_busy = True
                threading.Thread(target=self._procs_worker, args=(dt,),
                                 daemon=True).start()

        # Nur ein GPU-Worker gleichzeitig. Braucht nvidia-smi länger als das
        # Intervall, stapeln sich sonst Threads und die Kurve springt.
        if not self.gpu_busy:
            self.gpu_busy = True
            threading.Thread(target=self._gpu_worker, daemon=True).start()
        return True

    def _procs_worker(self, dt):
        try:
            procs = processes()
            ticks = os.sysconf("SC_CLK_TCK")
            for p in procs:
                delta = p["cpu"] - self.prev_procs.get(p["pid"], p["cpu"])
                p["pct"] = 100 * delta / ticks / dt
            self.prev_procs = {p["pid"]: p["cpu"] for p in procs}
            procs.sort(key=lambda p: -p["pct"])
            GLib.idle_add(self._fill_procs, procs[:6])
        finally:
            self.procs_busy = False
        self.dyno_id = None
        self.dyno_samples = []

    def _gpu_worker(self):
        try:
            g = gpu()
            if g:
                GLib.idle_add(self._gpu_done, g)
        finally:
            self.gpu_busy = False

    def _gpu_done(self, g):
        self.tiles["GPU"][0].set_text(f"{g['util']:.0f} %")
        self.tiles["GPU"][1].push(g["util"])
        v, u = self.kpi["GPU-TAKT"]
        v.set_text(f"{g['clock']:.0f}")
        u.set_text(_("MHz gedrosselt") if g.get("throttled") else "MHz")
        self._state(v, not g.get("throttled"), True)
        if self.stack.get_visible_child_name() == "Live-Monitor":
            self.charts["gpu"].push({"util": g["util"], "temp": g["temp"]})
            self.charts["gpu_val"].set_text(f"{g['util']:.0f} % · {g['temp']:.0f} °C")
        return False

    def _state(self, widget, good, ok):
        for c in ("state-ok", "state-warn", "state-crit"):
            widget.remove_css_class(c)
        widget.add_css_class("state-ok" if good else "state-warn" if ok else "state-crit")


def selftest():
    assert parse_driver_branches(
        "nvidia-driver-595-open, (kernel modules ...)\n"
        "nvidia-driver-610, (kernel modules ...)\n"
        "nvidia-driver-580-server, (kernel modules ...)\n") == [610, 595, 580]
    assert parse_driver_branches("") == []
    # Vorgeschlagen wird der empfohlene, nicht der hoechste Branch
    devices_out = (
        "== /sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0 ==\n"
        "modalias : pci:v000010DEd00002484sv00001458sd0000403Bbc03sc00i00\n"
        "vendor   : NVIDIA Corporation\n"
        "model    : GA104 [GeForce RTX 3070]\n"
        "driver   : nvidia-driver-610 - third-party non-free\n"
        "driver   : nvidia-driver-595 - third-party non-free recommended\n"
        "driver   : nvidia-driver-580-server - distro non-free\n"
        "driver   : xserver-xorg-video-nouveau - distro free builtin\n")
    assert parse_recommended_driver(devices_out) == ("nvidia-driver-595", 595)
    assert parse_driver_branches(devices_out) == [610, 595, 580]
    assert parse_recommended_driver(
        "driver   : nvidia-driver-550-open - distro non-free recommended\n") \
        == ("nvidia-driver-550-open", 550)
    # Ohne Markierung wird nichts vorgeschlagen, lieber gar nichts als geraten
    assert parse_recommended_driver(
        "driver   : nvidia-driver-610 - third-party non-free\n") == (None, 0)
    assert parse_recommended_driver("") == (None, 0)
    # Serie aus der Bibliotheksversion, '?' darf nicht zum Absturz fuehren
    assert branch_of("610.43") == 610 and branch_of("595") == 595
    assert branch_of("?") == 0 and branch_of("") == 0
    assert parse_disabled_snaps(
        "Name  Version  Rev  Tracking  Publisher  Notes\n"
        "blender 5.2.0 7599 latest/stable bf** classic\n"
        "livepatch v10.15.0 393 latest/stable canonical** disabled\n") == [("livepatch", "393")]

    # Die ID behält :arch, sonst aktualisiert der Befehl auf Multi-Arch-Systemen
    # das falsche Paket. Größe kommt aus der --print-uris-Ausgabe.
    assert parse_apt_updates(
        "Inst code [1.130.0-178] (1.131.0-178 code stable:stable [amd64])\n"
        "Inst libfoo:i386 [2.0] (2.1 Ubuntu:24.04/noble-updates [i386])\n"
        "Conf code (1.131.0-178 code stable:stable [amd64])\n",
        "'https://x/code_1.131.0-178_amd64.deb' code_1.131.0-178_amd64.deb 233296358 M\n") == [
            ("code", "code", "1.130.0-178", "1.131.0-178", 233296358),
            ("libfoo:i386", "libfoo", "2.0", "2.1", 0)]
    assert parse_apt_updates("0 upgraded, 0 newly installed.\n") == []
    assert parse_size("50.2MB") == 50200000 and parse_size("149.4 MB") == 149400000
    assert parse_size("1.2GB") == 1200000000 and parse_size("-") == 0
    # So kommt Flatpaks schmales Leerzeichen unter LC_ALL=C an
    assert parse_size("149.4?MB") == 149400000
    assert parse_size("149.4 MB") == 149400000 and parse_size("512 B") == 512
    # Snap hebt oft nur die Revision an, dann muss die Zeile die Revision zeigen
    assert parse_snap_updates(
        "Name  Version  Rev  Size    Publisher  Notes\n"
        "cups  2.4.19-2 1238 50.2MB  openprinting** -\n"
        "obsidian 1.13.4 65 115MB obsidianmd classic\n",
        "Name  Version  Rev  Tracking  Publisher  Notes\n"
        "cups  2.4.19-2 1200 latest/stable openprinting** -\n"
        "obsidian 1.12.7 60 latest/stable obsidianmd classic\n") == [
            ("cups", "cups", _("Rev {rev}").format(rev="1200"),
             _("Rev {rev}").format(rev="1238"), 50200000),
            ("obsidian", "obsidian", "1.12.7", "1.13.4", 115000000)]
    assert parse_snap_updates("All snaps up to date.\n") == []
    # Refs ohne Version dürfen nicht mit leerer Änderungszeile durchfallen
    assert parse_flatpak_updates(
        "Mesa\truntime/org.fd.GL/x86_64/24.08\t26.1.5\tf046ba86468f\t149.4 MB\n"
        "Flatseal\tapp/com.tchx84.Flatseal/x86_64/stable\t2.4.2\tabcdef123456\t2.1 MB\n"
        "Basis\truntime/org.fd.Base/x86_64/24.08\t\tfeed0000beef\t8 MB\n",
        "org.fd.GL/x86_64/24.08\t26.1.5\tac4c5853488c\n"
        "com.tchx84.Flatseal/x86_64/stable\t2.4.1\tef9fe38e9cb9\n") == [
            ("org.fd.GL/x86_64/24.08", "Mesa",
             _("Build {id}").format(id="ac4c5853"),
             _("Build {id}").format(id="f046ba86"), 149400000),
            ("com.tchx84.Flatseal/x86_64/stable", "Flatseal", "2.4.1", "2.4.2", 2100000),
            ("org.fd.Base/x86_64/24.08", "Basis", _("neu"),
             _("Build {id}").format(id="feed0000"), 8000000)]
    assert parse_fwupd_updates('{"Devices": []}') == []
    assert parse_fwupd_updates("kein json") == []
    assert parse_fwupd_updates(json.dumps({"Devices": [
        {"Name": "System Firmware", "DeviceId": "ab12", "Version": "1.0",
         "Releases": [{"Version": "1.1", "Size": 4194304}]},
        {"Name": "Ohne Release", "Version": "3.0"}]})) == [
            ("ab12", "System Firmware", "1.0", "1.1", 4194304)]
    # Trennt Paketnamen von allem, was als Option oder Löschbefehl durchginge
    assert valid_pkg("libfoo1.2+git") and valid_pkg("org.fd.GL/x86_64/24.08")
    assert valid_pkg("libfoo:i386")
    assert not valid_pkg("--force-yes") and not valid_pkg("foo-") \
        and not valid_pkg("rm -rf") and not valid_pkg("")
    # pkexec setzt die Umgebung zurück, deshalb muss env davor stehen
    assert update_cmd("apt", ["a"])[:3] == ["pkexec", "/usr/bin/env",
                                            "DEBIAN_FRONTEND=noninteractive"]
    assert update_cmd("snap", ["a"])[-3:] == ["refresh", "--", "a"]
    assert cmd_steps(["a", "b"]) == [["a", "b"]]
    assert cmd_steps([["a"], ["b", "c"]]) == [["a"], ["b", "c"]]
    # Fortschritt kommt aus den Ausgabezeilen, nicht aus geraten Prozenten
    assert progress_name("Setting up libfoo1:amd64 (1.2-3) ...") == "libfoo1:amd64"
    assert progress_name("Unpacking code (1.131.0) over (1.130.0) ...") == "code"
    assert progress_name("Preparing to unpack .../code_1.131.0_amd64.deb ...") == "code"
    assert progress_name("Refreshing snapd") == "snapd"
    assert desktop_icon("[Desktop Entry]\nName=Code\nIcon=vscode\n") == "vscode"
    assert desktop_icon("Name=Ohne") == ""
    assert update_icon("flatpak", "org.fd.GL/x86_64/24.08", "Mesa") == "org.fd.GL"
    assert update_icon("apt", "gibtsnicht:amd64", "x") == ""
    # Auf einer Datenpartition darf kein apt-Befehl angeboten werden, dort
    # liegt kein Paket das er entfernen koennte
    data = {"mounts": [{"target": "/media/x/Games", "total": 100, "used": 95,
                        "free": 5, "src": "/dev/sdc1", "fs": "ext4"}]}
    f = check_filesystems(data)
    assert f.cmd is None and f.argv is None, (f.cmd, f.argv)
    root = {"mounts": [{"target": "/", "total": 100, "used": 95, "free": 5,
                        "src": "/dev/sda2", "fs": "ext4"}]}
    assert "autoremove" in check_filesystems(root).cmd
    # Release-Upgrade nur melden, wenn do-release-upgrade wirklich eins nennt
    assert parse_release_upgrade("New release '26.04.1 LTS' available.\n"
                                 "Run 'do-release-upgrade' to upgrade to it.") \
        == "26.04.1 LTS"
    assert parse_release_upgrade("There is no development version of an LTS "
                                 "available.") == ""
    assert os_release("VERSION_ID")
    assert terminal_cmd(["x"])[-1] == "x"
    # Solange Ubuntu nur erschienen, aber nicht freigegeben ist, wird nichts
    # gemeldet. Der Zustand darf dabei nicht kaputtgeschrieben werden.
    before = state_read()
    assert release_notify() is None or state_read().get("release_notified")
    assert state_read().get("last_check") == before.get("last_check")
    # Ubuntus Releaseliste: 26.04 steht in der LTS-Datei mit Supported 0, weil
    # die Freigabe fuer LTS-Nutzer erst mit dem Point-Release kommt.
    meta = ("Dist: noble\nVersion: 24.04 LTS\nSupported: 1\n\n"
            "Dist: resolute\nVersion: 26.04 LTS\nSupported: 1\n\n"
            "Dist: sonstwas\nVersion: 26.10\nSupported: 0\n")
    rel = parse_meta_release(meta)
    assert rel[1] == ("26.04 LTS", "resolute", True), rel
    assert newer_release("24.04", rel)[0] == "26.04 LTS"
    assert newer_release("26.04", rel) is None
    assert version_tuple("24.04 LTS") == (24, 4)
    # Treiberwechsel ohne Neustart: Modul alt, Bibliothek neu
    assert parse_nvml_mismatch("Failed to initialize NVML: Driver/library version "
                               "mismatch\nNVML library version: 610.43") == "610.43"
    assert parse_nvml_mismatch("Mon Jul 31 08:00:00 2026\n+---+\n") == ""
    assert nvidia_loaded_version(
        "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  580.173.02  "
        "Release Build\nGCC version: 13.3.0") == "580.173.02"
    assert nvidia_loaded_version("") == ""
    # Beide Quellenformate, alte .list-Zeile und deb822
    assert parse_apt_source(
        "deb [signed-by=/x.gpg] https://pkgs.tailscale.com/stable/ubuntu noble main\n"
        "# deb kommentiert\n"
        "deb [signed-by=/y.gpg] https://downloads.naps2.com ./\n") == [
            ("https://pkgs.tailscale.com/stable/ubuntu", "noble"),
            ("https://downloads.naps2.com", "./")]
    assert parse_apt_source(
        "Types: deb\nURIs: https://ppa.launchpadcontent.net/lutris/ubuntu/\n"
        "Suites: noble\nComponents: main\n") == [
            ("https://ppa.launchpadcontent.net/lutris/ubuntu/", "noble")]
    # Aus dem PPA-Dateinamen faellt der Programmname, damit die Flatpak-Suche greift
    assert ppa_program("lutris-team-ubuntu-lutris-noble") == "lutris"
    assert ppa_program("tomtomtom-ubuntu-woeusb-noble") == "woeusb"
    assert ppa_program("heyarje-ubuntu-makemkv-beta-noble") == "makemkv-beta"
    assert ppa_program("tailscale") == "tailscale"
    # Basislinie aus den eigenen Laeufen, ein Ausreisser darf sie nicht kippen
    runs = [{"disk": 3000}, {"disk": 3100}, {"disk": 2900}, {"disk": 3050},
            {"disk": 1800}]
    assert bench_baseline(runs, "disk") == 3025
    assert round(bench_drop(runs, "disk"), 3) == -0.405
    assert bench_drop([{"disk": 3000}, {"disk": 3000}], "disk") is None   # zu wenig
    assert bench_drop([{"disk": 3000}] * 5, "disk") is None               # stabil
    assert median([1, 2, 3]) == 2 and median([1, 2, 3, 4]) == 2.5 and median([]) == 0.0
    # Messwerte zum Vorfall, damit aus der Fehlermeldung ein Zusammenhang wird
    assert format_snapshot({}) == ""
    # Sprachunabhaengig geprueft, der Katalog darf den Wortlaut aendern.
    line = format_snapshot({"cpu_temp": 71, "gpu_temp": 87, "gpu_clock": 1800,
                            "gpu_throttled": True, "ram": 64, "load": 3.75})
    assert all(v in line for v in ("71", "87", "1800", "64", "3.8"))
    assert line.count("·") == 3
    snap = system_snapshot()
    assert isinstance(snap, dict) and all(
        k in ("ram", "cpu_temp", "gpu_temp", "gpu_clock", "gpu_throttled", "load")
        for k in snap), snap
    # Pruefstand: aus Messpunkten wird die Frage beantwortet, ab wann gedrosselt wird
    samples = [{"t": 100.0, "cpu": 20, "gpu_temp": 60, "gpu_clock": 2600},
               {"t": 130.0, "cpu": 95, "gpu_temp": 78, "gpu_clock": 2600},
               {"t": 160.0, "cpu": 97, "gpu_temp": 87, "gpu_clock": 1800,
                "throttled": True},
               {"t": 190.0, "cpu": 96, "gpu_temp": 88, "gpu_clock": 1750,
                "throttled": True}]
    su = record_summary(samples)
    assert su["secs"] == 90 and su["n"] == 4
    assert su["gpu_temp"] == {"min": 60, "max": 88, "med": 82.5}, su["gpu_temp"]
    assert su["gpu_clock"]["min"] == 1750
    assert su["throttle_share"] == 50 and su["throttle_from"] == 60
    assert record_summary([]) == {} and format_summary({}) == _(
        "Keine Messpunkte aufgezeichnet.")
    text = format_summary(su)
    assert "1:30 min" in text and "1:00 min" in text
    assert _("Die Grafikkarte drosselte in {pct} % der Messpunkte, erstmals "
             "nach {mins}:{secs:02d} min.").format(pct=50, mins=1, secs=0) in text
    assert _("Keine Drosselung aufgezeichnet.") in format_summary(
        record_summary(samples[:2]))
    s, cur = record_sample(cpu_times())
    assert "cpu" in s and "ram" in s and isinstance(cur, tuple)
    # App-Prüfung: Herkunft und Sandbox-Lücken erkennen
    assert exec_binary("env BAMF_DESKTOP_FILE_HINT=x /snap/bin/obsidian %U") \
        == "/snap/bin/obsidian"
    assert exec_binary("/usr/bin/firefox %u") == "/usr/bin/firefox"
    # 'env -u NAME' frisst zwei Tokens, sonst gilt '-u' als das Programm
    assert exec_binary("env -u GIO_MODULE_DIR __GL_MaxFramesAllowed=1 "
                       "/home/x/Applications/Kyber-x86_64.AppImage") \
        == "/home/x/Applications/Kyber-x86_64.AppImage"
    assert exec_binary('"/usr/bin/nextcloud" --background') == "/usr/bin/nextcloud"
    assert exec_binary("") == ""
    assert app_source({"Exec": "/home/x/Foo.AppImage"})[0] == "appimage"
    # Fachbegriffe müssen übersetzt werden, sonst hilft der Befund niemandem
    # Nur der dpkg-Status als Quelle heißt: von Hand installiert, nie Updates
    assert parse_apt_policy(
        "discord:\n  Installed: 1.0.139\n  Candidate: 1.0.139\n"
        "  Version table:\n *** 1.0.139 100\n        100 /var/lib/dpkg/status\n") \
        == ("1.0.139", "1.0.139", False)
    assert parse_apt_policy(
        "code:\n  Installed: 1.130.0\n  Candidate: 1.131.0\n  Version table:\n"
        "     1.131.0 500\n        500 https://packages.microsoft.com/repos/code "
        "stable/main amd64 Packages\n") == ("1.130.0", "1.131.0", True)
    assert parse_apt_policy("N: Unable to locate package foo") == ("", "", False)
    # Der Selbst-Check haengt genau an diesen drei Werten
    assert parse_apt_policy(
        "dynotiq:\n  Installed: (none)\n  Candidate: 0.2\n  Version table:\n"
        "     0.2 500\n        500 https://ppa.launchpadcontent.net/x/y/ubuntu "
        "noble/main amd64 Packages\n") == ("(none)", "0.2", True)
    assert check_self_update({}) is None or shutil.which("apt-cache")
    assert iface_text("audio-record")[0] == _("Mikrofon")
    assert iface_text("removable-media")[0] == _("USB-Sticks und externe "
                                                 "Laufwerke")
    assert iface_text("irgendwas-neues") == (
        "irgendwas neues",
        _("Was genau dahinter steckt, sagt die Beschreibung des Snaps."))
    # info ist ein Hinweis und darf im Bericht nicht wie ein Fehler aussehen
    assert app_check_text("X", [("info", "A", "B", None)]).endswith("·  A: B")
    assert app_source({"Exec": "/usr/bin/flatpak run --branch=stable "
                               "--command=rustdesk com.rustdesk.RustDesk @@u %u @@"}) \
        == ("flatpak", "com.rustdesk.RustDesk")
    assert app_source({"Exec": "/snap/bin/localsend"}) == ("snap", "localsend")
    assert parse_snap_connections(
        "Interface  Plug              Slot   Notes\n"
        "alsa       firefox:alsa      -      -\n"
        "audio-playback firefox:audio-playback :audio-playback -\n"
        "camera     firefox:camera    -      -\n", "firefox") == ["alsa", "camera"]
    assert parse_flatpak_perms(
        "[Context]\nsockets=x11;wayland;\ndevices=dri;\n")["Grafikbeschleunigung"] \
        == ["dri"]
    assert parse_flatpak_perms("[Context]\nsockets=x11;\n")["Grafikbeschleunigung"] == []
    n, ops = parse_denials(
        'kernel: apparmor="DENIED" operation="open" label="snap.thunderbird.tb"\n'
        'kernel: apparmor="DENIED" operation="dbus_method_call" label="snap.thunderbird.tb"\n'
        'kernel: apparmor="DENIED" operation="open" label="snap.other.x"\n',
        "snap.thunderbird")
    assert (n, ops) == (2, ["dbus_method_call", "open"]), (n, ops)
    assert progress_name("Get:3 http://archive.ubuntu.com jammy/main amd64 x") is None
    assert progress_name("") is None
    # Leere lspci-Ausgabe darf den Treiber-Scan nicht sprengen
    assert parse_lspci("") == [] and parse_lspci("\n\n") == []
    # Ausführbare Fixes dürfen nur feste Argumentlisten sein, nie ein Shell-String
    for chk in (check_journal, check_filesystems, check_gpu_driver):
        f = chk({"gpu": {"vendor": "nvidia", "driver": "1.0"}})
        if f and f.argv:
            for step in cmd_steps(f.argv):
                assert step[0] == "pkexec", step
                assert all(isinstance(a, str) and "&&" not in a and ";" not in a
                           for a in step), step
    # Units über einer Minute oder Stunde sind genau die, die man sehen will
    assert parse_blame("11h 26min 16.414s snapd.service\n"
                       "1min 5.432s snapd.seeded.service\n"
                       "  8.123s NetworkManager.service\n"
                       "   543ms cups.service\n"
                       "kaputte Zeile\n") == [
        (41176.414, "snapd.service"), (65.432, "snapd.seeded.service"),
        (8.123, "NetworkManager.service"), (0.543, "cups.service")]
    assert unit_disable_cmd("foo.service")[0] == "pkexec"
    assert unit_disable_cmd("foo.service", ("--user",))[:2] == ["systemctl", "--user"]

    devs = parse_lspci(
        "08:00.0 VGA compatible controller: NVIDIA GA106 (rev a1)\n"
        "\tSubsystem: MSI GA106\n"
        "\tKernel driver in use: nvidia\n"
        "\tKernel modules: nouveau, nvidia\n"
        "0a:00.0 SATA controller: AMD FCH SATA\n")
    assert [d["driver"] for d in devs] == ["nvidia", None], devs
    assert devs[0]["modules"] == ["nouveau", "nvidia"]
    assert devs[1]["class"] == "SATA controller"

    e = parse_desktop("[Desktop Entry]\nName=Test\nName[de]=Prüfung\n"
                      "Hidden=true\n[Other]\nName=Ignoriert\n")
    assert e["Name[de]"] == "Prüfung" and e["Hidden"] == "true" and e["Name"] == "Test"

    # Fälle aus den Sentinel-Tests, damit die Wissensbasis beim Portieren nicht kippt
    detail = "kernel: NVRM: Xid (PCI:0000:01:00): 79, pid=2140 - GPU has fallen off the bus"
    fix, summary, _c, _s = classify("GPU-Treiberfehler erkannt", detail)
    assert fix == "crit" and "fallen off the bus" in summary
    assert classify("GPU-Treiberfehler erkannt", "kernel: NVRM: Xid: 43")[0] == "info"
    fix, summary, _c, steps = classify("systemd-Unit fehlgeschlagen", "vboxdrv.service")
    assert "VirtualBox" in summary and any("virtualbox-dkms" in x for x in steps)
    assert "bluetooth.service" in classify("systemd-Unit fehlgeschlagen",
                                           "bluetooth.service")[1]
    assert classify("Irgendwas Neues", "irrelevant")[0] == "info"

    line = "2026-07-30T23:14:02+0200 host kernel: Out of memory: Killed process 1234"
    assert strip_prefix(line).startswith("Out of memory")
    assert journal_time(line) > 1700000000
    assert journal_time("ohne Zeitstempel") > 0
    assert incident_key({"t": 1.9, "cat": "GPU", "title": "a", "detail": "b"}) == "1|a|b"
    # Die Unit-Episode aus Sentinels systemd_units.rs, drei Fälle:
    # erster Ausfall meldet, Dauerausfall behält seinen Beginn, und eine
    # reparierte Unit fängt bei erneutem Ausfall eine neue Episode an.
    ep = unit_episodes({}, ["bluetooth.service"], now=100.0)
    assert ep == {"bluetooth.service": 100.0}
    assert unit_episodes(ep, ["bluetooth.service"], now=500.0) == ep
    assert unit_episodes(ep, [], now=500.0) == {}
    assert unit_episodes({}, ["bluetooth.service"], now=900.0) \
        == {"bluetooth.service": 900.0}
    # Solange die Episode läuft, bleibt der Schlüssel gleich, danach nicht mehr
    a = {"t": 100.0, "cat": "Systemd", "title": "x", "detail": "bluetooth.service"}
    assert incident_key(a) == incident_key(dict(a, t=100.9))
    assert incident_key(a) != incident_key(dict(a, t=900.0))
    # Inkrementell lesen, aber nur wenn der letzte Lauf plausibel ist
    assert scan_window(None) == "-24h"
    assert scan_window(0) == "-24h"
    assert scan_window(1000.0, now=1000.0 + 25 * 3600) == "-24h"
    assert scan_window(1000.0, now=1000.0 + 60) == "@1000"
    assert scan_window(9e9, now=1000.0) == "-24h"          # Uhr in der Zukunft

    assert alpha("#FF6B2C", .13) == "rgba(255,107,44,0.13)"
    assert lighten("#000000", .5) == "#7F7F7F"
    assert "@ACC@" not in build_css() and COLORS["acc"] in build_css()
    assert fmt_bytes(2**30) == "1.0 GB" and fmt_bytes(512) == "512 B"

    prev = cpu_times()
    assert 0 <= busy_percent(prev, cpu_times()) <= 100
    assert len(cpu_times(per_core=True)) > 1
    t, a = meminfo()
    assert t > 0 and 0 <= a <= t
    assert net_bytes()[0] >= 0 and disk_bytes()[0] >= 0
    assert any(p["pid"] == os.getpid() for p in processes())
    assert all(m["total"] > 0 for m in mounts())
    assert bench_ram(0.05) > 0 and bench_cpu(1, 0.05) > 0
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--watch" in sys.argv:
        watch()
    elif "--install" in sys.argv:
        ensure_icons()
        ensure_desktop()
        print(f"Icons in {HICOLOR}, Starter in {DESKTOP_FILE}")
    else:
        # WM_CLASS kommt vom prgname und muss zum StartupWMClass im Starter passen.
        GLib.set_prgname("dynotiq")
        GLib.set_application_name("dynotiq")
        page = (sys.argv[sys.argv.index("--page") + 1]
                if "--page" in sys.argv else "Übersicht")
        # Die Seitennamen sind intern deutsch, auf Englisch tippt aber
        # niemand "Speicher". Beide Schreibweisen gelten.
        if page not in NAV:
            page = next((n for n in NAV if _(n).lower() == page.lower()),
                        "Übersicht")
        sys.exit(App(page).run(None))
