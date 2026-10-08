# CF7限定実サイト対応の前提: 観察結果とCore安全判定の接続

## 基準とゴール

基準は `codex/integration@cef1e6a`。CF7実サイト対応へ向けた差分確認で、管理下観察のnegative/review holdがCore permissionに接続されていないことを確認した。今回はこの前提工程を完成させる。実サイトのAdapterやTransportを開放した成果ではない。

## 変更

- `form_observation_projection.py`: 既存読取APIの保存hash・canonical JSON・Project/Company/Job/Run結合・鮮度検証を共通Serviceへ移動。API形式、URL、認証、権限は維持。
- `form_observation_safety.py`: Project/Companyに属する最新1件の保存観察を読み取り、Coreに禁止または確認待ちのみ返す。ネットワーク、Job登録、DB更新、承認、送信を行わない。
- `contact_permission.py`: 通常ProfileがREADY/ALLOWEDでも、保存観察が未検証であればALLOWEDにしない。既存Profileの禁止、Company連絡禁止、結果UNKNOWN、Suppression、共有窓口の停止は維持。
- SQLAlchemyの既存店舗条件を `true()` に合わせ、共通判定もCIのmypy対象へ追加。

| 最新観察 | Core判定 | 理由 |
| --- | --- | --- |
| CURRENT + 営業禁止/BLOCKED | PROHIBITED | form_sales_prohibited |
| CURRENT + CAPTCHA検出 | UNCERTAIN | form_captcha_review |
| CURRENT + 静的解析未検証/未対応/その他Human Required | UNCERTAIN | form_observation_review |
| EXPIRED/SOURCE_CHANGED/RETIRED/INVALID | UNCERTAIN | form_observation_review |
| 記録なし/旧版で保存schemaなし | 既存判定 | 既存互換性を維持 |

観察の無効化や時間経過を、送信許可を回復する操作にしない。CAPTCHA以外のHuman RequiredはCAPTCHAと誤表示しない。観察はCompany単位の保守的な停止で、別フォームへの自動切替による解除はしない。Emailにはこのフォーム観察holdを適用しないが、既存連絡禁止/Suppressionは適用する。

過去全履歴の禁止解除・再確認ワークフローは今回追加しない。最新観察も必ず禁止またはUNCERTAINなので、後続の静的観察だけでALLOWEDへ戻ることはない。確認済みのpositive evidenceから制限を解除する仕組みは別工程で設計する必要がある。

## 検証

専用テストDB・合成HTMLのみ使用。Backend関連160件PASS（98.86秒）。新しいCore接続、既存観察読取/保存、連絡可否、CF7候補準備、Human Approvalを確認。

営業禁止/CAPTCHAの合成HTMLを既存parser→保存contract→append-only保存→Core判定まで通す試験を追加。別Companyへの非伝播、Emailへの非適用、ソース変更/無効化時の停止維持、旧schema互換性、既存禁止優先、承認/Email/Form配送0件を検証。期限切れ等の各projection状態も検証。

Ruff・format・mypy（4ファイル）、Frontend typecheck・lint・build成功。Frontendに変更なし。既存bundleサイズ警告あり。テストfixtureのMigration upgrade・Alembic model diff確認成功。Model・Migration・dependency追加なし。

PC/Mobileの既存フォーム確認画面4件PASS（2.5分）。最後にProfileなしでも観察holdを確認するケースを追加し、Core/連絡可否の15件を再実行してPASS。160件と15件は一部重複し、合算しない。最終Ruff・format・mypyもPASS。GitHub CIは未push時点では未確認。

ローカルAPIのhealth正常、outbound OFF、worker起動なしを確認。Company26/Raw Snapshot80/Raw Review0/Approval0/Email0/Form0件はAPI再起動前後不変。Frontend変更はない。

## 安全と次の停止点

実サイトGET・Form POST・Email・AI・Human Approval作成を今回実行しない。送信workerを起動しない。outbound OFFを維持。テスト内の合成承認は既存承認回帰用で、稼働データの承認とは区別する。

この工程でCF7実送信対応が完成したとは扱わない。次は自社候補の限定GETに必要な取得許可/URL範囲/保持・削除/parse隔離を決め、既存observerの限定対応を検証する。実POST接続、Humanの窓口/選択/同意確認、step-up承認はさらに別工程。管理下labのflagを稼働DBで有効にして実サイト対応を代替しない。
