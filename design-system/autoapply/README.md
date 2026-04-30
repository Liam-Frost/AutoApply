# AutoApply Design System

Generated via `ui-ux-pro-max` skill. This README pins the **canonical decisions** so Phase B/C implementations have a single source of truth — `MASTER.md` and `pages/*.md` are raw tool output and may contain internal inconsistencies (mixed legacy CSS snippets, leftover landing-page patterns). When in doubt, this README wins.

---

## Canonical Direction

**Product framing:** Productivity tool / data-heavy admin dashboard (job application tracker). Desktop web primary, responsive down to 768px tablet. Mobile is supported but not the design target.

**Style:** Dark Mode (OLED) as primary, with a parallel light mode. The `MASTER.md` tool output called this "Dark Mode (OLED) only" but AutoApply already supports light/dark — we keep both. Light mode uses the same semantic tokens with inverted lightness.

**Pattern:** None of the landing-page patterns in `MASTER.md` apply. AutoApply is an authenticated app, not a marketing site. Ignore the `Pattern Name` / `Section Order` / `CTA Placement` fields in `MASTER.md` and `pages/*.md`.

---

## Color Palette (Authoritative)

| Role | Hex | Token |
|------|-----|-------|
| Primary | `#1E40AF` | `--color-primary` |
| Primary FG | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#3B82F6` | `--color-secondary` |
| Accent / CTA | `#D97706` | `--color-accent` |
| Background | `#F8FAFC` (light) / `#0A0F1A` (dark) | `--color-background` |
| Foreground | `#1E3A8A` (light) / `#E2E8F0` (dark) | `--color-foreground` |
| Muted | `#E9EEF6` (light) / `#1A2233` (dark) | `--color-muted` |
| Border | `#DBEAFE` (light) / `#1E2B43` (dark) | `--color-border` |
| Destructive | `#DC2626` | `--color-destructive` |
| Success | `#16A34A` | `--color-success` |
| Warning | `#D97706` | `--color-warning` |
| Ring (focus) | `#1E40AF` | `--color-ring` |

**Notes:** Blue for data + amber for accents/highlights. Accent adjusted from `#F59E0B` → `#D97706` to meet WCAG 3:1 against white.

---

## Typography

- **Headings:** Fira Sans (300, 400, 500, 600, 700)
- **Body:** Fira Sans (400, 500)
- **Code / data tables:** Fira Code (400, 500, 600) — use for tabular numerals, IDs, paths

```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

**Type scale:** 12 / 14 / 16 / 18 / 20 / 24 / 30 / 36
**Line height:** 1.5 (body), 1.25 (headings)
**Tabular numerals:** required in tables, prices, dates, counts.

---

## Spacing & Layout

Use the 4/8 rhythm from `MASTER.md`:

`--space-xs 4` · `--space-sm 8` · `--space-md 16` · `--space-lg 24` · `--space-xl 32` · `--space-2xl 48` · `--space-3xl 64`

- App max-width: **1400px** (data views can go full-width)
- Sidebar nav: **240px** desktop, collapsible
- Content gutter: 24px desktop, 16px tablet, 12px mobile
- Grid: 12-column for dashboard / data views

---

## Shadows & Elevation

OLED-style: minimal shadows, prefer **borders** for separation in dark mode and light shadows in light mode.

| Token | Light | Dark |
|-------|-------|------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,.05)` | `0 0 0 1px rgba(255,255,255,.04)` |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,.08)` | `0 0 0 1px rgba(255,255,255,.06)` |
| `--shadow-lg` | `0 10px 20px rgba(0,0,0,.10)` | `0 8px 24px rgba(0,0,0,.45)` |

---

## Motion

- Micro-interactions: **150–200ms** ease-out
- State transitions (modals, sheets): **200–300ms** ease-out enter, `~140ms` ease-in exit
- Press feedback: scale `0.97` on active, restore on release (no layout shift)
- Honor `prefers-reduced-motion`

---

## Anti-Patterns (Hard "no")

- ❌ Emojis as icons → use Lucide (Vue: `lucide-vue-next`)
- ❌ Glass / heavy backdrop blur as primary surface (current AutoApply does this — replace with flat surfaces + 1px borders)
- ❌ Layout-shifting hovers (no `translateY` on cards)
- ❌ Color-only state indicators (always pair with icon or text)
- ❌ Body text < 14px on desktop, < 16px on mobile
- ❌ Custom focus rings that hide the default — use a visible 2–3px ring with `--color-ring`

---

## How to Use This (Phase B/C workflow)

1. Read this README first.
2. Read `MASTER.md` for the spacing / shadow scales (top sections only — ignore the legacy CSS in `Component Specs` and ignore `Style Guidelines` / `Page Pattern`).
3. For a specific page, read `pages/<page>.md` — only the `Layout Overrides` and `Spacing Overrides` sections are reliable; ignore `Pattern Name` and `Sections`.
4. When something is ambiguous, this README wins.

---

## Files

- `MASTER.md` — raw tool output (use for spacing/shadow/colors only)
- `pages/dashboard.md`, `pages/jobs.md`, `pages/applications.md`, `pages/materials.md`, `pages/profile.md`, `pages/settings.md` — page-level layout hints
