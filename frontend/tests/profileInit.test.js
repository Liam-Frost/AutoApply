// Where the writing of the profile stands, as the pages say it (profileInit.js).
import { describe, expect, it } from 'vitest'
import { phase, working } from '../src/profileInit.js'

const task = (t) => ({ blank: false, task: { id: 1, status: 'done', applied: false, draft: '', settled: '', ...t } })

describe('phase', () => {
  it('nothing asked for', () => {
    expect(phase(null)).toBe('none')
    expect(phase({ blank: true, task: null })).toBe('none')
    expect(working(null)).toBe(false)
  })
  it('queued and being written are "working": the page asks again in a few seconds', () => {
    expect(phase(task({ status: 'queued' }))).toBe('queued')
    expect(phase(task({ status: 'running' }))).toBe('running')
    expect(working(task({ status: 'queued' })) && working(task({ status: 'running' }))).toBe(true)
  })
  it('written: saved when there was no profile, a proposal when there is one', () => {
    expect(phase(task({ applied: true }))).toBe('applied')
    expect(phase(task({ draft: '# Applicant profile' }))).toBe('proposal')
    expect(working(task({ draft: '# Applicant profile' }))).toBe(false)
  })
  it('a proposal that was dealt with is not one any more', () => {
    expect(phase(task({ settled: 'adopted' }))).toBe('adopted')
    expect(phase(task({ settled: 'discarded' }))).toBe('discarded')
  })
  it('not written', () => {
    expect(phase(task({ status: 'failed', error: '读不出文字' }))).toBe('failed')
    expect(phase(task({ status: 'held' }))).toBe('none')
  })
})
