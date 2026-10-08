# 新CF7候補契約のwireを実CF7で照合

## 1. 完了範囲

2026-10-06、`codex/integration@83272c4` を基準に、docs/118の新しいmultipart encoderを、隔離した公式CF7 6.1.4で検証した。**新wireのCF7受付、Browserとのfield/捕捉mail hash一致、失敗時UNKNOWN、構造変更時のHTTP前停止を確認。**

これはprotocol/wire検証であり、Human Approval・永続台帳・Production transportを接続したend-to-end dispatchではない。実企業アクセス、SMTP/PHPMailer配送、実企業フォーム送信、deploy、利用中DB/workerの変更を行っていない。

## 2. 構造と変更

- `scripts/cf7_lab/contract_probe.py`：管理下の標準DOMから候補を作り、snapshotを照合して新encoderのbytesを取り出す。MIMEとしてdecodeした値と実Browser wireを比較する。
- `cases.py`：既存35チェックを維持し、新wireのcapture/fail/Browser/query-root/変更停止を追加。
- `browser_probe.cjs`：検証用emailを既知2値だけから選択可能。各Browser実行はPOST1回、外originは拒否。
- `test_contract_probe.py`：opt-in、既知fixture限定、未知variant/field/CAPTCHA拒否、変更停止、任意endpoint拒否のoffline5テスト。

bridgeがimportするLeadHiveコードは純粋な候補契約とInputValueだけ。app.main、config、database、approval/dispatcherをimportしない。

**候補内の `https://managed.example` は論理placeholderであり、実行しない。** 管理下で観測した正確なloopback CF7 feedback routeだけへwire bytesをPOSTする。これは本番URLの書き換え、承認URLの転用、localhost例外ではない。固定UUIDはlab metadataであり、LeadHive DB上の企業・Project・承認記録を参照しない。snapshot照合のexpected hashはlab内の固定データから計算し、Human proofと扱わない。

標準4field・通常acceptanceだけをbridgeで扱う。optional/invertの実CF7既存caseは残すが、新候補bridgeがそれらに対応済みとは判定しない。DOM attributeやmultipart payloadの曖昧な型は拒否する。

## 3. 外部配送の隔離

docs/115と同じ固定CF7 source commit/checksum、WordPress 6.8.3/PHP 8.3.28、MariaDB 11.4 digestを使用。UUID付き専用internal networkのみ、container port公開なし、loopback gateway→Docker stdin→自身のApacheだけ。

WP HTTPと数値IPへの外部443/25/587接続の遮断、pre_wp_mail捕捉の有効性を最初のPOST前に確認する。実PHPMailerは禁止。終了時は作成記録と所有labelが一致する専用container/volume/networkだけを撤去し、既存資源を変更しない。

## 4. 結果

最終runの詳細・版・digest・件数は [共有集計JSON](fixtures/119_cf7_candidate_wire_summary.json) に保存する。**全43チェック合格、cleanup failures 0。**

| 確認 | 結果 |
|---|---|
| 新wire | snapshotのwire hash/sizeと実bytesが一致。decodeしたhidden6＋入力4、UTF-8/CRLF値が期待どおり |
| 実CF7 capture | new encoderのraw bytesを再エンコードせず送信しmail_sent、RECEIPT_REPORTED。捕捉mail/submission各1回 |
| 実CF7 failure | 同じwireを明示した別failure caseとして送信しmail_failed→UNKNOWN。自動retryなし |
| 実Browser比較 | 新候補と同一の架空sender/本文/同意を通常CF7 JavaScriptでPOST1回。全field値・endpoint・捕捉subject/body hashが一致 |
| query REST root | 実DOMからindex.php?rest_route形式を観測し、新wireで受付。捕捉mail hashはpath形式と一致 |
| 構造変更 | 保存した実DOMの同意文/unit tagをoffline変更。旧snapshotとの照合で停止、HTTP/submission/mail呼出しを追加しない |
| 総件数 | feedback POST19回、CF7 submission17回（415/400の2回はsubmission前拒否）。protocol mail捕捉10回、WP初期通知/probe別2回 |
| 異常応答 | 既存のspam/abort/demo/skip、別form ID/unit tag等の否定チェックを維持。mail_sentを到達保証と扱わない |
| Browser版 | Chromium 153.0.8010.12、outside-origin requestなし |
| 片付け | 専用container/network/volume残存0。Docker全体reset/pruneなし |

既存15＋新bridge5のoffline **20テスト成功**。専用leadhive_location_testで新候補18件＋既存契約/承認121件＝ **139テスト成功**（50 subtestsを加算しない）。pytest開始時upgrade head/Alembic check成功、新Migration/Model変更なし。

Ruff lint/format、Python compileall、Node構文、bridgeのmypy（check-untyped-defs / follow-imports=silent）成功。mypy strictによるlab全体のinterface検証ではない。Frontend typecheck/lint/build成功。利用中API health 200・app/database ok、送信worker exited。Backend全suite、Migration往復、Human UI E2Eは今回再実行していない。

raw report/page/query-page/candidate-snapshot/candidate-wire/candidate-browser-wireはignored `dist/leadhive-cf7-lab-<UUID>/`。すべて管理下の架空データ。共有JSONにはpassword/cookie/API key、本文全文、WordPress初期通知を入れず、版・結果・hash・件数だけを残す。

## 5. 判定の限界

- raw multipartの意味と管理下CF7処理の一致を示す。multipart boundary自体はBrowserと異なるため、Browser全bytesが同じという意味ではない。
- CF7 posted_data_hashは動的でありLeadHive idempotency/approval hashではない。メール到達・相手の閲覧・第三者pluginの副作用なしを証明しない。
- HTTPS候補URL/DNS/TLSを実WordPressへ接続した試験ではない。docs/116–117の通信prototypeとは別の証拠であり、loopback gatewayを本番transportに転用しない。
- 新candidateはNON_EXECUTABLEのまま。新候補のHuman Approval保存/step-up、DB consume guard、reservation、永続UNKNOWNとの連結は未実装。
- Production observer、CAPTCHA、ログイン/nonce、JS変換、file、subdirectory、追加plugin、実企業、大量運用は対応確認の対象外。

## 6. 次のゴール

**新CF7候補を保存・Human確認へ渡すための設計と、非実行DB guardの条件を整理する。** 現行Foundation/fixture契約を再利用し、承認と送信を分離する。既存guardを緩めたり、通常workerへCF7を登録したり、送信を有効化しない。今回のwire検証後に停止する。
