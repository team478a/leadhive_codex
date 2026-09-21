import type { ApplicationService, ApplicationSettings, ServiceConnectionTest } from './types'

type SettingSource = 'database' | 'environment' | 'unset'

const services: Array<{
  id: ApplicationService
  name: string
  purpose: string
  sourceKey: keyof Pick<ApplicationSettings, 'openai_api_key_source' | 'serper_api_key_source' | 'google_places_api_key_source' | 'gbizinfo_api_token_source'>
  steps: string[]
  notes: string
  links: Array<{ label: string; href: string }>
}> = [
  {
    id: 'serper', name: 'Serper API', purpose: 'Google検索結果から営業候補を集める', sourceKey: 'serper_api_key_source',
    steps: [
      'Serper公式サイトで「Sign up」を選び、Googleアカウントまたはメールアドレスで登録します。',
      'ログイン後のDashboardでAPI Keyを表示し、コピーします。',
      'この画面の「Serper APIキー」へ貼り付け、「全体設定を保存」を押します。',
      '企業収集画面で収集元を「Serper」にすると利用できます。',
    ],
    notes: '公式サイトでは初回2,500クエリを無料で試せます。継続利用前にDashboardで残量と料金を確認してください。',
    links: [{ label: 'Serper公式サイトを開く', href: 'https://serper.dev/' }],
  },
  {
    id: 'google_places', name: 'Google Places API（New）', purpose: '地図上の店舗・事業所情報を検索する', sourceKey: 'google_places_api_key_source',
    steps: [
      'Google Cloud Consoleでプロジェクトを作成または選択します。',
      'プロジェクトへ請求先アカウントを設定します。',
      'APIライブラリで「Places API（New）」を有効にします。',
      '「APIとサービス → 認証情報」でAPIキーを作成します。',
      'APIの制限を「Places API（New）」に設定し、本番ではサーバーIPも制限します。',
      'この画面の「Google Places APIキー」へ貼り付けて保存します。',
    ],
    notes: 'Google Maps Platformは従量課金です。予算アラートと利用上限を設定してから本番利用してください。',
    links: [{ label: 'Google公式の設定手順を開く', href: 'https://developers.google.com/maps/documentation/places/web-service/get-api-key' }],
  },
  {
    id: 'openai', name: 'OpenAI API', purpose: '企業のAI判定と営業文面の生成に使う', sourceKey: 'openai_api_key_source',
    steps: [
      'OpenAI Platformへログインし、利用するProjectを選択します。',
      'API Keys画面で「Create new secret key」を選びます。',
      '表示されたキーをその場でコピーします。キーは後から再表示できません。',
      '必要に応じてAPI Platform側で支払い方法や利用上限を設定します。',
      'この画面の「OpenAI APIキー」へ貼り付け、利用モデルを確認して保存します。',
    ],
    notes: 'ChatGPTの契約とAPI Platformの課金は別です。API利用料は使用したモデルと量に応じて発生します。',
    links: [
      { label: 'OpenAI APIキー画面を開く', href: 'https://platform.openai.com/api-keys' },
      { label: 'OpenAI公式クイックスタート', href: 'https://platform.openai.com/docs/quickstart/make-your-first-api-request' },
    ],
  },
  {
    id: 'gbizinfo', name: 'gBizINFO API', purpose: '法人番号を持つ国内企業を検索する', sourceKey: 'gbizinfo_api_token_source',
    steps: [
      'gBizINFOの公式案内を確認し、Web API利用申請を行います。',
      '申請時に利用目的、利用予定、連絡先などを入力します。',
      '発行されたAPIトークンをこの画面の「gBizINFO APIトークン」へ貼り付けます。',
      'API URLは通常、画面に表示されている初期値のまま保存します。',
    ],
    notes: '実運用では動作確認用トークンを使わず、必ず利用申請で発行されたトークンを設定してください。',
    links: [{ label: 'gBizINFO公式の利用案内を開く', href: 'https://info.gbiz.go.jp/about/document/HowTo.pdf' }],
  },
]

function sourceLabel(source: SettingSource | undefined) {
  return source && source !== 'unset' ? '設定済み' : '未設定'
}

export function ServiceSetupGuide({ settings, testingService, testResults, onTest }: {
  settings: ApplicationSettings | null
  testingService: ApplicationService | null
  testResults: Partial<Record<ApplicationService, ServiceConnectionTest>>
  onTest: (service: ApplicationService, label: string) => void
}) {
  return <section className="api-setup-guide" aria-label="APIキー取得ガイド">
    <div className="api-guide-heading"><div><h3>APIキーの取得手順</h3>
      <p className="muted mt-1 text-sm">使いたい収集方法だけ設定すれば開始できます。Serperが最も簡単です。</p></div>
      <span className="badge">管理者向け</span></div>
    <div className="api-guide-list">{services.map((service, index) => {
      const source = settings?.[service.sourceKey] as SettingSource | undefined
      const configured = source !== undefined && source !== 'unset'
      return <details id={`setup-${service.id}`} className="api-guide-item" open={index === 0} key={service.id}>
        <summary><span><strong>{service.name}</strong><small>{service.purpose}</small></span>
          <span className={configured ? 'api-status configured' : 'api-status'}>{sourceLabel(source)}</span></summary>
        <div className="api-guide-content"><ol>{service.steps.map(step => <li key={step}>{step}</li>)}</ol>
          <p className="api-guide-note"><strong>確認：</strong>{service.notes}</p>
          <div className="api-guide-links">{service.links.map(link => <a href={link.href} target="_blank" rel="noreferrer" key={link.href}>{link.label} ↗</a>)}</div>
          <div className="api-test-row"><button type="button" className="secondary" disabled={!configured || testingService !== null}
            onClick={() => onTest(service.id, service.name)}>{testingService === service.id ? '接続確認中…' : `${service.name}をテスト`}</button>
            {!configured && <span className="muted text-xs">先にAPIキーを保存してください。</span>}</div>
          {testResults[service.id] && <p className={testResults[service.id]?.ok ? 'api-test-result success' : 'api-test-result failure'} role="status">
            {testResults[service.id]?.message}<small>{new Date(testResults[service.id]!.checked_at).toLocaleString('ja-JP')}</small></p>}
        </div>
      </details>
    })}</div>
    <p className="api-security-note">APIキーはGitHub、チャット、メールへ貼り付けず、この設定画面へ直接入力してください。保存後は暗号化され、画面には再表示されません。</p>
  </section>
}
