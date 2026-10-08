# 自社利用CF7 2件の限定契約差分測定

## 基準と目的

branch: `codex/integration`。
測定commit: `abff223120063bd4ecc1e6f9b6193a9c6d255dfe`、測定開始時working tree clean。
前工程で実装した静的契約差分診断を、既存の対象2件に適用した。
実サイトの契約差分を測る工程であり、送信アダプターの対応追加・許可範囲拡大はしない。

集計正本: `docs/results/self-use-cf7-contract-shape-2026-10-08.json`。
個別URL・Profile IDを含む診断はGit管理外の `dist/cf7-contract-read-*` に保存。HTML・hidden値・入力値は保存しない。

## 取得と安全

対象は自社営業Projectの既存CF7候補2件のみ。各サイトrobots.txtと既存フォームURLのGET、合計4回。
DNS固定、TLS証明書検証、同一origin、redirect拒否、robots確認、サイズ・時間上限を持つ既存限定GETを使用。
検索API、AI、追加リンク巡回、POST、Human確認の代行は行わない。

DBは `SET TRANSACTION READ ONLY`。Company、Profile、Field、Draft、Approval、HumanProof、Email、Form、Job、AnalysisLog、DestinationChoice、DMPreparationの12テーブルについて前後hash一致。
観測をDBへ書き込んでいないため、UIの保存診断も今回の実測へ自動更新していない。
outbound OFF、通常送信worker未起動。review書込、Approval、Email、Formはすべて0。

## 測定結果

| 項目 | 6.2の1件 | 6.1.4の1件 |
|---|---:|---:|
| 保存済み構造との比較 | SAME_STRUCTURE | SAME_STRUCTURE |
| CF7候補 | 検出 | 検出 |
| 管理下テストと同じ版 | いいえ | はい |
| hidden6項目 | あり | あり |
| 限定hidden形状との一致 | いいえ | はい |
| 契約外hidden | 0 | 1 |
| 現行契約の項目名形式に不一致 | 18 | 1 |
| 同名入力の重複数 | 14 | 3 |
| checkbox | 18 | 4 |
| radio | 0 | 1 |
| select | 0 | 0 |
| 初期checked | 0 | 0 |
| disabled | 0 | 0 |
| 静的営業禁止表記の検出 | なし | なし |
| CAPTCHA静的判定 | NOT_DETECTED_STATIC | NOT_DETECTED_STATIC |
| 送信・承認可能 | いいえ | いいえ |

「項目名形式に不一致」は現行の狭い非実行契約の正規表現との比較であり、そのWebフォーム自体が不正という意味ではない。
同名入力の数は、その名前の最初の1件を除く追加項目数。フォーム数・独立送信先数ではない。
6.2のhidden形状不一致には少なくとも版の不一致が含まれる。他のhidden値が一致したかを、この複合真偽値から推測しない。

両件とも構造が一致したことは、送信先の用途・営業可否・同意・CAPTCHA・受付を保証しない。
「営業禁止未検出」をALLOWEDへ、「静的CAPTCHA未検出」をNONEへ変換しない。
6.1.4でも追加hidden、同名入力、契約名形式、radioが残るため、既存候補契約にそのまま投入できない。

## 結論と優先順位

2件ともhidden不足より、選択項目・同名入力の扱いが次の共通課題。
「同名なので重複削除」「複数の値を文字列連結」「初期値・AI選択で同意」では解消しない。

推奨する次の1工程は、**管理下テストで同名checkbox groupの非実行契約を設計・検証すること**。
項目グループと選択肢を別IDで保持し、明示された選択値、未選択、必須条件、payload固定、送信時の複数同名値の順序を検証する。Humanの選択をCodexが代行しない。

ただし、この対応だけで2件が送信可能になるとは主張しない。6.2版のProtocol検証、6.1.4側の追加hiddenとradio、営業可否と同意確認は独立した停止点として残す。
今工程では契約・wire lab・DB・UIの対応範囲を変更せず、実POSTへ進まない。

## 費用と再現性

GET試行4、検索API0、AI0。費用は料金を測定していないためnull。
測定時刻、コードcommit、取得Service・parser・inspectorのSHA-256は集計JSONに固定。
前工程の集計結果は上書きしない。
今回の変更は監査文書と集計JSONのみ。コードテストは前工程の84 tests / 50 subtests、PC/Mobile E2E4件PASSを参照し、新しいテスト実行と混同しない。
GitHub CIは未pushのため未確認。
