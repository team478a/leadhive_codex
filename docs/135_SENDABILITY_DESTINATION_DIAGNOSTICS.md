# Phase B1 — 窓口ごとの利用可否・不足理由

## ゴールと境界

保存済み情報だけを使い、企業詳細で窓口ごとのREVIEW / HOLD / BLOCKED、理由、次の確認作業を表示する。
この工程はPhase Bの診断基盤であり、窓口用途の確認・保存、Recommended Destination確定、DM READY確定は次工程。
READYは将来の状態として予約するが、B1では返さない。用途がsalesであるという単なるDB属性やFormProfile READYを、確認証跡へ昇格させない。

このAPIは承認・送信の権限を付与しない。Human Approval、既存Contact Permission、Suppression、UNKNOWN、配送予約とworkerの制御は維持する。
Scoreの導入や既存基準の緩和、外部AI/検索/サイト取得、配送開始を行わない。

## 実装前の100店舗確認

[読み取り専用の集計](results/sendability-preimplementation-100-locations-2026-10-06.json)を保存。
稼働中DBでREAD ONLY transactionによる集計を行いrollback。稼働DBのMigrationやデータ変更は行わない。

| 項目 | 件数 |
| --- | ---: |
| 候補店舗 | 100 |
| 登録サイト | 43 |
| 登録メール / 担当者メール | 0 / 0 |
| FormProfile | 139 |
| FormProfile READY / REVIEW_REQUIRED | 6 / 38 |
| FormProfile STALE / ERROR / BLOCKED | 25 / 69 / 1 |
| 営業可否 ALLOWED / UNCERTAIN / PROHIBITED | 29 / 109 / 1 |
| delivery_supported | 12 |
| CAPTCHAなし / その他 / reCAPTCHA | 129 / 2 / 8 |

Profile単位の件数を店舗単位の性能に読み替えない。43件の登録URLは公式確認完了を意味しない。
構造化された窓口用途・公式照合証跡が旧DBにないため、READY率や点数の妥当性を検証済みとは扱わない。
元のBaselineを上書きしない。69件のERRORについて、この集計だけで原因を断定しない。

## APIと既存機能の再利用

GET `/api/companies/{company_id}/sendability`

- 既存Human sessionとCompany/Project閲覧境界を再利用。Viewerは閲覧のみ。他Project、Agent credentialとHuman cookie混在は拒否。
- definition_version `sendability-b1-v1`、評価日時、全体状態、窓口別状態、Reason Code、表示理由、次の確認作業を返す。
- 全体のBLOCKED理由と、候補ごとの問題を分ける。全体の理由一覧には利用できない別候補の理由も含むため、全体状態と窓口別状態を併記する。
- `recommended_destination=null`、`dm_ready=false`、`execution_allowed=false`、`live_destination_checked=false`。
- `ready_evaluation=PENDING_VERSION_BOUND_PURPOSE_REVIEW`。
- 書込API、Agent scope、Model、Migrationは追加しない。サービス本体のSQLはSELECTのみ。

ContactPerson登録メールも既存の窓口候補整理へ含める。無効な担当者メールは候補表示から勝手に消さず、CONTACT_INVALIDで診断する。
URL正規化では末尾ドットを含むlocalhost/.localの候補も拒否する。DNSや実サイト疎通は行わず、危険URLの実行安全性を保証するAPIではない。

## 決定規則

1. 全体のdo_not_contact、既存Suppression、保存済みの営業禁止、送信結果UNKNOWNを最優先で止める。
2. 複数Profileのうち一つに営業禁止/BLOCKEDがあれば、別Profileやメールへ切り替えて解除しない。既存Coreより保守的な準備判定。
3. 窓口別に既存Contact Permission、共有窓口、送信済み/処理中/UNKNOWN履歴を確認。
4. フォーム候補URLとProfileを正規化して照合。主ProfileのALLOWEDを別URLへ流用しない。
5. CAPTCHA、営業可否未確認、Profile非READY、技術未対応、fingerprint不足、必須項目・本文のマッピング不足を区別。
6. 解析日時不明・未来日時・7日を超える解析はHOLD。7日はB1の保守的なキャッシュ期限であり、対応率から校正した値ではない。新鮮な解析でも実送信時の構造再確認を省略できない。
7. メールは既存のCompany/contact品質verifiedかを確認。ALLOWEDだけで準備完了にしない。
8. 用途属性が予約/採用/サポートならHOLD。その他の用途属性も、version-bound確認証跡が未実装のためREVIEW。

窓口別はHard Block > 情報/技術不足HOLD > REVIEW。
全体のHard Blockがなければ、残る候補のREVIEW > HOLD > BLOCKEDを採用する。禁止候補のScoreで許可へ覆す処理はない。
共有窓口はREVIEW対象に表示しても、既存CoreのPROHIBITEDを解除しない。
過去の同じ窓口にsubmitted/sent/pending/queued/runningがあればB1では期間制限なしで再利用を止める。将来の再接触期間・再承認設計は別工程。
配送履歴の衝突確認は既存のグローバル窓口guardに合わせる。他ProjectのID・企業名・文面は返さず一般的な停止理由だけ返す。
UNKNOWNは全体BLOCKEDとし、自動retryを提案しない。

## UI

企業一覧 → 詳細 → リスト完成の根拠 → 「窓口の利用可否と理由」。
日本語の理由と次の作業、Reason Code、全体と窓口別状態、既存Coreの可否、評価時刻を表示する。
窓口候補の整理後や企業情報保存後に再取得する。長いURLは折り返し、窓口別詳細は開閉可能。
承認/送信ボタンを追加しない。目的確認操作は次工程と明示する。
DashboardのA2暫定在庫分類と本APIは別定義。大量集計やFunnelへの確定反映は行わず、DM READY率は未判定を維持。

## 品質確認

合成データで、技術READYとDM READYの区別、属性だけの用途確認拒否、Identity変更、禁止条件と共有/代替メール、CAPTCHA、古い解析、必須項目、主フォームURL違い、担当者メール品質、危険URL、他Project/Viewer/混在認証、UNKNOWN/処理中/送信済みの同一窓口履歴、SELECTのみ・外部通信なしを検証する。
追加12件と既存のLead Completion・計測18件、計30件が成功（39.10秒）。desktop/mobile E2E 2件が成功（1.2分）。Backend Ruff、変更4ファイルformatチェック、変更3ファイルmypy、Frontend typecheck/lint/build、API起動と現行Migrationのmodel差分を確認した。Windows作業コピーの既存5ファイルは混在改行によるformatチェック差分があるため、無関係なコードを変更せずLinux CIの全体チェックを確認する。
最終の全回帰と配布/Migration検証はGitHub Actionsの結果を完了報告で確認する。

## 次のゴール B2

Human owner/editorによる用途・scopeの確認証跡を、対象・窓口・Identity・Profile fingerprint/versionにbindして保存する。
用途確認は営業禁止解除・Human送信承認と別概念。変更・失効で証跡を無効化し、既存安全制御を通った独立窓口だけ準備候補READYへ進める。
その後に窓口選択とFunnelへの確定反映を行う。新モデルが必要ならadditive migrationとProject境界を設ける。
DM本文生成はPhase C、承認/配送/Funnel結合はPhase Dとして分離し、今回開始しない。
