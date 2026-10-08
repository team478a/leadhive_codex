# Phase 2 — 収集精度集計

基準PR #2。30観測のsnapshot cohort hash: `e28cdcf53c32b6a0658e35ec095061a636b98b7fe8ad843292059994a5bf28b4`。個別payloadのhashと集合hashを再検証し、元データを上書きしていない。

| 指標 | 現在値 | 分母 |
| --- | --- | --- |
| 観測 | 30 | 固定Raw |
| domain | 25 | domain単位、企業正解数ではない |
| 正式Raw review済み | 0 | 30観測 |
| review coverage | 0% | 0/30という既知値 |
| 営業対象適合率 | null | 項目別Human label 0 |
| 公式サイト特定精度 | null | 候補URLの項目別Human label 0 |
| 問い合わせ先精度 | null | 固定窓口候補の項目別Human label 0 |
| 企業重複率 | null | 正式Raw review 0 |
| 判定不能率 | null | 正式Raw review 0。未review30をUNCERTAINへ変換しない |
| domain再出現観測 | 5 | 5/30=16.7%、企業重複率とは異なる |
| 同一domain Pair候補 | 6 | 組合せ数、SAME label 0 |

**今回Human truth確定は未完了。** 会話での採用・自動分類・取得可能なWeb・URL構文の正しさを正式正解にしない。問い合わせ先について、別集合17社の診断を今回30観測の検出正解データへ流用しない。

## 計算仕様

`scripts/prepare_phase2_evaluation.py` は既存Rawの `digest/ratio` を再利用する。

- Raw Strict precision = CORRECT / 正式Raw review済み（UNCERTAIN含む）。Raw Resolved = CORRECT / (review済み−UNCERTAIN)。これは地域・業種・entity等を総合したRaw品質であり、項目別営業適合率とは別。
- 項目別strict = CORRECT / (項目label済み−NOT_APPLICABLE)。resolved = CORRECT / (CORRECT+INCORRECT)。UNKNOWN数と未label数を別表示。全件UNKNOWN又は分母ゼロの場合は両precision=null。
- Duplicate rate = DUPLICATE / 正式Raw review済み。同一domainだけではDUPLICATEにしない。同一企業へのCORRECT重複entity_keyが残る場合は整合性を人間が確認してから集計する。
- Uncertain rate = UNCERTAIN / 正式Raw review済み。公式性等の項目UNKNOWN率と総合UNCERTAIN率を混ぜない。
- 項目別精度は正解を判断できた割合・review coverageを併記する。UNKNOWNをINCORRECTへ変換しないが、strictの分母に含むことは明示する。

今回の全件未reviewはprecision=nullであり0%ではない。Human評価が一部だけ完了した場合はその分母と未評価数を表示し、30件全体の精度と称しない。単一サイトに複数Rawがある場合、観測単位のprecisionとSAME確認後のentity単位を別に扱う。Coverage/recallは完全Reference Setがないためnull。

## 実行・再現

```powershell
$env:DATABASE_URL='postgresql+psycopg://offline:offline@127.0.0.1:9/offline'
$env:OPENAI_API_KEY=''
$env:OUTBOUND_ENABLED='false'
python scripts/prepare_phase2_evaluation.py --cohort <private-cohort.json> --forms <private-diagnostics.json> --output <new-private-directory>
```

Python環境は既存backend依存を使用する。新しいdependencyは追加しない。出力は新規ディレクトリのみ、既存出力を上書きしない。入力が今回固定30件でない・payload/hashが変わる場合は停止する。資格情報・session Cookie・秘密URLを資料へ入れない。正式exportの信頼性は認証済みserverと運営者の照合が前提。

今回の実行結果は `docs/results/ai-phase2-preparation-2026-10-09.json`（集計のみ）。private資料の場所はHuman Truth手順を参照。
