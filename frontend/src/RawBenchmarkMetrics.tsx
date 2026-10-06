import { outcomeLabels, percent, type RawReport } from './rawBenchmarkTypes'

export function RawBenchmarkMetrics({ report, onCancel }: { report: RawReport; onCancel: (id: string) => void }) {
  return <section aria-label="Raw Collection集計" className="panel mt-5">
    <h2>Raw Collection Quality — {report.phase}</h2>
    <p>Found {report.found} / Reviewed {report.reviewed} / Correct {report.correct} / 未レビュー {report.unreviewed}</p>
    <p>Strict Precision {percent(report.strict_precision)} / Resolved Precision {percent(report.resolved_precision)}</p>
    <p>Duplicate Rate {percent(report.duplicate_rate)} / Uncertain Rate {percent(report.uncertain_rate)} / Coverage {percent(report.coverage)}</p>
    <p className="muted">FoundはSourceから返却された候補の出現数です。独立店舗数とは異なります。Strictは全レビュー、ResolvedはUNCERTAINを除いたレビューが分母です。未レビューをCORRECT・UNCERTAINへ推測しません。</p>
    <p>Human照合IDによるUnique Correct {report.unique_correct} / 作業時間 {report.human_review_seconds === null ? '未測定 / null' : `${report.human_review_seconds}秒`} / 推定API費用 {report.estimated_api_cost ?? '未測定 / null'}</p>
    <h3>Error Breakdown</h3>
    <ul>{Object.entries(report.error_breakdown).map(([code, value]) => <li key={code}>{outcomeLabels[code] ?? code}: {value.count} / {percent(value.rate)}</li>)}</ul>
    <h3>Source Comparison</h3>
    {report.sources.length === 0 && <p>収集Sourceはまだありません。</p>}
    {report.sources.map(s => <article key={s.source} className="mt-3"><strong>{s.source}</strong><p>Found {s.found} / Reviewed {s.reviewed} / Correct {s.correct} / Strict {percent(s.strict_precision)} / Duplicate {percent(s.duplicate_rate)} / Unique Correct {s.unique_correct} / Unique Gain {s.unique_gain ?? '未測定 / null'}</p></article>)}
    <h3>Run Comparison / Marginal Gain</h3>
    <p className="muted">追加効果は実行順・Humanレビュー済み部分だけの値です。全件レビュー前の値をSource性能として一般化しません。AIによる正解ラベルはありません。</p>
    {report.queries.map(q => <article key={q.job_id} className="mt-3 break-all"><strong>{q.source}: {q.query} / {q.status}</strong><p>Found {q.found} / Reviewed {q.reviewed} / Correct {q.correct} / Strict {percent(q.strict_precision)} / Duplicate {percent(q.duplicate_rate)} / Unique Correct {q.unique_correct} / Marginal Gain {q.marginal_gain ?? '未測定 / null'}</p>{q.error && <p role="alert">{q.error}</p>}{q.status === 'RUNNING' && report.can_review && <button className="secondary" onClick={() => onCancel(q.job_id)}>この収集を中断</button>}</article>)}
    <h3>Field Completeness — CORRECTのRaw値だけ</h3>
    <ul>{Object.entries(report.field_completeness).map(([field, v]) => <li key={field}>{field}: {v.available} / {v.denominator} — {percent(v.rate)}</li>)}</ul>
    <p className="muted break-all">初回Query依頼 {report.base_requested_count} / Pilot上限30。反復込み依頼 {report.requested_count} / 最大90。定義commit：{report.code_commit}。後工程の補完結果は含めません。</p>
  </section>
}
