# Changelog

## 0.2~beta1 - Waiting, not just heat

### Incidents

- Three disk detectors, all of them the kind that makes a machine feel broken
  without saying why: an ext4 error that remounts the partition read only, an
  NVMe that stops answering and gets reset by the driver, and an uncorrectable
  PCIe error. Each one names the likely cause and what to do, and the disk
  advice deliberately says to run fsck from a live stick rather than on the
  mounted system
- Two more graphics detectors: an AMD ring timeout, and a rejected page flip,
  which is what a frozen or flickering desktop looks like in the journal
- systemd-oomd killing an application is now recognised as its own incident.
  Ubuntu ships it enabled against the user session, so this hits games and
  browsers rather than servers
- New Xid 48, and a new incident category for disks in the filter
- The knowledge base is shared: an entry brings its own pattern, severity,
  explanation and next step, and the same entry serves both the incident page
  and the app check

### Dyno

- Records what the machine waits for, not only how warm it got. Stall times for
  CPU, memory and disk come from the kernel pressure counters, the time the game
  spent queued for a core from its own scheduler statistics, and its paging
  accesses from the process itself. Those counters keep running between the
  samples, so a hitch of 300 ms still shows up although a reading is taken every
  two seconds
- A run can now end in PAGING: nothing was warm, nothing throttled, and the
  machine still stood still waiting for memory. That case was invisible before
- CLEAN says more than it used to. Where the counters are there, it states that
  the machine did not wait for a core, for memory or for the disk either, so a
  remaining stutter is not down to this machine
- The reason for throttling comes from the driver instead of being guessed from
  the temperature. NVML names it, and the bits were being collapsed into a plain
  yes or no before
- CPU limit is checked before clock loss. A card that clocks down for lack of
  work was reported as one that gets too warm, together with the advice to clean
  out the dust
- Clock loss no longer claims heat when the temperature did not rise
- Advice for a busy core, for waiting on a core, on the disk, and for constant
  paging, each with the reading it follows from
- Every measure carries the button that belongs to it: the installed tuning tool
  for fan curve and undervolting, the governor switch, or the page of the app
  that shows the culprits

### Games

- ntsync: Ubuntu ships the module and never loads it, so Proton quietly falls
  back to the older way of handling threads. The check tells the three states
  apart and offers to load it and keep it loaded
- Resizable BAR, read from the PCI resource bitmap. Which BAR carries the view
  onto the graphics memory depends on the vendor
- Games set to a Proton build that is not installed anywhere. Steam says nothing
  about it and silently starts them with something else. The internal name from
  compatibilitytool.vdf is what counts, not the directory name, and the two
  differ regularly
- Proton prefixes of games that were uninstalled long ago, with the space they
  take. Steam's own template and non-Steam shortcuts stay out of that list
- An incomplete Steam runtime is explained in the app check, with the button
  that has Steam verify it
- The file handle limit is explained by ntsync now. It used to name esync, which
  no longer exists in Proton

### App check

- Journal lines are explained rather than printed. Where the knowledge base
  knows a line, it says what happened and what to do about it, once per kind
- The search filtered nothing at all. A GtkDropDown only searches once an
  expression is set, and even then it matches the start of a name and nothing
  else. The list has its own search field now that matches anywhere in the name
  and ignores case, so "Hunt: Showdown 1896" is found by typing showdown and
  "A Total War Saga: TROY" by typing troy

### Fixes

- The dyno logged the runtime or the Proton build as the game. Both paths sit in
  the process list of every Proton title, and whichever came first won. A run
  filed under that name was never found again for the game it belonged to
- A library folder called Games was taken for the title. What sits directly
  above steamapps is a library, not a game
- The game is now measured on the process that does the work, not on the wrapper
  shell or the sandbox that carry the same path
- The dyno started a measuring thread every two seconds without checking whether
  the previous one had finished. When nvidia-smi hangs, which is what happens
  with a throttling card, the samples overtook each other
- Throttling was reported from the start of the recording instead of the start
  of the load phase, so a long loading screen was counted in
- On AMD the dyno had no verdict at all: VRAM and power draw were hard coded to
  zero and the throttling flag was never set, so a card running into its limit
  came out as clean
- A run recorded by an older version can no longer take down the dyno page
- The Proton check counted entries in Steam's CompatToolMapping instead of
  games. Steam leaves the entry behind when a title is uninstalled, so most of
  what the finding reported were dead entries rather than games that would
  actually start with the wrong build. It now lists installed titles only,
  names each one with the build it points at, and says which builds are present
- Seven startup entries are not a warning. That finding moved to the notice
  group, lists what it counted and offers the way to the page where entries can
  be switched off
- Findings that name a problem now offer the way to the page that can act on
  it: startup entries, updates, incidents, drivers, storage, the live monitor,
  the dyno and the benchmark. All of them were dead ends before, where the
  button next to the finding opened a dialog repeating the same sentence
- Old snap revisions are measured instead of counted. snapd keeps the previous
  revision after every refresh, so the finding used to fire on every healthy
  system. It reports only when they add up to more than 2 GB now, lists the
  largest ones and removes them without a copied shell loop
- The count of pending updates comes from dist-upgrade, the same command the
  updates page uses. The two pages named different numbers
- The journal finding names the processes writing the most instead of offering
  a command that needs jq, which the package does not depend on
- A benchmark result older than 30 days no longer warns. One slow run used to
  warn forever, long after anyone last measured
- A device whose module is present but not loaded is no longer as critical as
  one the kernel has nothing for at all
- Proton prefixes are summed before the list is capped, so the size was
  reported too small on a machine with many leftovers
- Swap running full only warns when memory is actually short as well. Pages
  swapped out and never touched again cost nothing
- The HWE kernel is only offered when its candidate is really newer than the
  running kernel. On an OEM or mainline kernel it would have been a step back
- The shader cache finding says that it read the variable from this session. Set
  in the launch options of a single game, it applies there and nowhere else

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
