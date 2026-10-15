# 企業画面とPC入力ランナーの受け渡し

基準: main@a33653d6a15486738a150e0427b64cefc7689d7b（PR #57、全CI成功）。

## 完成した範囲

企業詳細の「PCで保存HTMLの入力を試す」で、保存HTMLの入力JSONから、その企業向けの依頼ファイルを作成できる。PCの隔離ランナーはこのファイルを受け取り、企業・Project・依頼ID・HTML hash・依頼hashを付けた診断結果を出す。結果を企業画面で選ぶと、対応関係を検査し、既存Activity APIで記録する。

これはファイルによる受け渡しであり、クラウドからPCを自動起動する常駐コネクターではない。実サイト入力・送信・デプロイは未実施。クラウド側にブラウザやHTML取得機能を追加しない。既存読み取り専用PCコネクターは変更しない。

## 手順

1. 所有者/編集者が企業詳細で入力JSONを選ぶ。形式は[保存HTMLランナー](OFFLINE_FORM_INPUT_RUNNER.md)に従う。HTMLと入力値を含む依頼ファイルがダウンロードされる。クラウドへこれらをアップロードしない。
2. PCのfrontendで環境変数を設定し、実行する。

```powershell
$env:LEADHIVE_OFFLINE_FORM_INPUT = '1'
$env:LEADHIVE_OFFLINE_INPUT_FILE = 'C:\private\offline-input-依頼ID.json'
npm run trial:offline-form-input
```

3. `frontend/test-results/offline-input-runner/**/offline-input-result.json`を、同じ企業詳細の「PC入力試行の結果JSON」で選ぶ。整合する結果だけ自動で活動履歴へ記録する。依頼のmetadataは同じタブのsessionStorageに保持され、再読込できる。別タブ・別端末ではこのmetadataがないため取り込めない。企業ごとの最新依頼1件のみを保持する。

## 保存と安全性

- HTMLや入力値はブラウザ/PC内のみ。依頼ファイルは機密データとして保管する。結果は企業ID・Project ID・依頼ID・hash・状態・停止理由・入力数・時間だけを保存する。
- UIはALLOWEDを送信権限として渡さない。通常はUNKNOWN、既存営業NG/フォーム禁止があればPROHIBITEDを固定する。
- ランナーは既定OFF、外部通信と確認/送信操作を遮断する。実企業へのGET/POST、Human Approval生成、営業NG解除は行わない。
- 改変された依頼、別企業/Project/依頼の結果、HTML不一致、送信・承認・live fetchを報告する結果、不明状態を拒否する。自由文を保存せず固定形式のreasonだけを保存する。
- 結果ファイルは署名されていない。hashの照合は取り違え防止であり、機械実行の証明ではない。履歴は`PC_REPORTED_UNVERIFIED`（PC報告・未認証・未送信）として保存する。HUMAN_REPORTED、SYSTEM検証済み、BROWSER_VERIFIED、Human承認には昇格させない。
- 現時点の営業NG状態を結果取込で解除しない。入力成功からSendabilityや送信権限を変更しない。既存Activityの権限境界（所有者/編集者・Project）を再利用する。Agentに新しい書込scopeは与えない。

DB、Migration、backend API、依存関係、認証、送信設定の変更なし。

## 検証と残課題

Desktop/Mobileで、依頼作成→PC実行→結果照合、改変、別企業、hash不一致、送信済み結果拒否、営業NG、入力情報を履歴へ保存しないことを検証する。UI比較はlocalhostの独立harness、実行は合成保存HTMLのみ。既存フォームPoCを維持する。

2026-10-10: typecheck / lint / build成功（既存chunkサイズ警告あり）。既存58件＋受け渡し2件＝60件のブラウザテスト成功。UIのDesktop/Mobile 4件成功（Viewerの操作制限と営業NG固定を含む）。合成依頼ファイルをCLIで実行し、企業bindingを含む未送信結果の出力を確認。既存PoC集計成功。実企業アクセス・送信・承認・本番DB変更は0件。

クラウドからの自動PC起動、自動結果転送、署名付きの実行証明、実サイトの保存HTML取得は未対応。これらは認証された専用経路とCore permission再確認を要する。実サイトへの入力/送信を可能にする変更は別工程。現在のフォーム構造や最新の営業禁止状態を、この保存HTML試行だけで保証しない。
