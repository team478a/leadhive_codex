# 実ページ入力：未送信結果の自動返却

## ゴールと基準

基準main: `824d5c4cf29ee605b5b520e6020f2fb18ae70294`。
作業ブランチ: `codex/live-input-result-transfer`。
開始時OPEN PR #4 / #5 / #35との重複なし。
未コミット変更のある元のcodex/integrationを変更せず、クリーンな別worktreeから開始。

PCで入力後、結果JSONを選び直す操作を省く。PCの自動起動・常駐Agent・フォーム送信は対象外。

## 操作

1. 企業詳細で入力内容を確認し「未送信のPC結果をLeadHiveへ自動で戻す」を選ぶ。
2. 入力のみの確認をして依頼JSONを保存。
3. 最新PCランナーで依頼を開き、独立して指定したLeadHive HTTPS URLとINPUTを確認。
4. PCで入力・読み戻しが終わると、未送信の診断結果だけを1回返す。
5. PCまたはスマートフォンの企業詳細で「PC結果を確認」。結果JSONの手動取込は不要。

選ばない場合、古い依頼の場合、転送失敗・期限切れの場合はローカルの結果JSONを取り込む。
通信失敗を理由に企業フォームの入力を自動再実行しない。自動転送失敗は入力失敗と区別してresult-transfer.jsonに保存。

## APIと安全境界

- 発行APIに任意のautoReportを追加。初期値false。入力payload hashの定義は変更しない。
- auto_reportはCore側のMAC保護済み依頼へ保存。依頼ファイルだけを書き換えて転送権限を得られない。
- POST `/api/live-input-trials/{trial_id}/result`: 既存の15分・1依頼専用tokenを使用。
- GET `/api/companies/{company_id}/live-input-trials/{trial_id}/result`: Browser HumanのProject境界。viewerも閲覧可能。
- Cookie混在、無関係Bearer、改ざん、失効、取消、発行Humanの権限喪失、別企業・別Project・別hashを拒否。
- LOAD/INPUTの単一実行境界は維持。未開始の成功報告を拒否。受理後REPORTEDとなり入力には再利用不可。
- Activityの結果作成と依頼のREPORTED遷移は行ロック下の同一transaction。
- 同じ報告の再到達は既存結果を返し、異なる結果への上書きを拒否。ランナー自体は自動retryしない。
- 結果GETは依頼MACと保存結果hashを照合。通常Activity編集による結果改ざんを検出。
- sent/approvalGranted/executionAllowed/confirmationReachedは厳密なfalse。成功は確認項目あり・通信遮断違反なし・STOP_BEFORE_CONFIRMATION_OR_SENDのみ。
- 転送は既存のDNS検証・IP固定・TLS検証・応答サイズ/時間制限付きHTTPS経路を再利用。リダイレクトしない。
- 企業ページ・ブラウザへtokenを渡さない。入力本文、メール等の入力値、tokenを報告本文・Activity・ログに保存しない。
- 報告はPC_REPORTED_UNVERIFIEDのまま。電子署名やHuman Approval、営業許可を意味しない。
- 実フォームへの外部POST、送信・承認経路の変更、APIキー利用、feature flag変更なし。
- DB変更・Migrationなし。既存Activityを再利用。live_form_input_enabledは引き続きdefault OFF。結果閲覧は無効化後も可能。

## 互換性・提供条件

既存の依頼ファイルにautoReportがなくても新ランナーは手動経路として受け付ける。
対応API・画面・最新PCランナーを揃えて利用する。旧ランナーは新しいautoReportフィールドを認識しないため更新が必要。
PC起動と依頼JSON選択は残る。クラウドからPCを直接起動する仕組みは今回追加しない。
外部送信OFF、実ページ入力機能OFFは勝手に変更しない。
PRレビュー・マージ後のクラウド反映と管理者による入力専用有効化が必要。実環境の自動転送は未検証。

## 検証

専用PostgreSQL `leadhive_live_report_20261011_test`のみ使用。通常DB・保存済み企業を変更しない。
- pytest: live input / PC transfer 61件PASS。
- Package integrity / PowerShell構文: 7件PASS。
- Ruff check、変更Python format、変更API mypy、API import: PASS。
- Desktop/Mobile UI 20件PASS。未着・別企業結果・手動fallback・自動転送の明示選択を確認。
- 既存form-lab安全回帰: 184件PASS。
- Frontend typecheck / lint / build: PASS。既存chunkサイズ警告は改善対象外。

最初のBackendテストでCookie混在の拒否期待を401としていたが、既存middlewareが403で先に拒否するためテスト期待を修正。実装の拒否条件は緩和していない。
テスト用の転送関数の引数型をLiveTaskへ修正。CIは最終PRチェック欄を正本とする。
実サイトGET・入力・フォーム送信・メール送信・承認: 今回0件。模擬フォームのみ。
