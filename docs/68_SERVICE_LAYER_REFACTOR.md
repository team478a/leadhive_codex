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

## 今後の分割候補

- `company_routes.py` を企業基本管理、営業ワークフロー、品質管理、分析・出力へ分割
- `CompaniesPage.tsx` を検索一覧、詳細編集、営業操作、担当者管理へ分割
- `schemas.py` と `models.py` を機能領域ごとのモジュールへ分割
