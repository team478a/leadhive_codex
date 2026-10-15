# Phase 3：適合2候補の現在のフォーム構造確認

## 基準・承認・範囲

2026-10-09。最新main `6484249ed19c82311ad5f800d196ed0e5831b1cc`。利用者が「候補12・20、トップと問い合わせ、最大20 GET、入力・POST・DB登録・承認・送信なし」という計画への続行を指示したため、限定GETを実行した。従来の27候補へ広げず、既知の4対象URLと同hostのrobots.txtだけを許可した。

実装コードは変更していない。private実行scriptは対象サービスのファイルを固定mainのsourceと照合した。既存 `TargetFetcher` のHTTPS・公開IP pinning・TLS検証・robots制限・サイズ/timeout・no redirect/no retryを使用。request開始前にGETを記録し、最大20・hostごと10を強制した。今回実数は8 GET（robots4、HTML4）で、すべて成功。外部JS/iframe/API/アセットを取得・実行していない。

## 集計

| 項目 | 件数 |
|---|---:|
| 対象企業候補 | 2 |
| トップ / 問い合わせHTML取得 | 2 / 2 |
| contact form観測 | 2 |
| 同domainトップに問い合わせリンク | 2 |
| CAPTCHA marker未観測 | 2 |
| 今回のページで営業禁止rule検出 | 0 |
| 確認ボタン観測 | 1 |
| 通常POST parserでcompatible | 0 |
| REVIEW_REQUIRED | 2 |
| Sendability READY / DM READY | 0 / 0 |

2社の対象適合は既存Human判定を維持。同domainで会社名・問い合わせ導線の一致を観測したが、法人同一性の独立したHuman確認とはしない。marker未観測をCAPTCHA不存在や営業許可の最終確定にしない。suppression・過去送信・現在のHuman送信承認は未検証。

## 構造1：協業選択肢付き・確認画面型

本文上の協業選択肢がDOMでも存在する。native selectのlabel/valueを確認したが、選択操作はしていない。名前・フリガナ・email・種別・知った経路・予算が必須。会社名・電話・website・本文は今回DOMでは任意。予算の選択肢は購入予算帯で、「未定」「提案側」「予算なし」は存在しない。OEMを販売する側の提案として適切な選択値は未確認であり、架空の予算を選ばない。

formは同domain POST、`multipart/form-data`。file inputは0。既存compatibilityの「ファイル送信用フォーム」という理由はenctypeによる保守的な停止であり、実際に添付入力を要求しているとは解釈しない。確認ボタンは `type=submit`、nameありで、「同意して送信内容を確認する」。外部contact.jsの記載はあるが、取得・実行していないためJS依存や次の確認画面・token・次actionは未検証。以前の「JavaScriptボタン」という説明はDOM再確認前の推測であり、標準submitの観測へ訂正する。

氏名のフリガナは利用者から未提供。氏名から推測しない。知った経路・協業種別は候補を提示できるが最終Human選択は未実施。privacy同意の確認・送信者情報・本文・承認も未実施。技術経路と目的に合う予算の問題が解消するまで停止する。

## 構造2：CF7 6.2.1・複数checkboxグループ型

独立したoffline parserでCF7候補・version 6.2.1・同origin REST link・基本hidden markerを観測した。hidden値はprivate HTMLに保持し、Git成果物へ出していない。既存の検証済みmanaged contract（6.1.6等）への一致は未確認で、通常parserはCF7として停止した。

18 checkboxが4つの異なるname配列に分かれ、全体の「お問い合わせ項目 必須」というgroup見出しを共有する。すべての選択肢を必須として扱ったり、4グループすべてを選択する仕様とは判断しない。既存parserもグループ範囲確認待ちを返した。名前・emailは必須、会社名・電話・本文はDOM上任意。個別required=trueの合計は前構造6＋本構造2で8だが、未確定の必須groupを除いた数であり、完全な必須入力数ではない。

「その他お問い合わせ」があるが、OEM販売提案を受け付ける根拠にはならない。顧客向け無料相談窓口の用途確認が必要。CF7のscriptやRESTへアクセスせず、候補contractを実行可能へ昇格しない。Codex支援タスクやブラウザ入力も開始しない。

## 成果物・安全

- 匿名集計：`docs/results/phase3-two-contact-get-review-20261009.json`
- private：`dist/phase3-two-contact-get-20261009T104641Z/`
- 固定計画・GET記録・robots応答・新しいHTML snapshot・解析field・fingerprint・構造検証結果をprivate保存。旧Raw/HTML/レビューを上書きしない。

search/AI API費用0、通信費null。AI0、search0、入力0、POST0、DB書込0、Approval0、Email0、Form送信0。評価processのoutbound OFF、worker起動なし、本番フラグ/worker変更なし。新しいlive観測は保存済み入力に基づく旧Benchmark値へ混ぜない。

## 結論・次の候補

両候補ともフォームが存在することと、自動入力・確認・送信できることは別。今回の2社を代表性のある全体対応率として扱わない。

1. 協業用の適切な窓口または予算条件をHumanが確認する。条件を創作して完了扱いにしない。
2. CF7の複数checkbox groupと6.2.1の静的contract差分を保存HTMLで評価する。managed fixtureで検証してから対応追加を検討する。
3. multipart＋確認画面の経路は別のoffline fixtureで検証する。今回実フォームへの確認POSTは実行しない。

今回の範囲ではいずれも送信対応実装へ進めず、結果を提出して停止する。サイトの追加探索・送信・Codex task起動は今回のGET承認に含めない。
