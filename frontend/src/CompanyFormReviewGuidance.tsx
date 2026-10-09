import type { FormProfile } from './types'

export function CompanyFormReviewGuidance({ profile }: { profile: FormProfile }) {
  const visible = profile.fields.filter(field => !['hidden', 'submit', 'button', 'reset', 'image'].includes(field.field_type))
  const required = visible.filter(field => field.required && (field.mapped_key === 'unknown' || field.confidence < 0.8))
  const optional = visible.filter(field => !field.required && field.mapped_key === 'unknown')
  return <section className="notice mt-3" aria-label="フォームの確認手順">
    <h3>このフォームで確認すること</h3>
    <ol className="mt-2 list-decimal pl-5 space-y-2">
      <li>元ページで、対象企業の窓口か・営業提案を受け付ける用途かを確認してください。<a className="text-link ml-2" href={profile.form_url} target="_blank" rel="noreferrer">元の問い合わせページを開く（別タブ）</a></li>
      {['STALE', 'ERROR', 'UNANALYZED'].includes(profile.form_status) && <li>保存情報は変更あり・解析失敗・未解析の状態です。現在のフォームと一致するか確認できていません。</li>}
      {profile.sales_contact_status === 'PROHIBITED'
        ? <li>営業禁止を検出しています。項目を修正しても送信対象にはできません。</li>
        : <li>営業禁止表記の未検出は、営業許可を確認した意味ではありません。連絡禁止・配信停止・過去送信も別途確認してください。</li>}
      {!profile.form_found && <li>取得したHTMLではフォームを確認できていません。埋め込みや表示後のフォームも未確認です。</li>}
      {profile.captcha_type !== 'CAPTCHA_NONE' && <li>CAPTCHAは人による操作・確認が必要です。項目の修正やCodex支援で自動送信可能にはなりません。</li>}
      {!profile.delivery_supported && <li>送信経路が未対応または未検証です。入力欄を確認できても、送信できるとは限りません。</li>}
      {profile.confirmation_page === true && <li>確認画面があります。次画面への遷移は別途確認が必要です。この画面からは進めません。</li>}
      {profile.confirmation_page === null && <li>確認画面・送信ボタンの動作は未確認です。</li>}
      {required.length > 0 && <li>入力先が未確定の必須項目：<ul className="mt-1 list-disc pl-5">{required.map(field => <li key={field.id}><a className="text-link" href={`#form-field-${field.id}`}>{field.label || field.name || '名称不明'}を確認する</a></li>)}</ul></li>}
      {optional.length > 0 && <li>用途が不明な任意項目もあります。名前だけから入力値や空欄が安全と推測せず、元ページで確認してください。</li>}
    </ol>
    <p className="text-sm mt-3">用途の表示は解析による推定です。確認した項目は下の既存「修正を保存」で記録できますが、フォーム確認や優先フォームの選択はHuman送信承認ではありません。</p>
  </section>
}
