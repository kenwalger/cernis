<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/logo__dark.png">
  <img alt="Afterword" src="img/logo_light.png" width="360">
</picture>

---

# Brand

**Version:** 1 (2026-10-30)

How the Cernis name and logo are presented, so that future sessions, contributors, and the author do not improvise with them. Cernis is a sibling of [Afterword](https://github.com/kenwalger/Afterword): it shares Afterword's palette and typeface family, but has its own concept and mark.

## The name

**Cernis** is pronounced **KER-nis**, in classical Latin, with a hard C. It comes from *cernere*: to separate, distinguish, discern, decide. *Cernis* itself is a real Latin form, "you discern," which suits a tool that lays out evidence and leaves the judgment to the author.

The Latin pronunciation is deliberate. It leaves room for Latin elsewhere in the brand, used sparingly:

| Latin | English | Use |
| --- | --- | --- |
| *Primum cerne, deinde suade.* | First discern, then advise. | The motto |
| *Non liquet.* | It is not clear. | The not-determinable status, in reports |

Other Latin phrases must be checked by someone with good Latin before they appear on anything permanent.

### The name in prose

In running text, write **Cernis**: one word, capital C only, no styling. Not "CERNIS" or "CerNis", and not "cernis" except as the package or command name (`pip install cernis`, `cernis audit`), which is always set in code formatting.

## Concept

The logo is a capital C divided into three horizontal bands. Each band stands for one of the three statuses a Cernis finding can have, stacked in the order they depend on each other:

- **Black, at the base: observed.** The foundation. A condition verified directly, with evidence you can stand on.
- **Blue, at the top: recommendation.** Built on what was observed, never floating free of it. A recommendation in Cernis must always cite an observation.
- **Outlined, in the middle: not determinable.** Cernis knows exactly where the gap is and can draw its edges, but cannot fill it in. The band's fill is the color closest to the background, so in either theme it reads as nearly empty: an outline around something that is almost not there.

The order is the idea: observation at the base, recommendations above it, and the honest gap between them. Anything that changes the order, fills the middle band with a strong color, or removes its outline removes the meaning.

## Meaning is carried by tone and line first

As with Afterword, where meaning is carried by posture before color, the Cernis mark does not rely on hue alone. The three bands are three clearly different tones in grayscale (checked for both variants), and the middle band is further distinguished by its outline. The mark stays meaningful in grayscale, in print, and for viewers who do not distinguish the colors.

## Colors

### Light backgrounds

| Role | Name | Hex | Notes |
| --- | --- | --- | --- |
| Observed (bottom band) | Ink | `#111111` | Shared with Afterword |
| Recommendation (top band), and the middle band's outline | Afterword Blue | `#477AA3` | Shared with Afterword |
| Not determinable (middle band fill) | Mist | `#C9D3DC` | Also the third color in Afterword's charts |

### Dark backgrounds

| Role | Name | Hex | Notes |
| --- | --- | --- | --- |
| Observed (bottom band) | Paper | `#F2F2F2` | Shared with Afterword's dark variant |
| Recommendation (top band), and the middle band's outline | Afterword Blue, light | `#689BC3` | See the note below |
| Not determinable (middle band fill) | Slate | `#34495A` | |

**To reconcile:** the dark-mode blue in the current artwork is `#689BC3`. Afterword's BRAND.md proposes `#6B9BC3` for the same role. The two are visually indistinguishable (contrast on `#0D1117` is 6.37:1 and 6.40:1), but the brands should share one value. Pick one, update both documents, and bump their versions.

### Contrast

Measured against WCAG 2 relative luminance:

| Pair | Ratio | What it means |
| --- | --- | --- |
| `#477AA3` on white | 4.58:1 | The blue band and outline read clearly |
| `#111111` on white | 18.88:1 | |
| `#C9D3DC` on white | 1.52:1 | Deliberately faint: the middle band is meant to read as nearly empty. The outline (3.02:1 against the fill) carries its edge |
| `#689BC3` on `#0D1117` | 6.37:1 | |
| `#F2F2F2` on `#0D1117` | 16.90:1 | |
| `#34495A` on `#0D1117` | 2.02:1 | Deliberately close to the background, for the same reason; the outline (3.14:1 against the fill) carries its edge |

The low contrast of the middle band against the background is the concept, not an accessibility gap: the band's edges are defined by the outline, and its meaning is carried by its position and outline, not its fill.

## Typography

The mark is artwork, not live text. Use the source files; never redraw the C from a font, since the band positions, outline weight, and terminals are part of the design.

- The C: [confirm the typeface and weight the C was drawn from, and record it here]
- The wordmark "Cernis": **IBM Plex Sans SemiBold**, in Ink on light backgrounds and Paper on dark. Unlike Afterword's wordmark, it is not split into two styles; the mark carries the concept.

## Variants

| Variant | File | Use |
| --- | --- | --- |
| Mark, light backgrounds | `img/cernis-mark-light.svg` (PNG fallback `img/cernis-mark-light.png`) | Default |
| Mark, dark backgrounds | `img/cernis-mark-dark.svg` (PNG fallback `img/cernis-mark-dark.png`) | Dark themes, including GitHub dark mode |
| Mark plus wordmark, light | `img/cernis-logo-light.svg` (to be created) | README header, documents |
| Mark plus wordmark, dark | `img/cernis-logo-dark.svg` (to be created) | Dark themes |
| Favicons | `img/favicon-16x16.png`, `img/favicon-32x32.png`, `img/favicon.ico`, `img/apple-touch-icon.png` (180), `img/android-chrome-192x192.png`, `img/android-chrome-512x512.png`, `img/site.webmanifest` (to be created) | Browser tabs, app icons, avatars |

One version of the mark serves every size. It was tested at 64, 32, 24, and 16 pixels on white and on GitHub's dark background (`#0D1117`): the C stays whole at every size, and the three bands remain distinguishable in grayscale. No separate small-size variant is needed.

Prefer SVG; PNG is the fallback. Favicons are exported from the light mark; check the 16 and 32 pixel versions by eye after any change, and confirm the middle band still connects the top and bottom bands.

## Usage rules

- **Minimum size:** 16 pixels for the mark alone. For the mark plus wordmark, at least 120 pixels wide.
- **Clear space:** keep empty space around the mark at least equal to the width of the C's stroke on every side.
- **Do not** reorder the bands, recolor them, or swap the light and dark palettes.
- **Do not** fill the middle band with a strong color, or remove its outline.
- **Do not** stretch, rotate, add shadows or gradients, or place the mark on busy images.
- **Do not** substitute a different blue. Use the hex values above.
- **Alt text** for the mark and logo is "Cernis".

## Using the logo in the README

Serve the light or dark variant automatically according to the viewer's theme:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/cernis-mark-dark.svg">
  <img alt="Cernis" src="img/cernis-mark-light.svg" width="96">
</picture>
```

Switch to the mark-plus-wordmark files once they exist.

## The same idea in the reports

The logo's three treatments are not only decoration. Reports may use the same visual language for finding statuses: a solid black or Paper badge for observed, a solid blue badge for recommendations, and an outlined badge with the Mist or Slate fill for not determinable. If they do, the colors and order follow this document.

## Change control

Changes to colors, variants, or rules update this document and bump its version. Logo artwork changes are recorded with the date and the reason, like any other design decision in this project.

| Version | Date | Change |
| --- | --- | --- |
| 1 | 2026-10-30 | First version: the three-band C, light and dark variants, palette shared with Afterword |