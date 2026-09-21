# サービス層の分離

保守性を高めるため、HTTPルーター、バックグラウンドワーカー、Phase 6 CLIから共通の業務処理を呼べる構成へ整理した。

## 分離した処理

- `services/web_analysis.py`：Web解析、手動保護項目の維持、重複判定
- `services/ai_analysis.py`：AI判定用コンテキスト作成、AI判定結果の保存
- `services/collection_jobs.py`：収集ジョブ作成、候補保存、重複・連絡禁止の除外、失敗記録
- `services/operations.py`：定期再解析対象企業の抽出

APIルーターは認証、入力検証、HTTP応答に集中する。ワーカーとPhase 6 CLIはルーターを経由せず、同じサービスを直接利用する。

## 互換性

既存のREST APIパス、DBテーブル、Migration、画面の操作方法は変更していない。既存のAPIテストはサービス層を直接差し替える方式へ更新し、外部サービスへ接続せずに振る舞いを検証する。

## 企業管理ルーターの分割

- `company_reporting_routes.py`：営業活動・送信成果の集計、保存フィルター、担当者別集計
- `company_quality_routes.py`：重複候補、企業統合、データ品質、再解析キュー
- `company_routes.py`：企業一覧・詳細、営業操作、フォロー、返信、担当者、CSV、ダッシュボード

既存のURLは維持し、各ルーターをアプリへ個別に登録している。

## 今後の分割候補

- `CompaniesPage.tsx` を検索一覧、詳細編集、営業操作、担当者管理へ分割
- `company_routes.py` の営業ワークフローと企業基本管理を分割
- `schemas.py` と `models.py` を機能領域ごとのモジュールへ分割
