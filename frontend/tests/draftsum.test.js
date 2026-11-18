// What a draft asks the applicant to decide (src/draftsum.js).
import { describe, expect, it } from 'vitest'
import { decisions, toDecide } from '../src/draftsum.js'

const a = (id, o = {}) => ({ id, label: 'Q ' + id, type: 'text', value: 'x', confidence: 'high', sensitive: '', sensitive_confirmed: true, delta: false, ...o })
const draft = (o = {}) => ({ answers: [], unresolved: [], materials: [], submit_mode: { mode: 'auto', reasons: [], why: [] }, ...o })

describe('what needs a decision', () => {
  it('is nothing but who submits, for a draft that is all plain facts', () => {
    const g = decisions(draft({ answers: [a('name'), a('email'), a('cv', { type: 'file', confidence: 'medium' })] }))
    expect(g.map((x) => x.key)).toEqual(['submit'])
    expect(g[0].label).toContain('程序自己提交')
    expect(toDecide(g)).toBe(0)
  })
  it('lists a question without an answer first, by the form\'s own wording', () => {
    const g = decisions(draft({ answers: [a('salary', { value: '', label: 'Expected salary?' }), a('name')], unresolved: [{ id: 'salary' }] }))
    expect(g[0]).toMatchObject({ key: 'unanswered', tone: 'bad', items: [{ id: 'salary', label: 'Expected salary?' }] })
  })
  it('lists each answer once, under the first reason it needs a look', () => {
    const g = decisions(draft({
      answers: [a('sponsor', { sensitive: 'sponsorship', sensitive_confirmed: false, confidence: 'low', delta: true }), a('why', { confidence: 'medium', delta: true }),
        a('start', { delta: true }), a('low', { confidence: 'low' }), a('blank', { value: '', confidence: 'low' }), a('seen', { sensitive: 'salary', sensitive_confirmed: true })],
    }))
    const by = Object.fromEntries(g.map((x) => [x.key, x.items.map((i) => i.id)]))
    expect(by.sensitive).toEqual(['sponsor'])
    expect(by.unsure).toEqual(['why', 'low'])          // not the sensitive one again, not the one that has no value
    expect(by.changed).toEqual(['start'])
    expect(g.find((x) => x.key === 'unsure').items.map((i) => i.note)).toEqual(['把握中等', '把握低'])
    expect(toDecide(g)).toBe(4)
  })
  it('names the files that were written for this posting', () => {
    const g = decisions(draft({ materials: [{ kind: 'resume_site', name: 'CV.pdf' }, { kind: 'tailored_resume', name: 'CV_Acme.pdf' }, { kind: 'cover_letter', name: 'Acme.pdf' }] }))
    const m = g.find((x) => x.key === 'materials')
    expect(m.to).toBe('materials')
    expect(m.items.map((i) => [i.label, i.note])).toEqual([['CV_Acme.pdf', '按岗位调整过的简历'], ['Acme.pdf', '求职信']])
    expect(toDecide(g)).toBe(0)                        // files and the line about submitting are not counted as open questions
  })
  it('says who presses Submit, and why when it is the applicant', () => {
    const g = decisions(draft({ submit_mode: { mode: 'manual', reasons: ['你把 Acme 设为人工提交'], why: [{ text: '你把 Acme 设为人工提交', where: '/settings/automation/submit' }] } }))
    const s = g.find((x) => x.key === 'submit')
    expect(s.label).toContain('由你点提交')
    expect(s.items.map((i) => i.label)).toEqual(['你把 Acme 设为人工提交'])
    // a draft from before the reasons had places: the sentences alone
    expect(decisions(draft({ submit_mode: { mode: 'manual', reasons: ['x'] } })).find((x) => x.key === 'submit').items[0].label).toBe('x')
  })
  it('is nothing for no draft', () => {
    expect(decisions(null)).toEqual([])
  })
})
