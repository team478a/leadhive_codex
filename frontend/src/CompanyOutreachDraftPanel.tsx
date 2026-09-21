import type { ReactNode } from 'react'
import type { Company, ContactPerson, OutreachDraft, OutreachDraftApproval, OutreachTemplate } from './types'

type Props = {
  company: Company
  contacts: ContactPerson[]
  drafts: OutreachDraft[]
  selectedDraft: OutreachDraft | null
  templates: OutreachTemplate[]
  approvals: OutreachDraftApproval[]
  channel: OutreachDraft['channel']
  contactId: string
  instruction: string
  templateName: string
  busy: boolean
  children: ReactNode
  onChannelChange: (value: OutreachDraft['channel']) => void
  onContactChange: (value: string) => void
  onInstructionChange: (value: string) => void
  onTemplateNameChange: (value: string) => void
  onSelectedDraftChange: (value: OutreachDraft) => void
  onGenerate: () => void
  onSelect: (draft: OutreachDraft) => void
  onSave: () => void
  onCopy: () => void
  onDelete: () => void
  onSaveTemplate: () => void
  onApplyTemplate: (template: OutreachTemplate) => void
  onDeleteTemplate: (template: OutreachTemplate) => void
}

export function CompanyOutreachDraftPanel({
  company,
  contacts,
  drafts,
  selectedDraft,
  templates,
  approvals,
  channel,
  contactId,
  instruction,
  templateName,
  busy,
  children,
  onChannelChange,
  onContactChange,
  onInstructionChange,
  onTemplateNameChange,
  onSelectedDraftChange,
  onGenerate,
  onSelect,
  onSave,
  onCopy,
  onDelete,
  onSaveTemplate,
  onApplyTemplate,
  onDeleteTemplate,
}: Props) {
  const matchingTemplates = selectedDraft ? templates.filter(template => template.channel === selectedDraft.channel) : []

  return (
    <section className="panel mt-7" aria-label="営業文面">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2>営業文面</h2>
          <p className="muted mt-2 text-sm">
            企業分析を基に下書きを生成します。内容を確認・編集してから使用してください。
          </p>
        </div>
        <span className="badge">{drafts.length} 件</span>
      </div>

      <div className="detail-grid mt-4">
        <div>
          <label className="field">
            連絡経路
            <select
              value={channel}
              onChange={event => onChannelChange(event.target.value as OutreachDraft['channel'])}
            >
              <option value="email">メール</option>
              <option value="form">問い合わせフォーム</option>
              <option value="sns">SNS</option>
            </select>
          </label>
          <label className="field">
            宛先担当者
            <select value={contactId} onChange={event => onContactChange(event.target.value)}>
              <option value="">担当者指定なし</option>
              {contacts
                .filter(contact => contact.verification_status !== 'invalid')
                .map(contact => (
                  <option value={contact.id} key={contact.id}>
                    {contact.name}
                    {contact.title ? `（${contact.title}）` : ''}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <label className="field">
          追加指示
          <textarea
            rows={4}
            maxLength={1000}
            value={instruction}
            onChange={event => onInstructionChange(event.target.value)}
            placeholder="例：初回連絡なので短く、無料相談を案内"
          />
        </label>
      </div>

      <div className="actions">
        <button
          disabled={busy || company.do_not_contact || company.ai_status !== 'completed'}
          onClick={onGenerate}
        >
          {busy ? '生成中…' : '文面を生成'}
        </button>
      </div>

      {company.do_not_contact && <p className="error">連絡禁止の企業には文面を生成できません。</p>}
      {company.ai_status !== 'completed' && (
        <p className="muted text-sm">文面生成にはAI企業分析の完了が必要です。</p>
      )}

      {drafts.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-5">
          {drafts.map(draft => (
            <button
              className={selectedDraft?.id === draft.id ? '' : 'secondary'}
              key={draft.id}
              onClick={() => onSelect(draft)}
            >
              {draft.channel === 'email' ? 'メール' : draft.channel === 'form' ? 'フォーム' : 'SNS'}・
              {new Date(draft.created_at).toLocaleString('ja-JP')}
            </button>
          ))}
        </div>
      )}

      {selectedDraft && (
        <div className="mt-5">
          {selectedDraft.channel === 'email' && (
            <label className="field">
              件名
              <input
                maxLength={300}
                value={selectedDraft.subject}
                onChange={event =>
                  onSelectedDraftChange({ ...selectedDraft, subject: event.target.value })
                }
              />
            </label>
          )}
          <label className="field">
            本文
            <textarea
              rows={12}
              maxLength={10000}
              value={selectedDraft.body}
              onChange={event => onSelectedDraftChange({ ...selectedDraft, body: event.target.value })}
            />
          </label>
          <p className="muted text-sm">
            生成：{selectedDraft.ai_provider} / {selectedDraft.ai_model}
          </p>
          <div className="actions">
            <button disabled={busy || !selectedDraft.body.trim()} onClick={onSave}>
              編集内容を保存
            </button>
            <button className="secondary" onClick={onCopy}>
              コピー
            </button>
            <button className="danger" disabled={busy} onClick={onDelete}>
              削除
            </button>
          </div>

          <div className="mt-5">
            <h3>文面テンプレート</h3>
            <div className="actions">
              <input
                aria-label="テンプレート名"
                maxLength={200}
                value={templateName}
                onChange={event => onTemplateNameChange(event.target.value)}
                placeholder="例：初回メール"
              />
              <button disabled={busy || !templateName.trim()} onClick={onSaveTemplate}>
                現在の文面を保存
              </button>
            </div>
            {matchingTemplates.length === 0 ? (
              <p className="muted text-sm">この連絡経路のテンプレートはありません。</p>
            ) : (
              <div className="grid gap-2 mt-3">
                {matchingTemplates.map(template => (
                  <article className="job-row" key={template.id}>
                    <div>
                      <strong>{template.name}</strong>
                      <p className="muted text-xs">
                        {template.subject || '件名なし'} / {template.body.slice(0, 80)}
                      </p>
                    </div>
                    <div className="actions">
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => onApplyTemplate(template)}
                      >
                        適用
                      </button>
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() => onDeleteTemplate(template)}
                      >
                        削除
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>

          <div className="mt-5">
            <h3>承認履歴</h3>
            {approvals.length === 0 ? (
              <p className="muted text-sm">まだ承認履歴はありません。</p>
            ) : (
              approvals.map(approval => (
                <article className="job-row" key={approval.id}>
                  <div>
                    <strong>
                      {approval.approval_type === 'email'
                        ? 'メール送信承認'
                        : approval.approval_type === 'form_direct'
                          ? 'フォーム送信承認'
                          : 'Codex支援フォーム承認'}
                    </strong>
                    <p className="muted text-xs">
                      {approval.subject || '件名なし'} / {approval.body.slice(0, 120)}
                    </p>
                  </div>
                  <time className="muted text-xs">
                    {approval.delivered_at
                      ? `送信済み ${new Date(approval.delivered_at).toLocaleString('ja-JP')}`
                      : `承認 ${new Date(approval.approved_at).toLocaleString('ja-JP')}`}
                  </time>
                </article>
              ))
            )}
          </div>

          {children}
        </div>
      )}
    </section>
  )
}
