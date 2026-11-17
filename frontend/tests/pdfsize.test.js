// The arithmetic of the PDF preview (src/pdfsize.js).
import { describe, expect, it } from 'vitest'
import { clampZoom, pageWidth, resized } from '../src/pdfsize.js'

describe('the PDF preview', () => {
  it('draws a page as wide as its box, less the padding, and never too narrow to read', () => {
    expect(pageWidth(824)).toBe(800)
    expect(pageWidth(600.7)).toBe(576)
    expect(pageWidth(200)).toBe(320)
  })
  it('zooms between a half and two and a half', () => {
    expect(clampZoom(1.25)).toBe(1.25)
    expect(clampZoom(0.25)).toBe(0.5)
    expect(clampZoom(9)).toBe(2.5)
    expect(clampZoom(1 + 0.25 + 0.25 + 0.1 - 0.1)).toBe(1.5)      // steps that do not add up exactly in binary
  })
  it('draws again when the box has really changed its width, not for a scroll bar', () => {
    expect(resized(824, 1100)).toBe(true)
    expect(resized(824, 600)).toBe(true)
    expect(resized(824, 807)).toBe(false)        // a scroll bar came (17 pixels on Windows)
    expect(resized(807, 824)).toBe(false)        // and went
    expect(resized(824, 824)).toBe(false)
    expect(resized(200, 300)).toBe(false)        // both are at the narrowest a page is drawn
  })
})
