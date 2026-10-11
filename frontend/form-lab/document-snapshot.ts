/** Omit only large embedded raster img.src values. Never trim safety/operation text. */
export function documentSnapshot(html: string): string {
  if (Buffer.byteLength(html) > 8_000_000) throw Error('BYTE_BUDGET')
  if (Buffer.byteLength(html) <= 500_000) return html
  const pieces: string[] = []
  let offset = 0
  while (offset < html.length) {
    const start = html.indexOf('<', offset)
    if (start < 0) { pieces.push(html.slice(offset)); break }
    pieces.push(html.slice(offset, start))
    if (html.startsWith('<!--', start)) {
      const end = html.indexOf('-->', start + 4)
      if (end < 0) throw Error('BYTE_BUDGET')
      pieces.push(html.slice(start, end + 3)); offset = end + 3; continue
    }
    let end = start + 1, quote = ''
    for (; end < html.length; end++) {
      const char = html[end]
      if (quote) { if (char === quote) quote = '' }
      else if (char === '"' || char === "'") quote = char
      else if (char === '>') break
    }
    if (end === html.length) throw Error('BYTE_BUDGET')
    let tag = html.slice(start, end + 1)
    const name = /^<([a-z][a-z0-9:-]*)(?=[\s/>])/i.exec(tag)?.[1].toLowerCase()
    if (name === 'img') {
      // Tokenize attributes; do not match a fake src inside another attribute's value.
      const attributes = [...tag.slice(4, -1).matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)]
      const sources = attributes.filter(attribute => attribute[1].toLowerCase() === 'src')
      if (sources.length === 1) {
        const source = sources[0], value = source[2] ?? source[3] ?? source[4] ?? ''
        if (value.length > 4096 && /^data:image\/(?:png|jpeg|gif|webp|avif);base64,[a-z0-9+/=\s]+$/i.test(value)) {
          const index = 4 + source.index! + source[0].indexOf(value)
          tag = tag.slice(0, index) + 'data:,' + tag.slice(index + value.length)
        }
      }
    }
    pieces.push(tag); offset = end + 1
    // These elements can contain literal markup. Preserve it verbatim, including JS.
    if (name && ['script', 'style', 'textarea', 'title', 'xmp', 'iframe', 'noembed', 'noframes', 'plaintext'].includes(name)) {
      if (name === 'plaintext') { pieces.push(html.slice(offset)); break }
      const close = new RegExp('</' + name + '\\s*>', 'ig'); close.lastIndex = offset
      const match = close.exec(html)
      if (!match) throw Error('BYTE_BUDGET')
      pieces.push(html.slice(offset, match.index + match[0].length)); offset = match.index + match[0].length
    }
  }
  const snapshot = pieces.join('')
  if (Buffer.byteLength(snapshot) > 500_000) throw Error('BYTE_BUDGET')
  return snapshot
}
