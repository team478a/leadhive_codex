# CF7 6.2専用非実行契約

## 目的・基準

branch `codex/integration`、基準commit `bce950df0da47c7013b3536406cc8fb3dfa4d26c`。
197の版比較を受け、6.2の管理下fixtureに限定したpayload契約を追加する。
実サイトadapter、Approval、dispatch、通常workerとは接続しない。
Model・Migration・API・製品UI変更なし。

## 契約と再利用

`cf7_62_contract.py`の`CF762Fields`はplugin `6.2`とsource commit
`34acb3a6995b403274820c5ea42abd01b754c03b`をLiteralで固定する。
`CF762Candidate`は`CONTROLLED_FIXTURE` / `NON_EXECUTABLE`、
`execution_allowed=false` / `eligible_for_approval=false`。
URLは`https://managed.example/contact/`とその固定REST rootに限定する。
このURLは契約上のplaceholderであり、実行先としてアクセスしない。

6.1.4の`CF7Candidate`は既存version・source commit・契約名を維持する。
共通の入力/hidden/同一origin/送信者/必須項目検証だけを`CF7ValidatedFields`へ抽出した。
中立クラス自体を実行・承認用APIへ公開しない。
6.1.4 canonical / wireは既存テストと固定wire hashの回帰検証を維持する。
6.1.4契約で6.2を受理する変更は行っていない。

checkbox group・radio・固定非秘密hidden・PartRefは既存の型を再利用する。
版に依存しないmultipart rendererを共有するが、必ず各版の契約を再検証してから使用する。
raw bytesはHTTP実行権限やHuman承認証明にはならない。

## 固定項目と変更検知

- 6つのCF7 hidden、明示的な氏名/email/本文/consent。
- 管理下のservices複数選択、topic単一選択、固定`leadhive_lab_context`。
- 全選択肢に明示choice。radio複数選択、未知値、名前衝突、欠落/重複partを拒否。
- 成功control全体のDOM順序を保存。未選択項目をwireへ追加しない。
- 元の混在form全体のDOM fingerprintを保持。削除した簡易DOMのfingerprintで代用しない。
- scope ID、payload version、source commit、canonicalization version、SHA-256をsnapshotに含める。
- snapshot/wire hash、期待version、Project/Company/Draft/FormProfileの不一致を拒否。
- 順序やDOMの変更は旧snapshotを無効にする。ただし契約単独で現実のDOM変更を検出するものではなく、再観測したcurrentとの比較が必要。
- option合計50、order120、値合計40KB、wire64KB上限。
- CR/LFをCRLFへ正規化し、boundary衝突・危険なmultipart名を拒否。

## 隔離検証

既存の固定source archive / WordPress image profileを使用する。新しい依存関係・OSSコピーは追加しない。
6.2はWordPress 7.1.2 / PHP 8.3.35、6.1.4はWordPress 6.8.3 / PHP 8.3.28。
両環境は異なるため、差をCF7の版だけに因果帰属しない。

6.2の標準・混在フォームについて、DOMから契約を構築する。
管理下9-form fixture、版、各値、option label、標準consent、イベントhandler不在を確認する。
14成功partの順序・値が観測したbrowser multipartと整合する。
契約wireの受付`mail_sent`と捕捉失敗`mail_failed`を確認する。
`mail_sent`は`RECEIPT_REPORTED`に留め、到達/実メール送信成功とは判断しない。
`mail_failed`等はUNKNOWN。再送・Human Approval・実行状態への接続なし。
順序・DOM・version・authority変更はHTTP前に拒否する。

containerは公開portなし・内部専用network、WP HTTP/socket制限とmail捕捉を使用。
HTTPは明示opt-inしたloopback fixtureへ限定し、契約のURLから実行先を選択しない。
専用container/network/volumeは所有labelを検証して撤去する。
詳細DOM・本文・reportはignored dist内。共有集計にcredentials/cookie/実企業情報を含めない。
検証件数・source hash・image・撤去結果の正本は
`docs/fixtures/198_cf7_62_contract_summary.json`。

6.2は35チェック/19ローカルPOST（新契約2 POST）、6.1.4は73チェック/45ローカルPOST成功。
今回の合計は64ローカルPOST。すべて専用fixture内で、実企業のフォーム送信ではない。
専用資源の撤去完了を確認。実運用DBのcompaniesは26件、approval_requests / email_deliveries / form_deliveriesは各0件。

## 品質確認

- Backend関連149 tests / 50 subtests PASS（新契約23 testsを含む）。
- Lab offline unit48件PASS。
- 専用test DBのhead upgrade・Alembic model差分検査成功。新Migrationなし。
- 変更ファイルのRuff / format、契約とbridge計4ファイルのmypy成功。
- Frontend typecheck/lint/build成功。既存bundle size警告あり。
- 製品UI変更なし。製品UI E2Eは再実行せず、隔離labの実ブラウザ検証を実施。
- 不正型model_construct負例のPydantic警告14件と既存radio警告6件あり。負例は拒否され、全テスト成功。
- 通常API `/api/health` はstatus/databaseともok。
- GitHub CIは未実行。全体mypyの既存課題解消や全suite成功は主張しない。

## 停止点

実企業アクセス、Email/Form実送信、Approval作成は0。outbound OFF、通常送信worker未起動を維持。
実サイト候補をREADYへ変更しない。対応済みと呼べる範囲はこの管理下の非実行契約だけ。
動的項目、CAPTCHA、任意hidden/token、実サイトadapter登録、承認・dispatch接続は未対応で別工程。
この工程完了で停止する。
