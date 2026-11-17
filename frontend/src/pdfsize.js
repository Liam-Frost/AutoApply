// The arithmetic of the PDF preview: how wide a page is drawn, how far it can be zoomed, and when the box it stands in
// has changed enough to draw it again.

// The width a page gets at "fit to width": the box, less its padding; never narrower than can be read.
export const pageWidth = (boxWidth) => Math.max(320, Math.floor(boxWidth) - 24)

export const clampZoom = (z) => Math.min(2.5, Math.max(0.5, Math.round(z * 100) / 100))

// Is the box now a different width, as far as drawing goes? (A scroll bar that comes or goes moves it by its own
// width - 17 pixels on Windows - and drawing again for that would make it come and go for ever. The box also keeps
// room for its scroll bar, so that it does not move at all: style.css, .pdf-pages.)
export const resized = (was, now) => Math.abs(pageWidth(now) - pageWidth(was)) >= 24
