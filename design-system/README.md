# dynotiq design system

The look of dynotiq, pulled out of the app so other dynotiq projects can reuse it.

Everything here is derived from the running application, not invented next to it.
The source of truth is `dynotiq.py`:

| Here | There |
| --- | --- |
| surfaces, text ramp, radii, component specs | `CSS_TEMPLATE` |
| accents | `ACCENTS` |
| status colours | `PALETTES` |
| accent hover / on-accent text | `lighten()`, `darken()` |
| type stacks | `SANS`, `MONO` |
| mark, wordmark, app icon | `icons/` |

## Files

```
tokens.css              every value as a CSS custom property
foundations/color.html  surfaces, text ramp, accents, status palettes
foundations/type.html   scale, weights, tabular figures
foundations/layout.html spacing, radius, elevation, window frame
foundations/brand.html  mark, wordmark, app icon, usage rules
components/buttons.html accent, fix, ghost, quiet, row-as-button
components/data-display.html card, KPI, tile, finding row, pill, bullet
components/navigation.html sidebar, nav item, badge, headerbar
components/controls.html switch, dropdown, swatch, popover, scrollbar
```

The HTML files are specimens. Each one carries its own token block so it renders
standalone, and each starts with a `@dsCard` comment naming the group, title and
subtitle a viewer should file it under. `check.py` insists on that line.

## Using it in a web project

Copy `tokens.css` in and reference the variables:

```css
@import "tokens.css";

.finding { background: var(--dq-surface); border: 1px solid var(--dq-line); }
```

Switching accent or status palette is an attribute on the root, same as the
Settings page does it in the app:

```html
<html data-dq-accent="cyan" data-dq-palette="warm">
```

## Keeping it in sync

Colours and component specs live in `dynotiq.py`. When `CSS_TEMPLATE`, `ACCENTS`
or `PALETTES` change, `tokens.css` and the affected specimen change with them,
otherwise this directory starts describing an app that no longer exists.

`check.py` verifies that the hex values in `tokens.css` still match the ones in
`dynotiq.py`. Run it after touching either side:

```
python3 design-system/check.py
```
