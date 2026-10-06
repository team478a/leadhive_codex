# Phase C2: DM READY計測とHuman承認への引き渡し

## 完成条件と境界

C1の根拠付き下書きを、選択窓口・公開情報の根拠・送信者・入力値を固定したPENDING ApprovalRequestへ引き渡す。既存Human Approval Foundationを再利用し、Agent承認・自動承認・外部通信・送信を追加しない。今回の操作は承認待ち提案の作成まで。

窓口READY、C1のDRAFT_PREPARED、C2のDM_READY、Human APPROVED、送信結果は別状態。DM_READYは「現在の保存済み情報に対して有効なC2 PENDINGまたはAPPROVED提案が存在する」状態で、送信許可ではない。CONSUMED・却下・取消・失効は現在の準備完了件数に含めない。履歴上の累積完成件数とは区別する。

## APIと画面

- GET `/api/dm-preparations/{id}/approval-preview`: Project内のHuman利用者が保存済みデータを確認。owner/editorのみ作成可能。
- POST `/api/dm-preparations/{id}/approval-request`: `expected_preparation_hash`だけを受け付け、PENDINGを作成。confirmed・宛先・送信者・入力値の上書きは拒否。
- 企業詳細の根拠付き下書きから「入力内容を確認」→「承認待ち提案を準備」。この操作では承認・送信しない。
- 既存Human承認画面で根拠URL・引用・使用した事実・窓口選択版も表示。承認には既存のsessionにbindした短時間・一回限りの再認証を使う。

## 固定と変更検出

ApprovalRequestの既存immutable payload_snapshotへサーバー専用の`lead_dm_binding`を追加。C1記録ID、元snapshot hash、窓口選択版、送信者hash、根拠、準備期限、canonical提案内容とフォーム依存hashを結ぶ。外部request schemaからこのmetadataを受け付けない。

メールは保存済みSMTPの公開送信者名・メール、設定がなければ環境設定から固定。資格情報は取得・出力しない。フォームは既存FormSenderSettingsとFormProfileのmappingを使い、必須項目・本文・連絡方法・同意等の既存guardを維持。確認画面が未確定／あり、POST先未確定、選択窓口との不一致は保留。サイト取得・POSTは行わない。

作成時はProject・membership・Company・送信者・フォーム・テンプレートの既存データをlockし、再確認する。同じ準備への繰り返し作成は有効な提案を再利用。有効期間は24時間と元の用途／窓口／C1準備期限の短い方。

根拠付き下書きの最新版、テンプレート、営業条件、用途・窓口選択、送信者、フォーム構造の変化は旧提案を無効にする。診断はread-onlyで現状を判定し、承認系操作の既存invalidationでREVOKED／EXPIREDとauditを同一transactionへ保存。承認済みpayloadの検証も同じguardを利用する。旧承認に対する一般revisionは禁止し、C1から再準備する。

作成するOutreachDraftはC2 bindingで保護し、従来の編集・削除・直接送信・Codex支援結果登録・支援payload取得と、metadataを落とした一般再提案を拒否する。通常の既存Draft動作は維持。

## DM READY率

固定リストの窓口診断に各Leadの`dm_ready`と未完了理由を追加。25件ずつ全件終了したときだけ、現在のDM_READY件数 ÷ 固定DISCOVERED分母を表示。削除・統合されたLeadも分母を維持。部分集計・中断・エラーでは率を未判定にする。ページ単位の観察期間の結果であり、全件を一時点で固定した送信承認snapshotではない。

既存のFunnel reportの未実装stageを推定値で埋めない。C2の現在状態は専用診断で集計する。Human承認率、累積送信Funnel、Cost per DM READYの金額換算は今後の工程。

## DB互換性と制約

新規Model・Migrationなし。既存LeadDmPreparation、ApprovalRequest、OutreachDraft、OutreachAuditEventを再利用。既存immutable guardを変更しない。既存承認・送信基盤の設定を有効化しない。SMTP/Form送信者設定は現状のinstallation単位であり、企業別設定分離は今回の変更に含まない。

## 検証と次工程

専用PostgreSQL _test DBと合成exampleデータで、PENDING作成・再作成・Human step-up・変更失効・他Project／viewer／Agent拒否・入力改ざん拒否・旧経路保護・read-only診断を検証。desktop/mobileのブラウザテストは送信／承認endpointを禁止して準備操作のみ確認。

次工程候補: Human承認済みDMの引き渡し・結果記録を既存Deliveryへ統合し、送信せず安全guardと測定の対応を検証する。実リスト・実サービスでのREADY率は今回測定していない。

## 今回の確認結果

- 関連Backend 141件（127件の承認・下書き・選択・診断回帰と、追加14件の既存Outreach/Form回帰）。最終C2 11件も再実行して成功。
- desktop/mobile E2E 6件成功。新C2ケースは実承認・送信endpointを禁止。
- Ruff、変更したBackend 6ファイルのmypy、Frontend typecheck/lint/build成功。
- 専用空DBで既存headから親revisionへのdowngrade→upgrade→model差分確認成功。API起動はE2E専用serverで確認。
- 既存Frontend bundleの500kB警告は継続。今回の機能動作とは分け、後続の読み込み分割候補とする。
- 実運用DB、稼働コンテナ、配布パッケージ、外部サービスは変更していない。
