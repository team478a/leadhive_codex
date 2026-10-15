# マージ後の20サイト保存HTML回帰比較

2026-10-09。作業branch `codex/contact-navigation-cohort-replay`。
Before: `c698e31b9af984e74da0b66a1b26b9bccfff278b`。
After: `73db23b71dd3901c49adc25cc134605a31b6f5c8`（PR #11 merge）。PR #11のpush/PR CIは全項目successを確認した。

## 方法

G1 Pilotの20サイトで保存した成功HTMLを、Before/Afterの同じ `contact_pages` 境界へ渡した。root URL、8追加ページ、深さ3、転送後URLによる相対リンク解決を固定。各HTMLは保存SHA-256と一致する生bytesで読み込み、Windows改行変換による内容変更を避けた。socket接続/DNS禁止のプロセスで実行し、外部アクセス・アプリDBを使用しない。

cacheにないURLは未確認として保持し、そのページの子リンクやフォームを合成しない。このcacheは成功HTMLだけで、robots・HTTP404等の失敗応答・完全な取得順序を再現できない。実サイト取得全体の同条件比較ではない。

## 結果

| 項目 | Before | After |
|---|---:|---:|
| 対象 | 20 | 20 |
| 保存DOMで問い合わせ検出 | 10 | 10 |
| cache不足・未確認分岐あり | 7 | 8 |
| 保存HTML範囲で静的未解決 | 2 | 1 |
| 保存埋め込み候補のみ・未確認分岐なし | 1 | 1 |
| 選択URLのうちcache外 | 24 | 26 |

保存DOM検出10件はすべて同じフォームURL。検出消失0、保存HTMLで新規検出0。cache不足の分類は、DOM検出があればDOM検出を優先し、その他は未確認分岐の有無を優先する。埋め込み候補があってもcache不足分類に含まれる場合があるため、以前の実サイトPilotの「埋め込み4件」と混同しない。

実サイトでのフォーム発見率改善、Human適合率、営業許可、READYは未測定/null。

## 選択が変わった2件

- Private行6: Before/Afterとも同じ保存フォームDOMを検出。Afterでは、その前に未保存URLを1つ選んだ。実サイト上の追加要求/遅延が増える可能性があり、失敗応答を持たないこのreplayだけでは否定できない。
- Private行15: Beforeは保存HTML範囲で未解決。Afterは以前検出した一般窓口を先に選ぶが、そのHTMLがないためcache不足。到達候補改善だけを確認した。

他18件の選択URL列は同一。2件だけを次の外部再確認候補とし、20件/184件を無条件に再実行しない。検出が残った10件についても一般的な実サイト回帰なしを保証するものではない。

## 成果物・検証

匿名集計: `results/contact-navigation-cohort-replay-20261009.json`。
Private結果と再現runner: Git除外 `dist/g1-cohort-replay/private.json` / `run.py`。runner hashを集計へ記録。個別企業名・窓口URL・HTMLはGitへ追加していない。

HTML全件hash照合、状態合計20、追加ページ上限8、旧検出先維持10を確認。外部要求、検索API、AI、承認、メール/Form送信すべて0。送信worker起動なし。アプリコード・DB・Migration・dependency変更なし。

## 次の狭い検証案（まだ未実行）

対象を同じprivate cohortの行6/15の2サイトに固定する。トップから現行実装で探索し、サイト毎32要求/60秒、追加8ページ/深さ3、全体最大64 GET（robots・redirect含む）。検索API・AI・DB登録・入力・POST・承認・送信なし。旧問い合わせURLを探索入力へ渡さない。cacheと時間・requests・失敗を保存し、取得不能や埋め込みを成功へ繰り上げない。

目的は、行15の新しい先頭候補でフォームDOMを確認できるか、行6の追加候補が既存窓口検出を阻害しないか、要求数・時間を確認すること。費用は有料API未使用、Human時間/総原価は不明値null。

実装計画§9に従い、新しい外部実行は対象と上限への承認後のみ。今回の「次のタスク」は保存データ比較として実施し、外部承認へ自動拡張していない。2サイト結果で停止し、Full Benchmark/全国/工程4以降へ進まない。
