# Phase 3: 二段階フォームの管理用HTTP検証

## 基準・結論

基準 `main@dda34ad`（PR #33統合後）。ブランチ `codex/two-stage-controlled-http`。

二段階専用の管理用binding契約を追加し、匿名localhostサーバーでmultipart入力→確認→最終受付を検証した。通常の単一POST契約、Human承認UI、送信worker、production adapter registryは変更しない。

**管理用テストのGOであり、実フォーム送信はNO-GO。** HTTP coordinator / concrete transport / serverはすべて `backend/tests/` に置く。本番のAPI・workerから利用できる送信経路は追加しない。outbound / legacy form deliveryはOFFのまま。

## 二段階契約

`app/services/two_stage_lab_contract.py` はFrozenContractの `TwoStageLabPlan` を提供する。CONTROLLED_LABとtwo-stage-lab-v1を固定し、承認ID/hash、Draft ID/hash、FormProfile ID/hash、送信者source hash、Company source hash、既存ExecutionPlanを結合する。

すべて既存のHuman承認済みimmutable snapshotに含まれる情報から決定する。Draft本文・件名、ProfileのURL/action/fingerprint/confirmation設定、現在のsender、必須field mapping、二段階route hashを照合する。添付、file/hidden/submit/buttonの保存済み入力、未知の必須値、危険なfield名・予約token名を拒否する。model_copyによる検証回避もcanonical再検証で停止する。

generic `form_plan_fixture` を本番ExecutableFormPlanへ昇格しない。fixture ApprovalRequestはCONSUMEDに変更しない。承認済みsnapshotが変更された場合は既存の失効・再承認ルールを維持する。

## 管理用HTTP経路

固定の `https://fixture.example/contact` / `confirm` / `submit` だけを認め、test transportが `127.0.0.1` のランダムportへ接続する。port範囲を検証し、その他のURL・method・queryを拒否する。proxy環境変数・redirect追跡・HTTP retryは無効。外部DNSや実企業サイトには接続しない。

1. 同一Human sessionのstep-up証跡、APPROVED hash/version、期限、現在のCore permissionを確認。
2. 現在のDraft/Profile/senderを再結合。既存duplicate判定、FormDispatchLimits、送信時間を確認。
3. 管理用試行のdaily/hourly/interval上限と共有URL重複を確認。review startと確認試行markerをcommit。
4. 保存済みfingerprint・2つのactionを管理用GET応答と照合し、承認済みfield valuesだけをmultipart POST。
5. serverはtrial ID・form ID・payload hash・field valuesに結びついたランダムtokenを発行。HTML、token、識別子を応答。
6. 応答の識別子/hashを照合し、5分以下のaware token期限と既存の厳格HTML parserを検証。確認値の変更・未知control・script・外部action等は停止。
7. 最終POST前にHuman/session・source bindings・Core permission・上限/時間・重複・token期限を再確認。
8. token消費ledgerと最終試行markerを同一transactionでcommitしてから、固定submitへmultipart POST。
9. serverは保存済みtoken/ID/hash/fields/期限を照合しtokenを一回だけ消費。最終応答もform/trial IDとfinal stage / fixture_acceptedを照合。

実DBへのcommitは独立したSessionから各POST直前に確認した。関連するDB行ロックはPOST中に保持しない。

## 結果とUNKNOWN

成功は `FIXTURE_SUBMITTED` として管理用ledgerに記録する。Lead CompletionのSENTや実際のDelivery実績には加算しない。確認結果の不一致はBLOCKEDまたはUNKNOWN。最終応答の曖昧さ・応答喪失・例外はUNKNOWN。

開始markerが存在する同じ承認からは再実行できない。結果markerのcommitに失敗しても開始/試行markerを自動的に消して再POSTしない。UNKNOWNはHuman review対象のまま。

管理用の共有URL保護は保守的に、別承認の先行確認試行がある同じURLへの再POSTも拒否する。実運用のduplicate windowやHumanによるUNKNOWN解除は今回追加しない。

## 検証

- 最終新規スイート20件PASS。
- 関連する確認・Human approval・単一POST実行の回帰スイート127件PASS（追加の応答境界ケース・並列ケース前）。その後、最終新規20件を再実行してPASS。
- 同時の独立DB接続2つから全フローを実行し、片方だけ成功、確認/最終POST各1回、受付1回を確認。
- Draft/sender/profile/suppression/CAPTCHA/limits/flagの確認後変更では最終POST0件。
- nonce/form/hash不一致、期限切れ、確認値変更、曖昧な最終結果、確認/最終応答喪失、未承認、禁止URL/method、予約field名を確認。
- 使い捨てDBのmigration upgrade / Alembic model diffと、独立接続からのcommit済みmarker/token消費を確認。
- Backend全体Ruff / format（475ファイル）、新規5ファイルmypy PASS。契約のmypyをCIへ追加。
- GitHub Actionsの全体回帰・E2E・migration往復・Windows配布/起動はPRで確認する。

全ケースで実送信予約・EmailDelivery・FormDeliveryは0件。匿名ApprovalRequestはAPPROVEDまたは安全なREVOKED/EXPIREDのみ。実営業Human承認の代行は0件。

## 未完了と次の境界

これは固定管理用サーバーでの検証で、実サイトのHTML/token/受付判定を信頼できるという証明ではない。新しいHTTP全フローの独立プロセスkill試験、実サイト用SSRF/DNS pinning・cookie/CSRF・HTML observation provenance、production二段階Dispatch/Deliveryのatomic consume、再承認UI、実サイト別の受付判定が残る。

既存のレビューstart/token消費はPR #33で独立processの競合とcommit前後killを検証済みだが、それを今回のHTTP全フローのprocess障害検証と同一視しない。

実候補の窓口用途・予算・必須入力はHuman確認が必要。CAPTCHA回避・営業禁止解除・実サイトGET/POST・検索/AI API・SMTP/フォーム送信・deploy・自動mergeは行わない。
