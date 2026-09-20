# CSV取込ワークフロー 実装記録

## 目的

列名が異なる顧客保有CSVを、取込前に内容を確認して安全に企業リストへ追加できるようにする。

## 実装

- UTF-8 CSVのヘッダー、総行数、先頭5行を取込前に表示する。
- 会社名、WebサイトURL、電話、メール、住所へCSV列を対応付ける。
- 標準英語列と一般的な日本語列は自動選択する。
- 最大5MB、1,000行の既存制限をプレビューと本取込で共通適用する。
- 会社名欠落と不正URLを行番号・理由付きで収集ジョブへ保存する。
- エラーがあるCSVジョブからUTF-8 BOM付きの行別エラーCSVを出力する。
- エラーCSVにもプロジェクト所有者のアクセス制御を適用する。

## API

| Method | Path | 内容 |
| --- | --- | --- |
| POST | `/api/projects/{id}/collection-jobs/csv/preview` | ヘッダー・先頭5行・推奨列対応を返す |
| POST | `/api/projects/{id}/collection-jobs/csv` | `column_mapping`を使って取り込む |
| GET | `/api/collection-jobs/{id}/errors.csv` | 行別エラーをCSV出力する |

従来の標準列CSVは`column_mapping`を省略しても取り込める。

## 検証

- 日本語列の自動対応、プレビュー、列対応付き取込
- 重複、会社名欠落、行別エラーCSV
- Migration往復とAlembic差分検査
- デスクトップ・モバイルのブラウザ操作
