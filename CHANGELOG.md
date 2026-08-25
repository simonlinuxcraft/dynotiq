# Changelog

## 0.4~beta - Light and dark

### Appearance

- The interface has a light appearance now. Switch it under Settings,
  Appearance; it applies at once, without a restart. Every tone of the
  interface lives in one place and both sets carry the same keys, so a
  colour forgotten on one of them fails the self test rather than showing
  up mid-session.
- No more traffic light. Green and orange said the same thing as grey and
  yellow, only louder. A grey bar means nothing to do, a yellow one means
  it is waiting for a decision, a red one means something is broken. Yellow
  follows the chosen accent, so the setting for status colours is gone.
- Findings carry that bar down the left edge of the whole row instead of a
  dot beside it.
- Every page has its own symbol in the navigation, and a field above it
  jumps to whichever page you type. It matches the English and the German
  name, the same way `--page` does.
- The score ring is a plain 270 degree arc in the accent colour. The glow
  was drawn by hand out of stacked arcs and read as decoration.
- New typeface: IBM Plex, with its monospace for anything measured, so
  readings and timestamps line up in a column. It ships as a Recommends;
  where the package is missing, Ubuntu carries the interface instead.
- The machine block in the sidebar can be turned off.

### Fixed

- Text views, entries, expanders and progress bars had no colour of their
  own and borrowed one from the system theme. That went unnoticed while
  everything was dark and would have left dark boxes on light cards.

## 0.3~beta - Proton, and free again

### Settings

- The background watcher is configurable. How often it looks is a setting now
  instead of a hardcoded 30 seconds, and it can be told to notify only about
  critical incidents. Warnings still collect on the incidents page, they just
  stop interrupting. Both are read on every pass of the service, so a change
  takes effect without restarting it
- One button puts colours, intervals and switches back to what they are on a
  fresh install. History and snoozed findings are not touched, and the dialog
  says so before anything happens
- A setting that needs a program which is not installed used to show a dead
  switch and the words "not installed". It now offers the way there, through
  the same dialog as every other intervention: command first, password after
- The settings are grouped by subject rather than listed as one column of
  switches. Appearance, program, background watching and updates are separate
  cards, so a setting that changes how updates run does not sit next to one
  that only changes a colour
- Drop-downs look like drop-downs. They had neither a border nor an arrow under
  this theme and read as status labels, which is why nobody clicked them
- The version was on screen three times on that page and is now on it once
- Paths moved into tooltips where a button next to them already does the job

### Updates

- Packages with no installed predecessor were invisible. That is exactly what a
  kernel with a new ABI looks like: the meta package gets raised, the actual
  linux-image and linux-modules packages are new. The page listed the meta
  package alone and announced two kilobytes for a download of several hundred
  megabytes. It now lists them, shows the real total, and drops
  `--only-upgrade` from the install command when the selection contains one,
  because apt silently skips such a package otherwise
- The age of the package lists is on the page, and a button fetches them. This
  page only ever asked apt what it already knew locally, so on a machine whose
  lists were a week old, "reload" changed nothing and said so to nobody.
  Fetching needs root, which is why it is its own button rather than something
  that happens on every visit
- A dist-upgrade that would remove packages says so. The page cannot carry that
  out, `apt-get install --only-upgrade` has no way to, and it names the packages
  and the command that can instead of leaving the update stuck without a reason
- Packages that are already downloaded show a size. apt reports no download size
  for anything sitting in `/var/cache/apt/archives`, so those rows said nothing
  and the total on the card came out too small. It reads the size out of the
  cache instead
- A flatpak update that fails because flatpak itself is too old says so, and
  names the way out that actually exists on this machine. It asks apt first, and
  only where Ubuntu has nothing newer does it offer the Flatpak project's own
  package source for this release, saying plainly that this is a source from
  outside Ubuntu and how to remove it again. Where neither has anything, it says
  that too rather than offering a button that would change nothing
- Updates apt is holding back by phasing are on the page instead of missing from
  it. A phased upgrade is deliberately given to a fraction of machines first, so
  apt lists it as kept back and installs nothing. The page said everything was
  current while apt disagreed. They are listed separately, with the reason, and
  they deliberately get no button: forcing one past its phase is a decision
  about being an early tester, not a repair
- A failed run says why in words rather than an exit code. The most common cause
  by far is the automatic update holding the dpkg lock, which now reads as that.
  A source that could not be asked at all no longer counts as a source with
  nothing to update, which is what made a scan report "everything current" after
  a failure
- Anything that removes or overwrites runs the real command as a dry run first
  and names what it would take, with the count on the button. The decision is
  then made in front of the list rather than after the fact
- Whether a release upgrade is offered at all comes from Ubuntu's own
  `Prompt=` in `/etc/update-manager/release-upgrades` instead of a guess. Set to
  `never`, nothing is offered, which is what the setting is for

### History

- Updates are recorded. The history knew scans, benchmarks and dyno runs, so
  there was no way to tell afterwards whether a measurement came before or
  after an intervention
- With that in place, the app can say something no other desktop tool says:
  "since the update of 28.07 all CPU cores are 14 % slower". It compares the
  last measurement before the update with the most recent one after it, and it
  says plainly that this is an order of events and not a cause. The same
  sentence is appended to the benchmark finding in the system check, which
  until now stated the drop without ever naming when it started
- The benchmark page relates the latest run to the very first one on this
  machine, once at least thirty days lie between them. The existing "usual"
  line is a moving median of the last eight runs, so a machine that slowly
  degrades over months drags its own baseline along and never notices
- A scan is only written when the score or the number of findings changed.
  Every start used to append a line, which is how 209 identical entries end up
  in a file that is supposed to show when something moved
- Dyno runs showed up in the history as a benchmark with nothing but zeroes.
  They carry a summary, not the benchmark keys, and now show duration and game

### Games

- The dyno records on its own. It could always do the measuring, it just hung
  on a button, and whoever thinks of it once the stutter is there has not
  measured the stutter. The background service notices a running game, measures
  along, and when you stop playing the report is waiting. Runs under three
  minutes are discarded rather than filed, because a verdict over ninety
  seconds misleads
- Frame rate and frame times are in the report. Neither can be measured from
  outside: they exist in the moment the game hands over a finished image, and
  only something sitting inside the render process sees that. dynotiq does not
  build a second overlay for it. It sets up MangoHud in its own colours,
  accent for the values, the same green/amber/red for load and frame rate,
  Inter as the font, and reads its recording into the report afterwards.
  Average and the slowest percent, which is the number you actually feel
- The dyno page says what is set up and what is not, and offers the missing
  step: a switch for the recording, a button for the overlay, and where the
  background service is off, the way to turn it on rather than a switch that
  would regulate nothing. Turning the overlay off puts a configuration that was
  there before back in place. Recording and overlay are separate throughout:
  without the overlay everything gets measured except the frame rate
- Frame rates come out of MangoHud's running log now, not out of the summary it
  writes at the end. The summary only exists once its recording stops, which is
  when the game closes, so a report pulled while still playing had no frame
  rate at all and a report pulled afterwards took whatever run happened to
  overlap, not the one that was measured. The log carries every frame with the
  time it was drawn, so the recorded window can be cut out of it exactly.
  Recording from the button never asked for frame rates in the first place,
  only the background service did. Both take the same route now
- A run without frame rates says why instead of leaving a blank. Games that
  render with OpenGL are invisible to MangoHud's Vulkan layer, and OpenGL has
  no layers to hook into, so those need 'mangohud' in the launch options.
  dynotiq recognises them from the libraries loaded in the running process and
  writes the reason under the report. The overlay dialog no longer claims that
  launch options never need touching, which holds for Vulkan and not for OpenGL
- The app check reports a MangoHud that is too old to draw in OpenGL games. Up
  to 0.8.1 the overlay stays invisible there even with the launch option set,
  while the recording still works. Fixed upstream in 0.8.2, which no Ubuntu
  ships yet

### Proton

- A page of its own, named the way Steam names it in the properties dialog.
  Every Proton version from 5.13 on runs inside a container that Steam downloads
  separately, and if that container is missing or the version was unpacked
  half way, no game starts on it while Steam says nothing beyond "exited
  unexpectedly". The page reads what is actually on the disk and states the
  cause: `toolmanifest.vdf` for the container a version asks for, the `version`
  file for what built a prefix, Steam's `config.vdf` for which title uses which
  version, and Steam's own `compat_log.txt` for the launches that already
  failed. Nothing on it is guessed, and every finding names the file it came
  from
- A version Steam refuses to list at all is reported, with the reason. A
  half-unpacked folder with no `proton` file in it, or a symlink to a folder
  that is gone: Steam drops both from its list without a word, so a title set to
  one of them simply stops starting. The button clears it away, and for the
  symlink it says outright that nothing is lost
- Versions unpacked into the wrong `compatibilitytools.d` are found. Steam only
  reads the one under its own installation, which on Ubuntu is
  `~/.steam/debian-installation`, while guides and tools name
  `~/.local/share/Steam`. Anything unpacked there never shows up in Steam's
  list, and the button moves it over
- A title whose Windows store was built by a newer Proton than the one it is set
  to is the finding that would otherwise cost saved games, and it carries a
  button rather than a paragraph and a path, which is of no use to anyone who
  does not know what a prefix is. It reads the versions and switches the title
  in Steam to one the store already fits. That is the safe way out, because
  Proton converts a store forwards by itself: any version that is not older than
  the store will do, not only the one that built it. Versions in a
  compatibilitytools.d that Steam does not read are left out of the choice,
  since setting a title to one of those is worse than the finding
- Where no version fits, the button moves the prefix aside to
  `<appid>.vor-dynotiq` and Proton builds a fresh one on the next start. Saved
  games in it are not thrown away, the game just stops seeing them, and the
  dialog says exactly that before anything happens. Deleting the prefix for good
  is there too, one step further in, under the details
- The row says what the action costs: safe, or saved games affected. And where
  more than one title can be switched, one button in the card header does them
  all in a single run, because each one on its own would close and restart Steam
- The entry Steam writes for a per-title Proton version is created if it is not
  there. Most titles have none and run on Steam's global default, so replacing a
  value would have missed exactly the common case. Only that one line changes,
  the previous file stays next to it as config.vdf.vor-dynotiq, and a run that
  cannot do its work restores it and says so
- Confirmation dialogs show the values a command works on, not the script around
  them. Thirty lines of awk prove nothing to anybody and push the file being
  touched out of sight. The window that runs the command still shows it in full,
  so the record is complete where a record belongs
- Descriptions across every page are readable. The grey they were drawn in sat
  at 4.3:1 against the card, under the accessibility floor for text that size,
  and these pages are mostly text
- A Steam runtime that is assigned a Proton version of its own is reported, and
  a button takes the assignment out. Steam lists its runtimes like games, so a
  tool that sets one Proton version for every entry at once assigns one to the
  runtime as well, and it is then meant to run under a version that needs it.
  Steam breaks the entry on that: it takes the files away from it, refuses to
  remove it because the entry "depends on it" and names the entry itself, and
  answers every attempt to fetch it again with "Invalid platform". From the
  outside the runtime just looks damaged
- A runtime whose entry Steam holds as installed with no depots behind it can be
  fetched again, which is the state that looks most like nothing can be done.
  Steam refuses both a repair and a fresh install there, because its own
  manifest says the entry is complete: `steam://validate` runs through and finds
  nothing to check, `steam://install` produces no download at all, and
  `steam://uninstall` is refused for a runtime after the dialog has already been
  confirmed. So the button closes Steam, takes out the assignment that blocks
  it, removes the false entry and starts Steam with the job of fetching, keeping
  the old configuration next to it as config.vdf.vor-dynotiq. Which of the three
  routes a runtime needs is decided from its files, not guessed: no manifest, a
  manifest with no depots, or files that are recorded and gone
- Failed launches are read from Steam's own `compat_log.txt`, so a finding can
  name the titles that did not start and when. Entries older than a week are
  dropped, and one that predates the repair of the runtime it blamed drops out
  too, rather than standing red for days after the fix worked

### Notifications

- The background service can remind about pending updates once a week. Ubuntu
  26.04 turned its own update notification off by default with no toggle in
  settings, so a machine that is never opened for maintenance says nothing at
  all any more. Weekly, never more often, and it can be switched off

### Fixes

- Advice that has already been followed is gone from the report. A report
  describes a run from back then, but it advises for now, and the power limit
  and the governor can both be changed in between. Raising the limit and then
  opening the report again offered the same button a second time, for something
  that was already done. Both are checked against the machine as it is now, and
  where the change has happened the report says so instead
- The overview tore a gap open in a maximised window. The KPI tiles need
  vexpand so that valign keeps them at the foot of the card, but GTK4 passes
  that up through card and row to the page, and the row then claimed all the
  space left over on a tall screen. The row now stops it. The header is 137 px
  shorter, which is what it takes for the live tiles at the bottom to be on
  screen at all
- A config file edited by hand, or half written when a disk filled up, could
  feed a timer a string or a value the interface never offers. Every value is
  checked against what the interface can produce, and unknown keys are dropped
- Menu entries with no program behind them are found and can be removed. Steam
  writes a launcher into the home directory for every title and leaves it there
  when the title is uninstalled, and AppImages leave the same thing behind.
  Clicking one does nothing at all, which looks like the machine being broken
- The navigation gave itself a scroll area and could shrink below its own
  content, cutting off the wordmark at the top and the machine block at the
  bottom. It sets the window's minimum height now
- A release lookup that could not reach the network was remembered for a day as
  "nothing new", so a machine that was offline once said nothing for the next
  24 hours even back online. Only a lookup that actually answered is cached
- Resetting the settings left the dyno page showing the old state of the same
  switch it carries a second time
- One damaged line in the history file took the history page down with it, and
  the page then showed nothing at all. Every consumer works with the timestamp:
  the page formats a date from it, the comparison against an update sorts by
  it. Lines without a usable timestamp are dropped when reading now, so one bad
  line costs one entry rather than the page
- Old snap revisions were never reported on a German desktop. Commands run with
  `LC_ALL=C`, but snap takes its language from `LANG` and ignores both `LC_ALL`
  and `LANGUAGE`, so the parser looked for "disabled" in a line that said
  "deaktiviert". On the machine this was found on, that hid 29 revisions
- The journal check only ever measured the user journal, which misses the most
  common cause by far: a system service in a loop. It also named the process,
  and for anything written in Python that is "python3". It reads the whole
  journal now and names the unit, so the line says which service to look at
- On an LTS, a release that is not itself an LTS is no longer offered. The
  finding used to pick the highest supported release, then promised a point
  release that only exists for LTS, and the button next to it would have moved
  a machine from five years of support to nine months
- Two processes write the state file, the app and the background service. The
  temporary file they wrote through had a fixed name, so both could hold the
  same inode and the loser wrote into the file that had already been renamed.
  A corrupt state file reads as empty, which loses snoozed findings and the
  release cache. Both writers go through one helper now, with a unique
  temporary name and fsync. The two places that held their copy of the state
  across a run of journalctl or apt re-read it before writing
- A source check with no network marked every source "unknown" and cached that
  for a week. The finding then read "0 of 11 third-party sources have no
  packages", which sounds like clearance. A failed attempt is no longer cached
- Clearing the user cache had no warning, and it is the one entry that also
  removes the compiled shaders of your games. The thumbnails were counted twice
  in the total, once on their own and once inside the cache above them
- Free space for the shader cache was checked on one partition, the one holding
  `/home`. Steam libraries usually sit on their own disks, and the one that
  fills up is the one being played from. Every partition holding a cache is
  checked, and the finding names it
- Turning off an autostart entry that has a second group wrote `Hidden=true` at
  the end of the file, where it lands in that group and neither gnome-session
  nor this app reads it. The switch sprang back on the next visit
- MangoHud writes one line per frame and a new file per application, around
  25 MB per hour played, and only the newest was ever read. The rest stayed
  forever. Old recordings are cleared after each evaluation
- Stopping a recording evaluated the whole run in the interface thread,
  including reading MangoHud's log. Two hours at 120 fps is roughly 860,000
  lines, and the window was dead for all of it. Two clicks on "rescan" started
  two scans that undid each other's progress display
- The advice on undervolting pointed at a curve editor in nvidia-settings that
  does not exist on Linux. It now names LACT for AMD and the power limit for
  NVIDIA, and the fan curve advice says that NVIDIA needs Coolbits and a fresh
  session for it
- The self-test wrote to the real state file, which suppressed the app's own
  release check for 24 hours on the machine running it, and it went to the
  network to do so. It works on a temporary file now
- `update-po.sh` failed in a fresh clone because msgfmt does not create the
  target directory, and `set -eu` left the run half done. The install page of
  the apt repository told people to write a `.list` file while the package
  ships the same source as `.sources`, so apt warned about a duplicate on every
  update and a purge left a file pointing at a deleted keyring. Building the
  repository now stops if the shipped keyring does not match the signing key
- Counts of one read as counts of one. "1 Updates warten" was the notification
  you got most often, because one waiting update is the normal case
- Several strings were German no matter which language was set: the status line
  of the app check, the sizes on the storage page, the progress line of the
  install window, the error text of a page that failed to load, and the message
  of both background service dialogs. The unit description had lost its umlaut
- Download sizes on a multi-arch system were wrong. Sizes were stored under the
  bare package name, so `libfoo:amd64` and `libfoo:i386` overwrote each other
  and both rows showed the same number. apt itself always downloaded correctly
- A clock set backwards no longer freezes three caches. Every one of them
  compared "now minus stamp" against a limit without checking for a negative
  result, so the release check served stale data and the update reminder never
  fired again
- The history file measured its limit in bytes but trimmed by line count. A file
  of mostly recording entries never got back under the limit and was rewritten
  in full on every single append, up to 3.4 MB at a time
- The window no longer freezes when a disk or the service manager hangs. Reading
  the NVMe temperature is an admin command to the controller and ran in the
  interface thread on every live tick, exactly the case the incident detectors
  themselves know about. Switching the background service on or off started
  three processes with a 15 second limit each in the signal handler
- Stopping a recording and immediately starting a new one mixed the two. The old
  measuring thread wrote its sample into the new series and overwrote its
  starting point. Runs carry a number now and a late sample is dropped
- A scan is around four seconds faster. `ubuntu-drivers devices` ran twice, once
  in the scan and again on the driver page, and it is the single most expensive
  command either of them runs. The result is kept until apt or dpkg changes
- Installed from the package, the app no longer copies ten icons into your home
  directory that are already in `/usr/share/icons`. They shadowed the packaged
  ones and stayed behind as a user theme after purging
- Clearing old snap revisions asks for the password once instead of once per
  revision. It ran one `pkexec` per revision, and polkit grants
  `org.freedesktop.policykit.exec` as `auth_admin` without `keep`, so it asks
  every single time. With 29 revisions that was 29 prompts, and dismissing one
  in the middle left the job half done. The finding also names the setting that
  keeps them from piling up again, `snap set system refresh.retain=2`, as text
  rather than a button, because it changes a system setting

### Licence

- dynotiq is free software again, GPL-3.0-or-later, one licence for everything.
  Version 0.2~beta1 was published as all rights reserved and that step is
  withdrawn. The sentence in the 0.2~beta1 release notes saying the source
  grants no permission to use it no longer applies to any version. LICENSE,
  `debian/copyright`, the module header and the repository page all say the same
  thing now
- Pull requests are welcome again. The clause that treated code posted in an
  issue as handed over unconditionally is gone, and no contributor agreement is
  needed: under GPLv3 every contribution carries the same licence as the rest.
  README says what is expected of one, which is an issue first for anything
  larger, a green selftest, the style of the surrounding code, and new strings
  that can be translated

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
