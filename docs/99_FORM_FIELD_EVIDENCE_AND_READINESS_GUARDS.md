# 入力項目の判定精度とREADY制御の改善

## 実施範囲

2026-10-05、[候補3店舗の精査](98_FORM_CANDIDATE_NON_SENDING_REVIEW.md)で見つかった入力項目の誤分類を、匿名のHTML fixtureで再現して修正した。実企業サイトのGET、入力、確認画面操作、Form POST、メール送信は今回行っていない。AI・APIキーは使用していない。

## 改善

| 問題 | 変更後 |
|---|---|
| フォーム全体の文章から氏名・電話等を本文と誤認 | 個別label、aria-label、同じ表行の見出し、dt/dd、同一入力欄だけを含むブロックを根拠にする |
| 表の必須表示を見落とす | 個別欄に対応する「必須」「required」「※／＊／*」を読む |
| Contact Form 7の必須・同意を見落とす | validates-as-requiredと非optional acceptanceを読む |
| 問い合わせ種別を本文へ誤分類 | 「お問い合わせ項目」「お問い合わせの種類」を種別として扱い、select/radio/checkboxを本文にしない |
| 選択肢の「電話／メール」を欄の用途と混同 | 選択肢の文章と欄の見出しを分け、連絡方法を推測でemailへ割り当てない |
| 複数欄を同じ本文へ割り当ててREADY | 本文の候補は1つ、text/textarea、confidence>=0.8を要求 |
| 手動修正を戻す前の判定が残る | 保存済みMANUALの対応を適用してから状態を判定 |

対象サイト・店舗名・業種の分岐は入れていない。未対応の必須欄はunknownのまま残し、REVIEW_REQUIREDにする。本文がない・複数ある・選択式欄へ割り当てられた・信頼度が不足する場合も理由付きのREVIEW_REQUIREDとする。

## 同じ基準を使う境界

`services/form_intelligence/fields.py`へ入力欄の抽出とmapping_review_reasonを分離し、肥大化していたanalyzerから移動した。既存のanalyzer.parse_form_fieldsの呼び出しも維持。

- Form Intelligenceによる保存状態・要確認理由。
- 既存の入力項目手動修正APIによるREADY再判定。
- 既存_ready_profileを使う承認用準備・フォーム送信準備。

古い保存状態がREADYでも、本文が重複・不確定なら送信準備はmanual_requiredで拒否する。手動修正やAIの対応付けを理由に本文型・重複の制約を迂回できない。Human Approval、suppression、重複宛先、CAPTCHA、fingerprint、UNKNOWNの既存制御は維持。

解析バージョンを1.2 → 1.3へ更新。抽出されるラベル・必須性が変われば既存fingerprint変更検知によりSTALEとなり、古い解析や承認をそのまま利用する根拠にはしない。DB Schema・Migration・新規API・送信権限の追加なし。

## 匿名テストで確認したこと

- 表形式の4欄を氏名・メール・電話・本文へ対応し、必須4欄を認識。
- 隣接する本文や他欄のrequiredが、不明な入力欄へ伝播しない。
- 問い合わせ種別selectと本文textareaを区別。
- 連絡方法radioは電話・メールの値だけでemailへ誤認せず、不明な必須欄として保留。
- Contact Form 7の必須・同意とoptional同意を区別。
- dt/dd形式の見出しから入力目的・必須性を取得。
- 本文重複、選択式本文、不明textareaの低信頼度はREADYにしない。
- MANUALでunknownにした本文は再解析後もunknown / REVIEW_REQUIRED。
- 保存済みREADYプロフィールの本文重複を承認準備APIが409で拒否。
- 既存の匿名フォーム種類別コーパス、禁止表記、CAPTCHA、fingerprint、承認準備・送信・結果記録・一覧の関連動作。

動的に追加される必須欄、JavaScript確認・送信経路、実サイトの最終POSTはこのテストの対象外。Contact Form 7や表形式を解析できることと、その実サイトへ通常経路で送信できることは別。前回のCecil/PALIOの技術保留は解除していない。

## 品質確認

初回の関連71テストで66成功・5失敗。5件は従来の正常系fixtureがconfidence未設定（既定値0）のままREADYを宣言していたため、新しい本文確認で拒否された。正常系fixtureをconfidence=1.0と明示し、重複本文は拒否される負のケースも追加。制御を緩める変更はしていない。

最終コードで、初回に通った解析・入力欄・互換性の60ケースと、修正後の承認準備・送信・結果・一覧・MANUAL再解析の53ケースが成功（重複を除いて113ケース）。全Backend・E2Eを今回実行したとは扱わない。

- Backend全app/testsのRuff、変更ファイルformat check、app compileall：成功。
- 専用_test PostgreSQLでの関連API・Serviceテストと既存Migration upgrade/model check：成功。
- Frontend typecheck / lint / build：成功。フロントコード変更なし。

## ローカル反映

変更5ファイルを利用中APIコンテナへ反映してAPIを再起動。コンテナ内の匿名fixtureで1.3、表の必須性とメール/本文対応を確認し、API health/database=okを確認した。配布済みWindowsパッケージ・既存Docker imageは未更新。他PCへの反映には新しいソースからのbuild・更新が必要。

利用中DBは読み取りのみ。企業100、FormProfile139、active job0、送信関連3テーブル0を維持。flagsすべてOFF、worker=exited。

現在の一覧分類はCAPTCHA9、確認画面4、解析エラー66、旧版解析2、フォーム未発見12、営業禁止1、要確認6。以前の構造上候補2はバージョン差分で旧版解析となった。最終連絡制御はALLOWED0 / UNCERTAIN83 / PROHIBITED17。今回実データを再解析したという意味ではない。

ローカル検証集計：`dist/field-accuracy-runtime-check.json`。一度限りの検証スクリプトはGitへ含めない。

## 次の工程

新しい解析で保留中の2店舗をGETのみ再確認し、入力欄・必須性・fingerprint・確認画面分類を比較する。実際の確認画面POSTや送信の検証、保留解除は別工程とする。
