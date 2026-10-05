# フォームのサイト別間隔制御と模擬負荷・中断復旧検証

## 今回のゴール

同じサイトへの試行を間隔制御し、待機中のサイトが他サイトの予約を妨げないようにする。300件・3,000件の合成予約によるスケジューラ検証と、50社の実際の準備/承認/予約を通す模擬送信で、結果不明・停止・中断時の保護を確認する。実送信はOFFを維持する。

## サイトの識別と間隔

予約時に、フォーム表示URLと固定したPOST先URLのhostnameをFormDispatchSiteへ保存する。小文字化、IDNA変換、末尾ドットの除去、先頭`www.`の除去を行い、HTTP/HTTPS・port・pathの違いでは別サイトにしない。表示先とPOST先が異なる場合は両方を制御し、共通フォーム提供元へ集中するケースも待機する。

既定は同じサイトへの試行間隔300秒。環境管理者だけが、既存の再認証・versionチェック・監査付き設定API/UIで60〜86,400秒へ変更できる。既存クライアントがsite_interval_secondsを省略した場合は保存済み値を維持する。環境全体の上限・間隔とサイト別間隔のすべてを満たす必要がある。

hostname単位の制御であり、すべてのsubdomain・別名domain・同一企業・同一IPを一つにまとめるものではない。`a.example.com`と`b.example.com`は別キー。PSL/eTLD+1による統合は今回導入していない。CAPTCHAや営業禁止の条件は別の既存安全制御で維持する。

## workerの変更

claimは直近の開始記録とサイトリンクをSQLで照合し、待機対象を除いた最も古いqueued予約を選ぶ。待機対象を一件ずつ読み取るループや、会社ごとのsleepは追加しない。候補全体をアプリへ読み出さず、indexとsubqueryを利用する。

POST開始直前にも、保存したサイトキーとpayloadの一致、最新のサイト間隔を再検証する。開始・判定・設定変更は既存のadvisory transaction lockを共有する。開始日時・CONSUMED・UNKNOWNの証拠は従来どおり同一transactionで保存する。UNKNOWN/failedも間隔に数え、UNKNOWNを再試行しない。サイトキー欠落/不一致では送信しない。

queuedの間隔待ちはDB上の新しいstatusを増やさず、一覧APIの`site_wait_until`として返す。画面は「同じサイトへの間隔待ち」と再確認可能な日時を表示する。日時は送信の約束ではなく、他の上限、承認期限、連絡禁止などの条件を再確認する最早時刻。

## DB・互換性

追加Migration `fae47ac5e861`、親`f9c36fb4d750`。

- FormDispatchLimits.site_interval_secondsを追加し、既存singletonへ300を設定する。
- FormDispatchSiteに予約ID・site_keyの複合主キーとsite_key indexを作る。
- 既存予約の固定URLからリンクをbackfillする。不正/欠落URLがあればMigrationは停止する。
- 既存snapshot、承認hash/version、Migrationは書き換えない。
- サイトリンクのupdate/deleteはDB triggerで拒否する。通常操作の編集APIは追加しない。
- downgradeは新しい設定項目/リンクだけを削除する。送信/承認証拠は保持する。戻す際は外部送信OFF・worker停止のうえでコードも戻す。

## 模擬検証の範囲と結果

2026-10-05、専用PostgreSQL `_test` DBで実施。報告データは [results/form-dispatch-load-2026-10-05.json](results/form-dispatch-load-2026-10-05.json)。実企業・外部SMTP・外部フォームへの通信は0件。

| 検証 | 方法 | 結果 |
|---|---|---|
| 合成300予約 | 先頭100件を同じ待機サイトにしたDB fixture。予約選択20回とlease切れを仮想時刻で再現 | 別サイトを選択、20件blocked、元のUNKNOWN再試行0 |
| 合成3,000予約 | 同じスケジューラ検証。PENDINGの合成提案を参照し、dispatchは実行しない | 別サイトを選択、UNKNOWN再試行0。予約選択平均57.1ms、最大69.4ms（20サンプル） |
| 50社 | 保存済み解析/Draft→APIによる準備→Human一括再認証/承認→予約→mock inspect/submit | mock成功45、blocked2、UNKNOWN2、failed1。mock submit呼出47、同一URLの重複呼出0 |

50社の内訳は、POST前ワーカー消失、開始証拠保存後のワーカー消失、応答不明、連絡禁止、POST前入力失敗を各1件注入したもの。実際のフォーム成功率ではない。準備・承認・予約は約11.1秒、全体約23.9秒だったが、通信とサイト間隔は仮想/mockで置き換えており、実送信件数/時間への換算はしない。

3,000件は候補選択の検証であり、3,000社の完全な準備・承認・HTML取得・POST・結果保存を通した試験ではない。50社試験でもHTML parser/HTTP transportはmock。DB・承認Service・workerの状態遷移を検証した。OSプロセスの強制終了、複数実workerの競争、ネットワーク障害をすべて実証したという扱いではない。

## 月10,000件への意味

今回の条件では、予約候補選択が3,000件規模でも先頭待機に詰まらないことを確認できた。実運用の主な制約は、承認期限24時間、フォーム対応率、実HTTP取得時間、営業禁止/CAPTCHA、同じPOST先の集中、Human Reviewの処理量。

単一サイトがすべてのPOST先になる場合、300秒間隔では理論上でも288試行/日以下。他の上限や停止でさらに減る。月10,000件を達成済みとは判定しない。安全条件を緩める前に対象の分散・対応可能数・例外量を計測する。

次工程は、期限切れ・blocked・UNKNOWNの運用整理と、再準備可能なケースへの導線。UNKNOWNの自動再送・CAPTCHA自動化・実送信有効化は行わない。

## 品質確認

- 新規サイト制御/負荷/50社模擬試験9件成功。関連Backend56件も成功（サイト試験を含むため合算しない）。
- PC/mobile E2E 4件成功。待機表示、サイト間隔の管理者保存、既存承認・取消・UNKNOWN保護を確認。
- Backend Ruff/compileall、Frontend typecheck/lint/build、API/Web Dockerビルド成功。
- 専用DBでupgrade→downgrade `f9c36fb4d750`→upgrade→Alembic check成功。空DB往復検証であり、履歴のあるbackfillの全パターンを実証したものではない。
- バックアップ後にローカルDBを `fae47ac5e861`へ更新し、Alembic check成功。API/worker/Webを更新し、API/DB healthを確認。企業100件、予約/フォーム送信/メール送信記録は各0件を維持。
- 保存済み上限は30/日・5/時・全体60秒・同じサイト300秒・version 1。API/workerの外部送信・承認済みフォーム・legacyフォーム・Agent flagはすべてfalse。上限の増加・実送信・Production導入・配布zip再生成は行っていない。
