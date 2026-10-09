# Raw Collection共通入力比較：オフライン境界実装

2026-10-09。監査PR #4に続くP0の実装。目的は、同じ検索結果を二つの収集境界へ渡し、判断差を再現できること。収集精度向上や実データPilotは本工程の完了条件ではない。

## 今回できること

- Serper Raw JSONを固定し、title/link/snippet・任意の原フィールド・query/source/run/region/観測時刻をprivate成果物に保持する。
- 固定SHAの旧版 `/api/collect/urls-preview` のdomain重複・homepage化・既知媒体/公的組織判定を副作用のないprojectionとして比較する。
- 現行通常収集のURL正規化・known aggregator・company domain重複を、独立した空Project相当のprojectionとして比較する。
- 各候補に原snapshot hash、旧/現行のstate/reason、website候補、Human未確認状態を残す。
- 同じquery/regionの最大3反復を受け付け、Raw観測hashのunion/intersection/repeat/single率を計測する。失敗・中断Runを成功Runのstabilityに混ぜない。
- private出力と集計出力を分け、既存ファイルを上書きしない。private出力がcheckout内ならGit ignoreを必須にする。

これは旧版アプリ全体の実行でも、現行DBへの保存でもない。旧版の別経路（通常collect/EC/補完）の振る舞いをこの結果から推測しない。target_count停止・query variation・location/既存DB/suppression状態は今回の比較に含まない。

## 隔離・ライセンスの境界

`backend/offline_replay/` は標準ライブラリだけで動く。`app`、DB、設定、API provider、送信serviceをimportしない。Human/Agent APIやApprovalを追加しない。

旧版はローカル固定Git objectからpolicy定数だけをAST/literal読取する。旧版Pythonをimport/起動/execせず、旧コード・domainリストをこのrepoへコピーしない。previewの小さな判断構造を監査から独立に実装した。

現行版は固定Git objectの `canonicalize_url` と `is_aggregator_domain` だけを抽出する。import・I/O builtins・未確認call・private attribute・decorator/defaultを拒否し、型注釈を除いた純粋関数を隔離namespaceで実行する。`app.config`や `.env` を読まない。CLI中はsocket作成・DNS・接続も拒否する。Gitはローカル `show` / `check-ignore` だけでfetchしない。

入力上限は5MB/12Run/合計1000hit。sourceはSerper限定、同query/regionは3Runまで。時刻はtimezone必須。secret fieldやcredentialを含むURLは、原データを改変して保存する代わりに実行を拒否する。自由文の機密情報検出を保証するものではなく、private fixtureの利用条件・内容確認は別途必要。

## 固定基準

| 項目 | 値 |
|---|---|
| Legacy source | `393f690e34c7a5fbdddd4b15e0285aa2ff313269` |
| Current source | `31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f` |
| Input schema | `serper-replay-input-v1` |
| Projection schema | `serper-boundary-replay-v1` |
| 原データ | fixture JSONのcanonical SHA-256 |
| 再現性 | source file hashes + runner file hashesを結果に記録 |

現在の作業フォルダにある未commitホームページroutingは比較基準へ混入しない。新しい版の比較には明示的な基準更新・projection review・新しい結果ファイルが必要。

## 実行方法（外部通信不要）

PowerShellでrepoの `backend` へ移動する。両固定commitがローカルGit objectに存在することが必要。不足していてもCLIはダウンロードせず停止する。

```powershell
New-Item -ItemType Directory -Path dist/offline-comparison -Force | Out-Null
python -m offline_replay.cli `
  --input offline_tests/fixtures/serper-synthetic-20.json `
  --legacy-root C:/path/to/local/legacy `
  --current-root .. `
  --summary dist/offline-comparison/summary.json `
  --private-output dist/offline-comparison/private.json
```

再実行は新しい出力名にする。終了code=2なら入力/基準/出力条件を確認し、収集APIへfallbackしない。private保存後にsummary保存が失敗した場合も既存privateを上書きせず、別名で再実行する。

実データ用fixtureは `dataset_kind=PRIVATE_LICENSED_RAW`。これはSource利用許諾をコードが保証するフラグではない。承認済みの保存済みデータだけを使用する。原query/Evidence/連絡先を含むprivate出力はGitへ追加しない。

## 合成20hitの再現結果

[集計JSON](results/raw-offline-replay-synthetic-2026-10-09.json) は **SYNTHETIC_BEHAVIOR_ONLY**。

| 判定 | 旧preview | 現行ingestion projection |
|---|---:|---:|
| Raw hits | 20 | 20 |
| CANDIDATE | 10 | 13 |
| DUPLICATE | 3 | 2 |
| EXCLUDED | 6 | 2 |
| SKIPPED | 1 | 3 |

stateが異なるhitは6件。双方CANDIDATEでURLが異なるhitは9件。旧版はhomepage化し、現行は原pathを保持する。旧版のsubstring媒体判定/公的組織判定、現行のHTTP URL検証の差も再現できた。

この合成入力は境界差を調べるために選んであり、企業の分布を代表しない。**13候補対10候補から現行の精度が高いとは判断しない**。旧previewのCANDIDATEには不正schemeを通す例も含まれ、保存Company件数ではない。現行のCANDIDATEも公式・業種・フォーム確認済みを意味しない。

Human reviewed=0。Strict/Resolved Precision、公式サイト精度、問い合わせ先発見率、API cost、Coverageはnull。1Runなのでstability率もnull。処理時間はオフラインprojectionのみであり、検索/API/サイト取得時間ではない。repeat overlapはRaw観測の一致で、Human Entityの同一性ではない。

## 品質確認

- Offline pytest: **28 passed**（DBなし）。原データ不変、snippet、domain境界、重複、invalid URL、空/部分/中断、反復上限、stability、Human label推測禁止、secret拒否、private保護、source不純化拒否、通信拒否、上書き拒否を確認。
- Ruff check/format、mypy、Python compile確認。
- CIへ `offline-collection-replay` jobを追加。pytest/mypyをAPIキー・DB・旧repo cloneなしで実行する。unit testの旧policyはsyntheticであり、固定旧SHAのCLI再現はローカルの別確認。
- Frontend、API、worker、Model、Migration、Humanレビュー・送信承認コードは変更なし。既存のCI回帰jobは維持。

実企業収集=0、企業サイトGET=0、有料API=0、AI=0、Completion=0、Approval=0、Email/Form送信=0。productionのoutbound/worker設定は変更していない。

## 残りと次の工程

1. 既存Human Raw Reviewの正本から、snapshot hash/version・reviewer・時刻・Evidenceを照合できるprivate評価export/import境界を設ける。JSONにCORRECTと書かれただけでHuman Truthとして受け入れない。
2. 実データはSource保持条件とHuman承認範囲を固定した少量Serper Pilotで測定する。今回の実装をlive実行の承認とは扱わない。
3. gBiz corporate schema、Places保存/用途、公式サイト/問い合わせC1/C2、条件別unique gainは別工程。Human確認済みの正解がない段階ではprecision改善を主張しない。

この工程ではオフライン比較までで停止する。Full Benchmark、収集改善、DM/Approval実行へ自動移行しない。
