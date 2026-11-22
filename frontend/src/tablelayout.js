// The column widths of a DataTable: from the column definitions and the width of the box - never from what the cells
// hold, so no value, however long, can move a column. Pure: DataTable.vue writes the result into a <colgroup>.
//
// A column is { id, width?, min?, max?, flex?, priority? }:
//   width            fixed, in px
//   min / max        the bounds of a column that takes part in sharing (min defaults to MIN_WIDTH, max to none)
//   flex             its part of the room left after every minimum (default 1 for a column without `width`; 0 = stays
//                    at its minimum)
//   priority > 0     optional: hidden when the minimums do not fit, the highest number first (of two with the same
//                    number, the later one first); a column without priority is never hidden

export const SELECT_WIDTH = 40      // the checkbox column of a selectable table
export const MIN_WIDTH = 64         // a column that says nothing about its width is at least this wide

const px = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Math.max(0, Math.round(Number(v))))

function shape(col) {
  const priority = Number(col.priority) > 0 ? Number(col.priority) : 0
  const fixed = px(col.width)
  if (fixed !== null) return { id: col.id, min: fixed, max: fixed, flex: 0, fixed: true, priority }
  const top = px(col.max)
  let max = top === null ? Infinity : top
  const min = px(col.min) ?? Math.min(MIN_WIDTH, max)
  if (max < min) max = min
  const flex = col.flex === undefined || col.flex === null ? 1 : Math.max(0, Number(col.flex) || 0)
  return { id: col.id, min, max, flex, fixed: false, priority }
}

// Whole pixels that add up to exactly `total`: each share rounded down, the pixels left over to the largest fractions
// (the earlier column first). A share is between whole bounds, so one more pixel never passes a maximum.
function whole(shares, total) {
  const out = shares.map(Math.floor)
  let left = total - out.reduce((s, v) => s + v, 0)
  const order = shares.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0] || a[1] - b[1])
  for (let k = 0; left > 0 && order.length; k = (k + 1) % order.length, left--) out[order[k][1]]++
  return out
}

// -> { visible: [ids, in order], widths: { id: px }, total: px of the whole table, scroll: Boolean, select: px }
// opts: { selectable } - a selectable table keeps SELECT_WIDTH for its checkbox column (in `total`, not in `widths`).
export function layoutColumns(columns, width, opts = {}) {
  const select = opts.selectable ? SELECT_WIDTH : 0
  const room = Math.max(0, Math.floor(Number(width) || 0) - select)
  const cols = (columns || []).map(shape)
  const need = () => cols.reduce((s, c) => s + c.min, 0)

  // what is optional goes, one column at a time, only while the minimums do not fit
  while (need() > room) {
    let drop = -1
    cols.forEach((c, i) => { if (c.priority > 0 && (drop < 0 || c.priority >= cols[drop].priority)) drop = i })
    if (drop < 0) break
    cols.splice(drop, 1)
  }

  const visible = cols.map((c) => c.id)
  const done = (list, scroll) => ({ visible, widths: Object.fromEntries(cols.map((c, i) => [c.id, list[i]])), total: list.reduce((s, v) => s + v, 0) + select, scroll, select })
  const least = need()
  // what must stay does not fit: every column at its minimum, and the table scrolls inside its box
  if (least > room) return done(cols.map((c) => c.min), true)
  if (!cols.length) return done([], false)

  // the room left is shared by flex; a column that reaches its maximum stops there and the others share its part
  const w = cols.map((c) => c.min)
  let rest = room - least
  let open = cols.map((c, i) => i).filter((i) => cols[i].flex > 0 && cols[i].max > cols[i].min)
  while (rest > 0 && open.length) {
    const weight = open.reduce((s, i) => s + cols[i].flex, 0)
    const part = (i) => (rest * cols[i].flex) / weight
    const full = open.filter((i) => w[i] + part(i) >= cols[i].max)
    if (!full.length) {
      const parts = open.map(part)
      open.forEach((i, k) => { w[i] += parts[k] })
      rest = 0
      break
    }
    for (const i of full) { rest -= cols[i].max - w[i]; w[i] = cols[i].max }
    open = open.filter((i) => !full.includes(i))
  }
  // Nothing may take more and there is still room (every column fixed or at its maximum): the table fills its box
  // all the same - a header that ends before the box does looks broken. The columns that are not fixed grow past
  // their maximum in proportion (all of them, when every column is fixed).
  if (rest > 0) {
    const free = cols.some((c) => !c.fixed) ? cols.map((c, i) => i).filter((i) => !cols[i].fixed) : cols.map((c, i) => i)
    const base = free.reduce((s, i) => s + w[i], 0)
    const add = free.map((i) => (base > 0 ? (rest * w[i]) / base : rest / free.length))
    free.forEach((i, k) => { w[i] += add[k] })
  }
  return done(whole(w, room), false)
}
