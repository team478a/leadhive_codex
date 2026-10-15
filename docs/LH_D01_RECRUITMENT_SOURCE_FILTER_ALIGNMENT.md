# LH-D01 — PR #49 二段階収集判定への整合

## 基準・作業履歴
- task ID: LH-D01
- 実行thread: 01a11817-37ae-75d2-a54e-7ecbe8ede9e7
- 着手main: 98bd6ae142e53d0dda857c5b1b9bcd02f652d23c
- 着手作業branch: codex/recruitment-source-filter
- 着手head: cea51806426eedf86c062e04c0a0530290dcc688
- main整合merge commit: 97a7286a01347261958901ea150a02ce361f326d
- PR: https://github.com/team478a/leadhive_codex/pull/49
- PR #65 / #66は統合済み。未知ARTICLE・求人タイトルは暫定保存する現行仕様を採用。
- OPEN #4/#5/#35/#49/#71および表示された進行中タスクを確認。見えている範囲で同じ限定修正の別担当は確認できず。#71は変更しない。
- 既存branchはlocal/remoteとも同一SHA、他worktreeによるcheckoutなし。clean worktreeを切り替え、通常mergeでmainを取り込んだ。rebase / force pushなし。

## 変更と維持する仕様
- `backend/app/services/collection_discovery.py`: 既知求人媒体に `r-agent.com` を追加する1行のみ。実subdomainも既存のドメイン境界照合を使用。
- `backend/tests/test_collection_discovery.py`: apex / www uppercase / 実subdomain / 別domain / 公式企業採用支援を対照化。通常・fairのRaw保持、Company非取込、枠非消費を検証。
- merge競合はmainの二段階判定を採用し、PR #49の限定host修正を再適用。未知ARTICLEの暫定保存を旧仕様へ戻さない。
- Human指定domain除外の範囲は変更しない。求人語の一般フィルタ、Query、予算、DB schema、承認・送信コードを変更しない。
- PR内の2026-10-10文書は過去仕様の履歴として保持。本書と最新集計を今回の評価とする。

## 修正前の再現と修正後
固定mainのSourcePolicyによるネットワーク禁止オフライン再生で、求人URLがOFFICIAL_SITE_CANDIDATE / eligible=trueとなることを再現。修正後はJOB_PR / EXTERNAL_PLATFORM / eligible=false。

通常・fairのworker試験では、求人Rawのtitle/linkと大阪regionが残り、NON_COMPANY_SOURCEとなり、目標2件は未知記事の暫定候補と通常企業候補で埋まる。求人が枠を消費しない。ARTICLEはSAVEDのまま。

## 保存済み40 Rawの比較
正規のローカルscratchに保存されたA/B各20件のtitle/urlを使用。取得し直していない。ファイルhashと投影入力hashは `results/lh-d01-recruitment-alignment-replay-20261011.json` に固定。

| Arm | Raw | mainの取込候補 | 修正後の取込候補 | 分類変化 |
|---|---:|---:|---:|---:|
| A | 20 | 13 | 13 | 0 |
| B | 20 | 16 | 15 | 1 |

これは分類・取込適格性の再生であり、Company DBへの40件worker再生ではない。ARTICLEはA8件/B12件を維持。r-agent以外のhost分類は全件不変。従来の「5候補保持」は旧仕様の値で、今回の固定期待値にはしていない。Human Truthなし、業種適合率・公式サイト正答率はnull。個別企業データはGitへ追加していない。

## 検証
Python: 既存backend/.venv、PYTHONPATH/MYPYPATHは本worktreeのbackend。
DB: leadhive_prefecture_20261011_test / 専用Docker PostgreSQL15449。既存本番・クラウドDBを使用しない。

| コマンド | 結果 |
|---|---|
| `python -m pytest backend/tests/test_collection_discovery.py backend/offline_tests -q` | PASS 129 |
| `python -m ruff check backend` | PASS |
| `python -m ruff format --check backend` | PASS 506 files |
| `python -m mypy --check-untyped-defs --follow-imports=silent backend/app/services/collection_discovery.py` | PASS |
| `python -c "from app.main import app; print(app.title)"` | PASS LeadHive V2 |
| `python -m pytest backend/tests -q` | 実行中。完了結果はPRの最終報告へ記録 |

main CI: https://github.com/team478a/leadhive_codex/actions/runs/38107604665
Backend / lint / offline / frontend / E2E等はPASS。migration-validationだけがPostgreSQL image取得時の `toomanyrequests: Rate exceeded` で失敗。runnerの自動pull3回で終了しており、migrationコマンド未実行。今回同じ失敗への手動無限再試行はしない。新規migrationなし。

最終head CIはPR上で確認し、成功・失敗・未実行・skipを分けて完了報告する。

## 完了条件と限界
- 限定求人host判定、ドメイン境界、正常企業対照: PASS
- 通常 / fair Raw保持・Company非取込・枠非消費: PASS
- 未知ARTICLE暫定保存: PASS
- 保存済み40件の固定入力比較: PASS（policy再生。worker再生と区別）
- 全Backend / 最終head CI: 完了確認待ち
- 本番配置、ライブ精度改善: 未確認

企業へのGET、検索API、AI、入力、送信、Human Approval代行、DB schema変更、main push/merge、deployは0。本書のテスト結果を本番提供済みと解釈しない。

次は最終headのCIが揃った後にPR #49をHumanがレビューする。CI基盤問題が続く場合、収集修正と切り分けてCI基盤対応の要否を判断する。自動merge / deployはしない。
