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
beforehand. Anything privileged is executed as an argument list through
`pkexec`, never through a shell, so nothing in a file or package name can be
interpreted as part of the command. Where a fix cannot be expressed that way,
it is offered to copy into a terminal instead of being run.

One read-only command does go through `bash -c`: the journal rate check pipes
`journalctl` output through `sed`, `sort` and `uniq`. It runs as your user,
takes no input from anywhere, and its output is only counted.

## Supported versions

Only the current release gets fixes. It is the version in the apt repository.
