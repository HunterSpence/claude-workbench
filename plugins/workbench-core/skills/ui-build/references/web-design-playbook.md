# Web design playbook

The judgement rubric for `ui-build`. Order of authority: the product's own design system, then
`BRAND_SPEC.md` (see `brand-spec`), then this page. Everything here yields to the first two.
Lines marked "published" come from a standard; lines marked "default" or "rule of thumb" are this
kit's own starting points, to be replaced by the product's numbers when it has them.

## 1. Budgets: check before calling a page done
- **Loading (published):** the largest content element appears within 2.5 seconds of the page
  starting to load (LCP).
- **Responsiveness (published):** interactions answer within 200 milliseconds or less (INP).
- **Stability (published):** layout shift of 0.1 or less (CLS). The published target is judged at the
  75th percentile of page loads. For an internal app with no field data, measure in the browser's
  performance panel on a mid-range laptop with the CPU throttled, and say that is what you did.
- **JavaScript (default):** about 150 KB compressed before the page is usable, for a content or
  marketing page. A data-heavy app sets its own number with the team; write it down.
- **Images (default):** explicit `width` and `height` on every image (prevents shift), lazy loading
  below the fold, never more than twice the displayed size.
- **Fonts (default):** at most two families and four weights, `font-display: swap`, only the face
  used above the fold preloaded.

## 2. Colour
- Tokens by role, never literals: background, surface, text, muted text, accent, accent hover,
  border, and one each for success, warning and danger.
- Write each colour as OKLCH with a plain hex line before it. A browser that cannot parse the second
  line keeps the first:
  `color: #1a5fb4; color: oklch(0.5 0.15 255);`
- **Palette (rule of thumb):** one accent, status colours used only for status, everything else
  neutral. If a third hue is arguing for attention, one of the three is wrong.
- **Contrast (published):** text at least 4.5:1 against its background, large text and interface
  parts at least 3:1. Check light and dark separately; the axe run in `ui-build` reports failures.
- Colour never carries meaning alone: pair it with an icon, a word or a shape.
- **Dark mode:** not the light palette inverted. Lower the chroma, separate layers by lightness
  steps rather than shadows, and look at images and charts in it.

## 3. Type and space
- One scale (rule of thumb: a ratio near 1.2), sizes in `rem`. Body at least 16px; 14px only for
  secondary text. Line height 1.4 to 1.6 for body, tighter for headings.
- Line length about 60 to 75 characters for reading text (rule of thumb); cap the measure, do not
  let a paragraph run the full width of a wide screen.
- Balanced wrapping on headings, tabular figures in number columns, no widows in short lines.
- One spacing scale on a 4px base. More space above a heading than below it; related things sit
  closer than unrelated things. One left edge per column.
- System fonts first. A web font from a third-party host is a network request the organisation may
  not allow (the screenshot script blocks it unless you pass `--allow-fonts`).

## 4. Motion: climb the ladder only as far as the job needs
1. **None.** Can the change be understood without motion? Then ship that.
2. **CSS transitions** on `transform` and `opacity` only: 150 to 250 ms for hover and press, up to
   400 ms for a panel; ease-out when something arrives, ease-in when it leaves. Never animate width,
   height, top or left.
3. **CSS scroll-driven animations** (`animation-timeline`) for effects tied to scrolling, in the
   browsers you target. Check support first and give a static result where it is missing.
4. **Web Animations API** for sequences that need script.
5. **An animation library** only when choreographing many elements is the requirement and the
   project already depends on one. Never add a second.

Always: honour `prefers-reduced-motion` (published: it reports that the user asked the system to
minimise non-essential motion), keep animations interruptible, and give anything that moves for
more than five seconds a way to pause it.

## 5. Layout and states
- Design at 390px first, then widen. Break where the content breaks, not at device names. Cap line
  and content width on large screens.
- Every interactive piece has: rest, hover, `:focus-visible`, pressed, disabled, loading, empty,
  error, very long text, and many items. A missing state is a defect.
- Focus is always visible. Never remove an outline without a replacement.
- Touch targets about 44px on a phone. Tap and keyboard alternatives for every gesture.

## 6. Generic-output tells
Each one is a defect unless the brief asks for it. The fix is a decision, not a different gradient.
- A purple-to-blue gradient on white as the only identity.
- Every section a centred heading over a row of three identical cards with an icon each.
- Gradient headline text; a decorative blob or glow behind the hero.
- Emoji as bullets or icons; icons that do not say what the label says.
- Identical rounded cards with the same shadow at every level, so nothing is more important.
- An all-caps eyebrow above every heading.
- Filler copy: "seamless", "powerful", "effortless", "unlock", "supercharge", placeholder names,
  round invented statistics, fabricated testimonials.
- "Get started" on every button, whatever it does.
- Glass or blur effects on surfaces that carry text.
- One font weight and one size everywhere, so there is no hierarchy.

## 7. Review rubric
Rate each area against what the screenshots and the code show. Severity: **blocker** (cannot be
used, or an accessibility failure of impact serious or critical), **major** (looks broken or
contradicts the system), **minor** (polish).

| Area | Passes when | Check by |
|---|---|---|
| Hierarchy | One thing is clearly first on each screen; size, weight and space say what is second | Squint at the 1440px shot |
| Consistency | Same thing, same look: buttons, spacing, radii, icon style | Compare two screens side by side |
| Spacing | Everything sits on the scale; groups are visible | Overlay the scale on one screen |
| State coverage | Every state in section 5 exists and was looked at | Walk each component in turn |
| Responsive | No horizontal overflow, nothing clipped at 390px | The `OVERFLOW` lines |
| Accessibility | Contrast, focus, labels, keyboard path, reduced motion | axe run, then Tab through it |
| Copy | Specific labels, errors that say the fix, no filler | Read every string aloud |
| Restraint | Nothing in section 6 without a reason | Read the list against the page |

Write each finding as `<screenshot name>, <region>: <defect> -> <fix>`. Fix blockers and majors,
re-shoot, list the minors. Then run the pinned rules list (`ui-build` step 6) as a second pass.
