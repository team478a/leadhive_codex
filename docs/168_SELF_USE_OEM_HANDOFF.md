# 自社利用：ハッシーOEM候補の保存・窓口確認・下書き引継ぎ

## 今回のゴール

共通サーバーDBは将来設計に留め、既存ローカル環境で自社の営業候補を再利用できる状態にする。今回は保存・確認待ちの整理・未承認下書きまで。送信可能性、Human承認、実送信の完了を意味しない。

基準コード：`codex/integration@3623baf7b848fea47d30738996ee097590979ea7`。

## 利用するフロー

1. 収集結果をRawとして保存する。後工程でRaw Snapshotを書き換えない。
2. 企業・公式サイトの同一性と、問い合わせ導線・営業禁止を確認する。
3. 営業目的に対する候補採用を記録する。対象外や連絡禁止も理由付きで保持する。
4. 有望候補のフォーム構造、必須項目、CAPTCHA、窓口用途を確認する。
5. 未承認下書きを作成する。下書きの存在をDM READYと数えない。
6. 根拠・Destination Review/Choice・Core permission等の既存条件を満たしてから、既存のDM PreparationとHuman Approvalへ進む。
7. 送信時は有効な承認と安全制御を再確認し、結果を保存する。UNKNOWNは自動再送しない。

## ローカル環境への引継ぎ結果

プロジェクト名：**自社営業｜ハッシーOEM｜採用候補16社**。所有者は既存Raw Projectの所有者と同じ。新しいユーザーやセッションは作成していない。

| 項目 | 件数 |
|---|---:|
| 保存した企業候補 | 16 |
| 営業禁止として連絡禁止を設定 | 2 |
| 未承認OutreachDraft | 14 |
| DM READY | 0 |
| Human送信承認の作成 | 0 |
| Email / Form送信 | 0 / 0 |

既存のProject、TargetProfile、Company、FormProfile、FormProfileField、ContactDestination、LeadDestinationLink、OutreachTemplate、OutreachDraftを再利用した。コード・DB schema・migration変更はない。

元のRaw Benchmarkと営業Projectは分離した。候補採用のチャット記録をRaw CORRECTラベル、Human窓口確認、公式サイトCONFIRMED、送信承認に変換していない。

公式サイト候補・問い合わせ候補は保持するが、FormProfileは営業禁止をPROHIBITED、それ以外をUNCERTAINとして保存した。delivery_supportedはfalse、未検証fingerprintは空のまま。Core permissionは全16社でALLOWEDではないことを確認した。

14件の文面は既存所有者のOEM提案Draftから再利用し、以前の相手企業名・会社固有のサービスへの言及を取り除いた。新しい宛名を差し込み、LPと署名を維持した。AI呼出しはない。Human作成と偽装しないよう作成者User IDは付与していない。C2の根拠付きLeadDmPreparation、DestinationChoice、ApprovalRequestは作成していない。

## 画面で確認する順序

1. プロジェクト一覧から上記プロジェクトを選ぶ。
2. 企業一覧・詳細で候補と連絡禁止を確認する。
3. 各社のメモで停止理由と根拠URLを確認する。
4. 連絡禁止でない企業の既存営業文面画面で未承認下書きを確認する。

資料請求・採用・サービス購入相談の窓口を営業提案の窓口として自動選択しない。営業・協業専用窓口の指定がある場合はそちらを候補にする。通常の問い合わせリンクがあることを営業許可とみなさない。

## 残る確認

- 企業・公式サイトの同一性、正式名称・所在地の確認。
- 窓口用途・営業可否、必要に応じたHuman Destination Review / Choice。
- JavaScript、外部フォーム、Contact Form 7等の経路確認。
- CAPTCHAのある経路はHuman Required。回避・自動突破しない。
- 必須入力項目・選択肢・同意項目・送信者情報の確認。
- 既存Projectの連絡禁止や履歴を別Projectへ移しただけで失わせないこと。実送信前には関連する既存履歴・opt-out等の照合も必要。

既存CF7候補準備はCONTROLLED_FIXTUREおよび専用試験DBを要求する。実企業の観測を管理下fixtureとして偽装したり、この制約を解除したりしていない。

## 検証・安全条件

- 新規作成後に再実行し、追加企業0・追加下書き0を確認。
- 企業16・連絡禁止2・Draft14をDBで検証。
- 元の承認・送信・OperationJob・Raw Review/Snapshot・LeadDmPreparationの件数不変を検証。
- 元の私用入力資料のSHA-256不変を検証。
- outbound、承認付きEmail/Form、Agent機能はOFF。
- 送信worker、新規外部検索、AI、SMTPテスト、Form POSTは実行していない。
- ローカルWeb応答200、匿名Project API401を確認。
- コード変更がないため、新規CI・migration検証は対象外。ブラウザのログイン後操作を今回実行したとは主張しない。

個別企業・窓口・下書き・照合結果はGit管理外のローカル資料および既存ローカルDBに保持する。詳細引継ぎ結果は`dist/provider-role-pilot-20261008T013912Z/self-use-handoff-result.json`。共通データベースや組織間共有は実装していない。

## 次工程

### 少数候補の未送信preflight

セルフアチーブ、RIVEREATE、トレプロの3候補について、保存済みDraftとFormProfile情報から、既知の送信者情報・本文・入力欄の対応を確認資料へまとめた。送信、入力、同意チェック、Human確認の代替は実施していない。

- セルフアチーブ：ブラウザ表示で氏名・メールに加えて「お問い合わせ項目」が必須と確認。保存済み静的解析はグループ単位の必須条件を検出できておらず、確認資料に未解決条件として追加した。各チェックボックスを全部必須と解釈してはならない。
- RIVEREATE：標準フォームのname属性と通常POST経路を確定できない。ブラウザのナビゲーションは到達したが、表示内容・スクリーンショット取得がタイムアウトしたため、ブラウザ検証完了とは扱わない。
- トレプロ：本文とCF7スパム対策用の隠しtextareaが同じmessageにマッピングされていた。確認資料では隠し欄に本文を入れないよう分離した。既存parserや実行経路を変更したわけではない。プライバシー同意はHuman確認待ち。

必須の送信者情報を用意できることと、全必須条件・利用用途・技術経路を確認できることは別。3件とも未承認・DM READY未達。確認資料はGit管理外の`self-use-three-candidate-preflight.json`。ブラウザで入力・送信は一切行っていない。

営業禁止・CAPTCHAを避け、少数候補の正式名称・窓口用途・必須項目を既存Human確認フローで確定する。その後、既存DM Preparationの安全条件を満たせるか検証する。未対応フォームをREADYへ繰り上げたり、Human step-upを代替したりしない。
