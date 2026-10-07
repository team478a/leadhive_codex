# Raw PilotのHuman確認・進捗表示

## ゴールと基準

基準 `codex/integration@f337a9b9b444e727ed927d9dfaec2b4d62613496`。[開始前CI 37594610366](https://github.com/team478a/leadhive_codex/actions/runs/37594610366) は全7 job成功を確認してから製品コードを変更した。

今回の限定ゴールは、代表候補の確認後に残る各回の取得結果を、同じ簡易画面でHumanが1件ずつ判定できること。精度測定の定義・Source取得・Lead Completion・送信を変更しない。DB Model・Migration・API追加なし。

## 確認方法

`/#raw` を開くと既存リストを表示する。最初は「代表候補を確認」で、同じRaw fingerprintの結果を代表表示する。これだけでは全Raw観測にHuman Truthがあるとは扱わない。

「各回の取得結果も確認」を押すと、反復取得・別Query・システムが対象外とした結果も含む全取得結果を順に確認できる。取得元・検索語・検索回を表示し、同じ対象はHumanが確認済み対象を選んでDUPLICATEとして保存する。判定を他の観測へコピーしない。モードは保存後の再読込でも維持し、別Benchmarkに切り替えたときは代表候補が初期値。ページ全体の再読込後は代表候補に戻る。

自社サイト以外とシステム判定した行には注意を表示し、簡易画面のCORRECTボタンを無効にする。対象外の理由や判断不能はHumanが確認してから記録する。これは画面上の支援であり、既存APIの判定を新しい自動正解ラベルで置き換えない。Viewerは閲覧のみ。

## 集計の見える化

既存report APIの取得結果総数・Human reviewed・未確認・CORRECT・Human照合IDのUnique Correct・Strict/Resolved Precision・重複率・判断不能率・作業秒数を、折りたたみ外に表示する。

分母は各回の取得結果で、代表候補数・独立店舗数・DM READY数ではない。未確認をUNCERTAINへ自動分類しない。0件や未測定率・時間はnull表示のまま。未確認がある場合は「一部」と明示し、収集全体の性能として確定しない。集計と表示件数が一致しない場合も再読込を案内し、全件確認を断定しない。Source/Query比較・Pair・Field Completeness等の詳細集計は維持する。

保存は既存Humanレビュー開始記録、snapshot hash、expected version、Project権限の検証とappend-onlyレビューを利用する。保存成功後だけ次へ進み、失敗時は現在候補に留まる。モード変更だけでレビューラベルを保存しない。

## 実データと安全境界

開始時の運用DBを読取専用で確認：Benchmark1 / RawSnapshot40 / RawReview0 / RawPairReview0 / Approval0 / EmailDelivery0 / FormDelivery0。過去のRaw観測Unique11と独立店舗の正解11を混同しない。Human Truthがないため実店舗のStrict/Resolved Precision・Error率は未測定null。Git集計JSONの既存測定結果を書き換えない。

画面表示に伴うHumanレビュー開始記録は既存動作であり、ラベル保存・送信承認ではない。実PilotについてCodexは判定ボタンを押さない。外部API・AI・Completion・承認・メール・フォーム送信0。outbound OFF、送信用worker未起動。Full Benchmark・次の精度改善は開始しない。

## 検証

既存Playwright構成・隔離テストDBのSynthetic候補のみで確認する。新規依存・AIテスト呼出しなし。

- 代表候補と全Raw取得結果の母数分離、未確認反復結果への非転記。
- 明示CORRECT / UNCERTAIN / DUPLICATE後のStrict/Resolved/重複率、確認時間。
- 保存後のモード維持、再読込後の判定保持、snapshot hash不変。
- システム除外候補の簡易CORRECT不可、手動モード変更で判定なし。
- 0件、null、失敗時停止、判定訂正、PC/Mobile横幅、禁止された外部・収集・送信リクエストなし。

最終テスト・CI結果は追記する。既存Frontend bundle 500kB警告は継続。

ローカルFrontend typecheck / lint / build成功。関連PlaywrightはPC/Mobile合計4件成功。初回は新規リスト作成完了前にfixture投入するテスト不備と、Mobileの再開ボタンのスクロール待機で失敗した。テストの完了待ちを追加し、集計を候補カードより下に配置して再実行。タイムアウトを増やしたり強制クリックで通したりせず、通常クリックで全4件成功を確認した。

実測Human Truthは未完了。次に利用者が保存済み候補を確認する必要がある。画面改善の完了と精度測定完了を分けて報告する。
