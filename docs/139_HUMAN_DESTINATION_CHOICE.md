# Phase B3c — 営業準備に使う窓口のHuman選択

## 目的と完了範囲

READYの窓口候補から、owner/editorが営業準備に使う1件を明示的に選択する。
用途確認・推奨・送信承認は独立した概念とし、選択による承認や送信は行わない。
DM READYは引き続き未確定であり、選択件数をDM READY件数として計上しない。
既存Human Approval、Suppression、共有窓口、UNKNOWN、CAPTCHAの制御を維持する。

## 保存とAPI

追加Model：`DestinationChoiceEvent`。企業ごとに連続する版でSELECTED/REVOKEDを追記する。
Project、企業、窓口、Human選択者、窓口種別・値、snapshot hash、用途確認版、日時・期限を固定する。
Migration `1ea563b6ad2d`（親`15fcce21f276`）は追加のみ。既存Migrationは変更しない。

- POST `/api/companies/{company_id}/destinations/{destination_id}/choice`
  - `expected_hash`, `expected_purpose_version`, `expected_choice_version`が必要。
  - 現在READY、用途確認版/hash一致、企業全体の選択版一致を検証。不一致は409。
- POST `/api/companies/{company_id}/destination-choice/revoke`
  - `expected_choice_version`。失効・安全条件変更後でもHumanが取消可能。
- GET `/api/companies/{company_id}/sendability`
  - `human_choice`として状態、版、記録窓口、CURRENTの場合だけ`active_destination`を返す。

Human cookie認証とProject owner/editor権限を要求する。viewerは参照のみ。
Agent Bearerとの混在を403拒否。Agent認証をHumanに変換しない。
`confirmed`や任意の期限等、未定義入力は422。選択者IDはサーバーで確定する。
ProjectロックとDB連続版制約で競合を停止する。

## 有効性と失効

最長7日、かつ元の用途確認期限以内。選択によって用途確認期限を延長しない。

| 状態 | 意味 |
|---|---|
| UNSELECTED | 記録なし |
| CURRENT | hash、用途確認版、期限、現在READYをすべて満たす |
| REVOKED | Humanが取消済み |
| EXPIRED | 選択期限切れ |
| STALE | 窓口消失、宛先・Identity・解析・用途確認版等の変更 |
| INELIGIBLE | hashは同じでもSuppression、UNKNOWN、共有窓口等でREADYではない |

B2のsnapshot hashでフォームの実field mappingやfingerprintを含む保存情報を照合する。
同じ内容で用途確認を更新してhashが変わらなくても、用途確認版の変更で失効する。
失効時は`active_destination=null`。他にREADYがあっても自動で代替しない。
推奨窓口は独立して提示する。推奨を選択済みとして扱わない。
安全条件が解消され、hash/版/期限が一致する場合は再評価でCURRENTに戻り得る。
これは送信許可の復活ではなく保存情報からの準備診断である。
将来のDM/承認/dispatchは改めてその時点の条件を照合する必要がある。

## DB履歴保護

UPDATE/DELETE/TRUNCATEをtriggerで拒否。INSERTもHuman membership、連続版、
Project内の有効窓口/link、現行用途確認版と期限を検証する。
REVOKEDは直前のSELECTEDをコピーするため、窓口が消失しても取消できる。
READYの安全判定はAPI serviceで行い、DB triggerだけで送信許可を決めない。
企業・窓口・選択者は歴史的IDで保存し、企業削除や統合後も台帳を移し替えない。
既存Project削除のcascadeは保持するため、Project削除を越える永久監査保存ではない。
台帳にデータがあるdowngradeを拒否する。空の検証DBでのみdowngrade/upgradeを検証する。

## UI

企業詳細「窓口の利用可否と理由」に独立した選択欄を追加。
状態・版・記録窓口・有効な準備対象・選択者・日時・期限を表示する。
READY候補だけ選択ボタンを出し、取消も追記として記録する。
送信・承認ボタンは追加しない。保存競合時には再取得して最新状態を表示する。

## 検証と運用境界

独立した`_test`DBと架空exampleドメインで検証する。
選択/取消/版競合、用途更新、fingerprint・営業禁止・CAPTCHA、Suppression、
UNKNOWN、共有窓口、期限、Agent混在、viewer/他Project、DB改変禁止を検証する。
PC/mobile E2Eで選択の永続化、取消、宛先変更による失効、外部通信・送信操作なしを確認する。
稼働中100店舗DB、配布パッケージ、workerは変更しない。実送信・外部APIは実行しない。

## ローカル検証結果（2026-10-06）

- 関連Backend 61 passed（うち本工程12件）。
- PC/mobile E2E 4 passed：新しい選択フローと既存照合・用途フロー。
- Ruff、変更Service/APIのmypy、Frontend typecheck/lint/build成功。
- 検証API起動成功。送信機能OFF、外部通信・承認/送信requestなし。
- 空の検証DBで親revisionまでdowngrade→head upgrade→Alembic check成功。
- 既存buildの500kB chunk警告は継続。品質失敗ではないが将来の分割課題。

## 次のゴール

Phase C：Template + 確認済みEvidenceを使うDM DRAFT準備。
CURRENTの選択窓口を利用し、本文・根拠URL・宛先・選択版をHumanが確認できるようにする。
DM READYの確定条件をこの段階で定義する。Human承認と実送信接続は別工程とする。
