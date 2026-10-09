# 一次収集精度調査 — SNS運用代行会社30観測

日付: 2026-10-09。コード基準: `7e875c317675a110733dae23921dd1624a06107e`。

## 評価データと分母

既存private `dist/sns-agency-readiness-pilot-20261008/candidate-audit-private.json` の40 Raw観測から、保存順で大阪15件・兵庫15件を選び固定した。重複を先に除去しない。これは**30社の正解企業ではなく30候補観測、25ドメイン**である。30社の独立正解企業を保証するデータセットの完成にはHuman照合が必要。

固定時のSHA-256は次のとおり。

```text
source: f743bbe5f059bf5951d675c2b6242fe1c029964643e312be0bccb771f1d2d327
cohort: e28cdcf53c32b6a0658e35ec095061a636b98b7fe8ad843292059994a5bf28b4
```

private保存先: `dist/ai-phase1-audit-20261009/cohort-30-private.json`、`aggregate.json`、`pure-tests.log`（元の作業ディレクトリ内、Git対象外）。個別企業名、電話、住所、候補URL、credentialsは本PRに含めない。元Rawファイルのhashが処理後も同じことを確認した。これらprivate成果物はPRだけからは再実行できないため、権限のある運営者が元データと照合する必要がある。

## 今回の実測

| 指標 | 実測 | 解釈 |
| --- | --- | --- |
| Raw観測 | 30 | 大阪15、兵庫15 |
| URL構文有効 | 30/30、100% | HTTP(S)正規化可能。到達性・公式性ではない |
| unique domains | 25 | 企業数ではない |
| 再出現domain観測 | 5/30、16.7% | entity duplicate rateとは区別 |
| 既知aggregator domain一致 | 0/30 | 未登録ポータルや記事ページの不在を保証しない |
| name/website候補/reference URL保有 | 各30/30 | 収集時の取得率 |
| address/phone/email保有 | 各0/30 | Rawのみ。後工程補完は加算しない |
| 保存済み過去ページ記録 | 25domain | FETCHED22、UNAVAILABLE3。今回取得していない |
| 正式Human review記録 | 0 | 会話での対象採用を各項目の正解ラベルへ変換しない |
| 対象企業適合率 | null | CORRECT等のHumanラベル待ち |
| 公式サイト特定精度 | null | 所有者・企業同一性の根拠待ち |
| 現在のURL有効率 | null | 新規GETなし |
| 企業重複率 | null | PairのSAME/DIFFERENT/UNSURE待ち |
| 問い合わせ先検出率 | null | 正しい会社/正しい窓口のHuman ground truthなし |
| フォームURL正確性 | null | 他の17社診断と分母を混ぜない |
| 収集1社あたり費用 | null | 価格・課金単位・正解企業数未確定 |
| 収集時間 | null | 今回新規収集しない。元ジョブの開始/終了を確認できない |
| offline正規化処理 | 3.61ms | このPCの小規模処理。ネット収集性能ではない |

過去FETCHED22/25を現在の有効率88%として報告しない。ドメイン一致だけで公式サイト/同一法人としない。nullを0件・0円にしない。

## Provider別に分かること

`docs/results/provider-role-collection-pilot-2026-10-08.json` は別の歴史的集計。基準 `cf419fe...`、working tree changesあり、Serper4 calls、raw40、saved30、26domain、地域横断重複domain4、過去GET72・取得23/26、Human reviewed0。今回30件/25domainとは選択単位が異なるため結合しない。価格未設定でcost=null。mentionやprovision contextをCORRECTとして使わない。

| Source | 現行用途 | 今回測定 | 制限 |
| --- | --- | --- | --- |
| Serper | 企業/サイト候補Discovery | 保存Rawの構文・項目・domain再出現 | 検索snippetだけで法人/地域/サービス提供を確定しない |
| Places | 店舗Discovery | mock mapping/pagination | SNS運用会社との適合率未測定。保存・表示条件確認が必要 |
| gBizINFO | 法人Identity/補完 | 実装確認のみ | 店舗Discoveryと同じ件数目標で比較しない |
| URL/CSV | 利用者提供候補 | parserの隔離テスト | 自動Discovery精度へ算入しない |

[Google Places保存・表示ポリシー](https://developers.google.com/maps/documentation/places/web-service/policies)では一般のコンテンツ保存に制約があり、place IDの例外がある。既存実装を条件適合と仮定せず、契約とデータ保存範囲を確認する。今回新規Places呼び出しも保存も行っていない。

## Human評価手順（未実行）

既存Raw Review/Pair Labelを再利用する。Humanは名称/法人/地域/サービス提供/公式性を証拠付きで確認し、PRIMARY/SERVICE等の用途分類とCORRECT/WRONG_INDUSTRY/WRONG_AREA/WRONG_ENTITY/PORTAL/DUPLICATE/CLOSED/UNCERTAINを別項目として記録する。作業時間・reviewer・snapshot hashを保持する。閉業などを推測で判定しない。

1. 30観測を盲検評価。情報不足はUNCERTAIN、公式性不明はUNKNOWN。
2. 25domain内・横断の候補Pairを確認。SAMEだけを企業重複の正解へ使用する。
3. 窓口の会社一致、用途、営業禁止、共有窓口を別に確認。存在は営業許可を意味しない。
4. Strict precision = CORRECT / 全review済み。Resolved = CORRECT / (review済み - UNCERTAIN)。分母ゼロはnull。
5. 未review件数とreview coverageを併記。Query/Source/Runを保持し、補完後の結果をRaw正解にしない。
6. 追加のGET/API検証は対象・上限・見積・保存条件を提示した後に別工程で行う。今回のPRは実行しない。

公式サイト精度の分母は評価済み候補URL、問い合わせ検出率はHumanが正しい窓口ありと確認した対象、フォームURL精度は検出URLのHuman評価済み件数。窓口が存在しない対象や未確認を成功として扱わない。完全母集団がないためrecall/coverage=null。

## 安全性・完了範囲

今回の企業向け新規外部request0、AI calls0、DB writes0、メール0、フォーム0、Approval0、Completion jobs0。workerは起動せず、送信flagを変更していない。Git/GitHubおよび公式資料取得はこの企業処理件数に含めない。

**データ固定・offline測定・評価設計は完了。Human truthを必要とする一次収集精度の数値化は未完了。** これを精度検証PASSと扱わない。最優先はHuman評価であり、収集ルール・モデルの変更はその後に一項目ずつ判断する。
