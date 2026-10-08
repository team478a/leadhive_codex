# 確定条件を収集ジョブへ接続

## 目的と基準

基準は codex/integration@667c349。前工程のHuman確定済みMUST/WANT/EXCLUDEを、既存の非同期収集へ接続する工程。自然言語解釈・新しい情報源・送信の実装ではない。

## APIと固定条件

既存 POST /api/projects/{project_id}/operations の collect_search に condition_request_id / condition_version / condition_hash を追加した。3項目は同時指定が必須。他の処理への指定は拒否する。Project・版・hashを検証し、サーバー側で条件snapshotを既存OperationJob.payloadへ固定する。未指定の場合は従来の収集を維持する。

workerは外部検索前と各keyword開始前に固定条件の整合性を検証する。後から新しい条件版を確定しても、既存ジョブの条件は変わらない。不整合は実行停止とする。過去CollectionJobに限定した条件は、新しい収集の条件として流用できない。

GET /api/operations/{job_id}/collection-conditions は、このOperationJobのCollectionJobに紐付いたLeadSourceObservationの候補だけを返す。Projectの既存企業全体を収集成果に含めない。条件は固定版、判定根拠は現在保存されている情報であり、Raw Snapshotの再評価とは異なる。ページ内件数と全候補数を区別する。実行中・中断・キャンセル時も保存済み部分だけを取得できる。

## 調査と費用制御

MEDIA_EXISTSのMUSTとEXCLUDEは既存ExternalPresence調査計画のREQUIREDへ追加する。追加調査OFFより優先するが、既存の検索回数・ページ・時間上限は増やさない。WANTだけで追加調査を強制しない。既存のSource利用条件制御も維持する。

保存済み根拠によってMUST不一致またはEXCLUDE一致が確定した候補は、残りの媒体追加検索を止める。企業レコードは削除しない。UNKNOWN・予算不足・利用条件未確認はREVIEW_REQUIREDとして残し、不一致や一致へ推測しない。地域・業種・求人条件などの未実装評価はUNKNOWNのまま。

既存のcancel/recoveryを再利用する。同一OperationJobの再実行では既存調査ledgerと上限を利用するが、主検索のcheckpoint再開を新規実装したわけではない。Humanによる明示retryは固定条件を保った新OperationJobであり、別の上限付き調査予算になる。

## UIと権限

収集画面で条件を確定した後、「確定条件を今回の収集に使う」を選択できる。未確定条件は接続しない。Project変更時は選択を解除する。各収集履歴から固定版・条件判定・理由・根拠リンクを表示する。

既存Human認証とProject owner/editorの収集権限を維持する。Viewerは結果参照のみ。Agent credential、混在認証、他Projectの条件流用は拒否する。CSV・URL入力・スケジュールの動作は今回変更しない。

## DBと安全性

新しいDB列・Model・migrationは不要。既存JSON payloadと関連情報を再利用する。Alembic checkでModel差分なしを確認した。

検証では外部検索をmock化し、実API収集・AI解析・Completion・承認作成・メール・Form送信を実行しない。outbound OFFと送信worker停止を維持する。E2Eは合成データのenqueueとcancelのみ。

## 検証

- Backend: 条件固定、版/hash競合、他Project、Viewer/Agent、追加検索上限、MUST/EXCLUDE停止、キャンセル、retry、不整合停止、既存媒体調査・収集回帰。
- Frontend: typecheck / lint / build、PC・Mobileの条件確定・enqueue・結果部分表示・cancel。
- CI: Backend全テスト、Ruff/format/mypy、Frontend、migration往復/model差分、E2E、Windows packageの既存workflowで確認する。

## 残課題と停止点

### 実行結果（2026-10-07）

- 実装commit: backend b30d6c5 / frontend 24769d5。検証対象HEAD: 4762fabd02c21eb1976176dd971904f4786b61a4。
- ローカルBackend関連テスト67件PASS、PC/Mobile関連E2E4件PASS。Ruff / format / mypy、Frontend typecheck / lint / build PASS。
- [GitHub Actions 37565482339](https://github.com/team478a/leadhive_codex/actions/runs/37565482339): 全7ジョブ成功。Backend全テスト、全E2E、Migration upgrade/downgrade/upgrade・Model差分、Windows packageを含む。
- ローカルAPI 127.0.0.1:18986を更新しhealthと追加endpointを確認。既存Raw Snapshot40件を保持。Companies / Human Review / ApprovalRequest / EmailDelivery / FormDeliveryはいずれも0件で変更なし。outbound OFF、worker未起動。
- Frontend buildには既存のbundle size警告が残る。ビルドは成功。今回bundle分割は対象外。

用途目的別エンジン全体の完了ではない。自然言語からの条件提案、地域・業種・求人等の検証Adapter、追加Source、DM根拠生成は次工程。実収集精度・Human Truthの改善はこのmock検証から主張しない。本工程は確定条件の収集接続までで停止する。
