# サービス層と画面責務の分離

保守性を高めるため、HTTPルーター、バックグラウンドワーカー、Phase 6 CLIから共通の業務処理を呼べる構成へ整理した。企業管理画面も、検索・一覧・集計・品質管理の責務を独立させた。

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

## 企業管理画面の分割

- `CompanyFilters.tsx`：プロジェクト選択、検索・絞り込み、CSV出力
- `CompanySavedFiltersPanel.tsx`：保存フィルターの適用、保存、上書き、名前変更、削除
- `CompanyList.tsx`：企業一覧、選択、一括状況変更、担当者設定、ページ送り
- `CompanyReportingPanels.tsx`：案件パイプライン、担当者別営業成果
- `CompanyContactsPanel.tsx`：先方担当者の一覧、追加、編集、削除
- `CompanyDealsPanel.tsx`：案件の登録と案件状況の表示
- `CompanyOptimizationPanels.tsx`：AI判定レビューと営業文面A/Bテスト
- `CompanyActivitiesPanel.tsx`：企業ごとの活動履歴の記録と表示
- `CompanyReplyQueuePanel.tsx`：受信返信の確認と対応結果の記録
- `CompanyEmailDeliveryPanel.tsx`：個別メールの送信予約、取消、再送
- `CompanyFormDeliveryPanel.tsx`：個別フォーム送信とCodex支援結果の記録
- `CompanyOutreachQueuePanel.tsx`：営業アプローチ対象の対応記録
- `CompanyDetailsPanel.tsx`：企業基本情報、連絡制御、営業状況の編集
- `CompanyFollowupTasksPanel.tsx`：追客タスクの完了・延期と次回対応の記録
- `CompanyQualityPanels.tsx`：データ品質、自動再解析、重複候補と統合
- `companyPageShared.ts`：一覧で共有する表示名、初期フィルター、URLクエリー生成
- `CompaniesPage.tsx`：データ取得、詳細編集、送信、営業対応の状態と操作

画面上の項目・操作・API呼び出しは維持したまま、一覧・レポート・品質管理に関する変更を他の機能へ波及させにくくした。

## 次の分割候補

- `CompaniesPage.tsx` の詳細編集、送信操作、営業キューを個別コンポーネントへ分割
- `company_routes.py` の営業ワークフローと企業基本管理を分割
- `schemas.py` と `models.py` を機能領域ごとのモジュールへ分割
