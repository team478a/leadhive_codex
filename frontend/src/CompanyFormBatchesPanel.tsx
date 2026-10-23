import type { FormDeliveryBatch } from './types'

type Props = {
  batches: FormDeliveryBatch[]
  busy: boolean
  onCancel: (batch: FormDeliveryBatch) => void
}

const itemStatusNames: Record<string, string> = {
  queued: '送信待ち',
  submitted: '送信済み',
  failed: '失敗',
  unknown: '結果不明・再送禁止',
  manual_required: 'Codex支援',
  skipped: '対象外',
}

export function CompanyFormBatchesPanel({
  batches,
  busy,
  onCancel,
}: Props) {
  return (
    <section className="panel mt-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2>過去の一括フォームDM</h2>
          <p className="muted mt-2 text-sm">
            旧一括フォームDMとForm Codex Queueの新規受付は終了しました。過去の結果と二重送信防止記録は保持しています。
          </p>
        </div>
        <span className="badge">履歴 {batches.length} 件</span>
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

            {['ready', 'running'].includes(batch.status) && <div className="actions">
              <button className="danger" disabled={busy} onClick={() => onCancel(batch)}>未完了分を中止</button>
            </div>}

            {batch.items.filter(item => item.status === 'unknown').map(item => (
              <p className="error text-sm mt-2" role="alert" key={item.id}>
                {item.company_name}：結果不明・再送禁止。送信やCodex作業をせず、受付結果を確認してください。
              </p>
            ))}
            {batch.items
              .filter(item => item.status === 'manual_required')
              .map(item => (
                <p className="muted text-sm mt-2" key={item.id}>
                  {item.company_name}：Codex支援が必要です（{item.reason}）
                </p>
              ))}

            {batch.items.filter(item => item.status === 'failed').map(item => <p className="error text-sm mt-2" key={item.id}>
              {item.company_name}：{item.reason || '送信に失敗しました。'}
            </p>)}
          </article>
        )
      })}

      {batches.length === 0 && <p className="muted mt-4">一括フォームDMはまだありません。</p>}
    </section>
  )
}
