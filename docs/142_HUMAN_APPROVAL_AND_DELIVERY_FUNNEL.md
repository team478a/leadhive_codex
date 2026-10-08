# Phase C3: Human承認と送信結果のLead Completion Funnel

## 目的

既存C2の固定リスト診断へ、根拠付きDMのHuman承認履歴と保存済み送信結果を追加する。集計のために承認状態・送信状態・外部接続を変更しない。新しい送信経路、送信設定の有効化、worker起動、Migrationは追加しない。

## 件数の単位と状態

- 現在DM READY: C2既定の有効なPENDING／APPROVED準備。取消・失効・使用済みは除外。
- 提案準備済みLead: C2に結び付いた検証可能なApprovalRequestが過去に存在するLead。
- Human承認記録Lead: 同一payload hash/versionのHUMAN `approval granted`台帳、承認者・承認日時・承認payloadが一致するLead。PENDINGやconfirmed属性だけを承認と見なさない。取消／期限切れ後も過去の承認事実は残す。
- 送信実行Lead: 紐付く保存済みattempt／dispatch開始証跡があるLead。予約、確認中、停止、取消だけでは送信実行に数えない。
- 試行件数: 開始証跡ごとに数える。同じLeadへの複数提案・試行はLead件数では一度、試行件数では複数。

全件診断後に提案→承認率、承認→実行率を表示する。途中で中断・エラーとなった場合は観察済みの件数だけを部分集計として表示し、率は未判定とする。分母ゼロも未判定。ページ間は観察期間の集計で、送信承認snapshotではない。

## 結果分類

各試行を次のいずれかに分類する。

| 分類 | 根拠 |
| --- | --- |
| ACCEPTED | EmailSendAttempt SMTP_ACCEPTED、または対応するFormDispatch／FormDeliveryのsubmitted一致と受付日時。相手の到達・閲覧・返信は推定しない |
| DELIVERED | SMTP受付後、同じ宛先／Project／EmailDeliveryへの保存済みdelivered feedbackあり |
| UNKNOWN | UNKNOWN結果、開始後の結果不明、SMTP受付後のsoft_bounce、フォーム終端記録の不一致 |
| FAILED | 明確な失敗、SMTP受付後のhard_bounce、不達 |
| IN_PROGRESS | 保存済み開始証跡があり結果がまだ確定していない |

メールfeedbackはHumanまたはProviderが記録した証跡で、LeadHiveによる独立検証とは区別する。delivered／hard_bounce／soft_bounceは発生日時・受領日時順の最新記録を利用。苦情・配信停止は到達分類として推定しない。もともとのUNKNOWNをdelivered記録だけで自動解消しない。UNKNOWN自動retryや送信再予約は実施しない。

予約・実行前、安全停止、取消、実行前失敗を別件数として表示。証跡のhash／version／対象等を結べない記録は証跡不一致として表示し、成功と推定しない。

## 読み取り境界

既存GET `/api/completion-cohorts/{id}/destination-diagnostics`に各Leadの`delivery_funnel`を追加。既存のProject ownership、viewer read／Agent拒否、固定分母・ページ上限・context hash検査を維持。集計方式は`cohort-destinations-c3-v1`。

`completion_delivery_metrics.page_history`はProjectと当該ページのCompany IDsで絞り込む。C2 bindingのversion、LeadDmPreparation ID、同一Project／Company、元snapshot hash、用途選択版・根拠・文面・channelと、ApprovalRequestのimmutable payload hashを照合。Human監査台帳と承認payloadが一致する履歴だけを承認済みと数える。メールはApprovedEmailReservation→EmailSendAttempt、フォームはApprovedFormDispatch→FormDeliveryの明示FKで読む。外部取得・HTTP・SMTP・状態変更・commitは呼ばない。

旧経路のEmailDelivery/FormDeliveryをCompanyが同じという理由だけで混ぜない。C2へ紐付かない履歴はこのFunnelの対象外で、従来のメール配信・フォーム履歴画面に残る。対象範囲を画面で明示する。

## UI

固定リストの窓口診断内に「Human承認と送信結果の履歴」を表示。現在DM READYと履歴Funnelを並べて比較する。Lead件数、試行件数、受付・到達・不明・失敗・結果待ち、実行前の停止を分離。受領responseの型・整数範囲・結果合計＝試行件数・承認／準備の包含関係を検証し、不正な応答を完了集計として扱わない。

## 互換性と限界

Model／Migration／送信API／設定の変更なし。承認の失効・消費・送信予約を集計から実行しない。現在のFunnel reportに未実装stageを推定して書き込まず、ページ診断の観察値として表示する。実100店舗の現在値・実送信・配信到達率は今回検証していない。過去実績の全件を一時点に固定した監査exportや金額換算は別工程。

## 検証

専用_test DBの合成データのみを利用。Human step-up承認は実既存APIで確認するが、送信結果はテストfixtureとして保存し、dispatch API・worker・外部接続を起動しない。予約のみ、取消後の承認事実、未承認、他Project、旧承認除外、フォーム受付／UNKNOWN／失敗、メール受付／到達／不達／UNKNOWN保持を検証する。desktop/mobileでは送信・承認endpointを禁止した準備と集計の画面テストを行う。

## 次工程候補

停止理由別に「次に完成へ進めるLead」を絞り込む作業キューを追加し、不足情報の確認・補完・下書き再準備の手間を減らす。Human承認と既存安全guardは維持する。

## 今回の確認結果

- 関連Backend 44件成功。C2準備・固定リスト診断・既存計測も含めて確認。
- desktop/mobile E2E 4件成功。説明修正後の集計画面2件も再実行して成功。
- Ruff、変更サービス2ファイルのmypy、Frontend typecheck/lint/build成功。
- 新しい専用DBでheadへのupgradeとmodel差分検証成功。E2E専用API serverの起動確認済み。
- 新規Migrationなし。実運用DB、worker、パッケージ、外部設定・実送信を変更していない。
- 既存Frontend bundleの500kB超警告は継続。
