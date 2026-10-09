# Phase 3：複数nameの必須グループ確認表示

## 目的・基準

基準：main `a34fd571d947d5893d0efed787e657307b6d69b2`（PR #28統合）。前工程で観測したCF7 6.2.1の4項目・18選択肢のような構造について、人が必須範囲を確認しやすくする。CF7 6.2.1の送信adapterや確認画面protocolの実装ではない。

## 既存機能の再利用

`form_choice_groups.inventory` と既存 `choice-groups` API、FormAnalysisLogのHuman review履歴を利用する。新規Model・Migration・endpointは追加しない。既存のowner/editor限定、Agent/Viewer拒否、source hash競合、24時間期限、stale、営業禁止保持は維持する。

## 追加した情報

- `grouping_basis=SAVED_HEADING_CANDIDATE`：保存見出しによる候補であり、DOM所属を自動確定した扱いにしない。
- `member_count` / `option_count`：項目と選択肢を分ける。4項目・18選択肢を18個の必須入力と解釈しない。
- `individual_required_count` / memberの `individually_required`：個別必須とグループ全体の条件を区別。
- `requirement_scope_status`：未記録・期限切れ・項目変更はUNCONFIRMED、有効なHuman記録だけHUMAN_RECORDED。
- `minimum_selected` / `maximum_selected`：未確定はnull。HumanがEXACTLY_ONEを記録した場合は1/1、AT_LEAST_ONEの場合は1/null。nullを0や無制限許可へ読み替えない。これはHuman記録の表示であり、実フォームの自動検証結果ではない。

## UI

「必須範囲：未確定（任意ではありません）」を表示。全nameに選択が必要と誤解しない説明を追加。各欄は長い選択肢一覧の代わりにnameと選択肢数を表示し、dropdownで実際の選択肢を確認できる。期限切れ/stale時は未確定に戻り、前回記録は履歴としてのみ表示する。

Humanが記録した後も「送信承認ではありません」を表示し、`execution_supported=false`、FormProfileのREVIEW_REQUIRED/BLOCKEDを維持する。同じnameで複数値を選ぶ操作は従来どおり未対応で、対応済みとは表示しない。

## 検証・制限

- Backend関連41件成功。4項目・18選択肢の匿名DB fixture、未確定のnull、Human記録後1/1、期限切れ/stale、既存Project/Viewer/Agent境界を検証。
- Ruff / format、変更serviceのmypy、Frontend typecheck / lint / build成功。
- Desktop/Mobileの既存form-intelligence Playwrightで未確定/記録済み表示を検証。
- DB schema変更なし。専用 `_test` DBだけを使用。外部検索・AI・実サイトGET/POST・営業DM・Human承認なし。worker・実運用設定は変更しない。

次候補はmultipart確認画面のmanaged fixtureによるprotocol設計。今回の表示改善は実送信対応率や実サイト送信成功の証明ではない。
