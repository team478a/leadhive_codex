export function FormAdapterPlanDetails({ plan, hash }: {
  plan: Record<string, unknown>; hash?: string | null
}) {
  return <section aria-label="管理下フォームの操作計画">
    <h3>管理下フォームの操作計画（予約のみ）</h3>
    <p>実行器は未接続です。承認・予約しても送信されません。実企業のフォームには使用できません。</p>
    <pre className="whitespace-pre-wrap break-all">{JSON.stringify(plan, null, 2)}</pre>
    <p className="break-all">計画hash: {hash}</p>
  </section>
}
