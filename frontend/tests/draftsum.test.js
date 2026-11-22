// What the record of an application asks the applicant to decide (src/draftsum.js).
import { describe, expect, it } from 'vitest'
import { decisions, toDecide } from '../src/draftsum.js'

const a = (id, o = {}) => ({ id, label: 'Q ' + id, type: 'text', value: 'x', confidence: 'high', ...o })
const draft = (o = {}) => ({ answers: [], unresolved: [], materials: [], policy: 'approve', ...o })

describe('what needs a decision', () => {
  it('is nothing but who submits, for a record that is all plain facts', () => {
    const g = decisions(draft({ answers: [a('name'), a('email'), a('cv', { type: 'file', confidence: 'medium' })] }))
    expect(g.map((x) => x.key)).toEqual(['submit'])
    expect(g[0].label).toContain('Agent 提交')
    expect(toDecide(g)).toBe(0)
  })
  it('lists a question without an answer first, by the form\'s own wording', () => {
    const g = decisions(draft({ answers: [a('salary', { value: '', label: 'Expected salary?' }), a('name')], unresolved: [{ id: 'salary' }] }))
    expect(g[0]).toMatchObject({ key: 'unanswered', tone: 'bad', items: [{ id: 'salary', label: 'Expected salary?' }] })
  })
  it('lists the answers the agent is not sure of, and not the ones that are open or empty', () => {
    const g = decisions(draft({
      answers: [a('why', { confidence: 'medium' }), a('low', { confidence: 'low' }), a('blank', { value: '', confidence: 'low' }), a('open', { confidence: 'low' }), a('sure')],
      unresolved: [{ id: 'open' }],
    }))
    const by = Object.fromEntries(g.map((x) => [x.key, x.items.map((i) => i.id)]))
    expect(by.unanswered).toEqual(['open'])
    expect(by.unsure).toEqual(['why', 'low'])
    expect(g.find((x) => x.key === 'unsure').items.map((i) => i.note)).toEqual(['置信度中', '置信度低'])
    expect(toDecide(g)).toBe(3)
  })
  it('names what was written for this posting', () => {
    const g = decisions(draft({
      materials: [{ slot: 'Resume', name: 'CV.pdf' }, { slot: 'Cover letter', name: 'Acme.pdf' }],
      tailor: { written: { name: 'CV_Acme.pdf' }, use: 'tailored' },
    }))
    const m = g.find((x) => x.key === 'materials')
    expect(m.to).toBe('materials')
    expect(m.items.map((i) => [i.label, i.note])).toEqual([['CV_Acme.pdf', '定制简历'], ['Acme.pdf', '求职信']])
    expect(toDecide(g)).toBe(0)                        // files and the line about submitting are not counted as open questions
    // a résumé that was rewritten and that the applicant chose not to use is not one of this application's files
    expect(decisions(draft({ tailor: { written: { name: 'CV_Acme.pdf' }, use: 'base' } })).find((x) => x.key === 'materials')).toBeUndefined()
  })
  it('says who presses Submit', () => {
    const mine = decisions(draft({ policy: 'hand_over' })).find((x) => x.key === 'submit')
    expect(mine.label).toContain('由你提交')
    expect(mine.tone).toBe('warn')
    expect(decisions(draft({ policy: 'auto' })).find((x) => x.key === 'submit').label).toContain('Agent 提交')
  })
  it('is nothing for no record', () => {
    expect(decisions(null)).toEqual([])
  })
})
