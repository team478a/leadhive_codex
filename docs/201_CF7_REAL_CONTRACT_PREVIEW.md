# CF7実サイト証拠と入力確認の契約プレビュー

## ゴール・基準

`codex/integration`、基準commit `b4304ee`。
Humanが記録した入力確認票を、保存済みの実サイト静的証拠と照合する。
宛先・版・項目型・必須性・値・DOM順序をbindした、送信不可のプレビューを生成する。
wire encoder、実サイトadapter、Approval作成、dispatch、Form POSTは今回接続しない。
実サイトCF7送信対応の完成を意味しない。

## 使い方

企業詳細のフォーム入力確認で「現在のフォームを確認」を明示操作する。
送信者・Draft・手動選択を整え、「入力内容をまとめて確認」して確認記録を作る。
記録後の「フォーム証拠と入力を照合」でプレビューまたは保留理由を表示する。
プレビューは保存済み情報だけを利用し、外部GET・承認作成・送信は行わない。
古い観測には今回の証拠がないため、再観測・入力確認が必要。
古い入力確認記録も、項目型を追加したv2確認票と一致しないため再確認が必要。

## 証拠の取得・保存

既存TargetFetcherの明示GET、SSRF・robots・サイズ制限を維持する。
隔離HTML parserはJavaScriptを実行せず、`var wpcf7 = <JSON>;`だけを読み取る。
設定は一意なliteral JSON、重複keyなし、`api.root`とnamespaceの既知構成に限定。
同一originの`/wp-json/` rootと`contact-form-7/v1`からfeedback URLを固定する。
REST linkだけでは契約証拠として十分と判断しない。

`cf7_static.contract_evidence`に次だけを保存する。

- `REAL_SITE_STATIC_HTML`、定義version、対象URL、HTML版マーカー。
- 同一originのREST root/feedback endpoint。
- 許可した6種類のCF7 hiddenメタデータ（前回送信hashは空文字必須）。
- 項目名・型・必須性・限定したcheckbox値、hiddenを含むDOM順序。
- 実行・承認資格は常にfalse。

HTML全文・script全文・任意hidden/nonce/token・入力の初期値・cookie・credentialは保存しない。
既存FormAnalysisLogのtarget_live_checkに限定証拠を保存する。
既存CF7ObservationはCONTROLLED_FIXTURE専用のまま。実サイト証拠を偽装して格納しない。
Model/Migration追加・既存migration変更なし。
隔離プロセスの出力上限は32KB、HTML上限256KB・時間上限5秒を維持。
証拠はstrict schemaで再検証し、50 controls/56 DOM namesを上限とする。

## 照合とAPI

`GET /api/form-profiles/{profile_id}/contract-preview`を追加。
Human認証と既存Project read境界、送信者情報の表示権限を再利用する。
クライアント提供payloadは受け取らない。サーバーで確認票・最新観測を再構築する。
GETはDBを書き換えず、POST同URLは405。Agent credentialは拒否。

照合条件：

- 入力確認票v2のhash一致、現在の入力と一致したRECORDED、確認者・確認時刻あり。
- 確認期限と観測期限が有効、CURRENT/SAME_STRUCTURE、観測hash一致。
- 実サイト静的証拠の型・既知hidden・フォームID/unit/version/REST route一致。
- 入力行とcontrol集合一致、型/必須性一致、必須値あり、email形式。
- checkboxは明示Human選択の現在の値と一致。未選択はpartから除外。

不足・変更・期限切れではHOLD、contract/hashはnull。
一致時はPREVIEW_ONLY。版別family `cf7-6.1.4` / `cf7-6.2`を分ける。
定義は`real-cf7-contract-preview-v1`。Project/Company/Profile/Draft、入力hash、
source hash、構造fingerprint、証拠hash、宛先・DOM順序のpart候補・確認者・期限をhashへbindする。
入力hashには本文・送信者・手動選択・観測・項目型を含める。
本文を新たな台帳行へ複製しない。プレビュー自体もDBへ保存しない。

## 対応範囲と限界

HTMLマーカー6.1.4/6.2に限定する。plugin実版/source commit/実行環境を証明するものではない。
`plugin_version_evidence=HTML_MARKER_ONLY`を明記する。
既存の固定fixture用6.1.4/6.2契約・専用test DB・feature flagを緩和しない。
これらのfixture契約として今回のデータを受理させない。

text/email/tel/textareaと、明示Human選択済み単独checkboxのみ。
追加hidden、radio/select/file、disabled、form属性、base、入力制約、inline handlerは保留。
CF7 acceptance wrapperのoptional/invert等の意味を推測しないため、今回の契約証拠対象外。
`cached`等が加わる未知configも保留。6.1.4/6.2固定ソースのcontroller.phpに
WP_CACHE時のcached追加を確認したが、今回その送信時更新挙動を検証済みとは扱わない。
独自JavaScript・実行時DOM変化・サーバー側受信挙動の検証は今回の静的証拠では解決しない。

営業禁止・suppression・CAPTCHAの既存安全判定を維持。
入力確認・プレビューで営業許可を解除しない。
execution_allowed/eligible_for_approvalはresponse/証拠/contractすべてfalse。
確認hashをHumanApprovalProof・SendAttemptへ流用しない。

## 検証

- Backend関連140件PASS（契約プレビュー・API・入力確認・静的点検・入力資料・live-check）。
- 実DBは専用test DBのみ。fake GET→隔離parser→保存→latest→Human入力確認→previewのroundtripを確認。
- 版別・DOM順序・宛先/項目型/hash/期限/観測変更・未知hidden・設定競合・Agent/Project/Viewer境界を検証。
- GET不変、query/bodyによる権限代替不可、承認/送信/job table不変を確認。
- Ruff/format、4 serviceファイルのmypy、Frontend typecheck/lint/build成功。
- Playwright Desktop/Mobile各2件、計4件PASS。PREVIEW_ONLY/HOLD切替と旧宛先表示の消去を確認。
  UIはfixture response、証拠保存と照合APIはBackend専用DBで検証。
- 専用DBでAlembic head/model差分検査成功。新Migrationなし。
- 既存Frontend bundle size警告あり。GitHub CIは未実行。
- 実企業GET、AI API、Approval作成、メール・フォーム送信は今回0件。
- 実データ26社、Approval/EmailDelivery/FormDeliveryは0件、outbound OFF・通常送信worker停止を維持。

## 次の工程

この非実行プレビューのpart候補を、版別の実行用エンコードへ変換する境界を隔離環境で検証する。
その後に実行時の再観測・Human送信承認・二重送信防止を別工程で接続する。
今回のhashやRECORDEDを送信承認とみなさない。
