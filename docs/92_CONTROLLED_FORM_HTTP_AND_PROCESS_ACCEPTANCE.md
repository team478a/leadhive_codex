# 管理下フォームの実HTTP・ワーカープロセス障害検証

## 今回のゴール

ローカルに管理下のフォームを起動し、実際のTCP/HTTPで取得・POST・結果判定を通す。受付後の通信障害とワーカープロセス消失で、永続UNKNOWNと再送禁止が維持されることを確認する。実企業のフォーム・メール・SMTP・Codex送信は利用しない。

## 検証構成

- `backend/tests/form_http_lab.py`: 127.0.0.1のランダムportへbindするThreadingHTTPServer。合成HTML、受付記録、切断、応答中断、遅延、redirectを提供。
- `backend/tests/test_form_http_acceptance.py`: 独立したHumanログイン・再認証・準備・承認・予約APIと、既存workerの検証。API自体はTestClientで呼ぶ。フォーム側の通信はHTTP mockではなく実ソケット。
- `backend/tests/form_http_process.py`: fresh SQL connectionを持つ別OSプロセス。claim/dispatchの実行と強制終了・再起動の検証。
- DBは専用 `leadhive_form_http_test`。実プロセスから読めるようテスト記録をcommitし、immutable履歴は消さない。通常のrollback fixtureや利用中のpreview DBとは分離する。
- 実行は `FORM_HTTP_LAB=1` と上記の正確なDB名が必要。通常suiteではこの15件をskipする。子プロセスも同じ境界を確認する。

### 通信の境界

既存SafeFetcherはprivate URL・非標準portを拒否する。その本番制御は変更していない。テスト限定のDNS seamで予約domain `form-lab.test`をpublic addressとして扱い、HTTP transportだけをそのdomainから管理下のloopback socketへ転送する。別domain、HTTPS、非標準portの要求はテストtransportで拒否し、proxyも使わない。

robots、フォームparser、fingerprint、送信前検証、POST、応答読込、redirect、完了判定は本番コードを通す。HTML取得・POSTの結果をmockで返していない。DNS解決、実際のpublic network、TLS証明書の検証は対象外。この方式を本番向けのlocalhost許可設定として公開しない。

試験間のrate/site間隔は仮想時計で進める。専用DBの合成Human sessionも試験時計に合わせる。送信量・performanceの実証とは区別する。テストHTTP clientのtimeoutは5秒。

## 検証ケース

| ケース | 件数 | 確認 |
|---|---:|---|
| 200受付・303後の完了GET | 2 | 受付1回、Unicode/2,000文字超本文の一致、再取得したhidden token、CONSUMED/送信履歴 |
| 受付後切断・Content-Length不一致・曖昧な200・307再POST要求・timeout | 5 | 受付1回、UNKNOWN保存、期限経過・繰り返しclaimでも再送なし |
| 事前fingerprint変更・CAPTCHA・営業禁止・事前確認後の再取得で変更 | 4 | POSTなし。事前停止blocked、開始証拠保存後の構造変更はfailed |
| 実claimプロセス2つの競争 | 1 | 同じ予約のclaim成功は1プロセスのみ、その後の受付1回 |
| GET待ち中・受付直後のプロセスkillと新プロセス起動 | 2 | GET中はlease後blocked/受付0、受付後はCONSUMED/UNKNOWN保持/受付1 |
| 本番private URL guard | 1 | 同じテスト環境でも127.0.0.1の直接URLを拒否 |

POST前の準備・承認・予約でフォームGET/POSTがないことも確認する。2プロセス試験は現在の同時checking 1件制御の実証であり、高並列送信の実証ではない。

## 発見した問題と修正

実HTTPの禁止表記試験で「営業目的の送信はお断りします」が既存PROHIBITED_PATTERNSに一致せず、合成フォームへPOSTされる問題を発見した。実企業への送信は発生していない。

`app/services/form_intelligence/rules.py`の共通ルールへ、営業目的の「送信」に対する禁止・お断り・ご遠慮の表現を追加した。Form Intelligenceの判定とフォームparserの送信前検証の両方が利用する。営業目的での送信、営業による送信、空白を挟んだ表現を含めて4件、禁止のない文言を3件検証する。

任意の禁止表現・否定・文脈をすべて理解するという保証ではない。新たな表現は別途収集・評価する。API、Model、Migration、権限、承認状態、UI、実送信flagは変更していない。

## 再実行方法

専用DBを作成し、backendディレクトリで以下を実行する。DB接続情報は管理者が安全な方法で環境変数へ渡す。利用中のDBを指定しない。

```powershell
# TEST_DATABASE_URL: PostgreSQLの専用leadhive_form_http_testを指す接続情報
$env:FORM_HTTP_LAB = '1'
.venv/Scripts/python.exe -m pytest tests/test_form_http_acceptance.py -q
```

通常の回帰試験は別の専用テストDBへ切り替え、FORM_HTTP_LABを解除する。テストの受付記録はメモリ上の合成データ。専用DBには合成承認・試行の監査履歴を保持する。再実行で過去UNKNOWNを解除・削除しない。

GitHub Actionsへ独立job `form-http-acceptance` を追加した。専用PostgreSQL serviceとloopback fixtureだけで実施する。GitHub上の実行成功はローカル結果とは別に確認する。

## 2026-10-05 検証結果

- 管理下実HTTP・実プロセス試験: 15件成功、約62.3秒。
- 共通禁止ルール、Form Intelligence、完了判定、承認済みフォーム、運用確認、UNKNOWNの関連回帰: 86件成功。通常DBでは専用labの15件をskipすることも確認。
- Ruff、format check、compileall成功。Frontend typecheck/lint/build成功。UI変更なし。
- 専用labの空DBをAlembic head `fae47ac5e861`へupgrade、model差分なし。新Model/Migrationなし。
- 詳細な件数とケース名: [results/form-http-acceptance-2026-10-05.json](results/form-http-acceptance-2026-10-05.json)。virtual clockやDNS/transport seamなどの試験条件も記録する。
- Backend Docker image build成功。禁止ルールをこのPCのAPI/workerへ反映し、health/DB正常を確認。既存企業100件、フォーム予約/送信・メール送信0件を維持。外部送信・承認済みフォーム・旧フォーム・AgentはOFF。配布zip再生成・Production deploymentは行っていない。

## 限界と次のゴール

実企業の対応率、インターネット/TLS/DNS障害、Windows全体やDocker/PCの電源断、DB server停止、共有フォームのURL alias、CAPTCHA操作、ブラウザ生成フォーム、月10,000件のperformanceは未検証。DB commit後・HTTP受付後のworker killは検証したが、あらゆる障害で外部サイト側の処理をexactly-onceにできると主張しない。

次のゴールはフォーム対応率の測定・改善。まず管理下のフォームfixtureを種類別に増やし、対応可能/人手が必要/禁止を分類する。実企業を使った収集・解析の評価は送信と分離する。
