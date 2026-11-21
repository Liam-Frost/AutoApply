// What a draft asks the applicant to decide, before the full table of answers.
//
// A draft is every question of a form with what the agent entered, where it has that from and how sure it is - sixty
// rows, most of them a name, an e-mail address, "yes, authorised to work". What needs a look is a handful: a question
// that has no answer, an answer the agent is not sure of, a file that was written for this posting, and who presses
// Submit. They are listed first, each leading to its row; the table stays as it is.

const has = (a) => a.value !== '' && a.value != null && !(Array.isArray(a.value) && !a.value.length)

// [{ key, label, tone, items: [{ id, label, note }], to }] - only the groups that have something in them.
// `to`: where the group as a whole is on the page ('materials', 'after'), for groups that are not rows of the table.
export function decisions(d) {
  if (!d) return []
  const out = []
  const open = new Set((d.unresolved || []).map((u) => u.id))
  const row = (a, note = '') => ({ id: a.id, label: a.label, note })
  const answers = d.answers || []

  const unanswered = (d.unresolved || []).map((u) => ({ id: u.id, label: u.label || (answers.find((a) => a.id === u.id) || {}).label || u.id, note: '' }))
  if (unanswered.length) out.push({ key: 'unanswered', label: '还没有答案，要你来答', tone: 'bad', items: unanswered })

  const unsure = answers.filter((a) => has(a) && a.type !== 'file' && ['low', 'medium'].includes(a.confidence) && !open.has(a.id))
  if (unsure.length) out.push({ key: 'unsure', label: 'Agent 没有十足把握的答案', tone: 'warn', items: unsure.map((a) => row(a, a.confidence === 'low' ? '把握低' : '把握中等')) })

  const written = d.tailor && d.tailor.written && d.tailor.use === 'tailored' ? [{ id: '', label: d.tailor.written.name, note: '为这个岗位改写的简历' }] : []
  const letters = (d.materials || []).filter((m) => /cover|letter|求职信/i.test(`${m.slot || ''} ${m.label || ''}`)).map((m) => ({ id: '', label: m.name, note: '求职信' }))
  if (written.length || letters.length) out.push({ key: 'materials', label: '为这个岗位写的材料', tone: 'info', to: 'materials', items: [...written, ...letters] })

  if (d.policy) {
    const mine = d.policy === 'hand_over'
    out.push({ key: 'submit', label: mine ? '批准后：Agent 停在最后一步，由你点提交' : '批准后：Agent 提交', tone: mine ? 'warn' : '', to: 'after', items: [] })
  }
  return out
}

// How many things in all need a decision (the rows; not the files and not the line about who submits).
export const toDecide = (groups) => groups.filter((g) => !g.to).reduce((n, g) => n + g.items.length, 0)
