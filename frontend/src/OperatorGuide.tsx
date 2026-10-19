import { useState } from 'react'
import type { Project, ProjectMember } from './types'

export type OperatorDestination = 'collection' | 'companies' | 'approvals' | 'targets' | 'analysis'

export function OperatorGuide({ projects, projectRoles, onNavigate, onCreateProject }: {
  projects: Project[]
  projectRoles: Record<string, ProjectMember['role']>
  onNavigate: (destination: OperatorDestination, projectId: string) => void
  onCreateProject: () => void
}) {
  const [projectId, setProjectId] = useState(projects.length === 1 ? projects[0].id : '')
  const selected = projects.find(project => project.id === projectId)
  const canEdit = !!selected && ['owner', 'editor'].includes(projectRoles[projectId])
  return <section aria-label="担当者の作業ガイド">
    <section className="panel mb-5">
      <h2>今日の作業を始める</h2>
      <p className="mt-2">収集担当は「リスト収集」、営業担当は「営業作業」のメニューを使います。収集したリストは同じプロジェクトで引き継げます。</p>
      <p className="muted mt-2">対象のプロジェクトを選び、必要な作業へ進みます。途中で止まった企業は理由を残し、次の企業へ進んでください。</p>
      {projects.length === 0 ? <button className="mt-4" onClick={onCreateProject}>プロジェクトを作る</button> : <>
        <label className="field mt-4">作業するプロジェクト<select value={selected ? projectId : ''} onChange={event => setProjectId(event.target.value)}>
          <option value="">選択してください</option>{projects.map(project => <option value={project.id} key={project.id}>{project.project_name}</option>)}
        </select></label>
        {selected && <p className="muted">対象地域：{selected.region} / {canEdit ? '結果の記録・編集ができます' : '閲覧のみです。結果の記録は所有者・編集者へ依頼してください'}</p>}
      </>}
    </section>
    <div className="grid gap-5 md:grid-cols-2">
      <article className="panel"><h2>収集作業：ターゲット設定 → 収集開始</h2><p className="mt-3">「収集ターゲット設定」で対象・地域を保存し、次の画面で目標件数を指定して収集します。収集だけ済ませておき、解析は別の日にまとめて実行できます。</p><p className="muted mt-2">検索にはAPI設定が必要です。URL・CSV取込も利用できます。検索回数上限は費用に影響します。</p><button className="mt-4" onClick={() => onNavigate('targets', projectId)}>収集ターゲット設定へ</button></article>
      <article className="panel"><h2>収集後のリスト解析</h2><p className="mt-3">サイト解析で公式サイトとフォームを順に確認し、完了後に「AI判定を開始」します。処理はバックグラウンドで進み、収集・送信は開始しません。</p><button className="mt-4" disabled={!canEdit} onClick={() => onNavigate('analysis', projectId)}>リスト解析へ</button></article>
      <article className="panel"><h2>2. 企業と問い合わせ先を確認</h2><p className="mt-3">企業一覧でプロジェクトを確認し、「詳細」を開きます。問い合わせ先がない場合は、既存のWeb解析・フォーム探索を実行します。</p><p className="muted mt-2">営業禁止を見つけたら「営業NGリストへ移す」。その企業には入力・送信しません。</p><button className="mt-4" disabled={!selected} onClick={() => onNavigate('companies', projectId)}>企業一覧へ</button></article>
      <article className="panel"><h2>3. フォームへ入力する（未送信）</h2><p className="mt-3">企業詳細の「実フォームへ入力する（送信しない）」を使います。PC入力は専用パッケージを使えるWindows PCで実行します。スマートフォンでは候補・結果の確認ができます。</p><p className="muted mt-2">任意項目は空欄で構いません。選択項目で停止する場合は理由を記録します。必須情報を推測せず、CAPTCHA・不明な同意は停止してください。確認・送信ボタンは押しません。</p><details className="mt-3"><summary>PCでの操作手順</summary><ol className="mt-2 list-decimal pl-5"><li>フォームと入力内容を確認し、入力専用タスクを保存。</li><li>専用パッケージの Start-Live-Input.cmd を起動し、保存したタスクを選択。</li><li>接続先と入力専用の確認を行い、処理終了まで待つ。</li><li>自動で戻す設定を選んだ場合はLeadHiveで結果を取得。未設定・転送失敗なら、画面の案内に従い結果JSONを取り込む。</li></ol><p className="mt-2">入力機能が無効なら管理者へ連絡してください。送信設定を有効にする必要はありません。</p></details></article>
      <article className="panel"><h2>4. 結果を残して次へ</h2><p className="mt-3">手動で試した場合は「入力を試した結果を残す」で結果を選び、「未送信の入力結果を記録」を押します。失敗時は止まった項目・理由を短く残してください。</p><p className="muted mt-2">PCの結果が既に保存されていれば、同じ結果を手動で重ねて登録する必要はありません。入力成功は送信成功や承認済みを意味しません。</p><button className="mt-4" disabled={!selected} onClick={() => onNavigate('companies', projectId)}>候補と結果を見る</button></article>
    </div>
    <section className="panel mt-5"><h2>止まったときの対応</h2><dl className="mt-3 grid gap-3">
      <div><dt><strong>営業禁止・連絡禁止</strong></dt><dd>営業NGとして理由と根拠を保存。入力・送信しない。</dd></div>
      <div><dt><strong>必須項目・選択肢が分からない</strong></dt><dd>推測で埋めず、入力できない理由を記録して次へ。</dd></div>
      <div><dt><strong>ページエラー・動的画面・iframe</strong></dt><dd>URLと停止した箇所を記録。繰り返し試さず次へ。</dd></div>
      <div><dt><strong>送信されたか分からない（UNKNOWN）</strong></dt><dd>再送せず管理者へ連絡。未送信の入力結果とは分けて扱う。</dd></div>
    </dl><p className="muted mt-3">メモやスクリーンショットにAPIキー・パスワード・入力した個人情報を残さないでください。記録は改善の材料です。記録だけで判定基準が自動学習・変更されるわけではありません。</p></section>
    <details className="panel mt-5"><summary>送信を始めるときだけ：Human承認</summary><p className="mt-3">対象企業・送信先・文章を人が確認して承認します。入力試行では承認を作る必要はありません。承認キューでも対象のプロジェクトを選んでください。承認は送信完了ではなく、外部送信が停止中なら送信できません。</p><button className="secondary mt-3" disabled={!selected} onClick={() => onNavigate('approvals', projectId)}>承認キューを見る</button></details>
  </section>
}

export function OperatorListHint() {
  return <details className="panel mb-4"><summary>担当者向け：この画面での作業順</summary><p className="mt-3">プロジェクトを選択 → 企業の「詳細」 → 問い合わせ先・営業NG確認 → 入力試行 → 結果記録 → 詳細を閉じて次の企業。</p><p className="muted mt-2">営業NGは「営業NGリストへ移す」。任意項目は空欄で構いません。必須項目不明・CAPTCHAは停止理由を記録してください。入力成功を送信済みとして記録しないでください。</p></details>
}
