// What a draft asks the applicant to decide, before the full table of answers.
//
// A draft is every question of a form with its answer, its reason and how sure the answer is - sixty rows, most of
// them a name, an e-mail address, "yes, authorised to work". What needs a look is a handful: a question that has no
// answer, an answer the program is not sure of, a sensitive question met for the first time, an answer that changed
// because the form did, a file that was written for this posting, and who presses Submit. They are listed first,
// each leading to its row; the table stays as it is.

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

  const sensitive = answers.filter((a) => a.sensitive && !a.sensitive_confirmed && has(a) && !open.has(a.id))
  if (sensitive.length) out.push({ key: 'sensitive', label: '敏感问题，第一次遇到这种问法', tone: 'warn', items: sensitive.map((a) => row(a)) })

  const taken = new Set(sensitive.map((a) => a.id))
  const unsure = answers.filter((a) => has(a) && a.type !== 'file' && ['low', 'medium'].includes(a.confidence) && !open.has(a.id) && !taken.has(a.id))
  if (unsure.length) out.push({ key: 'unsure', label: '程序没有十足把握的答案', tone: 'warn', items: unsure.map((a) => row(a, a.confidence === 'low' ? '把握低' : '把握中等')) })

  for (const a of unsure) taken.add(a.id)
  const changed = answers.filter((a) => a.delta && has(a) && !open.has(a.id) && !taken.has(a.id))
  if (changed.length) out.push({ key: 'changed', label: '表单变了之后新出现或改过的', tone: 'info', items: changed.map((a) => row(a)) })

  const files = (d.materials || []).filter((m) => m.kind === 'tailored_resume' || m.kind === 'cover_letter')
  if (files.length) out.push({ key: 'materials', label: '为这个岗位写的材料', tone: 'info', to: 'materials', items: files.map((m) => ({ id: '', label: m.name, note: m.kind === 'tailored_resume' ? '按岗位调整过的简历' : '求职信' })) })

  if (d.submit_mode) {
    const manual = d.submit_mode.mode === 'manual'
    out.push({ key: 'submit', label: manual ? '批准后：填好停下，由你点提交' : '批准后：程序自己提交', tone: manual ? 'warn' : '', to: 'after',
      items: manual ? (d.submit_mode.why || (d.submit_mode.reasons || []).map((text) => ({ text }))).map((w) => ({ id: '', label: w.text, note: '' })) : [] })
  }
  return out
}

// How many things in all need a decision (the rows; not the files and not the line about who submits).
export const toDecide = (groups) => groups.filter((g) => !g.to).reduce((n, g) => n + g.items.length, 0)
