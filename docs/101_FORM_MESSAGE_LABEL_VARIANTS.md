# 本文ラベルの表記揺れ対応

## 変更

2026-10-05、[保留2店舗の再確認](100_HELD_FORM_V13_GET_ONLY_RECHECK.md)で発見した「お問合せ内容」の低信頼度判定を、業種・店舗によらないFIELD_RULESの追加で改善した。

本文ラベルに「お問合せ内容」「問合せ内容」「お問い合わせの内容」「問い合わせの内容」を追加。局所ラベルの根拠がある場合、textareaのfallback confidence=0.75ではなくRULEの0.9でmessageと認識する。閾値0.8は変更していない。

種別の別表記「お問合せ種別」「問合せ種別」「お問合せ項目」もcontact_categoryへ対応。「お問合せ」だけの曖昧なラベルを広く本文へ割り当てる変更や、サイト全体の文から用途を推測する変更は行っていない。入力欄型・本文重複・未対応必須欄の既存制御を維持する。

解析バージョンは1.3→1.4。旧保存結果を新ルールで再解析済みと扱わない。schema・Migration・API・UI・認証・送信機能の追加なし。

## 検証

匿名fixtureを10ケース追加した。

- 6種類の本文表記を、表見出しに対応するtextareaへmessage / confidence=0.9 / required=trueと認識。
- 3種類の問い合わせ種別を本文と区別。
- 曖昧な「お問合せ」だけのtextareaは引き続き低信頼度・要確認。

既存の不明欄・選択式本文・本文重複・MANUAL修正・解析・フォーム互換性・承認準備・一覧を含む関連100テストが成功（95.95秒）。専用_test PostgreSQLでMigration upgrade/model差分チェックも成功。全Backend・E2Eの実行とは扱わない。実店舗への入力・GET・確認POST・送信は今回の対象外。

Backend全app/testsのRuff、変更3ファイルのformat check、app compileallが成功。Frontend typecheck / lint / buildが成功。フロントコードは変更していない。

## 運用への影響

PALIOで確認した本文ラベルを一般ルールで認識できるようにする修正であり、同店舗の実行経路を検証したものではない。Cecilの必須連絡方法とContact Form 7、PALIOのJavaScript確認画面に関する技術保留は維持する。通常送信可能という判断や保留解除は行わない。

利用中DBの保存済みプロフィール・送信記録を変更しない。ローカルAPIへの反映はソース差し替えとAPI再起動のみ。worker停止・外部送信flags OFFを維持する。配布済みWindowsパッケージ・Docker imageの再buildは別途必要。

反映後、コンテナ内で解析1.4と匿名表形式の「お問合せ内容」認識を確認。API health/database=ok、保留プロフィール2件、企業100、FormProfile139、active job0、送信関連3テーブル各0を確認した。worker=exited、flags全OFF。利用中DBは読み取りのみ。店舗別情報を含まない[稼働検証集計](results/message-alias-validation-2026-10-05.json)を保存した。

## 次の工程

連絡方法の必須選択項目について、標準キーと送信者設定からの選択値生成の最小設計を確認する。これはメールアドレス欄への誤割り当てとは分けて扱い、同意の必須性やJavaScript経路も未検証事項として残す。
