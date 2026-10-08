# CF7契約プレビュー変換経路の固定サーバー受付検証

## 基準・ゴール

`codex/integration`、基準commit `0b89baf`。
202の非実行multipart変換を、固定CF7 6.1.4 / 6.2サーバーで検証する。
実サイト送信adapter・Human送信承認・worker・LeadHive実DBへは接続しない。
結果の正本：`docs/results/cf7-encoding-reception-2026-10-08.json`。
測定時のservice/parser/encoder/lab source SHA-256とCF7 source/image/runtimeを記録。

## 検証で見つかった点と修正

実CF7 DOMには標準でtext/email `maxlength=400`、textarea `maxlength=2000`が付く。
前工程のparserはmaxlength全体を未対応として保留していたため、通常フォームも契約化できなかった。
制約を削除してテストを通すことはせず、限定した文字数上限の保存・照合を追加。

- `EvidenceControl.maxlength`にstrict整数0〜20,000またはnullを追加。
- 新規証拠は`real-cf7-static-evidence-v2`。v1も既存の無制約証拠として読める。
- 非整数・負数・不明文字列・範囲外は証拠を作らない。
- textareaのCR/CRLFをDOMのLFへ揃え、UTF-16 code unit数で上限判定。絵文字は2単位。
- text/email/telの改行は、ブラウザのsingle-line値変換で内容が変わるため拒否。
- maxlength以外のminlength/pattern/multiple等は未対応のまま保留。
- 制約をevidence hashに含める。制約/定義の変化で以前の入力確認・プレビューを流用しない。
- v1保存観測を再検証するとnullable項目が補われhashが変わり得るため、旧入力確認の再確認が必要。

最初の実行では新しい検証ページのpretty URL取得が失敗した。
検証ページだけnumeric page URLとcanonical redirect例外を使うlab fixtureへ修正。
続いてWordPressがJSON URLのスラッシュをescapeするため、固定loopback→HTTPS placeholderの
test-only変換がliteral文字列だけでは一致せず停止した。
固定originのJSON slash-escaped表現も扱い、未知の外部URLへの置換やorigin guard緩和はしない。
テーマの検索formが先にある場合に備え、唯一のCF7 formのdocument indexを使う回帰テストも追加。
本番HTMLを書き換える機能ではない。

## 固定fixture・安全境界

既存9-form回帰cohortを変えず、別ページにrequired name/email/messageの通常フォームを作る。
acceptance、radio、追加hidden、CAPTCHA等を外した専用fixtureであり、全フォーム対応とは主張しない。
実rendered DOMのmaxlength、hidden、項目順序をそのまま限定parserへ渡す。
HTTP loopbackのlab originだけ、非実行契約用HTTPS placeholderへ字句変換する。
元のHTTP endpointを独立した`observe`で確認し、既存`local_post`の固定loopback guardでPOSTする。
契約URL自体を実行しない。入力確認はsynthetic fixture recordであり、実Human承認記録を生成しない。

Docker内部networkのみ、containerの公開portなし。
既存gatewayはこのlab所有containerへstdin relayするだけ。
WP外部HTTPと数値IP socketを禁止し、pre_wp_mailでcapture、PHPMailerも禁止。
フォーム内のメール宛先はsink@example.invalid、実SMTPは呼ばれない。
受信後は$_POSTのname順序と各値SHA-256をlab evidenceへ保存し、本文を成果物へ載せない。
文字列の日本語・絵文字・LF/CR/CRLF・末尾改行を含めて比較。
fixture/php/MU-pluginは開発用のみ。LeadHive運用環境へ配置しない。

## 結果

| 固定版 | CF7 source | WP / PHP | 新経路POST | capture | fail | 負例 |
|---|---|---|---:|---|---|---:|
| 6.1.4 | 165278e868387ec393569ecd2dbfda37e8b5b950 | 6.8.3 / 8.3.28 | 2 | RECEIPT_REPORTED | UNKNOWN | 6拒否 |
| 6.2 | 34acb3a6995b403274820c5ea42abd01b754c03b | 7.1.2 / 8.3.35 | 2 | RECEIPT_REPORTED | UNKNOWN | 6拒否 |

両版とも新経路の14チェックPASS。PHPが受け取った全項目順序と値hashが一致。
mail captureとsubmissionは各ケース1回ずつ。mail失敗をUNKNOWNとし、自動再送なし。
Draft/target/DOM順序/期限/wire hash/maxlength変更はすべてPOST前に拒否。
新経路計4回のPOSTは隔離CF7へだけ。実サイトへのForm送信・メール送信・Approval生成は0。
UNKNOWNのテスト後に同じケースを自動retryしない。
受付statusは最終顧客の受領や返信を保証しない。
WP/PHP環境も異なるため、版間の差をCF7 pluginだけの影響とは断定しない。

## 実行履歴と回帰の区別

5回の未成功attemptも集計に記録。いずれもcleanup成功。
最初の全体runでは既存6.1.4回帰73チェック、6.2回帰35チェックが通り、新しい統合段階で停止。
したがってその全体runを成功とは扱わない。
最終成功runは`CF7_ENCODING_ONLY=1`で今回の統合経路だけを測定し、regression_suite_skippedを明記。
最終runで全73/35チェックを再実行したとは主張しない。
既存labのdefault動作には回帰suite→新経路を追加。encoding-onlyは開発用の明示設定のみ。

## 品質・運用状態

- Backend関連157件PASS。文字数上限・絵文字・改行・0上限と既存API境界を検証。
- 最初はsingle-line改行拒否追加により、wire上限テストのtext fixtureが先に拒否された。
  大量改行を意図するfixtureをtextareaへ修正し、157件を再実行して全PASS。安全条件は維持。
- Lab offline unittest 52件PASS、新probeの4件を含む。
- Chromium serialization比較6ケースも再実行して一致。外部requestなし。
- Playwright Desktop/Mobile各2件、計4件PASS。
- Ruff / format、変更した2 serviceファイルのmypy成功。
- Frontend typecheck/lint/build成功。既存bundle size警告あり。
- 専用test DBのAlembic head/model差分検査成功。DB Model/Migration変更なし。
- GitHub CIは未実行。ローカル検証と区別。
- 7つのlab attemptすべて所有resourceのcleanup成功。lab container残存なし。
- LeadHiveの26社・Raw Snapshot 80件を維持。実Approval/EmailDelivery/FormDelivery 0件。
- outbound OFF・通常worker停止。実企業GET・AI API・Production deployなし。

## 次の境界

次は、実サイトの候補payloadをHuman送信承認へ渡す際の固定・変更失効境界。
今回のRECORDED、contract hash、wire hash、隔離受付成功を送信権限として扱わない。
現時点では実サイトCF7送信adapter未接続。送信直前の再観測・suppression/opt-out・重複保護・
idempotency/UNKNOWN保護を備えた承認付き実行への接続は別工程。
