# AI進化対応ロードマップ — Phase 1監査からの提案

コード基準: `7e875c317675a110733dae23921dd1624a06107e`。本Phaseは監査・検証・設計のみ。以下は未実施の次工程案であり、自動開始しない。

## 目標と判断

営業条件 → 正しい企業・店舗候補 → 根拠ある適合判定 → 正しい窓口 → 根拠付きDM → Human承認 → 安全配送に絞る。CRM/SFA/MA、巨大企業DB、汎用Agent、完全自律営業を追加しない。モデルの新しさではなく、Human truthに対する改善、原価、作業削減、安全性で採否を決める。

今回30 Raw観測/25domainを固定し、URL構文30/30・再出現domain5を測定、純粋テスト19PASS。正式Humanラベル0のため適合率・公式性・連絡先精度はnull。別の17社フォーム診断はHOLD15/BLOCKED2。これらから「新モデルで精度改善」や「送信可能」と結論しない。

## 最優先3項目

工数は1名のエンジニアによる概算、人日=8時間。外部API費用、実施承認、Human作業を含む確約ではない。

| 優先 | 改善対象・根拠 | 想定工数 | 受入条件 |
| --- | --- | --- | --- |
| 1 | Human truthと一次収集評価を完成。30観測に正式ラベルがなく、現在の精度を説明できない | 整備1–2人日 + Human2–4時間、判断不能は別調査 | 全30観測にHuman outcome/evidence/hash/時間または明示UNKNOWN。Pairを同定。strict/resolved precision・公式性・窓口精度を正しい分母で再集計。nullや重複を成功へ昇格しない |
| 2 | AI比較manifest・prompt版・回帰gate。共通モデル設定、最終ruleの再判定、最新結果上書きが比較の障害 | 2–4人日 + Human評価時間、API費用は見積後 | 同一snapshotで旧/候補model比較を再現。raw/final判断を分離。重大創作/注入安全違反ゼロ、false positive非悪化、使用量・価格版・error保存、旧設定への復元検証 |
| 3 | 頻出フォーム停止理由の再現と検証。17社の13件がREVIEW、技術実行可ゼロだが原因を一括断定できない | 分類・fixture整備2–3人日。実Adapter修正は別見積 | 停止理由を根拠付きで分類。選んだ一構成だけowned fixtureで検証。変更fingerprint停止、未知必須停止、suppression/CAPTCHA/UNKNOWN保護維持。独立DestinationとHuman時間で効果測定 |

1→2→3を基本順序とする。評価manifestとフォームfixtureの文書整備は並行可能だが、ラベルのない精度を使ってモデルや収集条件を採用しない。次に実施すべき一工程は**既存30候補のHuman評価資料を確認し、正式ラベルと根拠を付けること**。

## 再利用と不足

| 項目 | 現在再利用できるもの | 最小追加候補 |
| --- | --- | --- |
| モデル設定 | ApplicationSettings + config fallback | per-task設定は評価で必要性が出た時のみ検討。初期はmanifestで影響範囲を固定 |
| prompt版 | Git commit、ai.pyの定数 | prompt/schema/context hashと明示版をrunに保存 |
| 比較 | AiProvider、typed output、Raw Human Review | private paired evaluatorとmanifest。新Gateway不要 |
| 切り戻し | Git・設定変更経路 | 旧モデル/版/閾値の保存、権限・利用可能性の確認、回帰合否 |
| 原価 | LeadProcessingUsage、token/elapsed/model | 全callerの捕捉漏れ確認、価格版・retry課金・請求照合。不明null |
| 監査 | AI latest fields、Human review、OutreachAuditEvent | 分析runのappend-only証跡候補。Outreach台帳を分析ログ代わりに乱用しない |
| 失敗改善候補 | form result/UNKNOWN/compatibility、Work Queue | 既存reason別集計とfixtureリンク。自動生成は提案に限定 |

モデル変更の候補は公式仕様とアカウント利用資格の確認後に選ぶ。現在のコード既定名だけでAPI利用可能とはしない。API費用は単価・usage・課金対象が確定した場合のみ計算する。

## Dots・Codexの役割

Dotsは改善候補の整理、作業履歴、Humanへの次案提示に限定し、LeadHive Coreや正本DBの代替にしない。Codexは監査、許可された実装、fixture/CIの検証を担当する。どちらも営業正解ラベルやHuman approvalをAI自己判断で作らない。

[Dots公式Controls](https://learn.chatgpt.com/docs/dots/controls)は利用者がActivity/ルール/権限を確認する方式であり、独自ルールで既存の権限・安全制御を上書きできない。[Tasks and memory](https://learn.chatgpt.com/docs/dots/tasks-and-memory)の継続文脈を企業/窓口/承認/送信結果のSystem of Recordにはしない。本監査でDotsの外部API接続能力やLeadHiveへのconnector利用資格は検証しておらず、自動組込みを約束しない。

Computer useはローカル/ownedフォームの検証候補。第三者の実送信、CAPTCHA回避、Cookie代理利用、承認代行は許可しない。改善候補の自動分類は変更を確定する権限ではない。

## Gateと停止条件

1. **評価データgate**: Raw固定・Human truth・保存条件・権限確認。Places利用を増やす前に保存制約/attribution/stable IDを確認する。
2. **比較gate**: 同一入力、manifest、null対応、モデル利用資格・予算。価格不明なら有償評価を開始しない。
3. **採用gate**: Humanが品質・原価・安全・切り戻しをレビュー。未reviewや不明を成功にしない。
4. **実装gate**: 別指示による最小変更と既存CI回帰。監査PRにコード/Migrationを混ぜない。
5. **運用gate**: deployment/sendは別承認。Human/Agent分離、immutable payload、suppression/opt-out、重複、UNKNOWN保護を維持する。

重大なHuman承認境界の迂回・誤企業への窓口紐付け・利用条件不適合が判明した場合、モデル改善より先にblockerとして停止する。現在の確認結果だけで全送信経路の安全性を保証しない。

## 今回の成果物と未完了

- [現行監査](LEADHIVE_AI_CURRENT_AUDIT.md)
- [収集精度レポート](LEADHIVE_COLLECTION_ACCURACY_REPORT.md)
- [AI評価計画](LEADHIVE_AI_EVALUATION_PLAN.md)
- [フォーム信頼性レポート](LEADHIVE_FORM_RELIABILITY_REPORT.md)

完了: コード/テスト照合、30観測固定、offline測定、19純粋テスト、モデル比較・フォーム評価・進化対応設計。未完了: Human truth精度、ライブURL/窓口評価、実モデル比較、原価・ライブ速度、第三者フォーム成功率。監査PR提出後に停止し、実装・merge・deployment・営業送信を開始しない。
