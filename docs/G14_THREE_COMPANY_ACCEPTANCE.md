# G1.4 3社向け受入・導入準備

2026-10-03 / codex/integration / HEAD f5885b7707536b4b7a7d8f50edeb724430933c58。
G1.1〜G1.3のローカル未commit実装を前提にした準備文書。3社の実機導入完了・送信運用可能・SLA達成を意味しない。

## 提供範囲と判定

初期は**1社1専用Windows PC/専用VM・専用DB・固有キー・個別管理者**。送信停止、Agent OFF、Dots不要で提供する。
Projectは企業間tenant境界ではない。同じPCのポート違い/フォルダー違いを3社分の隔離として使わない。
ローカルはその端末で利用する。他PC/スマートフォンからの共有利用には別途専用サーバー・HTTPS・ネットワーク権限の受入が必要。

本工程の判定は「導入資料・模擬受入の準備完了、実機受入待ち」。下記署名gateが通るまで「3社提供完了」にしない。

## 使用する記録票

- [導入台帳（A/B/C、未記入項目は空欄）](acceptance/THREE_COMPANY_DEPLOYMENT_REGISTER.csv)
- [受入結果（各社20項目、全てNOT_RUNで開始）](acceptance/THREE_COMPANY_ACCEPTANCE_RESULTS.csv)
- [外部アクセス不要のダミーCSV](acceptance/LEADHIVE_ACCEPTANCE_SAMPLE.csv)
- [初心者向け開始・日常操作](G14_BEGINNER_QUICKSTART.md)

配布ZIPには初心者ガイド・Open-QuickStart.cmd・ダミーCSVだけを追加する。導入台帳/受入結果は提供元で管理し、全社分を利用者へ配らない。

A/B/Cは仮称。実名・担当者・端末・人数・提供日・予算・backup保管責任はHuman管理者が埋める。ID/volume/commitは実環境の値だけ記録し、仮IDを作らない。
導入票は提供元管理用。提供先にはその会社の行だけ渡す。パスワード、APIキー、SMTP/IMAP資格情報、credential、session、暗号化キーを記録しない。
backup_storage_referenceは保管場所の管理番号。秘密・backup本体を添付しない。

結果はNOT_RUN/PASS/FAIL/BLOCKEDのいずれか。実施者・日時・根拠がなければPASSにしない。例外や適用外はnotesと管理者承認に記録し、自動合格にしない。

## 提供前の受入手順

1. G1.1〜G1.3をレビューし、分けてcommitする。cleanな候補commitをCIへかけ、固定commitの配布ZIP・hash・manifestを作る。未commit workspaceやGitHubのソースZIPを配らない。
2. 提供元の破棄可能な専用Windows/VMで、外向きSMTP/フォーム送信をnetwork/mockで封じる。実APIキー・実SMTPは入れない。
3. 新規導入・再起動後再実行・旧版更新・失敗時停止・別DB復元・新PCImportを実行し、INS/UPD/RST/MOVEの証拠を残す。backupはダミーDBだけ。
4. 3つの独立したOS/VMでA/B/CのID/volume/キー/管理者を確認し、実業務データを使わず非共有を検査する。異なる会社のbundle混入は検証環境で拒否を確認する。
5. データ/権限/承認/worker/外部送信停止を下記の範囲で確認する。
6. 提供元試験を合格後、A社をpilotとして導入。A社責任者の確認後にB、Cを順に進める。実端末へ導入する工程は別の実行指示で開始する。

同じ候補commitを全社へ配る。更新は1社ずつ。同じ環境IDで元PCと新PCを同時運用しない。

## UI・データ受入（実外部アクセスなし）

- 初回管理者ログイン→送信停止表示→オンボーディング→受入Project/Profileを作成。
- サンプルCSV2件を取込。website_urlは空欄なので企業サイトへアクセスしない。再取込で同じ会社が増えないこと、詳細/活動/追客/連絡禁止の再読込を確認。
- 所有者/編集者/閲覧者をダミーアカウントで確認。追加ユーザーは既存CLI、Projectメンバーは画面で設定。共有パスワードを使わない。
- A2承認キューで架空宛先の提案を作成し、誤った再認証→拒否、正しい再認証→承認、取消を確認。送信しないこと、hash/versionと台帳を確認。
- 検証環境でSMTPテスト・メール予約・直接フォーム・Batch・Campaign・Codex引渡しが停止することを確認。実ホスト/実フォームへ試さない。
- 収集/解析worker継続はprovider/scraper mockで検証する。送信待ちとattempt_countを保持する。CSV取込成功だけを非同期検索成功の証拠にしない。

実Serper/Places/AI/IMAP疎通、実サイトの分析品質・速度、実データPhase 6は今回未実行。設定後の限定検証は別gate。SMTPテストメールは初期範囲外。

## 更新・復元受入

元DBを残した隔離復元、全テーブルhash/schema/復号検証、append-only ledger、session/proof/Agent credential失効、承認失効を確認。
バックアップは同名dump/env.local/identity.jsonの3点を安全な別媒体へ保管。backup/update/restore後は送信停止、worker pauseを確認し、Resumeで収集だけ再開する。
失敗時は元DBとファイルを保持する。factory reset、volume削除、キー再生成、migration downgrade、台帳削除を通常復旧手順にしない。

## 現在の証拠と未実施

| 項目 | 証拠 | 状態 |
| --- | --- | --- |
| Backend・A2・送信停止 | G1.3で243 passed、新規送信停止25件 | 既存回帰成功。G1.4ではruntime変更なし、再実行省略 |
| Frontend typecheck/lint/build・API起動 | G1.3でpass | 同上 |
| Desktop/mobile E2E | G1.3で6 passed、停止表示・SMTP503・A2・企業閲覧 | 同上 |
| DB復元 | G1.2でnative PostgreSQL42table一致、復号/認可失効/台帳 | 隔離nativeで検証、Dockerでの復元は未実行 |
| Windows orchestration | G1.3で46 passed | Docker/DB mockのみ |
| A/B/C模擬分離 | G1.4で49 passed | 独立ID/volume/key、6方向backup混入、3方向key混入の模擬試験 |
| 初心者用サンプルCSV | コードのparserで2件・エラー0・URLなしを確認。3社台帳/60項目/リンクも検証 | 実機UI取込はNOT_RUN |
| 実Docker確認 | このPCのdocker infoがLinuxEngine pipe未存在で失敗 | BLOCKED。Docker起動修復/別検証VMが必要 |
| 3社実機/利用者実演/署名 | 導入票60項目にNOT_RUN | 未実行 |
| 配布内容検査 | 隔離clean fixtureのZIPを展開してmanifest・開始command・ガイド・CSVを検査 | pass。会社別の内部台帳/受入票はZIPへ同梱しない |
| 検証済みリリース公開 | workspace未commit | 未実行。fixture ZIPを実リリースに使わない |

mock分離試験は同じmock inventoryに3instanceをモデル化したもの。別OSのcontainer/DB/ネットワーク非共有を証明するものではない。

## 受入署名gate

- release/instance/担当者/利用範囲/バックアップ窓口を記録。
- 提供前の必須試験PASS、未解決FAIL/BLOCKEDなし。署名者・日時・証跡を記録。
- 各社のログイン/CSV/承認/停止/backup/Resume操作を本人が実演。
- 実API疎通を除く収集準備と、送信停止運用までを提供範囲として合意。
- 未完了Dispatch Foundation、共有tenant、実送信、旧Codex payload無効化の限界を提供元の残課題として記録。

## 次に進める1工程

G1.5: G1.1〜G1.4のローカル変更をレビューし、工程別commit・CI・clean release候補を準備する。実機受入はDockerが稼働する破棄可能VMを確保してから行う。
G1.4終了で停止。3社への実導入・送信有効化・Dots/自動化接続は開始しない。
