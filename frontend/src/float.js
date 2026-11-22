// Where a floating box goes: a tooltip, a menu, a popover. Pure arithmetic - no document - so that it can be tested
// at every edge of the window (tests/float.test.js); the callers measure and write the result into `left` / `top` of a
// `position: fixed` box.

const OPPOSITE = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' }
const clamp = (v, lo, hi) => (hi < lo ? lo : Math.min(Math.max(v, lo), hi))      // (a box larger than the room starts at the near edge)

// `anchor`: { left, top, right, bottom } in window coordinates (a DOMRect will do); `size`: { width, height } of the
// box; `viewport`: { width, height }. Options:
//   placement  top | bottom | left | right - the side of the anchor that is wanted
//   align      center | start | end - along the other axis: centred on the anchor, or its start / end edges in line
//   offset     the gap between the anchor and the box
//   pad        how near the box may come to the edge of the window
// The wanted side is kept when the box fits there; otherwise the opposite side when it fits there; otherwise the side
// with more room. Along the other axis the box is moved until it is inside the window; as a last resort it is held
// inside the window on both axes (and then it may cover the anchor). Returns { left, top, placement } - the side that
// was used.
export function place(anchor, size, viewport, { placement = 'top', align = 'center', offset = 8, pad = 8 } = {}) {
  const side = OPPOSITE[placement] ? placement : 'top'
  const upright = side === 'top' || side === 'bottom'
  const need = (upright ? size.height : size.width) + offset + pad
  const room = { top: anchor.top, bottom: viewport.height - anchor.bottom, left: anchor.left, right: viewport.width - anchor.right }
  const other = OPPOSITE[side]
  const used = room[side] >= need ? side : room[other] >= need ? other : room[other] > room[side] ? other : side

  const along = (a0, a1, len) => (align === 'start' ? a0 : align === 'end' ? a1 - len : (a0 + a1 - len) / 2)
  let left, top
  if (used === 'top' || used === 'bottom') {
    top = used === 'top' ? anchor.top - offset - size.height : anchor.bottom + offset
    left = along(anchor.left, anchor.right, size.width)
  } else {
    left = used === 'left' ? anchor.left - offset - size.width : anchor.right + offset
    top = along(anchor.top, anchor.bottom, size.height)
  }
  return {
    left: Math.round(clamp(left, pad, viewport.width - pad - size.width)),
    top: Math.round(clamp(top, pad, viewport.height - pad - size.height)),
    placement: used,
  }
}

// --- what the callers measure (these two read the document; `place` does not) ----------------------------------------

// The window, without its scroll bars.
export const windowSize = () => ({ width: document.documentElement.clientWidth, height: document.documentElement.clientHeight })

// A floating box is put on <body>, so the level its stylesheet gives it (`token`: --z-tip, --z-pop) is right when what
// it belongs to lies lower. When that is in something higher - a question, a select's list, another floating box -
// the box has to lie over that: the level to give it then, or null when the stylesheet's own will do.
export function zOver(el, token) {
  let z = 0
  for (let p = el; p && p.nodeType === 1; p = p.parentElement) {
    const v = parseInt(getComputedStyle(p).zIndex, 10)
    if (v > z) z = v
  }
  const own = parseInt(getComputedStyle(document.documentElement).getPropertyValue(token), 10) || 0
  return z >= own ? z + 1 : null
}
