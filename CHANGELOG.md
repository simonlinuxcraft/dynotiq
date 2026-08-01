# Changelog

## 0.1 - First release

dynotiq scans an Ubuntu machine for what slows it down, explains every finding
in plain language and offers the matching fix.

### Diagnostics

- System check with a score, findings sorted by severity, each with the exact
  command it would run
- Incident detection from the journal: audio dropouts, GPU driver errors,
  out-of-memory kills and failed systemd units, with the machine's temperature
  at that moment
- Knowledge base for NVIDIA Xid codes, audio xruns and OOM kills, each with
  causes and steps
- Driver page listing devices without a kernel driver, and the NVIDIA driver
  Ubuntu recommends for the card

### Maintenance

- Updates from apt, snap, flatpak and fwupd in one place, with sizes, a live
  log and an optional Timeshift snapshot beforehand
- App check: missing libraries, cut off sandbox permissions, blocked accesses,
  crashes and journal errors for any installed application
- Storage page showing what can be reclaimed, startup entries with boot times,
  live monitor for CPU, GPU, RAM, network and disk

### Measurement

- Dyno records temperature and clock over minutes and reports when sustained
  load starts throttling
- Benchmark for single and multi threaded CPU, memory copy and disk write,
  compared against your own earlier runs rather than other machines

### Interface

- German and English, following the desktop language
- Four accent colours, three status palettes, adjustable refresh interval
- Optional background service reporting new incidents as notifications
- Nothing is changed without a click: every fix shows its full command first
  and asks for the password through the system dialog
