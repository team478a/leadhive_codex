# CF7 6.2差分検証・隔離プロファイル

## 基準と目的

branch `codex/integration`、基準commit `5e3092b`。
6.1.4に限定した既存非実行契約を維持し、CF7 6.2の受付仕様を管理下で比較する。
実サイトadapter登録、Human Approval、dispatch、通常worker、実DBへ接続しない。
Model・Migration・API・製品UI変更はない。backendのCF7契約は変更しない。

## 公式仕様・固定ソース

公式6.2リリースはWordPress 7.1以上、PHP 8.3以上を要求する。
SWV 2導入、REST管理endpointの認証状態に応じたstatus code、UTF-8処理、型宣言等に変更がある。
旧WordPress 6.8.3をそのまま使って「6.2対応確認済み」とはしない。

- [CF7 6.2公式リリース](https://contactform7.com/2026/10/06/contact-form-7-620/)
- [6.2 RC変更説明](https://contactform7.com/2026/09/22/contact-form-7-62-rc/)
- [固定v6.2.0ソース](https://github.com/rocklobster-in/contact-form-7/tree/34acb3a6995b403274820c5ea42abd01b754c03b)
- [WordPress公式Docker定義](https://github.com/docker-library/official-images/blob/master/library/wordpress)

v6.2.0 tagのcommit `34acb3a6995b403274820c5ea42abd01b754c03b` を使用。
archive SHA-256 `be61bf5bd0f99187e7f15b285b1bf1590038105e2b267501b81003066c93d1cb`。
初回取得は公式GitHub codeloadの固定commitから行い、その後は同一hashを再検証する。
これは取得archiveのpinであり、上流が公開した署名/checksumとの照合ではない。
source header/定数は6.2。固定commitのreadmeのStable tagは6.1.7のままなので、readmeだけで実行版を判断しない。
実行時WPCF7_VERSIONと実際のWP/PHP versionを確認する。
sourceはignored cacheに保持し、第三者コードをLeadHive本番へコピーしない。

## Lab変更

`profiles.py`に固定allowlistを追加。

| Profile | CF7 | WP image |
|---|---|---|
| 既定値 | 6.1.4 / 従来commit | wordpress:6.8.3-php8.3-apache |
| 明示6.2 | 6.2 / 上記commit | wordpress:7.1.2-php8.3-apache |

`CF7_PROTOCOL_LAB=1`必須。`CF7_LAB_PROFILE=6.2`で比較のみを選択する。
未知profileは資源作成前に拒否。任意commit・任意imageを環境変数で指定させない。
imageは取得後RepoDigest/IDへ固定して起動し、記録する。
6.2用公式WP imageを新しく取得するが、既存LeadHive container/image・DB・設定は変更しない。
内部network、公開portなし、外向きHTTP/socket遮断、POST前のmail捕捉を維持する。
PHPMailerを実行せず、架空本文・送信者だけで測定する。

`protocol.observe()`は既定値6.1.4を維持する。
lab比較処理から明示した場合のみ6.2 DOMを観測できる。
本番CF7Candidateのplugin/source pinは6.1.4のまま。6.2 DOMを旧契約へ偽装しない。

## 比較内容

`version_probe.py`で固定standard/mixedフォームだけを測定する。

- 必須hidden集合、feedback endpoint、REST root、unit tag、受付応答のkey/status。
- multipart成功、urlencoded拒否、unit tag欠落、必須項目/同意欠落。
- mail処理失敗、spam、abort、skip-mail。
- mixedのcheckbox複数値、radio、固定非秘密hidden、必須選択欠落。
- hidden変更・radio重複のraw負例。server拒否を勝手に仮定しない。
- 実ブラウザの全part順序、endpoint、捕捉mail hash。
- query形式REST root。
- 6.1.4 candidateが6.2をHTTP前に拒否すること。

新しい6.2 candidate contractを追加した検証ではない。
比較用のraw wireは固定labだけで実行し、実サイト・既存承認へ接続しない。
UNKNOWNは自動retryしない。mail_sentは受付応答であり外部配送・到達の証明ではない。
管理endpointの認証status差はソース監査対象。今回は管理APIの変更・認証付き試験をしない。

## 初期化の信頼性

旧profileの初回再実行で、fixture作成出力のJSON解析が受付前に失敗した。POSTは0、cleanup成功。
詳細な原因を確定できる出力は保存されておらず、DB準備との競合を確定原因とはしない。
既存runnerはWP設定ファイル出現のみ待ち、DB接続可能性を確認していなかった。
`readiness.py`でread-only DB接続の成功を待ってからfixture installへ進む。
短い待機と上限を設定し、timeout時は停止。fixture作成/送信を再実行するretryではない。
接続値はcontainer環境変数から読み、password・例外詳細を出力しない。

## 実測差分

6.2初回では必須同意の欠落を旧版と同じvalidation_failedと予測し、検証が停止した。
実際はHTTP 200 / acceptance_missing、mail捕捉0、submission1、classification UNKNOWN。
版別期待値を実測に合わせ、UNKNOWN扱いと送信禁止境界を維持した。
試験の失敗を隠さず、失敗時の5ローカルPOST・cleanupを集計に含める。

旧環境はWP 6.8.3/PHP 8.3.28、新環境はWP 7.1.2/PHP 8.3.35。
WP/PHPも異なるため、観測差の原因がCF7だけだとは断定しない。
純粋なplugin差の原因特定には同一WP/PHPでの追加対照試験が必要。

| 項目 | 6.1.4環境 | 6.2環境 |
|---|---|---|
| 標準hidden | 既存6項目 | 同じ6項目、version値は6.2 |
| feedback API | contact-form-7/v1、multipart | 同じnamespace・multipart。urlencodedは415 |
| unit tag欠落 | 400 | 400 |
| 必須名前/checkbox/radio欠落 | validation_failed | validation_failed |
| 必須同意欠落 | validation_failed | acceptance_missing |
| mail失敗 | UNKNOWN | UNKNOWN |
| 変更された追加hidden | mail_sent | mail_sent |
| 同名radio重複 | mail_sent | mail_sent |
| browser mixed順序 | ordered契約14項目一致 | 比較wire14項目一致 |
| query REST root | 受付成功 | 受付成功 |

6.2でも変更hidden・重複radioをserverに拒否させる設計にはできない。
LeadHiveの単一値・固定hidden・不変payload検証を維持する。
skip-mailはmail捕捉0でもmail_sentを返した。receiptと外部配送は引き続き区別する。

4試行: 旧profileの初期化失敗0 POST、旧profile成功73チェック/45 POST、6.2初回差分検出で停止5 POST、6.2最終成功29チェック/17 POST。
この工程の計67ローカルPOST。全試行の専用資源撤去成功。
旧版と新版は異なるcase数を実行しており、成功率の比較指標にはしない。

## 結果・制限

実測結果は `docs/fixtures/197_cf7_62_version_comparison_summary.json` を正本とする。
ソース比較hash、WP/PHP/CF7 version、image digest、HTTP件数、status/response key、撤去結果を記録する。
raw DOM・詳細wire・reportはignored distだけに保存。共有成果物にURL・cookie・credentials・本文を含めない。
全fixtureの一致を任意フォーム・追加plugin・JSへの等価性としない。
CAPTCHA、未知token、file upload、動的control、実際のメール配送は未検証。
SWV/文字処理の変更は入力種別ごとの追加検証が必要。本試験は固定した文字列/選択肢に限定する。

## 品質確認

- Backend既存契約126 tests / 50 subtests PASS。専用test DB head upgrade・Alembic model差分検査成功。
- Lab offline unit44件PASS。既定版の厳格性、未知profile、固定DOM、未知値、実origin拒否、DB待機/timeout、acceptance_missingのUNKNOWN維持を確認。
- Ruff、format、新規labモジュールのmypy check-untyped-defs成功。
- Frontend typecheck/lint/build成功。既存bundle警告あり。製品UI変更なし。
- lab実ブラウザで検証。製品UI E2EとGitHub CIは今回未実行。
- 既存radio負例のPydantic警告6件は既知。全体mypy成功とはしない。

## 停止点

実企業アクセス・実Email/Form送信・Approvalは0。outbound OFF、通常worker未起動を維持。
6.2比較までで停止する。旧契約の版制限を解除せず、保存済み実サイトをREADYへ変更しない。
次候補は測定結果を基にした6.2専用の非実行契約。実サイト登録・承認・dispatchは別工程。
