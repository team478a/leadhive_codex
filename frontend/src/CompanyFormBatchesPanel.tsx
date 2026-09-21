import type { FormDeliveryBatch, OutreachTemplate } from './types'

type Props = {
  selectedCount: number
  templates: OutreachTemplate[]
  templateId: string
  batches: FormDeliveryBatch[]
  confirmed: boolean
  busy: boolean
  onTemplateChange: (value: string) => void
  onConfirmedChange: (value: boolean) => void
  onCreate: () => void
  onExecute: (batch: FormDeliveryBatch) => void
  onCancel: (batch: FormDeliveryBatch) => void
  onRetry: (itemId: string) => void
}

const itemStatusNames: Record<string, string> = {
  queued: '送信待ち',
  submitted: '送信済み',
  failed: '失敗',
  manual_required: 'Codex支援',
  skipped: '対象外',
}

export function CompanyFormBatchesPanel({
  selectedCount,
  templates,
  templateId,
  batches,
  confirmed,
  busy,
  onTemplateChange,
  onConfirmedChange,
  onCreate,
  onExecute,
  onCancel,
  onRetry,
}: Props) {
  return (
    <section className="panel mt-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2>一括フォームDM</h2>
          <p className="muted mt-2 text-sm">
            一覧で選択した企業へ同じフォーム文面をキュー化します。通常フォームだけを承認後に最大20社ずつ送信し、入力項目が不足するフォームはCodex支援対象として残します。
          </p>
        </div>
        <span className="badge">選択 {selectedCount} 社</span>
      </div>

      <div className="detail-grid mt-4">
        <label className="field">
          フォーム文面テンプレート
          <select value={templateId} onChange={event => onTemplateChange(event.target.value)}>
            <option value="">選択してください</option>
            {templates
              .filter(item => item.channel === 'form')
              .map(item => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
        </label>
      </div>

      <div className="actions">
        <button disabled={busy || !templateId || selectedCount === 0} onClick={onCreate}>
          選択企業で一括DMを作成
        </button>
      </div>

      {batches.map(batch => {
        const statusCounts = batch.items.reduce<Record<string, number>>(
          (result, item) => ({
            ...result,
            [item.status]: (result[item.status] ?? 0) + 1,
          }),
          {},
        )
        const batchStatusName =
          batch.status === 'ready'
            ? '送信待ち'
            : batch.status === 'running'
              ? '実行中'
              : batch.status === 'completed'
                ? '完了'
                : '中止'

        return (
          <article className="job-row block mt-4" key={batch.id}>
            <div className="flex flex-wrap justify-between gap-3">
              <div>
                <strong>一括フォームDM</strong>
                <p className="muted text-sm">
                  {new Date(batch.created_at).toLocaleString('ja-JP')} / {batch.items.length}社
                </p>
              </div>
              <span className="badge">{batchStatusName}</span>
            </div>

            <div className="job-stats mt-3">
              {Object.entries(statusCounts).map(([status, count]) => (
                <span key={status}>
                  {itemStatusNames[status] ?? status} {count}
                </span>
              ))}
            </div>

            {batch.status === 'ready' && (
              <>
                <label className="checkbox-row mt-3">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={event => onConfirmedChange(event.target.checked)}
                  />
                  対象企業、文面、送信済み・連絡禁止の除外を確認し、通常フォームへの一括送信を承認します。
                </label>
                <div className="actions">
                  <button disabled={busy || !confirmed} onClick={() => onExecute(batch)}>
                    最大20社を順次送信
                  </button>
                  <button className="danger" disabled={busy} onClick={() => onCancel(batch)}>
                    中止
                  </button>
                </div>
              </>
            )}

            {batch.items
              .filter(item => item.status === 'manual_required')
              .map(item => (
                <p className="muted text-sm mt-2" key={item.id}>
                  {item.company_name}：Codex支援が必要です（{item.reason}）
                </p>
              ))}

            {batch.items
              .filter(item => item.status === 'failed')
              .map(item => (
                <div className="actions mt-2" key={item.id}>
                  <span className="error text-sm">
                    {item.company_name}：{item.reason || '送信に失敗しました。'}
                  </span>
                  <button className="secondary" disabled={busy} onClick={() => onRetry(item.id)}>
                    再試行待ちに戻す
                  </button>
                </div>
              ))}
          </article>
        )
      })}

      {batches.length === 0 && <p className="muted mt-4">一括フォームDMはまだありません。</p>}
    </section>
  )
}
