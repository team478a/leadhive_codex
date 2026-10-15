# Phase 3：2候補のフォーム停止原因・オフライン検証

## 今回のゴール

保存済みHTMLだけを使って候補12・20の停止原因を再現し、独立した匿名fixtureで安全境界を回帰検証する。実フォーム対応を有効化する工程ではない。基準main：`6484249ed19c82311ad5f800d196ed0e5831b1cc`。

前工程の限定GET結果は `PHASE3_TWO_CONTACT_GET_REVIEW.md`。今回の新しい外部request、検索API、AI、入力、承認、Email/Form送信はすべて0。実データのDB・worker・設定は変更せず、private HTMLはhash照合で不変を確認した。test harnessだけが専用 `_test` DBに既存migrationのupgrade/checkを実行する。本番DBとは区別する。

## 保存HTMLでの再現結果

| 項目 | 候補12 | 候補20 |
|---|---:|---:|
| 通常送信compatibility | 非対応 | 非対応 |
| 独立選択項目 / group数 | 3 | 4 |
| 自動選択された項目 | 0 | 0 |
| CF7 version | 該当なし | 6.2.1 |
| checkbox DOM数 | 0 | 18 |
| 実行contract evidence | なし | なし |
| 実行権限 / 承認可能へ昇格 | なし | なし |
| Raw HTML変更 | なし | なし |

`docs/results/phase3-two-contact-offline-replay-20261009.json` に匿名集計とsnapshot hashを保存。レビュー提案には架空のtest送信者だけを使用。提案結果をDBへ保存しない。個別会社名・連絡先・hidden値・実HTMLはGitへ入れない。

## 候補12：multipart・確認ボタン

multipartのため既存経路は停止。file inputが0でも停止することを確認した。「ファイル送信用」という現在の表示はenctype由来であり、添付必須の証拠ではない。予算・種別・発見経路はHuman選択待ち。フリガナは未提供で、氏名から推測されない。

独立fixtureからenctypeだけを削除するとnative compatibilityはsupportedになる。この判定は標準POST形状の検査であって、確認画面の到達・token・次action・最終送信との区別を保証しない。したがって**enctypeの停止だけを緩和する修正は採用しない**。実候補は今回も非対応のまま。次工程でmanaged fixtureの確認画面protocolを設計し、最終POST前に承認payloadと一致することを検証する必要がある。

## 候補20：CF7 6.2.1・cross-name checkbox group

4 name配列・18選択肢を一つの必須見出しが覆う。review materialは4項目とも `GROUP_SELECTION_REVIEW_REQUIRED` を返す。個別required=falseは「任意」という意味ではなく、name単位で表現できないgroupの要件が未確定であることを示す。

匿名fixtureは事前checkedを含む場合も含まない場合も、自動選択せずHuman確認待ちにする。6.2.1を既存6.2等のmanaged contractへ置き換えず、contract evidence・execution・approval適格を与えない。18件のinvalid nameは厳しい既存contractのname制限による数であり、サイトHTMLが壊れていると判断しない。

## 追加した回帰テスト

`backend/tests/test_two_contact_offline_boundaries.py`：6ケース。

- multipartでfileなしでも通常parseを拒否。
- 確認ボタンはDOM上submit、draft提案では入力しない。
- 予算・種別・発見経路を自動選択せず、フリガナを創作しない。
- enctype削除だけでは確認画面protocolが検証されないことを明示。
- cross-name groupの18選択肢を4review項目へ保持し、checked既定値も自動採用しない。
- CF7 6.2.1は証拠なし・実行なし・承認適格なし。専用suiteのoutbound/legacy送信flagはOFFで、socket接続とDNS呼出を拒否。

静的CF7 inspectionは既存isolated parserを利用し、HTTPを呼ばない。testのfixture markupは独立作成で、実siteからコード・hidden値・文面をコピーしていない。

## 品質確認

- 関連6module：119 tests passed（追加6件を含む）。
- Ruff：backend全体成功。format：462 files成功。
- 既存test harnessによる専用test DBのmigration upgrade/check成功。migration追加なし。
- API application import成功。runtime/UI/model/API/worker変更なし。
- 既存CI対象のfields / review material / static inspectionのmypyを確認。
- 追加でcompatibility.pyを直接mypyすると既存3件のBeautifulSoup属性型エラーを検出した。今回同ファイルは未変更で、CIの直接チェック対象外。これを新規fixtureの成功と混同しない。一般的な型改善は別工程。
- Frontend未変更。今回のPR CIで既存frontend/build/E2E/migrationを確認する。ローカルで全体E2Eを実行したとは報告しない。

## 次の実装候補・停止境界

1. CF7 6.2.1 cross-name groupのreview専用情報を整備する。複数nameをまたぐmin/max要件を未確定のまま表示できるようにし、各nameのrequiredへ誤変換しない。まずmanaged fixtureに限定し、実siteの送信権限を与えない。
2. multipart＋確認画面protocolをmanaged fixtureで検証する。URL/field/token/fingerprint/承認snapshotの変化とUNKNOWNを検証し、実POSTに接続しない。
3. 購入予算しかない窓口の営業用途はHuman確認が必要。技術adapter追加で用途不一致を解消した扱いにしない。

実企業での再GET/POST・ブラウザ入力・Codex送信taskは今回実行していない。今回完了は「原因を再現し、安全境界を回帰検証したこと」であり、送信成功・対応率改善の実証ではない。
