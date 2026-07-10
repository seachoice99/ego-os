# Presentation Website — Deliverable Format & Capability Spec

This document specifies a recurring deliverable type observed in real client work (a tender/pitch presentation built and iterated as a live website instead of a static PPTX/PDF): **"online presentation" / "presentation website."** It captures the fixed product format that must be preserved across projects, the technical architecture that implements it, the asset pipeline that keeps it fed with content, and the operating discipline an employee (human or digital) needs to run the loop reliably.

This is not a proposal — it is a distillation of a format and workflow that was used successfully end-to-end on a real premium-event tender pitch (deck + video references + interactive case portfolio + a linked PDF export), and is intended as input for whoever designs the Ego OS employee/capability that should own this deliverable type going forward.

## 1. What this deliverable is

A client expects "a presentation." Instead of a flat PPTX or PDF, the deliverable is a **scroll-based website that behaves like a slide deck** but gets the benefits of a live medium: clickable video references, an interactive case-study gallery, instant reshareable link, and cheap iteration (swap one image, redeploy, done — no re-export of a 50-slide file).

A parallel **static PDF export** is generated from the same source when the client needs an offline/attachable artifact — see Section 5. The website is the source of truth; the PDF is a derived, link-annotated snapshot of it.

## 2. Fixed visual/UX contract

These properties are the format's identity — preserve them across projects, regardless of client:

- **Always dark theme.** Background near-black/dark-navy, light text. This is non-negotiable for this format; it reads as premium/technical regardless of client industry.
- **One accent color**, used for links, active states, the scrollbar thumb, and small UI chrome (deck counter, captions). It must be the client's primary brand color, or — if the deck has no single declared brand color — the dominant accent color actually used across the slide artwork. Never a generic default blue.
- **A persistent side thumbnail panel** for navigation (jump to any slide, see current position at a glance) alongside the main scrollable viewer.
- **Vertical scroll, one full-bleed slide per section.** Each slide is a single image filling the viewport; there is no "next/prev button" pagination model, the format is scroll-native.
- **A deck counter** (e.g. "12 / 49") so the viewer always knows how deep they are.
- **In-page video pop-ups**, never navigation away from the deck. Clicking a reference or a case thumbnail opens a modal with an embedded player (YouTube or VK-style embed) over the current slide; closing it returns exactly where the viewer was.
- **An interactive case/portfolio grid** where relevant (a "kейсы" style gallery): default state is a static (often intentionally monochrome) thumbnail, hover reveals a color/hero frame, click opens the case video in the same shared modal.

## 3. Technical architecture

Static site, no build tooling, no framework — this is intentional: it keeps iteration cost near zero (edit HTML/CSS/JS directly, scp to the host, done).

```
index.html        one <section class="slide-frame"> per slide, in reading order, inside
                   <div class="viewer-shell"><aside class="thumb-panel">…</aside>
                     <div class="main-viewer"><div class="deck" id="deck">…sections…</div>
                       <div class="deck-counter"></div></div></div>
                   plus one shared #videoModal at the end of <body>.
styles.css        dark theme tokens, .slide-frame / .thumb-panel / .video-modal /
                   .video-hotspot / .portfolio-grid rules, accent-color variable.
script.js         thumbnail panel generation + scroll-sync, deck counter, video modal
                   open/close (openEmbed(src)), image self-healing retry logic.
img/<deck>/       designer-delivered PNGs, one per slide, numbered sNNN.png.
img/<deck>-opt/   build output: sNNN.webp / sNNN.jpg / sNNN-mobile.webp / sNNN-mobile.jpg.
img/portfolio/    NN_default.jpg/webp + NN_hover.jpg/webp per case-grid tile.
```

**Per-slide markup pattern:**

```html
<section class="slide-frame">
  <div class="slide slide--full">
    <picture>
      <source type="image/webp" media="(max-width: 720px)" srcset="img/t4-opt/sNNN-mobile.webp">
      <source type="image/jpeg" media="(max-width: 720px)" srcset="img/t4-opt/sNNN-mobile.jpg">
      <source type="image/webp" srcset="img/t4-opt/sNNN.webp">
      <img src="img/t4-opt/sNNN.jpg" alt="…" loading="lazy" decoding="async">
    </picture>
    <!-- optional: one or more hotspots layered over the image -->
    <button type="button" class="video-hotspot"
            style="left:X%;top:Y%;width:W%;height:H%"
            data-youtube-id="VIDEO_ID" aria-label="…"></button>
  </div>
</section>
```

- `loading="eager" fetchpriority="high"` on the cover slide and the first few slides only; `loading="lazy"` everywhere else.
- Hotspot position is **percentage-based**, relative to the slide image, so it survives any responsive scaling. It is derived by measuring the actual source PNG (see Section 6), never eyeballed.
- A slide with a full interactive case grid instead of (or in addition to) a hotspot uses `.portfolio-overlay > .portfolio-grid > button.portfolio-tile[data-embed-src]` — CSS grid (`repeat(4,1fr)`, fixed px gap, tiles at `aspect-ratio:16/9`), positioned as a percentage box (`left/right/top/bottom`) over the slide background image.
- The shared video modal is one `<iframe>` whose `src` is set at click time by `openEmbed(url)`; `data-youtube-id` builds a `youtube.com/embed/…` URL, `data-embed-src` is used verbatim (covers non-YouTube embeds).

**Deploy target:** plain nginx static host over `scp`. No CI — every change is a manual, verified push (Section 6).

## 4. Asset pipeline

Every slide image goes through the same optimization step before it's usable on the site:

- Desktop variant: resized to max width 2000px.
- Mobile variant: resized to max width 1280px.
- Each size exported as both WebP (q≈76–80) and progressive JPEG (q≈78–82) for fallback.
- Result: 4 files per slide (`sNNN.webp`, `sNNN.jpg`, `sNNN-mobile.webp`, `sNNN-mobile.jpg`).

New slides inserted mid-deck use a suffix on the **designer's own filename**, not a full renumbering of every following file (`s018_1.png`, `s018_2.png`, `s030_2.png`) — this lets the designer keep working in their native numbering while the deck's live order is whatever `index.html` says, independent of the filenames.

## 5. Derived deliverable: linked PDF export

When a static/offline copy is needed, it is generated **by parsing the live site's own source**, not rebuilt by hand:

1. Parse `index.html` for the ordered slide sections, each slide's desktop image, and any `video-hotspot` / `portfolio-tile` elements with their position + target URL.
2. Read the actual CSS layout rules for anything positioned by CSS instead of inline style (e.g. the portfolio grid's `left/right/top/bottom`, column count, px gap, tile aspect-ratio) and reproduce that math directly — never approximate a grid by eye.
3. One PDF page per slide, sized to the source image's own pixel dimensions (1 px = 1 pt is a convenient identity that keeps every percentage-based rect a direct multiply, no unit conversion).
4. Insert the slide image full-page, then a URI link annotation for every hotspot/tile rect, converting each platform's data attribute into a real followable URL (YouTube `watch?v=`, VK `vk.com/video{oid}_{id}`, etc.).
5. **Composite any per-tile thumbnail images too**, not just the background — a grid whose tiles are separate DOM images on the live site will render as empty boxes in the PDF unless each tile's own image is placed into its computed rect as well.
6. Verify before calling it done: render at least the pages that carry links back to a raster image with the link rects drawn on top, and visually confirm each rect actually sits on its intended text/thumbnail.

## 6. Operating loop (designer ↔ agent ↔ production)

This is the day-to-day discipline that keeps the site trustworthy while a designer is iterating on slides in parallel:

1. **Never act on "I updated slide N" alone.** Check the source file's modification time first — confirm it actually changed before doing anything.
2. **Always view the actual content before deploying it.** Never push a file you have not looked at, even for a "just re-upload it" request.
3. **Hold the deck's established creative rules in working memory and check new content against them unprompted** (e.g. "the key visual must not be fully revealed before the climax slide" — this kind of standing constraint needs to be re-checked on every new asset, not just when someone asks).
4. **When positioning anything (a hotspot, a link rect), measure the source pixels — never guess-and-iterate.** Crop the exact region, read off pixel bounds, convert to percentage.
5. **Full pipeline per change:** copy designer file into the working image folder → run the optimize step (4 outputs) → deploy all 4 files (+ `index.html` if markup changed) → verify by diffing local vs. remote file sizes (or an explicit render check for anything visual/positional). Treat the four steps as one atomic unit; don't skip verification because the previous nine times worked.
6. **Auditing "what's done" means re-opening every file, not recalling from memory.** A placeholder pattern (e.g. literal `"[ФИО]"`, `"фото + текст"`, empty dashed boxes) is only found by actually looking.
7. **When a client-supplied structured document has a strict format (e.g. a budget spreadsheet template) that must not be altered:** distinguish clearly between *entering data* (always allowed) and *changing a formula* (never do it unless explicitly asked). If the template itself is internally broken or inconsistent (a formula silently missing on one row, a sum range that excludes a row it should include), **say so plainly rather than silently "fixing" it to look right or silently leaving it broken** — the human decides whether it's a bug to patch or intended behavior to respect.

## 7. What a digital employee needs to own this deliverable type

Mapped to `architecture/005_EMPLOYEE_MODEL.md` terms — required capabilities, not a specific model or vendor:

- Image manipulation (resize/format-convert/crop-and-measure) at the pixel level.
- Static HTML/CSS/JS editing without a build step.
- Remote file sync + verification (upload, diff-check, no blind trust in "it worked").
- Structured document parsing for derived-artifact generation (HTML/CSS → PDF with live links, in this case).
- Spreadsheet-formula literacy: read a formula chain well enough to know what's safe to fill vs. what would silently change behavior.
- Sustained adherence to a standing creative/brand constraint across many independent small tasks, without needing it restated each time.
