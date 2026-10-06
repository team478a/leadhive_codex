import { percent, type RawReport, type Stability } from './rawBenchmarkTypes'

function Values({ value }: { value: Stability | null }) {
  return value ? <p>Union {value.union} / Intersection {value.intersection ?? 'null'} / Intersection Rate {percent(value.intersection_rate)} / Repeat Discovery Rate {percent(value.repeat_discovery_rate)} / Single-run Rate {percent(value.single_run_rate)}</p> : <p>未測定 / null</p>
}

export function RawRunStability({ report }: { report: RawReport }) {
  return <section aria-label="Raw Run Stability" className="panel mt-5">
    <h3>Run Stability / Query別比較</h3>
    <p>Raw Hit {report.found} / Raw観測のUnique Candidate {report.unique_candidates}。同じ観測のfingerprintは店舗Identityの確定ではありません。Human判定を自動転記しません。</p>
    <p>失敗・中断・commit不明・条件差のあるRunは比較不可。1 Runだけの共通率・反復率はnullです。Human Entityの比較は全Hitの判定と照合が完了するまでnullです。</p>
    {report.query_groups.map(q => <article key={`${q.source}:${q.keyword}`} className="mt-3 break-all">
      <strong>{q.source} / {q.keyword} / Runs {q.runs}</strong>
      <p>Found {q.found} / Unique Candidate {q.unique_candidates} / Unique Correct {q.unique_correct} / Strict {percent(q.strict_precision)} / Marginal Gain {q.marginal_gain ?? 'null'}</p>
      <p>Raw観測の安定性（実在・対象業種の証明ではありません）</p><Values value={q.raw_stability} />
      <p>Human Entityの安定性</p><Values value={q.human_entity_stability} />
    </article>)}
    <p>Human確認時間（修正履歴を含む累計）: Raw {report.raw_review_seconds ?? 'null'}秒 / Pair {report.pair_review_seconds ?? 'null'}秒 / 合計 {report.human_review_seconds ?? 'null'}秒</p>
    <p>Human Pair Label: SAME {report.pair_labels.SAME} / DIFFERENT {report.pair_labels.DIFFERENT} / UNSURE {report.pair_labels.UNSURE}</p>
  </section>
}
