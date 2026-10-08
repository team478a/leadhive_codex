# リリース前ハードニング・main統合準備

確認日: 2026-09-27

## 現在の判定

`codex/integration`の機能・Migration・自動テスト・Windows配布は、main統合PRを作成できる状態にある。mainへのmergeは実行していない。

Phase 6の100社+100社実データ検証は、検証利用者とSerper/OpenAI APIキーの設定待ちである。これを「実装完了」と区別し、mainを最終確定する前に結果を記録する。

## 差分確認

ハードニングruntime実装: `d058fe0d24fcf3d43f70ea755831191e4e7534e9`

全検証・統合準備文書HEAD: `accf075b7aa2ac73eac8e47d14c8ec5bf45d1aee`

| 項目 | 結果 |
| --- | --- |
| `origin/main` | `b66ed40c533476d2adb7ad74940e6b9f86faa34b` |
| merge base | `b66ed40c533476d2adb7ad74940e6b9f86faa34b` |
| main固有commit | 0 |
| integration固有commit | 227 |
| 変更ファイル | 304 |
| merge-tree競合marker | 0 |
| Alembic head | `c1d9f6a2b4e8`、単一head |

mainはintegrationの分岐後に進んでおらず、現在のGit履歴上は競合を検出していない。ただし変更量が大きいため、PRではMigration、権限、送信処理、Windows配布を重点確認する。

## 今回のハードニング

- Form Intelligenceの専用Playwright E2Eを追加した。
- PCとスマートフォンで、複数Profile、primary変更、手動修正、解析ログ、viewer参照専用表示を確認する。
- Form Intelligenceのviewer画面では、再解析、primary変更、項目修正、一括解析を無効にした。
- GitHub ActionsをNode.js 24対応世代へ更新し、Linux runnerをUbuntu 24.04へ固定した。
- Starlette TestClientを`httpx2`へ移行し、テストのdeprecation warningを解消した。
- Windows配布へ診断、確認付きDB復元、復元前安全バックアップを追加した。

## Windows配布候補

- ZIP: `LeadHive-Windows-Local-accf075.zip`
- SHA-256: `8a9a915e751c3fae8f9bd136f6835185d5e2f546a35389de83010c4b80e3114d`
- ZIP checksum、全manifest hash、未登録ファイル、必須ファイル、PowerShell構文、Compose構成を検証済み

クリーンな別Windows PCでの初回導入、Docker Desktop自動導入、バックアップからの実復元は最終リリースsmoke testとして残る。現在の利用データを破壊して確認しない。

## main統合PR案

### タイトル

`feat: integrate LeadHive V2 operations, outreach, and Form Intelligence`

### 説明

LeadHiveの段階的な開発成果を1本の統合候補へまとめ、企業収集から営業管理、承認付きメール・フォーム送信、Form Intelligence、Windowsローカル配布までを一貫して利用できるようにする。

主な変更:

- 認証、Project、Target Profile、企業収集、Web解析、AI判定
- Background Job、recovery、monitoring、schedule、データ品質、重複統合
- メンバー権限、連絡禁止、担当者、フォロー、活動・成果分析
- Outreach Draft、メール配信、SMTP・APIキー管理、返信処理
- 承認付きフォーム送信、一括フォームDM、Codex支援
- Form Intelligenceによる事前解析、営業禁止・CAPTCHA・構造変更検知
- Windowsインストール、更新、バックアップ、復元、診断

検証:

- Backend Ruff・pytest
- Alembic upgrade / downgrade / upgrade / model差分・DB整合性
- Frontend typecheck / lint / build
- Playwright desktop / mobile
- Windows package build / manifest / PowerShell / Compose検証

未完了として明示する項目:

- Phase 6のSNS運用事業者100社・運送事業者100社の実データ検証と人手レビュー
- JEV Provider実通信
- JavaScript・iframe・Shadow DOM Formの静的解析

## merge前チェックリスト

1. Phase 6の100社+100社収集、AI判定、人手レビュー、sanitized summaryを完了する。
2. `origin/main`が上記SHAから進んでいないことを再確認する。進んでいた場合は先にintegrationへ取り込む。
3. Alembicが単一headであることを確認する。
4. 全GitHub Actionsを最終HEADで成功させる。
5. クリーンなWindows環境で初回インストールsmoke testを行う。
6. `Backup-LeadHive.cmd`でDBと`.env.local`を保存する。
7. `Restore-LeadHive.cmd`で専用検証環境への復元を確認する。
8. merge前のmain SHAを保護refまたはrelease tagとして記録する。
9. PR review後、`codex/integration`からmainへ1回だけmergeする。

## rollback手順

1. merge前のmain SHA、merge commit SHA、DB backup、`.env.local`を記録する。
2. アプリ停止後、問題のあるmerge commitをrevertするか、保護した旧main refから再配布する。
3. DB互換性に問題がある場合はAlembic downgradeを本番rollbackに使わず、`Restore-LeadHive.cmd`で事前backupを復元する。
4. 旧コードと旧DBを同じ時点へ戻してからAPI、worker、webを起動する。
5. health、ログイン、Project一覧、企業一覧、送信待ち件数を確認する。

## branch整理

main統合前はbranchを削除しない。統合後に`codex/smtp-settings-ui`とそのancestor branchを再監査し、`KEEP`、`MERGE済み`、`OBSOLETE`、`UNKNOWN`へ分類する。削除は別の明示指示後に行う。
