# 業種の別名を使ったHuman確認支援

## ゴールと基準

基準: `codex/integration@d41af30379012f8fb1edbc99c9348d5f7f0b300b`。
開始前の [CI 37587880487](https://github.com/team478a/leadhive_codex/actions/runs/37587880487) は全体成功。
用途・目的別エンジンStage 3の限定工程として、業種の表記違いから保存済み公式サイトの確認候補を表示する。地域の既存Evidence判定は変更せず回帰確認する。求人現在性・媒体の自動取得・実データPilotは開始しない。

## 利用方法

ターゲットプロファイルを編集し「業種確認に使う別名（1行に1業種）」へ入力する。標準プロファイルは複製して設定する。

```text
美容院: 美容室, ヘアサロン
運送会社: 運送業, 貨物運送
```

これは入力例であり、業種固有のコード・初期設定ではない。最大20業種、1業種10別名、各表記2〜100文字。利用者が業種ごとに設定する。自動的に逆引き・推移展開しない。

企業収集の「対象条件を確認・分類する」で業種条件を確定し、確認待ちの企業を開くと、公式サイトの保存済み本文から条件の表記・その別名を含む候補を最大3つ表示する。見つかった表記、根拠URL、取得日時を確認できる。人がページと当該企業・店舗の事業内容を確認してから既存レビューを保存する。

## 判定境界

- 新規の外部検索・GET・AI呼出しなし。検索キーワード・query expansion・目標件数・検索予算を変更しない。
- 有効な公式サイト確認、保存本文の出典、取得日時（24時間以内）、解析完了が必要。出典不明・他ドメイン・期限切れ等は候補を返さない。
- 別名は文字列として正規化・エスケープして扱う。正規表現やWeb本文からの命令として実行しない。否定表現・顧客事例・求人文にも含まれ得るため、存在だけでMATCHにしない。
- HumanレビューがなければINDUSTRYはUNKNOWN/REVIEW_REQUIREDのまま。NO_MATCH・取り消し・期限・企業変更に関する既存レビューの権威を維持する。
- 別名設定はHumanの事業確認を代替しない。設定変更で自動的にHumanレビューを作らず、確認済み条件の意味も変更しない。
- 企業のProjectに結び付くTargetProfileだけを使用。別利用者のカスタムプロファイル、不正・無効設定は採用しない。Viewerの読み取り、Human/Agent境界を既存APIで維持する。

## 保存・互換性

既存TargetProfileのJSONB `scoring_rules` に予約キー `industry_review_aliases` を格納する。DB Model・Migration・新APIなし。スコアルールJSON編集欄と別名入力欄を分離し、予約キーの手動重複指定は拒否する。空欄保存は当該設定を削除する。

AI分析contextへこの予約キーを渡さず、rank_thresholds等の従来スコアルールは保持する。既存JSONを読み取るAPIは維持し、不正な別名設定の新規保存は422。旧不正設定から確認候補は生成しない。既存Profile cloneで設定を再利用できる。

保存直後、一覧の再取得前に再編集すると古い値を表示する既存の競合も修正した。再取得が完了してから編集画面を閉じる。API保存データを失っていた問題とは区別する。

## 検証と制限

関連Backend（業種・地域・Human事実レビュー）62件成功、AI解析の既存テスト5件成功。追加の旧設定互換テストと最終CI結果は下記へ追記する。mypy4ファイル、Ruff/format、Frontend typecheck/lint/build成功。PC/Mobile E2E2件成功。最初の2件失敗は保存後の一覧再取得競合を再現し、製品修正後に再実行した。skip/timeout延長による回避なし。

Docker停止により最初のローカルDBテストは接続不能で未実行。その後Dockerと既存DBコンテナだけを再起動し、初期化せず検証した。

Human Truth・実データ業種判定精度・作業時間削減率は未測定。本文に別名がなければ「不一致」ではなく確認候補なし。別名追加を収集精度改善の実測成果とは扱わない。Frontend bundleの既存500kB警告は継続。

製品の外部API/AI call、Completion job、送信承認、メール・フォーム送信はいずれも0。outbound OFF、送信用worker未起動を維持。HotPepper・求人媒体の取得許諾、求人現在性、媒体店舗同定、Full Benchmarkは保留。

## ローカル追加検証

業種レビューの追加・互換テスト24件成功（地域等を含む初回62件とは重複あり）。Backend mypy4ファイル成功。古い予約キーの不正JSONもGET可能で、候補生成には使用しないことを確認した。

起動中APIを実装HEAD `9ddbd853be6f69217e60c94bf846df5e6e0858e9` へ更新。保存前後のCompany0 / RawSnapshot40 / RawReview0 / Approval0 / EmailDelivery0 / FormDelivery0は不変。送信用worker未起動。画面サーバーは通常の管理されたターミナルで `http://localhost:18985/` に起動する。バックグラウンド起動は自動承認レビューのポリシーで拒否され、管理されたターミナル起動は許可された。

画面HTTP200、同じ画面の `/api/health` で `status=ok / database=ok` を確認した。

## 最終CI

Backend実装 `009e980`、UI・E2E `166742f`。検証HEAD `9ddbd853be6f69217e60c94bf846df5e6e0858e9` の [CI run 37590459996](https://github.com/team478a/leadhive_codex/actions/runs/37590459996) は全7 job成功。

- Backend: 1,286 passed / 45 skipped / 50 subtests passed。
- E2E: 74 passed / 2 skipped。今回の業種別名設定・保存再読込・Human確認・取り消しはPC/Mobileとも成功。既存skipを未検証機能の成功と扱わない。
- Ruff / format / mypy / API import、Frontend typecheck / lint / build成功。
- Migration upgrade / downgrade・upgrade / Alembic check成功。DB Model差分・Migration追加なし。
- Windows packageおよびローカル模擬フォームHTTP acceptance成功。実企業への送信なし。

結果追記は文書だけで、CIが検証した製品コードから変更していない。限定ゴール完了。実データ精度・求人現在性・媒体取得許諾・指定Pilotは未完了のまま停止する。
