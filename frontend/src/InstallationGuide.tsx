import { useEffect, useState } from 'react'

type Download = { url?: unknown; version?: unknown; sha256?: unknown }
type Links = { cloud?: Download; local?: Download; pc_input?: Download }

function publicHttps(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' || url.username || url.password || !url.hostname.includes('.') || /^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.)/i.test(url.hostname)) return null
    return url.href
  } catch { return null }
}

function DownloadLink({ item, label }: { item?: Download; label: string }) {
  const url = publicHttps(item?.url)
  return <div className="mt-4">
    {url ? <a className="guide-link" href={url} target="_blank" rel="noopener noreferrer">{label} ↗</a> : <p className="muted">配布リンクは準備中です。管理者に配布ファイルを確認してください。</p>}
    {url && typeof item?.version === 'string' && <p className="muted mt-2">配布バージョン：{item.version}</p>}
    {url && typeof item?.sha256 === 'string' && /^[a-f0-9]{64}$/i.test(item.sha256) && <details className="mt-2"><summary>ファイル確認用 SHA-256</summary><code className="break-all">{item.sha256}</code><p className="muted">ダウンロードしたファイルのハッシュと比較してください。</p></details>}
  </div>
}

export function InstallationGuide({ onGuide }: { onGuide: () => void }) {
  const [links, setLinks] = useState<Links>({})
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setState('loading')
    fetch('/installation-links.json', { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('config unavailable')
        const value: unknown = await response.json()
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid config')
        setLinks(value as Links)
        setState('ready')
      }).catch(() => { if (!controller.signal.aborted) { setLinks({}); setState('error') } })
    return () => controller.abort()
  }, [attempt])
  const cloudUrl = publicHttps(links.cloud?.url) ?? publicHttps(window.location.origin)
  return <section aria-label="導入・ダウンロード">
    <section className="panel mb-5"><h2>利用する場所を選ぶ</h2><p className="mt-3">スマートフォンや複数のPCから使う場合はクラウド版。データを自社PCで管理する場合はローカル版を使います。どちらも企業収集・確認・DM準備の操作は共通です。</p><p className="muted mt-2">フォームへのPC入力には、本体とは別の「PC入力専用ツール」を使います。</p></section>
    {state === 'loading' && <p role="status" className="muted mb-4">配布リンクを確認しています…</p>}
    {state === 'error' && <div className="notice mb-4" role="status">配布リンクを読み込めませんでした。利用説明はこのまま確認できます。<button className="secondary ml-3" onClick={() => setAttempt(value => value + 1)}>再読み込み</button></div>}
    <div className="grid gap-5 md:grid-cols-2">
      <article className="panel"><h2>クラウド版</h2><p className="mt-3">インストール不要。管理者から案内されたURLをブラウザで開き、発行されたアカウントでログインします。</p><ol className="list-decimal pl-5 mt-3"><li>クラウド版を開いてログイン。</li><li>担当プロジェクトを選択。</li><li>企業収集・確認・入力結果の記録へ進む。</li></ol>{cloudUrl ? <a className="guide-link inline-block mt-4" href={cloudUrl} target="_blank" rel="noopener noreferrer">クラウド版を開く ↗</a> : <p className="muted mt-4">クラウドURLは管理者から受け取ってください。</p>}<p className="muted mt-3">データはクラウド側で管理します。スマートフォンでは候補と結果の確認ができます。PC入力専用ツールはWindows PCで使用します。</p></article>
      <article className="panel"><h2>ローカル版（Windows）</h2><p className="mt-3">自社PCでLeadHive本体を動かします。Windows 10/11、空き容量、初回のインターネット接続が必要です。Dockerの導入・利用条件も確認してください。</p><DownloadLink item={links.local} label="ローカル版をダウンロード" /><ol className="list-decimal pl-5 mt-4"><li>配布ZIPを取得し、OneDrive以外のフォルダへ展開。</li><li>Install-LeadHive.cmd を起動。案内に従い、必要な再起動を行う。</li><li>初期管理者のメールアドレスとパスワードを設定。</li><li>ブラウザで http://localhost:8787 を開いてログイン。</li></ol><p className="muted mt-3">初回は数分以上かかる場合があります。GitHubのソースZIPはインストールパッケージとは異なります。</p><details className="mt-3"><summary>2回目以降・更新・バックアップ</summary><ul className="list-disc pl-5 mt-2"><li>起動：Start-LeadHive.cmd</li><li>停止：Stop-LeadHive.cmd</li><li>バックアップ：Backup-LeadHive.cmd</li><li>更新：バックアップ後、Update-LeadHive.cmd</li><li>詳しい手順：Open-Manual.cmd</li></ul></details></article>
      <article className="panel"><h2>PC入力専用ツール（Windows）</h2><p className="mt-3">クラウド版で準備した入力専用タスクをPCで実行するためのツールです。LeadHive本体をインストールするパッケージとは異なります。</p><DownloadLink item={links.pc_input} label="PC入力専用ツールをダウンロード" /><ol className="list-decimal pl-5 mt-4"><li>企業詳細で問い合わせ先と文章を確認し、入力専用タスクを保存。</li><li>配布ファイルを展開し、Start-Live-Input.cmd を起動。</li><li>保存したタスクを選び、接続先と入力専用の確認を行う。</li><li>結果をLeadHiveへ戻す。転送できない場合は結果JSONを取り込む。</li></ol><p className="muted mt-3">入力機能が無効の場合は管理者に連絡してください。入力成功は承認・送信完了を意味しません。確認・最終送信ボタンは押しません。</p></article>
      <article className="panel"><h2>使い始める前に</h2><ul className="list-disc pl-5 mt-3"><li>管理者が検索APIなどを運用設定に保存します。キーやパスワードを担当者へ配布しないでください。</li><li>ローカル版でも検索・AI処理には外部通信とAPI費用が必要な場合があります。</li><li>クラウド版とローカル版のデータは自動同期されません。同じ企業へ両方から重複送信しないよう、運用先を決めてください。</li><li>スマートフォンのlocalhostはPCのLeadHiveを指しません。スマートフォン利用はクラウド版のURLを使います。</li><li>営業NGには入力・送信しません。送信には既存のHuman承認と送信設定が必要です。</li></ul><button className="secondary mt-4" onClick={onGuide}>担当者の作業ガイドへ</button></article>
    </div>
  </section>
}
