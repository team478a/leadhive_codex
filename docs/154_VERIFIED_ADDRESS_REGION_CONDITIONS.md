# 確認済み住所による地域条件判定

## 目的・基準

基準 `codex/integration@ff22b7e31d0ae680c22247d56484b45a3b55c4b8`。
保存済みの現在の住所根拠を再利用し、地域条件のHuman確認を減らす。新しい検索・AI・Crawlを行わず、一次収集精度やHuman Truthを改善した成果としては扱わない。

## 自動判定の範囲

- 条件は都道府県を明示した所在地。例：`兵庫県`、`兵庫県姫路市`、`兵庫県 / 姫路市`。
- 登録された都道府県・市区町村と完全な住所の先頭が一致し、番地相当の数字が存在することが必要。
- 住所根拠が有効な場合、都道府県・市の完全一致はMATCH、明確に異なる都道府県・市はNO_MATCH。
- 都道府県なし、OR/AND、曖昧な町・区の範囲、部分一致、住所不足・矛盾はUNKNOWN。自治体の存在を照合する全国住所辞書ではない。営業エリア・商圏を所在地から推測しない。
- 業種のAI推定、検索語、Source地域文字列は確定根拠にならない。INDUSTRYは既存Human Fact Reviewのまま。

## 有効な根拠

Human Site Identity Reviewがある場合は、最新の記録がCURRENT、現在のProject・identity hashと一致、作成から24時間以内、ADDRESS_MATCHと現在の住所一致が必要。取消・失効・企業変更後は自動根拠へ戻らない。

Human Site Identity Reviewがないcompanyレコードに限り、現在identity hashに紐づく最新LeadSiteEvidenceを利用する。CONFIRMED、ADDRESS_MATCHとCOMPANY_NAME_MATCH、24時間以内が必要。現在の保存Web本文にも会社名・住所があることを確認する。最新根拠が未確認なら古いCONFIRMEDへ戻らない。根拠URLは現在の公式ドメインに限定し、既存のURL安全検査を利用する。

locationレコードはチェーン共通Web本文の住所だけで自動確定しない。既存Human Site Identity Reviewで当該店舗住所を確認済みなら再利用できる。

## Human訂正・安全境界

同じ地域条件にCollectionFactReviewが存在する場合、その最新記録を優先する。不一致・取消・失効・企業変更後も自動判定で復活させない。訂正は既存の追記式ledger、company hashとreview versionによる競合防止を再利用する。

既存のMUST/WANT/EXCLUDE判定、Project・Viewer・Agent権限、収集に固定された条件版、追加媒体検索の予算上限を維持する。地域の既知NO_MATCHは既存の停止条件として扱われるがCompanyを削除しない。条件一致はHuman承認・送信許可を意味しない。

## 実装・互換性

`services/region_condition.py`にread-only判定を分離し、`collection_fact_reviews.result`のAREA未レビュー時だけ呼ぶ。既存のProject結果APIとOperation結果APIの双方に反映される。追加API・Model・Migration・dependencyなし。UIに自動判定の理由、根拠URL、確認待ちの理由を表示し、入力例に都道府県を明示する。

## 検証

Backend関連85件PASS。根拠のない住所、期限切れ・未来の証拠、企業変更、URL不一致、本文削除、最新未確認、店舗、Human取消、優先度、INDUSTRYの非確定を含む。既存監査履歴の更新禁止を維持し、取消テストは新イベントの追記で検証する。

Ruff / format / mypy、Frontend typecheck / lint / build、Alembic check成功。既存bundle size警告は残る。PC/Mobile E2E・GitHub Actions・ローカル起動の最終結果は検証後に追記する。

実企業GET・追加検索・外部AI・送信・Human Approval作成は行わない。Raw Snapshot・Human Truth・既存100店舗の評価値は変更しない。

## 残課題

地域表記の正規化・自治体辞書による照合、根拠不足の公式サイト発見、業種根拠の抽出、求人現在性、PilotのHuman Truth実測は別工程。安全条件を緩めて自動判定率を増やさない。本ゴールで停止する。
