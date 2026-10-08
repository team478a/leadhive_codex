# 自社サイト以外の収集結果を営業候補から除外する

## 方針

対象企業・店舗の自社サイトを営業対象として扱う。予約、口コミ、まとめ、SNSのページ自体を対象企業の公式サイトと扱わない。未知のサイトは確認待ちとし、除外リストにないという理由だけで公式と確定しない。

既存の共通ドメイン判定を再利用し、ホットペッパー、各SNS、タウンページ等に加えて以下を追加した。ホスト完全一致または実際のサブドメインだけに適用し、`hotpepper.jp.example.com` のような文字列を誤除外しない。楽天ドメイン全体やWix等のホスティングサービス全体を除外しない。

- [楽天ビューティ](https://beauty.rakuten.co.jp/): 美容院の検索・予約
- [ミニモ](https://minimodel.jp/): サロンの検索・予約
- [エキテン](https://www.ekiten.jp/): 店舗を掲載するサービス
- [ヘアログ](https://hairlog.jp/): 美容室の口コミサイト

追加先を2026-10-07にサービスの公開ページで確認した。ページの取得はサービス分類確認のみで、Pilot店舗の再検索・再解析はしていない。

## 通常収集との整合性

既存の `services/collection_jobs.py` は共通ドメイン判定でcompany型の第三者ページを除外する。location型の利用者提供CSV等は店舗レコードを維持し、第三者ページをreferenceとして残してwebsiteを空にする。この互換性を維持する。referenceが第三者サイトでも、別に自社website候補がある場合は、そのwebsite候補を確認対象とする。

## Raw Benchmarkとの分離

Raw BenchmarkはSourceのフィルタ前の返却を測るため、第三者ページもimmutable Snapshotとして維持する。削除・書き換え・再収集しない。

APIのSnapshotレスポンスへ派生値 `site_policy` を追加する。

- `EXCLUDED_THIRD_PARTY`: 既知の予約・まとめ・SNSドメイン。通常の確認キューから除外。
- `REVIEW_REQUIRED`: 自社サイトか未確認。利用者がページ・対象条件を確認する。
- `rule_version`: `official-site-only-v1`

Reportにシステム除外のRaw観測数と代表候補数を追加する。元のFound、Humanラベル、Precisionの分母、Source/Query/Runの測定定義は変更しない。派生ルールの除外をHumanの `PORTAL_OR_AGGREGATOR` 判定として保存しない。旧レビューも変更しない。

通常画面では対象外数と理由を表示し、確認対象だけ順番に表示する。詳細画面では全Raw取得結果を閲覧・Humanレビューできる。対象店舗が実在するというRaw正解判定と、そのURLを営業候補に採用するかは別である。対象条件と自社サイトを明示的に確認する操作文言に変更する。

## 現在の保存済みPilotへの適用

外部収集を追加せずに、保存済みSnapshotから派生計算した値。

| 項目 | 数 |
|---|---:|
| 元のRaw観測 | 40 |
| 第三者サイトのRaw観測 | 24 |
| 代表候補 | 11 |
| 第三者サイトの代表候補 | 6 |
| 自社サイトか確認する代表候補 | 5 |

5件を公式サイト確認済み・CORRECTと扱わない。Humanレビューは未実施のまま。Precision改善やCoverage改善の実測結果でもない。

## 検証・変更範囲

ドメイン完全一致、サブドメイン、大文字・末尾ドット、偽の類似ドメイン、未知サイト、websiteとreferenceの分離、Raw保存・分母・Human判定の維持をBackendテストで確認する。Desktop/Mobile E2Eでシステム除外の表示と確認キューの分離を検証する。

DB Model・Migration・承認・送信処理は変更しない。追加のSource検索、Completion、AI、送信、Full Benchmarkを実行しない。
