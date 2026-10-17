import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { Company, CompanyPage, OutreachTemplate } from './types'

const placeholders = ['会社名', '送信者名', '送信者会社名', '送信者メール', '送信者電話']
const stopMethod = (body: string) => body.split(/[。.!?！？\n]+/).some(sentence =>
  /不要|停止|解除|受け取らない|unsubscribe|opt[- ]?out/i.test(sentence)
  && /返信|連絡|メール|リンク|こちら|下記|フォーム|unsubscribe|opt[- ]?out/i.test(sentence))

export function SendFlowTemplatePanel({ projectId, channel, canWrite, initialTemplateId = '', onTemplateCountChange }: {
  projectId: string; channel: 'email' | 'form'; canWrite: boolean; initialTemplateId?: string; onTemplateCountChange: (count: number) => void
}) {
  const [templates, setTemplates] = useState<OutreachTemplate[]>([])
  const [samples, setSamples] = useState<Company[]>([])
  const [sampleId, setSampleId] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [name, setName] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const selectedTemplate = templates.find(template => template.id === templateId)
  const selectedSample = samples.find(company => company.id === sampleId)
  const matchingTemplates = templates.filter(template => template.channel === channel)

  useEffect(() => {
    let live = true
    Promise.all([
      api<OutreachTemplate[]>(`/projects/${projectId}/outreach-templates`),
      api<CompanyPage>(`/projects/${projectId}/company-list?offset=0&limit=20&sort=company_name`),
    ]).then(([nextTemplates, page]) => {
      if (!live) return
      setTemplates(nextTemplates)
      setSamples(page.items)
      setSampleId(page.items[0]?.id ?? '')
      const initialTemplate = nextTemplates.find(template => template.id === initialTemplateId && template.channel === channel)
      setTemplateId(initialTemplate?.id ?? '')
      setName(initialTemplate?.name ?? '')
      setSubject(initialTemplate?.subject ?? '')
      setBody(initialTemplate?.body ?? '')
    }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [channel, initialTemplateId, projectId])

  function selectTemplate(id: string) {
    setTemplateId(id)
    const template = templates.find(item => item.id === id)
    setName(template?.name ?? '')
    setSubject(template?.subject ?? '')
    setBody(template?.body ?? '')
    setNotice('')
  }

  function insertPlaceholder(value: string) {
    const textarea = bodyRef.current
    if (!textarea) { setBody(current => `${current}{{${value}}}`); return }
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const token = `{{${value}}}`
    setBody(current => `${current.slice(0, start)}${token}${current.slice(end)}`)
    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(start + token.length, start + token.length)
    })
  }

  async function save() {
    if (!canWrite || !name.trim() || !body.trim() || !stopMethod(body)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = { name: name.trim(), channel, subject: channel === 'email' ? subject : '', body: body.trim() }
      const saved = await api<OutreachTemplate>(templateId ? `/outreach-templates/${templateId}` : `/projects/${projectId}/outreach-templates`, templateId ? 'PUT' : 'POST', payload)
      const next = templateId ? templates.map(item => item.id === saved.id ? saved : item) : [...templates, saved]
      setTemplates(next); onTemplateCountChange(next.filter(item => item.channel === channel).length)
      setTemplateId(saved.id); setNotice('テンプレートを保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  async function remove() {
    if (!selectedTemplate || !canWrite || !window.confirm(`テンプレート「${selectedTemplate.name}」を削除しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/outreach-templates/${selectedTemplate.id}`, 'DELETE')
      const next = templates.filter(item => item.id !== selectedTemplate.id)
      setTemplates(next); onTemplateCountChange(next.filter(item => item.channel === channel).length)
      setTemplateId(''); setName(''); setSubject(''); setBody(''); setNotice('テンプレートを削除しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  const companyName = selectedSample?.company_name?.trim() || selectedSample?.domain?.trim() || '（会社名未登録）'
  const renderPreview = (value: string) => value.replace(/{{(会社名|送信者名|送信者会社名|送信者メール|送信者電話)}}/g, (_match, key: string) =>
    key === '会社名' ? companyName : `【${key}の設定値】`)

  return <section aria-label="文面テンプレート" className="space-y-4">
    <p className="muted text-sm">テンプレートは企業別の下書き作成に使います。メールの配信停止リンクは送信時に既存処理が付与します。</p>
    <p className="badge">{channel === 'email' ? 'メール' : 'フォーム'}用テンプレート</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <label className="field">既存テンプレート<select disabled={busy} value={templateId} onChange={event => selectTemplate(event.target.value)}>
      <option value="">新しいテンプレートを作成</option>{matchingTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
    </select></label>
    <div className="detail-grid">
      <label className="field">テンプレート名<input maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label>
      {channel === 'email' && <label className="field">件名<input maxLength={300} value={subject} onChange={event => setSubject(event.target.value)} /></label>}
    </div>
    <div className="mt-3 flex flex-wrap gap-2" aria-label="差し込み項目">
      {placeholders.map(value => <button className="secondary" type="button" key={value} disabled={!canWrite || busy} onClick={() => insertPlaceholder(value)}>{`{{${value}}} を挿入`}</button>)}
    </div>
    <label className="field mt-3">本文<textarea ref={bodyRef} rows={8} maxLength={10000} value={body} onChange={event => setBody(event.target.value)} /></label>
    {!stopMethod(body) && <p className="error" role="alert">停止方法の一文（例：今後のご案内が不要な場合はご返信ください）を本文に追加してください。</p>}
    {channel === 'form' && body.length > 1000 && <p className="error" role="status">フォーム本文が1,000文字を超えています。入力文字数制限に注意してください（保存は可能です）。</p>}
    <div className="mt-4 rounded-lg border p-4">
      <h3>会社別プレビュー</h3>
      <label className="field mt-2">プレビューする会社<select value={sampleId} onChange={event => setSampleId(event.target.value)}>
        {samples.map(company => <option key={company.id} value={company.id}>{company.company_name || company.domain || '名称未登録'}</option>)}
      </select></label>
      {selectedSample ? <><p className="mt-3"><strong>{companyName}</strong></p>{channel === 'email' && <p className="mt-2">件名：{renderPreview(subject)}</p>}<pre className="mt-2 whitespace-pre-wrap break-words">{renderPreview(body)}</pre>
        <p className="muted mt-2 text-xs">送信者の差し込みは保存済み送信者設定から実行時に反映されます。</p></> : <p className="muted mt-3">プレビュー対象の会社がありません。</p>}
    </div>
    <div className="actions flex-wrap">
      {canWrite && <><button type="button" disabled={busy || !name.trim() || !body.trim() || !stopMethod(body)} onClick={() => void save()}>{busy ? '保存中…' : templateId ? '変更を保存' : 'テンプレートを保存'}</button>{selectedTemplate && <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>削除</button>}</>}
    </div>
    {!canWrite && <p className="muted">閲覧のみです。テンプレートの作成・編集は所有者または編集者が行えます。</p>}
  </section>
}
