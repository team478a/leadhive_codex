# 実CF7 protocol lab（開発者用・送信機能ではありません）

公式CF7 v6.1.4を専用WordPressで実行し、実DOM・multipart・受付statusを確認する。
LeadHive API/worker/DBへ接続しない。Human承認や送信許可を生成しない。
本番adapter/任意企業URL検証器として使用しない。

## 必要条件

- Docker Desktopが起動済み。既存containerを停止・初期化する必要はない。
- リポジトリのBackend仮想環境（httpx/BeautifulSoup/Pydantic/email-validator）とNode。
- `frontend/npm ci` 相当の依存関係とPlaywright Chromium。
- 公式imageの取得とCF7公開sourceのdownloadが可能な開発PC。

リポジトリrootのPowerShellで、runtime開始前にimageを取得する。

```powershell
docker pull wordpress:6.8.3-php8.3-apache
docker pull mariadb:11.4
backend/.venv/Scripts/python.exe -m unittest discover -s scripts/cf7_lab -p 'test_*.py'
$env:CF7_PROTOCOL_LAB = '1'
try {
    backend/.venv/Scripts/python.exe scripts/cf7_lab/run.py
    if ($LASTEXITCODE -ne 0) { throw 'CF7 lab failed; see its report' }
} finally {
    Remove-Item Env:CF7_PROTOCOL_LAB -ErrorAction SilentlyContinue
}
```

scriptは取得済みimageのdigestを解決してそのdigestで起動する。MariaDBのtagは取得時に
変わり得るため、再検証の同版比較では結果にあるdigestを取得・確認する。CF7は固定commit
とarchive SHA-256を照合する。不一致時は停止し、checksumを無検証で書き換えない。
第三者pluginのsourceはignored `dist/` とlab内にのみ置き、LeadHiveコードへコピーしない。

## 隔離と停止

202の変換経路受付だけを測定する場合は`CF7_ENCODING_ONLY=1`を明示する。
この場合、既存回帰suiteを省略したことをreportの`regression_suite_skipped`に記録する。
全回帰suite成功の代替にはならない。新しい固定fixtureへ各版2回だけlocal POSTし、実SMTPはcaptureする。
通常のdefaultでは既存回帰suiteの後にこの受付検証を行う。詳細はdocs/203を参照。

- UUID付き専用container/network/volumeだけを作成する。既存DB/envを読まない。
- 内部networkにだけ接続し、containerのportは公開しない。
- ホスト側の `127.0.0.1` 一時portの検証用gatewayからDocker exec/stdinで中継する。
  container内のrelayは自身のApache `127.0.0.1:80` 以外へ接続しない。
  ホストの任意URLへのproxyやProductionの通信器として利用しない。
- WP HTTP遮断、数値IPへの外部socket遮断、mail捕捉を確認してからfeedback POSTを開始する。
- `pre_wp_mail` で呼出しを捕捉し、PHPMailer実行も拒否する。SMTP設定/外部配送はない。
- 架空の `example.invalid` アドレス・本文のみ使用する。捕捉証拠は本文/subjectのhash。
- HTTP retryなし・redirectなし・環境proxy継承なし。Browserも同origin外requestを拒否する。
- 終了時は作成記録と所有labelを確認して当該資源だけを撤去する。

プロセス強制終了/PC停止ではfinallyの撤去が走らない場合がある。
残る `leadhive-cf7-lab-<UUID>` の資源は停止したlabとして扱い、結果のoriginにアクセスし続けない。
Dockerのlabel/nameを確認してそのlabだけを撤去する。`docker system prune` や既存volume削除を
復旧手段にしない。作成した資源を検査できない場合は停止し、cleanup failuresを確認する。

## 成果物と判定範囲

`dist/leadhive-cf7-lab-<UUID>/report.json`、`page.html`、`browser-wire.json`。
全て架空データのローカルartifactでGitへ含めない。共有用文書には版/digest・集計結果・
確認範囲を記載する。WP管理password、DB password、cookie、API keyは報告しない。

- `protocol.py`：I/Oなしのlab限定観測・保守的な受付分類。Production SSRF対策ではない。
- `cases.py`：実CF7 HTTPとBrowserの比較。構造変更/応答変造はoffline判定として区別。
- `contract_probe.py`：純粋なCF7候補契約のwireをlabだけで照合。契約内のHTTPS placeholder URLは実行せず、管理下loopback fixtureへbytesだけを渡す。DB/承認/dispatch未接続。
- `group_probe.py`：固定fixtureの同名checkbox groupを検証。必須/任意、未定義値の拒否、複数値の順序、Browserと捕捉mailの比較。既存19 POSTにgroup6 POSTを追加。結果は [docs/188](../../docs/188_CF7_CHECKBOX_GROUP_PROTOCOL_LAB.md)。同意/radio/実サイト向けDOM mapperではない。
- `run.py`：取得・隔離検査・起動・撤去。LeadHiveの承認・予約を変更しない。
- `gateway.py` / `relay.php`：隔離を保ったままBrowser/HTTPを実Apacheへ中継。
  POSTは固定CF7 feedback routeだけ。credential/cookieを転送しない。
- PHP fixture/MU plugin：管理下の標準フォーム、同意変種と捕捉/失敗/skip/abort/spam/demo。
- Browser probe：従来fixtureと新候補比較の各ケースで、実CF7 JavaScriptのPOSTを1回ずつ観測。

新候補のraw snapshot/wireとBrowser比較artifactもignored distへ保存する。共有するのは版・hash・件数だけ。新encoderの照合結果と制限は [docs/119](../../docs/119_CF7_CANDIDATE_WIRE_PROTOCOL_LAB.md)。

`RECEIPT_REPORTED` はCF7受付応答の確認だけ。メール到達の証拠ではない。
UNKNOWNの自動retryやdispatch連携をこのlabは実装しない。承認基盤のprocess停止/競合は
docs/113の別試験であり、このlabを通しただけでCF7との一体動作を証明したとは扱わない。
HTTPS/DNS rebinding対策、追加plugin、実企業、大量運用も別検証。
中継器を使うため、実サイトのネットワーク性能・TLS特性の測定には使わない。
