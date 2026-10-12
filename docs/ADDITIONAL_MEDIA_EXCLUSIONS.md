# 追加の掲載媒体・ランキング除外（2026-10-12）

## 基準と変更

基準 main: a27978be97b356f35967e55b99fcda4300dc1d2b（PR #95）。
ユーザーの画像で指摘された第三者の掲載媒体を、既存の収集判定へ追加した。
営業対象の店舗・企業の公式サイトとして取り込むことを防ぐ変更であり、送信判定は変更しない。

追加ドメイン（完全一致・正しいサブドメインのみ）:

- retty.me — [Retty](https://retty.me/)
- jalan.net — [じゃらん](https://www.jalan.net/)
- tabiiro.jp — [旅色の公式案内](https://page.line.me/423hdaeg?openerKey=profileRecommend&openerPlatform=liff)
- precious.jp — [Precious](https://precious.jp/)
- kit-press.com — [キットプレスについて](https://kit-press.com/concept)

これらは PORTAL_DIRECTORY / EXTERNAL_PLATFORM と分類する。通常収集・fair方式の
双方で、Rawを保持し、Companyに取り込まず、収集目標件数を消費しない。
既存のExternalPresence捕捉を維持する（媒体ごとの新しいPresence taxonomy追加は今回対象外）。
ドメイン集合は既存のTHIRD_PARTY_DOMAINSを使用し、設定項目・依存関係・DB変更はない。

未知ドメインでも「ランキングTOP10」「ランキング トップ50」「ランキングtop１０」の
組み合わせを ARTICLE / AGGREGATION_TITLE と判定する。単語「ランキング」だけでは除外しない。
当社サービス、ランキング改善、一般的な企業ページの保護と、未知ARTICLEの暫定保存を維持する。

## 検証

専用DB leadhive_classification_test（ローカル15449、_test末尾）を使用。

- pytest backend/tests/test_collection_discovery.py backend/tests/test_collection_runtime.py -q:
  94 passed / 2 skipped（private Raw入力未提供）
- pytest backend/offline_tests -q: 136 passed（外部通信禁止の合成データ）
- Ruff / backend format / 変更範囲mypy / API import / diff check: 実行結果をPRに記録
- 全Backend試験・最終head CI: CIにて確認。進行中の結果を成功とは扱わない。

境界試験では実ドメイン・www・listingサブドメインを除外し、
retty.me.example.testやURLのクエリに媒体名がある企業サイトは保持する。
通常/fairの統合試験では媒体5件＋未知ランキング1件のRaw8件すべてを保持し、
正常企業1件を保存、後続1件のみ目標到達扱いにする。

最初のpytestコマンドに存在しないtest_source_page_policy.pyを指定して失敗した。
その実行ではテストは走っていない。存在する関連試験へ修正し、上記結果を得た。

## 未確認と反映条件

画像のみでURLが不明な「TableCheck」「-」「大阪のイタリアンで季節の味覚とワインを愉しむ」は、
企業公式・掲載記事・予約ページを画像だけで区別できないため、推測で除外しない。
TableCheckの運営企業やサービス紹介ページまでドメイン全体で除外する変更は行っていない。
URLと保存済みRawが確認できれば、ページ単位の判定を検討する。

本番反映・既存データの削除や再判定・再収集・検索API・AI・フォーム操作・送信は未実施。
今回の検索による一次資料確認は媒体の種別とドメインの確認のみであり、収集精度測定ではない。
Human適合率・実データでの改善率は未測定（null）。
既存登録済み企業にこの変更が遡って適用されることはない。

PRをマージした後、APIとcollection-workerを更新すると、新規収集から適用される。
前のPR #95のデプロイも未確認のため、表示中の候補が最新規則で収集されたとは断定できない。

保存済みの掲載媒体をまとめて対象外へ移し、履歴を残して復元する方法は
[保存済み掲載媒体の整理](EXISTING_SOURCE_CLEANUP.md)を参照してください。
