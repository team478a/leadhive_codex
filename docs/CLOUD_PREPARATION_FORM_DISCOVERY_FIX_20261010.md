# クラウド営業準備：フォーム探索・停止理由の改善

## 基準と範囲

- 実測対象：検索語比較A・大阪SNS運用代行の保存済み5社。
- 実測時コード：main `40a630f3224a9192b63b6bc362e83c2a23337801`。
- 修正基準：main `ad0ca17`（PR #50統合済み）。
- 修正ブランチ：`codex/form-preparation-diagnostics`。
- 追加検索0、AI上限10、最低営業スコア60、フォーム下書き準備。
- 実送信・Human承認・本番反映は対象外。

## 修正前の実測

| 指標 | 実測 |
|---|---:|
| 保存済み候補 | 5 |
| 処理完了 | 5 |
| AI判定 | 5 |
| 追加検索 | 0 |
| 要確認 | 3 |
| 営業禁止による停止 | 1 |
| 営業適性条件未達 | 1 |
| 下書き完成 | 0 |
| 承認・メール送信・フォーム送信 | 0 |

要確認の理由はフォームURL未発見1、CAPTCHA1、ファイル送信フォーム判定1。
会社名の文字化けも1件観測した。これらはシステムの実測結果であり、
Human Truthによる正答率評価ではない。費用・トークン数は未測定。

## 原因と変更

### 問い合わせURLがない場合の探索スキップ

`sales_preparation.prepare_item` は `company.contact_url` が空欄の場合、
`analyze_company_forms` を呼ばなかった。一方、既存アナライザーは、
問い合わせURLがなくてもサイトのリンクと候補パスからフォームを探索できる。

フォーム準備ではURLの有無に関係なく既存探索を呼ぶ。
検索APIの追加呼び出しはない。`allow_ai=False`、探索済みチェックポイント、
同一サイト制限、robots、SSRF、ページ数・時間上限を維持する。
フォームを発見しても送信承認にはならない。安全判定後に未承認の下書きだけを準備する。

### multipart とファイル入力の混同

`enctype=multipart/form-data` だけで「ファイル送信用」と表示していた。
有効なファイル入力がない場合は「multipart形式の送信経路が未検証」と表示する。
実ファイル入力がある場合は従来の理由を維持する。

**multipart対応は追加していない。どちらも `supported=False` のまま。**
BEASTARの実フォームについて、ファイル入力の有無や改善後の操作可否を確認したとは報告しない。

### 日本語HTMLの文字コード

SafeFetcher はHTTPのcharset指定がない場合、HTML内の指定を読まずUTF-8として復号していた。
既存BeautifulSoupのUnicodeDammitで明示HTTP charset、HTML metadata/BOMを考慮する。
新規依存はない。サイズ・時間・取得先の安全制限を変更しない。

今回観測した文字化けの実サイト原文は保存されていないため、その会社の
文字化け原因が文字コード指定だったと断定しない。再現テストで検証した修正である。

## テスト

- 問い合わせURLが空欄でもForm Intelligenceを呼ぶ。AI fallbackは使わない。
- 模擬サイトのトップにリンクがなくても候補パスでフォームを発見する。
- 模擬フォームの正常ケースでは未承認下書きだけを作る。
- 営業禁止は停止、CAPTCHAは要確認。いずれも下書き・承認・送信を作らない。
- multipartはファイル入力の有無・disabledで理由を分け、未対応状態を維持する。
- UTF-8、CP932/Shift_JIS、EUC-JP、HTTP charset優先、UTF-8 BOMで日本語名・問い合わせリンクを抽出する。
- 既存の収集、Form Intelligence、Contact Permission、営業準備の回帰テストを実行する。

結果：営業準備・Contact Permission **20 PASS**、スクレイパー・Form Intelligence・
Contact Discovery **48 PASS**（合計68）。Ruff全backend、format全backend、変更3サービスの
`mypy --check-untyped-defs --follow-imports=silent`、compileall、diff checkもPASS。
初回の正常模擬フォームで「要確認」を期待したテストは、実際には未承認下書き準備まで
進んだため期待値を修正し再実行した。営業禁止・CAPTCHAの期待値は変更していない。
GitHub全CIはPR作成後に別途確認する。

### 統合後のCI確認

PR #51の全体Backend CIで `test_two_contact_offline_boundaries` の旧表示文言の
期待値1件が失敗した（2196 PASS、47 SKIP、1 FAIL）。このテストはファイル欄がない
multipart模擬フォームに「ファイル送信用」を期待していた。期待値を「multipart・未検証」
に変更し、ファイル送信用ではないことも確認する。
`supported=False`、実送信パーサーの `manual_required`、Human未承認の検証は維持する。
クラウド収集ワーカーの確認時点の配備は `40a630f` であり、PR #51統合後のコードは
まだ反映されていなかった。ブラウザ接続が応答しないため配備・実データ再検証は未実施。

## 制限と次工程

- DB migration、UI、Human Approval、送信経路の変更なし。
- 保存済み企業情報の手動修正・再解析・承認操作なし。
- 実サイトへの追加GET、検索API、AI API、送信は修正作業で実行していない。
- CAPTCHAは依然としてHuman Required。回避しない。
- このPRは探索漏れと理由表示を改善する。実データのDM READY増加は未実証。
- レビュー・統合後に、フォーム未発見の1社を先に上限付きGETで再確認する。
  multipartの1社は保存診断または承認されたGETで実ファイル入力を確認し、
  ブラウザ候補として扱う。今回multipart送信の実装へは進まない。
