# Docker不要のWindows配布方式の試作

## 目的と範囲

基準は `codex/integration@20738e66615f45ac29e692f6f3f801a97ec042c8`。
Windows x64の配布先でDocker、WSL、Python、Node、PostgreSQLを事前準備せず、
同梱したランタイムで既存LeadHiveを起動する方式を検証する。
既存Docker配布・DB・承認・送信ロジックには変更しない。

この工程は本番インストーラー完成ではなく、新規の隔離環境に対する方式検証。
workerはGUIから起動せず、送信フラグは環境にかかわらずOFF。
バックグラウンド収集の実運用、既存データ移行、送信は本検証の対象外。

## 配布物

`scripts/package-windows-native.py` が実行ファイル・画面・PostgreSQL・ライセンス・
`README-FIRST.txt`・ファイルハッシュ付き `MANIFEST.json` をまとめたZIPを生成する。
ビルド元のcommit、PostgreSQL配布元・version・SHA-256、開発中ビルドかを記録する。
リリース用ビルドは未commitの変更があるcheckoutを拒否する。
`--development` は方式検証用であり、配布版と混同しない。

利用者の操作はZIP展開 → `LeadHive.exe` → 初回管理者入力 → セットアップ → 起動。
GUI用と隠して動かすサービス用のEXEを分け、PowerShellの一瞬の終了に依存しない。
画面はビルド済みで、APIと同じlocalhost originから配信する。
セットアップ時に外部からランタイムを取得しない。

## データと安全制御

- データは `%LOCALAPPDATA%/LeadHiveNative/instance-v1`。専用PostgreSQL 16を同梱。
- 作成したWindowsユーザーのACLとDPAPIでDBパスワード・設定暗号鍵を保護する。
- 空フォルダのみ初期化。部分インストール・既存データの上書き・他フォルダの採用は禁止。
- DBのsystem identifier、data directory、instance UUID、保存先、migration headを検証。
- DBとWebは127.0.0.1のみ。使用中ポートは上書きしない。launcher間はOSロックで排他。
- HostのSMTP/APIキー/PYTHONPATH/送信フラグを子プロセスへ引き継がない。
- `OUTBOUND_ENABLED` とHuman approved Email/Form、legacy form、Agent等のフラグはOFF固定。
- 既存migrationを新規DBに適用するだけで、新しいmigrationは作成しない。
- 未対応のschema更新は停止し、勝手に既存DBを更新しない。
- PostgreSQL配布のSHA-256をビルド時に照合する。ビルド用dependencyだけを追加。

DPAPIで保護したデータは別PC/別Windowsユーザーへフォルダコピーするだけでは移行できない。
本試作を既存DBの置換として使用しない。

## 検証方法

ビルド用PCでは既存backend venv、Nodeと次のbuild dependencyが必要。
配布先にはこれらを要求しない。

```powershell
backend/.venv/Scripts/python -m pip install -r scripts/native/build-requirements.txt
backend/.venv/Scripts/python -m unittest discover -s scripts/native -p test_native_runtime.py
backend/.venv/Scripts/python scripts/package-windows-native.py
backend/.venv/Scripts/python scripts/native/verify_package.py
```

受入試験は新規専用フォルダで行い、PATHをWindows System32のみとして、
日本語・空白を含むデータパス、初回migration・管理者作成・ログイン・session・API・
frontend・承認APIの存在・不明APIの404・停止・同じinstanceの再起動を確認する。
EmailDelivery/FormDelivery/ApprovalRequestのレコード数もDBから確認する。
localhost以外のサービスはこの試験から呼び出さない。通信監視による全プロセス計測とは区別する。

GitHub Actions `windows-native` にbuild/unit/frozen acceptance/artifact uploadを追加する。
Hosted runnerには開発環境がインストールされているため、PATH分離の成功を
完全に未導入のPCでの成功と同一視しない。

## 残る環境依存・次の配布工程

- Windows x64とOS同梱機能、DLL/VC runtime、実行ポリシー、セキュリティソフト。
- EXE署名・SmartScreen、一般権限のクリーンVMでの動作、企業PCの実行制限は別途検証。
- 自動更新、バックアップ復元、Docker版からの移行、クラッシュ時の診断/復旧は未完成。
- GUIのDesktop/DPI/アクセシビリティの実機検証は別途必要。
- 配布媒体はUSB/Driveでよいが、ZIP展開と実行はローカルディスクに置く。
- 本番配布では利用する各同梱物のライセンス・noticeの最終確認も必要。

本番配布判定は **CONDITIONAL GO（方式検証のみ）**。既存Docker版の代替配布を確定しない。

## 参考

[PostgreSQL Windows公式ページ](https://www.postgresql.org/download/windows/) は、
アプリインストーラーへ同梱する用途のbinary ZIPを案内している。
[EDB binary配布](https://www.enterprisedb.com/download-postgresql-binaries) から16.15 x64を取得。
[PyInstallerの配布方式](https://pyinstaller.org/en/stable/operating-mode.html) に従い、
Windows上でinterpreterを含むonedir packageを作成する。

実測結果・commit・CI・ZIPは検証完了時にこの文書へ追記する。
