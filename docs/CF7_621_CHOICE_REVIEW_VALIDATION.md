# CF7 6.2.1候補: 選択・同意・追加hiddenの隔離検証

基準: `b10393ca9075966100eee4dc14e756ec1dd41a79`。

## 完了した範囲

6.2.1表記の保存済み候補で観測したselect・同意checkbox・追加hiddenを、独立して記述したsynthetic HTMLで検証した。実サイトのHTML・会社情報・tokenをfixtureへコピーしていない。productionコード、版allowlist、API、UI、DB、migration、承認・送信処理は変更していない。

今回のゴールは入力確認資料の安全性と停止条件の再現であり、6.2.1用送信契約や実サイト対応の完成ではない。

## 上流ソースの確認

GitHub APIで公式リポジトリのタグと[比較](https://github.com/rocklobster-in/contact-form-7/compare/v6.2.0...v6.2.1)を確認した。最初の `v6.2` 指定は404だったため、実在する `v6.2.0` を使用した。

| Tag | Commit |
| --- | --- |
| v6.2.0 | 34acb3a6995b403274820c5ea42abd01b754c03b |
| v6.2.1 | f3c41966bde736bd557d81989780004728aa878b |

変更ファイルは `includes/swv/swv.php`、`load.php`、`package-lock.json`、`package.json`、`readme.txt`、`vendor/composer/installed.php`、`wp-contact-form-7.php`。SWVのschema-holder/script-loaderの読み込み位置とautoloadのパス指定が変わっている。フォーム生成・REST受付・reCAPTCHAのファイルはこの比較で変更されていない。

これは実サイトの版・addon・実行挙動を証明しない。PHP/JavaScript実行やdependency追加、上流コードの移植はしていない。HTMLの版表記は未信頼データである。

## 保存1件の再検証

キャッシュのSHA-256を既存snapshotと照合してから既存隔離解析器を実行した。後工程の値や現在のサイト情報を混ぜていない。

| 観測 | 件数 |
| --- | ---: |
| HTML記載6.2.1 | 1 |
| 追加hidden項目 | 4 |
| select | 1 |
| checkbox | 1 |
| 限定契約の対応外control | 1 |
| 生成した静的送信契約証拠 | 0 |
| Human確認 / 送信可能確認済み | 0 / 0 |

既存確認資料では用途選択が `CHOICE_REVIEW_REQUIRED`、同意が `HUMAN_CONSENT_REQUIRED`。hidden等の `DO_NOT_FILL` が11、送信者候補未入力が4、本文候補未入力が1。今回の再検証は送信者・件名・本文を空として分類し、実入力や選択をしていない。人数・項目数を停止理由の独立Lead数へ換算しない。

匿名成果物: [cf7-621-choice-review-20261009.json](results/cf7-621-choice-review-20261009.json)。個別会社・URL・連絡先・hidden値はGitへ含めない。

## 検証した境界

- synthetic fixtureは6.2.1表記、基本hidden 6項目、独自の追加hidden 4項目、必須select、privacy acceptanceを含む。実サイトの追加hiddenの意味を再現・証明するものではない。
- hidden値を確認資料へ混入させず、手動入力候補にしない。
- selectやcheckboxに既定selected/checkedがあっても、選択・同意を推測しない。
- inverse acceptanceは未対応のHuman確認を維持する。
- multipart/CF7を通常フォーム対応へ昇格させない。
- 6.2.1表記を既存6.2契約のplugin version/hidden値へ混ぜた入力を拒否する。
- file、外部control、hidden重複で送信契約を生成しない。

関連Backendテスト: **41 passed**。Ruff/format成功。既存6.2契約の不正構造テストでPydantic serializer警告14件が出たが、テストは成功。Frontend・API・migration変更はなく、それらのローカル再検証は今回行っていない。

## 残る実装と安全

selectの選択値・option/required/disabled状態を束縛する契約、acceptanceの意味とHuman確認の束縛、複数追加hiddenの用途・更新条件・送信値の検証、版別のimmutable payloadをまとめて設計・検証する必要がある。今回のfixture検証を根拠に旧契約へaliasしたり、unknown hiddenを送信値へ採用したりしない。

この検証で送信対応件数は増えていない。営業対象・用途・sales permission・suppression・opt-out・過去送信・senderの確認も未完了。外部企業GET・AI・実データDB書き込み・承認・Email/Form送信はすべて0。GitHub公式ソースのread-only調査だけを外部通信として行った。
