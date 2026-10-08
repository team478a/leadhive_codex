# フォーム種類別の対応判定・検証セット

## 今回のゴール

管理下の合成HTMLを種類別に用意し、Form Intelligenceの状態と現在のHuman承認済み単一段階フォーム経路の候補判定を測定する。送信・外部AI呼出・実企業のWeb取得は行わない。対応率を上げる前に、未対応のフォームをREADYと誤判定するケースを減らす。

## 検証セット

`backend/tests/form_compatibility_cases.py`に26種類の正解付きHTMLを定義した。通常POST、日本語label、aria-label、hidden CSRF、select/radio、単一同意checkbox、disabled項目、確認画面、不明な必須項目、GET、外部POST先、ファイル、password、multipart、nameなし、CAPTCHA、JavaScript、iframe、同名項目、複数選択、空フォーム、本文なし、営業禁止を含む。

`test_form_compatibility_corpus.py`は合成ページを既存解析Serviceへ渡し、DBへFormProfile/Fieldを保存して、実際の保存済みデータから準備Serviceを呼ぶ。既存のHuman UI/送信APIは追加しない。HTTP取得はFakeFetcher、AIはOFF。正解は仕様としてケースに固定し、実装結果から生成しない。

候補の定義は、保存済み準備が成功し、確認画面なしと確定していること。承認や実送信の許可ではない。確認画面ありは解析上READYでも、現在の単一段階経路の候補には数えない。

## 修正前後

| 指標 | 修正前 | 修正後 |
|---|---:|---:|
| ケース数 | 26 | 26 |
| 状態・候補の正解一致 | 21 | 26 |
| 現在の単一段階経路の候補 | 10 | 8 |

修正後はREADY 9、REVIEW_REQUIRED 15、BLOCKED 2。READYのうち1件は確認画面ありで候補外。8/26は意図的に難しいケースを多く含む合成集合内の割合であり、実企業の対応率・実送信成功率ではない。26/26も現実の全フォームへの判定精度保証ではない。

詳細なケース別結果と理由は [results/form-compatibility-2026-10-05.json](results/form-compatibility-2026-10-05.json) に保存。

## 発見・修正した問題

- 同名text項目をREADYとしていた。従来の準備APIで重複を拒否していたが、解析時点でもREVIEW_REQUIREDへ分類する。
- 複数選択selectと同名checkbox複数を単一値で扱っていた。現在のpayload形式では全選択値を保存できないため、解析時・送信前parserの共通compatibility guardで拒否する。
- 空フォームをREADYとしていた。入力項目がない場合は人の確認へ回す。
- 本文欄のないフォームをREADYとしていた。営業文面のmessage mappingがない場合はREVIEW_REQUIREDへ分類する。既存の準備APIによる拒否も維持する。
- CAPTCHAの確認理由を「Codex支援」から「人による操作・確認が必要、自動送信不可」へ修正した。

同名radioは単一値の選択として既存対応を維持する。単一checkbox、通常select、hidden CSRF、disabled項目も維持する。複数値payloadやブラウザ自動操作、CAPTCHA自動化は追加していない。

Analysis versionを1.2へ更新。新Model/Migration、承認変更、外部送信flag変更なし。既存の保存済みREADYを一括書き換えない。再解析で新判定を保存する。古い保存結果が残っていても、送信直前parserは現在のcompatibility guardで未対応構造を拒否する。

## 再実行

専用 `_test` PostgreSQLへTEST_DATABASE_URLを設定してbackendディレクトリで実行する。通常suite/CIにも含まれる。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_form_compatibility_corpus.py -q
```

測定JSONを出す場合だけ、FORM_COMPATIBILITY_REPORTへ結果ファイルのパスを指定する。通常試験はリポジトリや利用中DBへ結果を書き込まない。

## 2026-10-05 検証結果

- 種類別26件＋送信parser拒否4件を含む関連Backend105件成功。最終ソースの種類別/parser試験30件を再実行し成功（合算しない）。
- 前工程の実HTTP・workerプロセス障害15件を再実行し成功。
- Ruff、format check、compileall、Frontend typecheck/lint/build、Backend Docker image build成功。
- テストDBのAlembic upgrade/model差分確認成功。新Migrationなし、head `fae47ac5e861`を維持。
- このPCのAPI/workerへ反映。health/DB正常、analysis version 1.2、既存企業100件、フォーム予約/送信・メール送信0件を維持。外部送信・承認済みフォーム・旧フォーム・Agent flagすべてOFF。Production deployment・配布zip再生成なし。

## 限界と次のゴール

実企業のフォーム発見率、HTML取得率、解析成功率、営業許可割合、単一段階候補数、人の作業時間は未測定。JS/iframe/複数値フォームを実送信に対応させた工程ではない。

次は収集・解析済み企業から「候補数・対象外の理由・人の確認が必要な件数」を集計できる運用画面を作る。実サイト調査をする場合も送信と分離し、対象と評価基準を明示する。
