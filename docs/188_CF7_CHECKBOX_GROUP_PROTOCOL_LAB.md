# CF7 6.1.4 checkbox group受付検証

## 基準と実施範囲

branch: `codex/integration` / 基準commit: `51e3f71`。
docs/187の非実行契約を、既存の隔離WordPress/CF7 protocol labへ接続し、架空fixtureだけで受付を検証した。
LeadHive API・DB・承認・dispatcher・通常workerへは接続しない。

実行時のWordPress/CF7/PHP版、Docker image digest、CF7固定commitとarchive checksum、lab各source hash、実行時刻は `docs/fixtures/188_cf7_checkbox_group_protocol_summary.json` に保存。
ソースarchive・imageは取得済みのcacheを再検証して使用。今回のdownloadなし。
第三者ソースをリポジトリへコピーしていない。

## 安全な実行

UUID付き専用container/network/volumeを再作成。Docker内部networkのみ、containerの公開portなし。
既存のloopback gateway経由で固定CF7 feedback routeへ送った。候補のHTTPS metadata URLを実行しない。
WP HTTP遮断、数値IPsocket遮断3件、mail捕捉を確認してからPOSTを実施。
`pre_wp_mail`で捕捉、PHPMailer実行は禁止。架空のフォーム・送信者・本文だけを使用した。
外部企業へのアクセス、実メール・実フォーム送信、実Human Approvalはすべて0。
既存outbound OFFと起動設定は変更せず、通常workerを起動していない。

## 新しいgroupケース

| ケース | CF7 status | 捕捉mail増分 | 結果 |
|---|---|---:|---|
| 必須groupで2値を選択 | mail_sent | 1 | 選択値の順序を保持して受付 |
| 必須groupを未選択 | validation_failed | 0 | 必須条件で拒否 |
| 任意groupを未選択 | mail_sent | 1 | group partなしで受付 |
| 定義にない値を送る負例 | validation_failed | 0 | CF7本体も拒否 |
| mail処理を失敗させる | mail_failed | 1 | UNKNOWNを維持、自動retryなし |
| 実ブラウザで同じ2値を選択 | mail_sent | 1 | 契約wireと意味・group順序・mail hash一致 |

group専用のPOSTは6回、submission記録6件、捕捉mail呼出4回。
既存19 POSTの回帰を含め合計25回。これはローカルlabのPOST件数であり、実企業への送信件数ではない。
`mail_sent`は捕捉処理が成功を返したCF7応答であり、メール配送・到達の証拠ではない。
validation_failedでは拒否を確認したが、既存の保守的receipt分類はUNKNOWNのまま。成功へ繰り上げない。

負例はlab内で意図的に契約を通さず送る試験。通常のgroup契約は必須未選択や未知の選択肢をwire生成前に拒否する。
この負例用コードは本番dispatchへ接続しない。

## Browser比較

実CF7 JavaScriptのFormDataで、選択した2値だけが同名 `services[]` partとして送られた。
PHP/CF7の処理後に記録した選択値hashの順序、各名前に属する値の順序、捕捉mailのhashは契約wireと一致。
全partの並び順は一致しない。Browserではgroupがconsentより前、lab契約ではbaseを先に置く。
この固定fixtureでは同じ結果になったが、任意のフォーム・追加plugin・JSに対する等価性の証明ではない。

## 変更

- `fixture.php`に必須/任意groupの2フォームを追加。既存4フォームを維持。
- `group_probe.py`に固定fixture専用の観測・契約wire・比較を追加。
- `browser_probe.cjs`に明示したlab group操作だけを追加。
- `safeguard.php`に処理後のgroup値hashを記録。本文・credentialは共有しない。
- `cases.py`で既存19ケースとgroup6ケースの件数を分離し、余分なPOSTがないことを確認。
- gateway上限拒否テストをheader admissionの検査へ修正。Windowsで未読の大きな本文がsocket resetとなる不安定さを避ける。gatewayの上限・拒否処理は変更していない。

Backendの非実行契約・Human Approval・Profile・UI・Migrationは変更なし。6.2、追加hidden、radio、同意条件の対応追加も行わない。

## 品質・撤去

実labの全チェック成功、全専用資源の撤去成功。所有labelによるcontainer/network/volume残存なし。
group bridgeのoffline試験を含むlab unit25件PASS。上限拒否試験は当初Windowsのconnection resetで失敗し、上記修正後にPASS。HTTP retryで隠していない。
Backend契約関連54 tests / 50 subtests PASS。専用DBのMigration upgrade/Alembic model diffも成功。
Ruff・format・mypy（bridgeのcheck-untyped-defs、follow-imports=silent）、Node構文確認成功。
Frontend変更なし、typecheck・lint・build成功。既存bundle警告は残る。
ローカルLeadHive API health/database正常。GitHub CIは未pushにつき未確認。

生のDOM、wire、Browser結果、snapshot、reportはignored `dist/leadhive-cf7-lab-d713e9e6ef71/` に保存。共有JSONにはURL・cookie・password・本文全文を入れない。

## 次のゴール

同名groupについて、実サイトの保存済み構造から選択肢を読み取り、Humanが各選択・未選択を確認するための表示と変更検知を設計する。
このfixture mapperを実サイトへ転用せず、選択肢・用途・同意の判定を自動で確定しない。
実サイト2件をREADYへ変更せず、実POSTや送信承認へ進めない。
