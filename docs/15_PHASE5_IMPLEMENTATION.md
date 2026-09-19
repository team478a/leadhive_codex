# Phase 5 実装記録

## 実装範囲

Phase 5として、AI判定結果を営業リストとして確認・管理するUIとAPIを実装した。

- 簡易ダッシュボード
- プロジェクト別企業一覧
- ランク、最低スコア、地域、営業状況、収集元、キーワードのフィルター
- スコア順、新着順、会社名順の並び替え
- 企業詳細
- 営業状況・メモ更新
- 現在の絞り込み条件を反映するCSV出力

Phase 6の実サイトを使った200社検証や精度調整は実施していない。

## 営業状況

`companies.status` は次の値に制限した。

- `unreviewed`: 未確認
- `target`: 営業対象
- `approached`: アプローチ済
- `replied`: 返信あり
- `meeting`: 商談
- `won`: 成約
- `lost`: 失注
- `excluded`: 対象外

自由入力メモは最大20000文字とし、企業の所有プロジェクトを通じてアクセス権を検証する。

## API

- `GET /api/projects/{project_id}/company-list`
- `GET /api/companies/{company_id}`
- `PATCH /api/companies/{company_id}/sales`
- `GET /api/projects/{project_id}/companies.csv`
- `GET /api/dashboard`

既存の収集用企業一覧APIは互換性のため維持し、営業リスト向けの検索APIを分離した。

## CSV

CSVにはランク、スコア、企業基本情報、問い合わせ先、AI判定、営業状況、メモ、収集元を含める。

- 現在の画面フィルターと並び順を反映
- Excelで文字化けしにくいUTF-8 BOM付き
- `=`, `+`, `-`, `@` で始まるセルを無害化
- 認証とプロジェクト所有権を確認

## ダッシュボード

複雑なBI機能は追加せず、仕様にある次の件数と直近5件の収集結果だけを表示する。

- 総企業数
- A / B / C / 対象外
- 営業対象 / アプローチ済 / 返信あり / 商談 / 成約

## DB変更

`companies` に `notes` を追加し、`status` に営業状況のcheck constraintを追加した。既存行は `unreviewed` のまま移行できる。

## テスト

- 一覧フィルター・並び替え・詳細
- 営業状況・メモ更新と入力検証
- 別ユーザーの企業へのアクセス拒否
- CSVフィルター、UTF-8、数式無害化
- ダッシュボード集計と直近ジョブ
- Migration downgrade / upgrade / 差分確認
- Backend test、lint、format
- Frontend typecheck、lint、build
- デスクトップ・モバイルで一覧、詳細、更新、CSV、ダッシュボードを操作

## 次のPhase

Phase 6ではSNS運用事業者100社、運送事業者100社を実データで収集・解析し、対象企業率、Aランク精度、誤判定、問い合わせ先・SNS取得率、営業目的による判定差を検証する。
