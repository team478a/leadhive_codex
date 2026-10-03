# LeadHive — 3社提供 G1構成・運用設計

## 1. ゴールと今回の完了範囲

ゴールは、既存LeadHiveを維持したまま3社へ安全に提供するための構成、分離境界、更新・復元手順、実装順序、受入基準を確定すること。
2026-10-03時点の設計であり、3社への導入完了・本番提供可能を意味しない。

- 調査branch: `codex/integration`
- 実装baseline: `f5885b7707536b4b7a7d8f50edeb724430933c58`
- 入力: `AGENT_AUTOMATION_GOVERNANCE_DIRECTION_CORRECTION.md`、A2実装記録、既存Windows導入・配布スクリプト。
- 今回は文書のみ作成。コード、Migration、DB、設定を変更しない。送信、接続、デプロイ、パッケージ生成、commit/pushを実施しない。
- Human Approval A2を削除・巻き戻さない。A2は実送信未接続であり、既存配送が全てA2承認で保護されているとは扱わない。

## 2. 採用する初期提供構成

**初期3社は1社1専用環境・1専用DBとする。共用SaaS化は別工程。**
同じ検証済みリリースを3社に配布するが、業務データ、暗号化キー、管理者、外部サービス認証情報は各社で独立させる。

| 提供対象 | 実行環境 | DB・保存領域 | 設定・アカウント | 外部Agent |
| --- | --- | --- | --- | --- |
| Company A | A社専用PC/専用VM | A社だけ | A社だけ | 初期OFF |
| Company B | B社専用PC/専用VM | B社だけ | B社だけ | 初期OFF |
| Company C | C社専用PC/専用VM | C社だけ | C社だけ | 初期OFF |

実行環境は独立したOS/VM境界とする。同じDocker engine上の単なるフォルダー複製は初期提供の対象外。
初期想定は各社の専用Windows PCでローカル利用。同社内でも複数PCへそれぞれ入れるとDBは別になり、共有・同期されない。
複数ユーザーで同じデータを使う会社には専用サーバー/VMが必要となる。その場合はHTTPS、公開範囲、Cookie、Origin、認証試行制限を別途検証し、localhost用Composeをそのまま公開しない。

企業名、担当者、端末、利用人数、同時利用、提供日、送信利用の有無は未確認。仮称A/B/Cを実会社へ割り当てる導入票が必要。
この未確認は本設計を止めないが、端末選定と本番導入の前提を確定するまで導入は完了扱いにしない。

## 3. 現在の実装と再利用判定

| 根拠 | 現状 | 判定・必要な対応 |
| --- | --- | --- |
| `compose.local.yaml` | DB非公開、Webは127.0.0.1。api/worker/webを起動 | REUSE AS-IS: 専用PC内の構成。ネット公開には別設計 |
| `scripts/windows/Common.ps1` | Compose名leadhive-local、既定volumeを検出し旧環境へ接続 | EXTEND: 提供先/instanceを明示して誤接続を停止 |
| `compose.local.yaml` | volume名はLEADHIVE_DATA_VOLUMEで指定可、既定固定 | 異なるポートだけではDB隔離にならない。script側の検出も含めて整合させる |
| `Common.ps1` | 初回DBパスワードと暗号化キーを乱数生成 | REUSE AS-IS: 各社で個別生成。配布物に生成済みキーを同梱しない |
| `backend/app/model_settings.py`、`services/application_settings.py` | SMTP/IMAP/API等はinstanceの共通設定、ApplicationSettings id=1 | 専用instanceでは再利用可。1instance複数社は不可 |
| `backend/app/model_core.py` | Project owner/member、User.is_admin。Organizationなし | 専用instance内の権限として再利用。tenant権限とは表示しない |
| `backend/app/config.py` | Agent機能既定OFF | 維持。Composeで将来明示する場合もfalseを既定とする |
| `backend/app/approval_routes.py`、`services/human_approval.py` | Human/Agent分離、step-up、hash/version、期限、台帳 | REUSE AS-IS: MANUAL承認基盤。送信保証とは分ける |
| `scripts/package-windows.ps1` | tracked fileを選別、秘密ファイル除外、ZIP/hash/manifest生成 | EXTEND: clean treeと検証済みcommit固定。現行はtracked working treeをコピーするためcommit名だけでは内容を保証できない |
| `scripts/windows/Backup-LeadHive.ps1` | DB dump + env.localコピー | EXTEND: 暗号化保管、同時実行制御、対応するrelease/schema/instanceの記録 |
| `scripts/windows/Update-LeadHive.ps1` | build --pull→migration→worker再起動 | EXTEND: バックアップとサービス停止、更新失敗時の停止、旧版復旧手順 |
| `scripts/windows/Restore-LeadHive.ps1` | 安全backup→停止→pg_restore --clean→migration→worker起動 | EXTEND: 新規隔離DBへの復元検証、暗号化キー一致、worker自動再開禁止 |

既存手順は存在するが、この監査では実行していない。Docker/Windows新規端末での導入成功を認定していない。

## 4. 分離契約

1. 各instanceは1提供先だけを扱う。Projectを企業境界の代用にしない。
2. instance IDを企業名・秘密値と独立した不変識別子として運用票に記録する。現行DBの新tenant列に見せかけない。
3. source/releaseは共通化してよいが、DB volume、env、backup、ログ、session、Agent credentialは共用しない。
4. 同じhostの別ポートはCookie隔離を保証する境界ではない。複数社を同じlocalhostのポート違いで提供しない。
5. 他社のdump/envを復元・コピーしない。提供元の実データ入りDBを配布テンプレートにしない。
6. SMTP送信元、返信先、IMAPメールボックス、API課金先を導入票で各社へ対応づける。初期に共通送信アカウントを使わない。
7. 支援者は各社の明示された支援範囲でだけアクセスし、共有管理者パスワードを配布しない。
8. Agentを将来有効にする場合も製品共通境界を使用。Dots専用分岐、Human sessionのAgent共有は導入しない。

## 5. 初期提供の機能境界

初期受入対象はログイン、Project/Profile、URL/CSV取込、企業一覧・解析結果、CRM活動、Human Approval Queueの準備・確認。
検索/AIの外部疎通は各社設定後に別の限定検証として行う。今回、実APIを呼ばない。
外部送信、自動化、Codex支援送信の有効化は別gate。Agent OFFだけでは既存Human送信やworker配送を停止できない。

送信をまだ許可しない段階は「利用者が押さない」だけに頼らず、全経路のserver-side dispatch guardと実行環境の送信先制限を受入条件とする。
現在、共通dispatch kill switchの実装完了は確認できない。SMTP未設定のみを送信停止の保証にしない。
収集と配送が同じworkerにあるため、workerを止めるだけで常用する設計にもできない。提供準備工程で経路別停止を実装・検証する。

送信有効化前の独立blocker:

- A2とlegacy confirmed/Campaign/Batch/Codex経路の共通認可接続が未完成。
- SMTP/Formの結果不明、二重送信、worker recovery、復元後の再送を共通で保護するDispatch Foundationが未完成。
- Project別suppressionだけでは同じ会社の別Project経由の送信禁止回避を防ぐ正本にならない。
- local PUBLIC_APP_URLのlocalhostはメール受信者のPCを指すため、外部受信者向け配信停止リンクには使えない。到達可能な安全なopt-out経路が必要。
- ローカルPCの停止中に返信取込や期限処理は動かない。常時稼働が必要なら専用サーバー案へ切り替える。

これらは独立instanceによる企業間隔離だけでは解決しない。MANUALでも送信gateを省略しない。

## 6. 配布と導入手順の設計

### 提供元で準備

1. 検証専用DBでBackend/Frontend/E2E/Migration検証を通したcommitをrelease候補にする。
2. cleanな固定commitからパッケージを作成し、release ID、完全commit、schema head、対応OS、manifest/hashを保存する。
3. packageに実DB、env、認証情報、バックアップ、診断実データがないことを検査する。
4. 新規専用検証VMで導入、旧版更新、復元を実行する。外部送信はnetwork/mockで封じる。

### 各社導入

1. instance ID、PC/VM、管理者、利用範囲、backup保管者を導入票に記入する。
2. 個別環境へ展開。既存LeadHiveの検出時は提供先とinstanceが一致しない限り中止する。
3. 初回キー/DB/管理者を個別生成。秘密値を導入票・ログ・配布ZIPへ記載しない。
4. API/画面/権限/承認キューをダミーデータで確認する。
5. backupから別の隔離検証環境へ復元して、件数・承認証跡・復号が正しいことを確認する。
6. 会社担当者へ日常起動・停止・backup・問い合わせ方法を引き渡す。

同一社の追加PCは「追加インストール」ではなく、専用共有環境へアクセスするか独立運用するかを決めてから進める。

## 7. バックアップ・復元

推奨の初期運用目標はRPO 24時間、RTO 1営業日。これは提案値でありSLA/測定済みの保証ではない。
日次backup、更新前backup、端末交換前backupを運用化し、稼働時間とデータ量から3社別に合意・測定する。
保持案は日次7世代、週次4世代、月次3世代。PC故障に備え別媒体へ保管し、会社別に暗号化・アクセス制限する。

backup bundleはDB dump + 対応する暗号化キー/env + release/schema + instance ID + checksum + 時刻で一組にする。
env内のDBパスワードと暗号化キーは機密であり、現行コピーはそれ自体が暗号化backupではない。
同時backupは同じcontainer内の固定/tmp/leadhive.dumpが競合するため排他または固有一時pathが必要。

復元はまず新規隔離DBで行う。A2台帳はappend-only triggerがあるため、既存DBに対するpg_restore --cleanが通ると仮定しない。
失敗時は本稼働DBを保持し、workerを起動しない。trigger解除や台帳削除を通常復旧の回避策にしない。
復元済みpending/running/承認済み配送は隔離し、実際の送信結果と突合するまで再開しない。checkpoint後の外部送信はDB rollbackでは取り消せない。
SMTP/IMAP/API秘密の復号と承認hash/versionを確認するが、値を画面やログに出さない。

## 8. 更新・rollback

1. まず提供元の隔離環境で旧版→新版のmigrationと復元を検証する。
2. 1社ずつ保守時間を確保。進行中ジョブ/配送を確認し、新規受付とworkerを停止してbackupを採る。
3. schema、dump、キー、旧releaseを一組で保管してからmigration・アプリ更新を実行する。
4. API/承認/主要機能の確認後、許可したジョブ種別だけ再開する。
5. 1社の確認が終わるまで残り2社を更新しない。提供先別の稼働versionを管理する。

rollbackは、互換性確認済みなら旧アプリへ戻す。DB変更が非互換なら旧dump+旧release+キーを隔離環境で復旧する。
本稼働DBのdowngradeやvolume削除を通常rollbackにしない。失敗時のworker自動再起動を禁止する。
build --pullで依存imageが変わる可能性もあるため、配布releaseのimage/dependency情報を固定・記録する工程を設ける。

## 9. 受入基準と現在の証拠

| 受入条件 | 必要な検証 | このG1時点 |
| --- | --- | --- |
| 3社の分離 | 3隔離環境で各社ダミー会社/ユーザー/設定の非共有、誤復元拒否 | 設計済み、未実行 |
| 初心者導入 | 新規Windowsで導入→ログイン→URL/CSV→承認準備 | 既存scriptあり、3社提供用未検証 |
| Agentは承認不可 | A2のprincipal/scope/step-up回帰 | 過去A2検証記録あり、今回再実行なし |
| 安全な提供開始 | 全送信経路を停止したまま収集worker使用可 | 追加実装・検証必要 |
| 更新 | 前版DB→新版、途中失敗で安全停止 | scriptあり、追加検証必要 |
| 復元 | dump+キー+release整合、ledger保持、再送ゼロ | scriptあり、追加検証必要 |
| 秘密保護 | ZIP/ログ/導入票に秘密なし、backupアクセス制限 | 配布除外実装あり、保管運用追加必要 |
| 手動運用継続 | Dots不要、Agent OFFでも承認UI利用可 | A2実装記録あり |

## 10. 次の実装順序

| 順序 | 工程 | 完了条件・停止点 |
| --- | --- | --- |
| 1 | G1.1 専用instance識別と誤接続防止 | installer/start/update/backup/restoreで同じinstance境界を検証。既存1社環境の安全な引継ぎ。Agent OFF |
| 2 | G1.2 安全な配布・更新・復元 | clean release、manifest、backup metadata、排他、隔離復元、worker再開gate。破棄可能DBのみで試験 |
| 3 | G1.3 収集運用と送信停止の分離 | 全legacy含むserver-side停止、worker収集だけ利用可、テスト送信も停止。mock/隔離で受入 |
| 4 | G1.4 3社受入と導入票・操作ガイド | 提供前のダミー環境試験、1社pilot→残り2社。実導入は別の実行段階 |
| 5 | 共通Dispatch Foundationの設計・段階実装 | Human/Policy認可境界、二重送信、UNKNOWN、禁止正本、opt-outを解決。実送信は別gate |
| 6 | 共用tenantが必要な場合のOrg導入 | Org/User/Project/credential/settings/台帳contextをadditive導入。専用提供を壊さない |
| 7 | G2/G3→G4/G5→G6/G7 | Policy dry-run/証跡→共通dispatch前提の自動化→共通Agent API/限定PoC。各工程ごとに停止 |

この順序は3社への専用提供を先行させるためのもの。G4/G5の共用運用にはOrganization隔離完了が必須で、専用instance識別をtenant実装の代替にしない。
次に実装する1工程は **G1.1 専用instance識別と誤接続防止**。今回は実装を開始しない。

## 11. G1設計の完了判定

構成、分離、既存再利用、不足、更新/復元、受入、次工程を文書化したためG1の設計ゴールは完了。
提供準備の実装、3社の導入、共同利用、Dispatch Foundation、自動化は未完了。
既存Governance設計とA2を維持し、コード/DB/Migrationを変更せずここで停止する。
