import { test, expect } from '@playwright/test'
import { documentSnapshot } from './document-snapshot'

const raster = 'data:image/png;base64,' + 'A'.repeat(600_000)
test('small documents are unchanged and only raster img.src is compacted', () => {
  const small = '<img src="data:image/png;base64,AAAA">営業禁止'
  expect(documentSnapshot(small)).toBe(small)
  for (const quote of ['"', "'", '']) {
    expect(documentSnapshot(`<IMG alt="safe" SRC=${quote}${raster}${quote}>`)).toBe(`<IMG alt="safe" SRC=${quote}data:,${quote}>`)
  }
})

test('scripts, styles, SVG, hidden values, comments and fake attributes are never discarded', () => {
  for (const html of [`<script>const x='<img src="${raster}">';</script>`, `<style>/*<img src="${raster}">*/</style>`,
    `<textarea><img src="${raster}"></textarea>`, `<!--<img src="${raster}">-->`, `<input type="hidden" value="${raster}">`,
    `<img src="data:image/svg+xml;base64,${'A'.repeat(600_000)}">`, `<img alt='src="${raster}"'>`,
    `<img src="${raster}" src="other">`, `<img src="${raster}`, `<img data-src="${raster}">`]) {
    expect(() => documentSnapshot(html)).toThrow('BYTE_BUDGET')
  }
  const safety = '<p>営業禁止</p><div data-sitekey="captcha"></div><input type="hidden" value="token"><script>window.safety=true</script>'
  expect(documentSnapshot(`<img src="${raster}">${safety}`)).toBe(`<img src="data:,">${safety}`)
})

test('raw and retained document bounds reject oversized nondecorative content', () => {
  expect(() => documentSnapshot(`<img src="data:image/png;base64,${'A'.repeat(8_000_000)}">`)).toThrow('BYTE_BUDGET')
  expect(() => documentSnapshot(`<img src="${raster}">${'x'.repeat(500_000)}`)).toThrow('BYTE_BUDGET')
})
