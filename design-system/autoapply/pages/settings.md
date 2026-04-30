# Settings Page Overrides

> **PROJECT:** AutoApply
> **Generated:** 2026-04-29 22:23:32
> **Page Type:** Settings / Profile

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 800px (narrow, focused)
- **Layout:** Single column, centered
- **Sections:** 1. Hero (benefit headline), 2. Lead magnet preview (ebook cover, checklist, etc), 3. Form (minimal fields), 4. CTA submit

### Spacing Overrides

- **Content Density:** Low — focus on clarity

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Lead magnet: Professional design. Form: Clean white bg. Inputs: Light border #CCCCCC. CTA: Brand color

### Component Overrides

- Avoid: Ignore accessibility motion settings
- Avoid: No feedback after submit
- Avoid: Placeholder-only inputs

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Hover states on CTA (color shift, slight scale), form field focus animations, loading spinner, success feedback
- Animation: Check prefers-reduced-motion media query
- Forms: Show loading then success/error state
- Accessibility: Use label with for attribute or wrap input
- CTA Placement: Form CTA: Submit button
