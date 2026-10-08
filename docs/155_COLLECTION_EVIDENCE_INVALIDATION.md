# 収集条件の根拠失効・取消の統一

## ゴール

基準 `codex/integration@228f71e`。収集条件の判定を、現在の有効な根拠だけで行う。人の取消・失効を古い自動根拠で復活させない。追加検索、AI、収集精度の測定、送信はこの工程の対象外。

## 発見・修正した問題

従来のOFFICIAL_SITE条件は、24時間以内の自動CONFIRMED根拠が1件でもあればMATCHとし、最新Human確認が取消・期限切れでも自動根拠へ戻る余地があった。最新の自動根拠が未確認の場合も古いCONFIRMEDへ戻れた。MEDIA_EXISTSとHuman Fact Reviewでは、未来日時の記録を有効とする余地があった。

`services/official_site_condition.py`へ収集用公式サイト判定を分離する。最新Human Site Identity Reviewが存在する場合、その状態を優先する。REVOKED / EXPIRED / STALE / 未来日時 / 24時間超過 / Project不一致はUNKNOWN。人の有効な確認があれば、その確認URLと日時を返す。

Human記録がない場合は当該Companyの最新LeadSiteEvidenceだけを利用する。現在identity hash・CONFIRMED・24時間以内かつ未来でないことを要求する。最新が未確認・別identity・期限切れなら、以前のCONFIRMEDへ戻らない。証拠URLは現在の公式ドメインに限定し、既存の安全検査を再利用する。

AREAも最新証拠を選んだ後にidentity hashを検証する方式へそろえる。過去の企業情報へ偶然戻ったときに古い証拠を拾わない。前工程の地域判定・店舗のHuman住所確認・地域Fact Review優先順位は維持する。

SNSのFOUNDは観測日時、NOT_FOUNDは既存のCOMPLETED調査日時について、24時間以内かつ現在以前であることを要求する。NOT_FOUNDのobserved_atは既存モデルで未設定であり、それを要求する変更は行わない。未調査・失敗を「なし」にしない。

Human地域・業種Fact Reviewも未来の作成日時はUNKNOWN。期限切れ・取消から自動根拠へ戻さない既存制御を維持する。

## 表示・互換性

公式サイトの取消、確認期限切れ、確認後の企業変更、根拠URL不一致、未来日時を日本語で表示する。原因が分からない単なるUNKNOWNにせず、確認待ちの理由を示す。既存の条件結果・Operation結果APIで使用する。Model・API・Migration・dependencyの追加なし。

この変更は収集条件の判定境界に限定する。Delivery、Human Approval、Lead Completionの既存公式サイト確認Serviceを大規模に変更しない。条件MATCHは送信許可ではない。MUST / EXCLUDEのUNKNOWNは確認待ち、WANTのUNKNOWNは希望未確認という既存分類を維持する。

## 検証・安全

取消・期限切れ・企業変更・未来日時・別Project・不正URL・最新未確認・古い証拠へのfallback禁止・現行Human証拠の採用をBackendで検証する。別ProjectのHuman証拠は既存DB guardでも拒否される。PC/Mobileでは、保存済み自動証拠があってもHuman取消後に一致から確認待ちへ戻り、理由が表示されることを合成データで確認する。

送信OFF、worker停止を維持する。実企業GET・AI・追加検索・Human Approval作成・メール/Form送信なし。Raw SnapshotとHuman Truthは変更しない。実行結果は検証後に追記する。

## ローカル検証結果

- Backend関連84件PASS。その後追加した未来Human Fact Reviewと最新地域根拠選択を含む最終の根拠・地域39件PASS（重複を含む）。合計85種類の関連テストを確認した。
- PC/Mobile関連E2E6件PASS。条件確定・地域確認・公式サイト取消と根拠URLを含む。追加した取消テストでは外部アクセス・収集Operation開始・送信がないことを検査する。
- Ruff / format / mypy、Frontend typecheck / lint / build、Alembic check成功。既存bundle size警告は残る。新Migrationなし。
- Backend `7ac0c2d`、UI/E2E `3c509f9`、全体検証対象 `318e04441634df6bbbe8a33b4f2d5defa215761d`。
- ローカルAPI 127.0.0.1:18986のhealth / DB疎通 / OpenAPI確認成功。既存Raw Snapshot40件、Raw Human Review0件を維持。Companies / ApprovalRequest / EmailDelivery / FormDeliveryも0件のまま。送信OFF・worker未起動。
- [GitHub Actions 37572274083](https://github.com/team478a/leadhive_codex/actions/runs/37572274083)：検証対象 `318e044` で全7ジョブ成功。Backend全テスト、Ruff/format/mypy、Frontend typecheck/lint/build、全PC/Mobile E2E、Migration往復/model差分、Windows配布、ローカルHTTPフォーム検証を含む。

## 残課題

業種の根拠抽出、求人現在性、自治体辞書、実PilotのHuman Truth測定は別工程。本ゴールで停止する。
