# LeadHive V2 - Codex 開発ルール

## 1. 開発単位

開発はPhase単位で行う。

- Phase 1: 基盤
- Phase 2: 企業収集
- Phase 3: Web解析
- Phase 4: AI判定
- Phase 5: UI・営業リスト
- Phase 6: 実データ検証

一度の指示で複数Phaseを勝手に進めない。

## 2. 既存機能の再利用

旧LeadHiveのコードは「参考」として扱う。

再利用する場合:

1. 旧コードの依存関係を確認
2. V2に不要な処理を除去
3. V2の設計に合わせて書き直す
4. テストを追加
5. 旧EC依存ロジックが混入していないことを確認

## 3. 業種依存禁止

以下をハードコードしない。

- SNS会社専用スコア
- 運送会社専用スコア
- EC会社専用スコア

業種差分はTargetProfileのJSON設定へ寄せる。

## 4. DB変更

DB変更時はMigrationを残す。

アプリ起動時に大量の `ALTER TABLE` を直接実行する方式にはしない。

## 5. API設計

REST APIを基本とする。

例:

- `/api/auth/*`
- `/api/projects/*`
- `/api/target-profiles/*`
- `/api/companies/*`
- `/api/collection-jobs/*`

## 6. エラー処理

外部APIエラーとアプリ内部エラーを分離する。

ユーザー画面には内部例外をそのまま表示しない。

## 7. ログ

最低限以下をログに残す。

- collection job start/end
- external API error
- scraper error
- AI error
- auth failure
- database error

機密情報はログへ出さない。

## 8. Git運用

大きな変更を1コミットにまとめない。

推奨:

- `feat: add project model and api`
- `feat: add target profile management`
- `feat: add login screen`
- `test: add project api tests`

## 9. 完了判定

「画面が表示された」だけで完了にしない。

各Phaseで:

- typecheck
- lint
- test
- build
- API起動確認

を通す。

## 10. 不要機能

ユーザーから指示がない限り追加しない。

特に:

- Stripe
- billing
- subscription
- 2FA
- Slack
- AutoMaster
- 全国企業DB
- 自動メール送信
- 自動DM
- 自動フォーム送信
- 複雑なCRM
