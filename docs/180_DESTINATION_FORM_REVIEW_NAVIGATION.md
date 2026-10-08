# 窓口用途確認とフォーム入力確認の往復導線

## ゴール・基準

基準 `codex/integration@c74adc683fe80e7b62f321e5dd2ee599aae98ba1`。同じ企業詳細にある「窓口の利用可否と理由」と「フォーム入力確認」を対象URLでつなぐ。Humanが画面を探し直す操作を減らし、確認・窓口選択・承認・送信は代行しない。

## 実装

- フォーム入力確認に「このフォームの窓口用途を確認」を追加。該当企業の一致する窓口詳細を開き、画面移動とフォーカスを行う。
- 窓口用途確認に「このフォームの選択・同意を確認」を追加。同じ企業の該当フォーム入力確認へ戻る。
- URL照合は画面移動専用。originとqueryは一致必須。fragmentと末尾のpathスラッシュは既存窓口台帳のURL保存仕様に合わせて扱う。www/別ドメイン/別scheme/別path/異なるqueryを同じと推測しない。
- 一致対象が0件または複数の場合は移動せず、対象を特定できない理由を表示する。候補整理やフォーム再解析は自動実行しない。
- hash routeは変更せず、企業・Project選択を変えない。URLをCSS selectorへ埋め込まない。企業ごとのsection内に照合範囲を限定する。
- 用途・対象範囲・根拠URL・本文・同意値は自動入力しない。用途確認、選択/同意確認、送信承認は別の操作のまま。
- Viewerは読み取り画面の往復ができる。用途や選択の保存権限は既存API/UIで維持。

Frontendのみ変更。Model・Migration・API・送信経路・判定ルール変更なし。画面移動でPOSTや外部アクセスは発生しない。

## 自社3候補のREAD ONLY検証

正本: `docs/results/self-use-destination-form-navigation-2026-10-08.json`。

保存済みProfileと既存ContactDestination/LeadDestinationLinkを照合。厳密な元URL文字列の比較では2社に末尾スラッシュ差があった。既存 `collection.canonicalize_url` と窓口台帳の保存仕様を確認し、画面移動だけの照合を整合させた。

| 指標 | 結果 |
| --- | ---: |
| 対象フォーム | 3 |
| 一致する登録済み窓口あり | 3 |
| 登録済み窓口なし | 0 |
| 営業可否 | UNCERTAIN 3 |
| Human用途確認 / 選択の記録 | 0 / 0 |
| Approval / Email / Form送信 | 0 / 0 / 0 |
| 外部アクセス | 0 |

DB READ ONLYを強制。Company/Profile/Field/Draft/Approval/Delivery/Job/解析Log/Choice/DM Preparationの前後hash一致。実データの窓口候補整理・再解析は行っていない。個別URL/IDはGit管理外の `dist/self-use-live-preflight-*/destination-form-navigation-private.json` のみに保存。

## 検証

Frontend typecheck・lint・build PASS（既存bundleサイズ警告）。Backend窓口用途・窓口選択・Sendability・入力確認API回帰58件が専用テストDBでPASS。Migration追加なし、テストDBの既存Migration upgrade確認。

PC/Mobileの既存Playwrightで、往復・フォーカス、用途/根拠の初期値が未確認のまま、移動中のPOSTなし、異なるqueryで停止、fragment/末尾スラッシュ対応、複数一致で停止、再読込、既存手動選択/Group記録、Viewer保存不可を確認。4件すべてPASS（1.7分）。PC/Mobile viewportで導線表示を目視確認。実企業GETなし。窓口候補整理やHuman記録は専用test fixtureのみで実行。

ローカル画面へ既存Vite更新で反映。Backend変更なしのため再起動不要。outbound OFF、送信worker未起動を維持。GitHub Actionsは未pushのため未確認。

## 完了範囲

確認する画面同士の引継ぎを完了。実データのHuman用途確認、同意、窓口選択、承認は未実施。3社のUNCERTAINは解除せず、技術未対応のフォームを送信可能に昇格させない。実送信はNO-GOのまま。

次はHumanが対象ページで窓口用途と選択・同意を確認し、管理画面の既存機能へ記録する工程。これを自動で実行しない。
