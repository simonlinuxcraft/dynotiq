# Security

## Reporting

Report security issues to simonlinuxcraft@pm.me. Please do not open a public
issue for them.

Include what you did, what happened, and which version you ran (`dynotiq
--version`).

This is a one-person project, so the honest number is a week: you get an
acknowledgement within seven days, and it will say whether the report is
understood and what happens next. If nothing arrives in that time, assume the
mail went astray and open a public issue asking me to check my inbox, without
the details.

If a fix is warranted it goes into the apt repository as a new version, and the
release notes name the issue once the fix is out.

## What is worth reporting

dynotiq runs as your user and asks for a password through `pkexec` for anything
that changes the system. Of interest are:

- A way to make it run a command as root that you did not confirm, or a
  different command than the one it showed you
- Anything that lets outside input, such as a file name, a package name or a
  journal line, end up in a command line or a shell
- The apt repository serving a package that its signature does not cover
- A crash or a hang that a normal system state can trigger, not a deliberately
  corrupted one

Not in scope: findings that require root to begin with, and the fact that the
source is readable. dynotiq is free software under the GPL, the source is meant
to be read, and being able to read it is not a weakness.

## How it handles privilege

Nothing runs as root without a click, and every command is shown in full
beforehand. Where a fix cannot be expressed as a command, it is offered to
copy into a terminal instead of being run.

Most privileged commands are plain argument lists handed to `pkexec`. Four of
them run a short shell script under `pkexec` instead: installing packages,
adding the Flatpak PPA, persisting the ntsync module and removing old snap
revisions. The reason is polkit, which offers `auth_admin` but not
`auth_admin_keep` for `org.freedesktop.policykit.exec`. Split into separate
calls, each of those asks for the password again, and whoever cancels the
second prompt is left half done.

Ten more shell invocations run as your user and never as root: the Steam and
Proton repairs, the shader cache setting and two `journalctl` pipelines.

In all of them, anything originating outside the source, a package name, a
path, a unit name, is passed as a shell argument and read back as `"$1"` or
`"$@"`. Nothing from outside is ever placed in the script text, so a name
carrying a semicolon or a backtick cannot become part of the command.

Where a command deletes or moves something, the script checks the path itself
before acting: a Proton prefix only below `steamapps/compatdata` and only with
an AppID for a name, a Proton build only below `compatibilitytools.d`. That
check sits in the shell rather than in the caller, so it holds regardless of
who assembles the call.

## What the package installs

The `.deb` brings an apt source and its key:

    /etc/apt/sources.list.d/dynotiq.sources
    /usr/share/keyrings/dynotiq.gpg

Without them a package installed by hand would never see an update.
`Signed-By` names that one key, so the source can vouch for nothing outside
dynotiq.

What that means is worth saying plainly: the key is what stands between this
repository and root on every machine that installed the package. If it were
taken, an update could carry anything. No CI job holds it, nothing on GitHub
signs anything, and no build server has a copy: the repository is signed by
hand on one machine. That is the whole of the protection.

To take the source back out again:

    sudo rm /etc/apt/sources.list.d/dynotiq.sources

The package keeps working, it just stops updating.

## Supported versions

Only the current release gets fixes. It is the version in the apt repository.
