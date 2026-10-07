# 毎日の送信可能時間

## 目的と操作

曜日を限定せず、毎日指定した時間だけメール・フォーム送信を開始する。運用設定の「送信可能時間」で時間帯の制限をONにし、開始・終了時刻を保存する。推奨初期入力は08:00〜20:00、日本時間固定。開始時刻を含み、終了時刻を含まない。日をまたぐ時間帯は指定できない。

日次・時間あたりの送信上限や送信間隔は従来どおり別に設定する。30日で月10,000件なら平均約334件/日、12時間で約28件/時間が必要だが、フォーム対応率、承認、人手確認、PC稼働時間によって達成できる件数は変わる。件数や到達を保証しない。

## 実行経路

- メールの日時予約は維持する。予約日時を過ぎても時間外ならclaimしない。
- Human承認メール、Human承認フォーム、旧メール、旧フォームbatchの取得・開始境界で時間帯を確認する。
- claim後に時間外になった未試行予約はqueuedへ戻す。フォームはstarted_at/delivery_idがない予約だけが戻れる。メールはrow lockとSendAttemptの照合で、試行済み・UNKNOWN・送信済み・別workerの予約を戻さない。
- SMTP接続前とDATA送信直前、フォーム各POST直前に、別Sessionで保存済み設定を読み直す。確認画面の次POSTも対象。POST後の結果確認GETは継続する。
- 終了時刻より前に始まった通信の完了を途中で取り消す機能ではない。時間帯変更や境界時刻で開始確認を通過できなければ外部送信を開始しない。
- durable attempt保存後に時間外へ切り替わった場合、保守的にUNKNOWN等の既存終端処理に入り、自動でqueuedへ戻さない。実際の受付結果をHumanが確認する。
- 次の送信可能時間にworkerが再取得する。PC/workerが停止していれば動作しない。曜日・祝日は除外しない。
- 承認期限は延長しない。再開時も既存のexpiration、immutable payload、suppression、宛先重複、rate limit等を確認する。失効は再承認が必要。

## 永続化・権限・互換性

`sending_windows` singletonへenabled/start_minute/end_minute/更新Humanユーザー/日時を保存する。APIはGET/PUT `/api/admin/sending-window`。既存current_adminを使用し、Agent credentialや非管理者へ変更権限を渡さない。

新規Migration `75d9c210ab34`、親 `1372277c354d`。過去Migrationは変更しない。既存環境の運用を勝手に変更しないため、レコード未保存・enabled=falseは時間帯制限なし。outbound OFFは別guardであり、この設定で外部送信を有効にすることはない。

フォームDB triggerは既存immutable/deletion/終端遷移の保護を維持し、未試行checking→queuedだけを追加する。downgradeはその遷移追加と設定テーブルのみを戻し、送信・承認記録を削除しない。downgrade前にはoutbound/workerを停止し、設定をbackupする。旧版には時間帯制限がないので、送信停止状態を維持してからrollbackする。

この設定は既存のSMTP・フォーム上限と同様にインスタンス全体が対象。Projectごと・Organizationごとの時間帯や別timezoneは今回追加しない。Codexによる独立した手動ブラウザ操作まで制御できると主張しない。新しい送信経路にはこのguardを適用する必要がある。

## 検証

専用PostgreSQL `_test` DBのみで検証する。日本時間境界・週末・無効設定・管理者API・Agent拒否・時間外claim・未試行待機・終端結果保護・SMTP/POST直前遮断をテストする。Desktop/Mobile E2Eで設定保存・再読込・入力エラー・送信リクエスト未発生を確認する。

実メール・フォーム送信、SMTPテスト、承認の代理操作、送信用worker起動は行わない。

## 2026-10-07 検証記録

- 基準: `codex/integration@6cab4bcb638823d4fa6af25f22f28e596b454997`。
- 新規機能とHuman承認メール・フォームの回帰: 77 passed。追加のPOST境界テストを含めた拡張回帰: 161 passed / 1 failed。送信OFF判定の順序を修正後、該当outbound guardと新規機能を再実行し39 passed。失敗を未解消のまま成功と扱っていない。
- Frontend typecheck/lint/build成功（従来のbundle size warningあり）。設定保存・再読込のDesktop/Mobile Playwrightは2 passed。
- Ruff lint/format、対象mypy、API import/compile、専用DBでmigration upgrade / downgrade / upgrade / Alembic model check成功。
- 稼働環境への適用では既存cohort/承認/送信記録の件数を適用前後で照合する。outbound、Agent、旧送信、承認送信の各実行flagはOFF、送信用workerは起動しない。
