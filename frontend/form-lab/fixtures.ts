import { createServer, type Server } from 'node:http'
import { randomUUID } from 'node:crypto'

export const scenarios = ['html', 'dynamic', 'confirmation', 'iframe', 'selection', 'consent'] as const
export type Scenario = typeof scenarios[number]
export const consentText = '入力した個人情報を問い合わせ対応に利用することに同意します'

const controls = `<label>お名前<input name="name" required></label>
<label>メールアドレス<input type="email" name="email" required></label>
<label>お問い合わせ内容<textarea name="message" required></textarea></label>`

function document(body: string) {
  return `<!doctype html><html lang="ja"><meta charset="utf-8"><title>匿名フォームPoC</title>
<body><h1>お問い合わせ</h1><p>ローカルの検証専用。営業許可ではありません。</p>${body}</body></html>`
}

function form(extra = '', dynamic = false) {
  const contents = controls + extra
  return document(`<form method="post" action="/never-send">
<div id="fields">${dynamic ? '' : contents}</div>
<button type="button" id="preview">入力内容を確認</button>
<button type="submit" disabled>最終送信（PoC対象外）</button>
<p role="alert" id="error"></p></form><section id="confirmation" hidden>
<h2>確認画面</h2><dl id="readback"></dl></section>
<script>
${dynamic ? `document.querySelector('#fields').innerHTML = ${JSON.stringify(contents)};` : ''}
document.querySelector('#preview').addEventListener('click', () => {
 const f = document.querySelector('form');
 if (!f.checkValidity()) { document.querySelector('#error').textContent = '入力エラー：必須項目または形式を確認してください'; return; }
 const output = document.querySelector('#readback'); output.replaceChildren();
 for (const [key, value] of new FormData(f)) {
  const dt = document.createElement('dt'); dt.textContent = key;
  const dd = document.createElement('dd'); dd.textContent = String(value); output.append(dt, dd);
 }
 document.querySelector('#confirmation').hidden = false;
});</script>`)
}

export type Fixture = {
  origin: string
  urls: Record<string, string>
  postCount: () => number
  forbiddenCount: () => number
  stop: () => Promise<void>
}

export async function startFixture(): Promise<Fixture> {
  const prefix = `/lab-${randomUUID()}`
  let posts = 0
  let forbidden = 0
  let origin = ''
  const pages: Record<string, string> = {
    html: form(), dynamic: form('', true), confirmation: form(),
    inner: form(),
    selection: form(`<label>お問い合わせ種別<select name="topic" required>
<option value="">選択してください</option><option value="business">事業提携</option><option value="support">サポート</option></select></label>
<fieldset><legend>返信方法</legend><label><input type="radio" name="reply" value="email" required>メール</label>
<label><input type="radio" name="reply" value="phone" required>電話</label></fieldset>`),
    consent: form(`<label><input type="checkbox" name="privacy" value="agree" required>${consentText}</label>`),
    prohibited: document('<p>営業・勧誘目的のお問い合わせはお断りします。</p>' + '<form></form>'),
    captcha: document('<p>CAPTCHA</p><div class="g-recaptcha"></div><form></form>'),
    password: form('<label>パスワード<input type="password" name="password" required></label>'),
    unknown: form('<label>不明な項目<input name="unknown" required></label>'),
    invalid: form(), robots: form(), terms: form(),
    changed: form() + `<script>document.querySelector('[name=name]').addEventListener('input', () => {
      document.querySelector('textarea').required = false;
    });</script>`,
  }
  const server: Server = createServer((request, response) => {
    const key = request.url?.slice(prefix.length + 1)
    if (request.method !== 'GET') {
      posts++
      response.writeHead(405).end()
      return
    }
    if (request.url === '/robots.txt') {
      response.writeHead(200, { 'Content-Type': 'text/plain' })
      response.end(`User-agent: *\nAllow: ${prefix}/\nDisallow: ${prefix}/robots\n`)
      return
    }
    if (request.url === `${prefix}/usage`) {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ allowed: [...Object.keys(pages), 'iframe', 'foreign-frame', 'redirect'], forbidden: ['terms'], owner: 'synthetic-fixture' }))
      return
    }
    if (key === 'redirect') {
      response.writeHead(302, { Location: `${origin}/unregistered-target` }).end()
      return
    }
    if (request.url === '/unregistered-target') forbidden++
    if (key === 'iframe') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      response.end(document(`<iframe title="問い合わせフォーム" src="${origin}${prefix}/inner"></iframe>`))
      return
    }
    if (key === 'foreign-frame') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      response.end(document('<iframe src="/unregistered-target"></iframe>'))
      return
    }
    if (!request.url?.startsWith(prefix + '/') || !key || !pages[key]) {
      response.writeHead(404).end()
      return
    }
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    response.end(pages[key])
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Loopback fixture required')
  origin = `http://127.0.0.1:${address.port}`
  const urls = Object.fromEntries(
    [...Object.keys(pages), 'iframe', 'foreign-frame', 'redirect', 'usage'].map(key => [key, `${origin}${prefix}/${key}`]),
  )
  return {
    origin, urls, postCount: () => posts, forbiddenCount: () => forbidden,
    stop: () => new Promise<void>((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve())
      server.closeAllConnections()
    }),
  }
}
