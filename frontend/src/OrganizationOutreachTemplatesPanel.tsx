import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { OutreachTemplate } from './types'

const stopMethod = (body: string) => body.split(/[。.!?！？\n]+/).some(sentence =>
  /不要|停止|解除|受け取らない|unsubscribe|opt[- ]?out/i.test(sentence)
  && /返信|連絡|メール|リンク|こちら|下記|フォーム|unsubscribe|opt[- ]?out/i.test(sentence))

export function OrganizationOutreachTemplatesPanel({ organizationId }: { organizationId: string }) {
  const [templates, setTemplates] = useState<OutreachTemplate[]>([])
  const [templateId, setTemplateId] = useState('')
  const [channel, setChannel] = useState<'email' | 'form'>('form')
  const [name, setName] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let live = true
    setTemplateId(''); setName(''); setSubject(''); setBody(''); setError(''); setNotice('')
    api<OutreachTemplate[]>(`/organizations/${organizationId}/outreach-templates`)
      .then(rows => { if (live) setTemplates(rows) })
      .catch(reason => { if (live) setError(errorMessage(reason)) })
    return () => { live = false }
  }, [organizationId])

  const matching = templates.filter(template => template.channel === channel)

  function selectTemplate(id: string) {
    const template = templates.find(item => item.id === id)
    setTemplateId(id)
    setName(template?.name ?? '')
    setSubject(template?.subject ?? '')
    setBody(template?.body ?? '')
    setNotice(''); setError('')
  }

  function changeChannel(value: 'email' | 'form') {
    setChannel(value); setTemplateId(''); setName(''); setSubject(''); setBody(''); setNotice(''); setError('')
  }

  async function save() {
    if (!name.trim() || !body.trim() || !stopMethod(body)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = { name: name.trim(), channel, subject: channel === 'email' ? subject : '', body: body.trim() }
      const saved = await api<OutreachTemplate>(
        templateId ? `/outreach-templates/${templateId}` : `/organizations/${organizationId}/outreach-templates`,
        templateId ? 'PUT' : 'POST', payload,
      )
      setTemplates(current => templateId ? current.map(item => item.id === saved.id ? saved : item) : [...current, saved])
      setTemplateId(saved.id); setNotice('共通テンプレートを保存しました。全プロジェクトで選択できます。')
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  async function remove() {
    const selected = templates.find(item => item.id === templateId)
    if (!selected || !window.confirm(`共通テンプレート「${selected.name}」を削除しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/outreach-templates/${selected.id}`, 'DELETE')
      setTemplates(current => current.filter(item => item.id !== selected.id))
      setTemplateId(''); setName(''); setSubject(''); setBody(''); setNotice('共通テンプレートを削除しました。')
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  return <section className="panel" aria-label="共通文面テンプレート">
    <h2>共通文面テンプレート</h2>
    <p className="muted mt-2">ここで1回登録すると、この利用企業のすべてのプロジェクトで下書き作成に使えます。</p>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {notice && <p className="notice mt-3" role="status">{notice}</p>}
    <div className="actions mt-4" aria-label="テンプレート種別">
      <button type="button" className={channel === 'form' ? '' : 'secondary'} onClick={() => changeChannel('form')}>フォーム</button>
      <button type="button" className={channel === 'email' ? '' : 'secondary'} onClick={() => changeChannel('email')}>メール</button>
    </div>
    <label className="field mt-4">既存の共通テンプレート<select disabled={busy} value={templateId} onChange={event => selectTemplate(event.target.value)}>
      <option value="">新しい共通テンプレートを作成</option>
      {matching.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
    </select></label>
    <div className="detail-grid mt-3">
      <label className="field">テンプレート名<input maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label>
      {channel === 'email' && <label className="field">件名<input maxLength={300} value={subject} onChange={event => setSubject(event.target.value)} /></label>}
    </div>
    <label className="field mt-3">本文<textarea rows={8} maxLength={10000} value={body} onChange={event => setBody(event.target.value)} /></label>
    <p className="muted text-sm mt-2">差し込み：{'{{会社名}}'} {'{{送信者名}}'} {'{{送信者会社名}}'} {'{{送信者メール}}'} {'{{送信者電話}}'}</p>
    {!stopMethod(body) && <p className="error mt-2" role="alert">停止方法の一文（例：今後のご案内が不要な場合はご返信ください）を追加してください。</p>}
    <div className="actions mt-4">
      <button type="button" disabled={busy || !name.trim() || !body.trim() || !stopMethod(body)} onClick={() => void save()}>{busy ? '保存中…' : templateId ? '変更を保存' : '共通テンプレートを保存'}</button>
      {templateId && <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>削除</button>}
    </div>
  </section>
}
