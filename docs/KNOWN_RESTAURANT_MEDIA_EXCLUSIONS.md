# 飲食店収集での既知媒体除外

基準main: `302d8db921b41dcba7b2197f88a292b36c94c605`。

利用画面でまとめサイトがCompanyとして表示された理由は、以下4媒体が既存のTHIRD_PARTY_DOMAINSに未登録だったため。記事タイトルだけによる一次除外を広げず、確認された掲載媒体のドメインを既存の判定へ追加する。

- lemon8-app.com
- livejapan.com
- gurumeguide.cpay.jp（cpay.jp全体は除外しない）
- travelbook.co.jp

Serperの通常収集・fair schedulerの両経路でRawを保持し、Company登録と目標枠の消費を防ぐ。正しいサブドメインは除外するが、別ドメインの接尾辞やパラメーター内の文字列は除外しない。未知の記事は現行の二段階判定へ残す。公式店舗の「当店おすすめプラン」等をタイトルだけで弾かない。

今後発見した媒体は、収集画面の「再収集しない掲載媒体」で根拠URL・理由・ドメイン全体の確認を登録できる。このProjectで以後の企業登録・Web解析を省く。検索結果へ再出現することはあり、検索APIからの取得自体を禁止する機能ではない。

保存済みCompany・Raw・Human判定は変更しない。除外ルールは営業NGやSuppressionとは別概念。媒体除外を営業禁止の証拠にしない。Web・送信・承認・DBの仕様変更なし。

検証: 専用test DBのcollection_discoveryとsource_exclusions 90 PASS、Ruff・変更範囲mypy・diff確認成功。検索API・外部サイトへのアクセス・送信なし。今回の新規媒体による実データ精度向上は未測定。マージ後のAPI・収集workerの配置が必要。
