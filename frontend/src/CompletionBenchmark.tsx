import { benchmarkStages } from './completionBenchmarkTypes'
import type { BenchmarkRow, BenchmarkMeta, BenchmarkEvidence } from './completionBenchmarkTypes'
const number = (v: unknown): string => typeof v === 'number' && Number.isFinite(v) ? String(v) : 'unknown / null'
const names = ['発見', '対象条件一致', 'Identity確認', '公式サイト確認', '窓口候補発見', '連絡候補許可', '送信準備READY', 'DM下書き準備', 'DM READY']

export function CompletionBenchmark({ rows, discovered, complete, metadata, onReason }: { rows: BenchmarkRow[]; discovered: number; complete: boolean; metadata: BenchmarkMeta; onReason: (code: string) => void }) {
  const evidence = rows.map(row => row.benchmark!)
  const reviewEvidence = rows.filter(row => row.status !== 'BLOCKED').map(row => row.benchmark!)
  const counts = benchmarkStages.map(code => ({ raw: evidence.filter(b => b.raw_stages[code] === true).length, unknown: evidence.filter(b => b.raw_stages[code] === null).length, passed: evidence.filter(b => b.passed_stages[code] === true).length, passedUnknown: evidence.filter(b => b.passed_stages[code] === null).length }))
  const reasons = [...new Set(evidence.flatMap(b => b.reason_codes))].map(code => ({ code, affected: evidence.filter(b => b.reason_codes.includes(code)).length, sole: evidence.filter(b => b.sole_blockers.includes(code)).length, unlock: evidence.filter(b => b.potential_unlock.includes(code)).length })).sort((a, b) => b.unlock - a.unlock || b.affected - a.affected || a.code.localeCompare(b.code))
  const destinations = new Map<string, { type: string; leads: number; shared: boolean }>()
  for (const row of rows) for (const d of row.destinations) { const old = destinations.get(d.key); destinations.set(d.key, { type: d.type, leads: (old?.leads ?? 0) + 1, shared: !!old?.shared || d.shared }) }
  const baseline = metadata.baseline
  const compare = [
    ['DISCOVERED', baseline?.discovered, discovered], ['登録URL（確認とは別）', baseline?.website_url_present, null],
    ['公式サイト確認', baseline?.official_site_confirmed_automatic, counts[3].raw],
    ['窓口候補Lead', baseline?.destination_found, counts[4].raw], ['Unique Destination', baseline?.unique_destinations, destinations.size],
    ['共有Destination', baseline?.shared_destinations, [...destinations.values()].filter(d => d.shared || d.leads > 1).length],
    ['READY', (baseline?.statuses as Record<string, number> | undefined)?.READY, counts[6].raw], ['DM READY', baseline?.dm_ready, counts[8].raw],
  ]
  return <section className="mt-5" aria-label="Lead Completion Benchmark">
    <h4>Lead Completion Benchmark</h4>
    <p>{complete ? '全件観察済み' : '部分集計・変換率は未判定'}：固定分母 {discovered}件 / 観察 {rows.length}件。未知を成功・0件とは扱いません。</p>
    <p className="muted">確認済みは有効なHuman確認証跡があるものだけです。各段階の観察数と全前段階を通過した件数を分けます。登録URLだけでは公式サイト確認に含めません。</p>
    <div className="overflow-x-auto"><table><thead><tr><th>Stage</th><th>観察数</th><th>不明</th><th>前段階も通過</th><th>前段階からの率</th><th>固定分母からの率</th></tr></thead><tbody>{counts.map((n, i) => {
      const previous = counts[i - 1]
      const transition = complete && previous && previous.passed > 0 && n.passedUnknown === 0 && previous.passedUnknown === 0 ? `${(100 * n.passed / previous.passed).toFixed(1)}%` : 'unknown / null'
      return <tr key={benchmarkStages[i]}><td>{benchmarkStages[i]}・{names[i]}</td><td>{n.raw}</td><td>{n.unknown}</td><td>{n.passed}（不明 {n.passedUnknown}）</td><td>{transition}</td><td>{complete && discovered > 0 && n.unknown === 0 ? `${(100 * n.raw / discovered).toFixed(1)}%` : 'unknown / null'}</td></tr>
    })}</tbody></table></div>
    <p>窓口候補：{counts[4].raw} Lead / 延べ {rows.reduce((n, r) => n + r.destinations.length, 0)} / Unique {destinations.size} / Shared {[...destinations.values()].filter(d => d.shared || d.leads > 1).length} / email {[...destinations.values()].filter(d => d.type === 'email').length} / form {[...destinations.values()].filter(d => d.type === 'form').length}。店舗数を独立送信先数にしません。</p>
    <ul>{['match', 'identity', 'official_site', 'permission', 'preparation'].map(field => { const values = evidence.map(b => String(b[field as keyof BenchmarkEvidence])); return <li key={field}>{field}: {[...new Set(values)].map(v => `${v} ${values.filter(s => s === v).length}件`).join(' / ')}</li> })}</ul>
    <h4>Before / Current</h4><p className="muted">Baselineは元の100店舗のhashが一致する場合のみ表示します。旧判定・過去の手動登録を含むため増減を改善成果として扱いません。未定義はunknown、差は算出しません。</p>
    <div className="overflow-x-auto"><table><thead><tr><th>KPI</th><th>Baseline</th><th>Current{!complete && '（部分）'}</th><th>差</th></tr></thead><tbody>{compare.map(([label, before, current]) => <tr key={String(label)}><td>{String(label)}</td><td>{number(before)}</td><td>{number(current)}</td><td>—（定義・範囲を要確認）</td></tr>)}</tbody></table></div>
    <h4>現在DM READYを止めている主な理由</h4>
    <p className="muted">affectedは理由を持つLead、soleは一つの窓口経路で単独の停止条件、potentialはその記録済み条件だけを解消できる場合の次の準備段階への候補です。上流の不明・未準備を解決した数や送信許可ではなく、実際の増加を予測しません。Hard Block・CAPTCHA・共有・不明はunlockに含めません。</p>
    <div className="overflow-x-auto"><table><thead><tr><th>Reason</th><th>affected</th><th>sole blocker</th><th>potential unlock</th></tr></thead><tbody>{reasons.map(r => <tr key={r.code}><td><button className="secondary" onClick={() => onReason(r.code)}>{r.code}</button></td><td>{r.affected}</td><td>{r.sole}</td><td>{r.unlock}</td></tr>)}</tbody></table></div>
    <p>Human作業分類（BLOCKEDを除外・重複あり）：公式サイト {reviewEvidence.filter(b => b.reason_codes.includes('OFFICIAL_SITE_NOT_FOUND')).length} / Identity {reviewEvidence.filter(b => b.reason_codes.includes('IDENTITY_UNCERTAIN')).length} / 用途 {reviewEvidence.filter(b => b.reason_codes.includes('DESTINATION_PURPOSE_UNCERTAIN')).length} / 共有 {reviewEvidence.filter(b => b.reason_codes.includes('SHARED_DESTINATION')).length} / Form {reviewEvidence.filter(b => b.reason_codes.some(c => c.startsWith('FORM_') || ['CAPTCHA', 'REQUIRED_FIELD_UNKNOWN'].includes(c))).length} / DM根拠 {reviewEvidence.filter(b => b.reason_codes.some(c => c.startsWith('DM_'))).length}</p>
    <p>費用・時間：検索 {number(metadata.cost.search_calls)} / Places {number(metadata.cost.places_calls)} / AI {number(metadata.cost.ai_calls)} / input tokens {number(metadata.cost.input_tokens)} / output tokens {number(metadata.cost.output_tokens)} / 推定API費用 {number(metadata.cost.estimated_cost)} / Cost per DM READY unknown / null / Human review seconds {number(metadata.cost.human_review_seconds)}</p>
    <p className="muted">作業時間は既存review ledgerを再利用します。分類別の過去作業時間は未記録です。利用ledgerはProject内のcohort作成後の部分記録で、全処理費用とは異なります。ROBOTS / JS・確認画面の内訳 / SENDERは計測証跡不足でnull。集計による承認・送信・外部アクセスはありません。</p>
  </section>
}
