import { percent, type RawReport } from './rawBenchmarkTypes'

const rate = (value: number | null) => value === null ? '未測定' : percent(value)

export function RawReviewProgress({ report, loadedCount }: { report: RawReport; loadedCount: number }) {
  return <section aria-label="一次収集の確認進捗" className="panel mt-5">
    <h2>一次収集の確認進捗</h2>
    <p>取得結果 {report.found}件 ／ 人が確認 {report.reviewed}件 ／ 未確認 {report.unreviewed}件</p>
    <p>対象として正しい {report.correct}件 ／ Human照合IDによる正しい対象 {report.unique_correct}件</p>
    <p>正解率（判断不能を含む）：{rate(report.strict_precision)}。判断不能を除く正解率：{rate(report.resolved_precision)}。</p>
    <p>重複率：{rate(report.duplicate_rate)} ／ 判断不能率：{rate(report.uncertain_rate)}</p>
    <p>確認作業時間：{report.human_review_seconds === null ? '未測定' : `${report.human_review_seconds}秒`}</p>
    <p className="muted">各検索回の取得結果が分母です。代表候補の確認だけでは全件確認になりません。未確認やシステム除外を人の正解・不正解へ自動変換しません。</p>
    {report.unreviewed > 0 && <p>まだ一部の確認結果です。現時点の正解率を収集全体の性能と確定しないでください。</p>}
    {loadedCount !== report.found && <p role="status">集計と表示件数が一致していません。全件確認と判断せず、最新の結果を読み直してください。</p>}
  </section>
}
