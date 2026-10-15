# CF7 6.1.6: 管理下fixtureと対応差分

## 今回のゴールと範囲

基準は `7569b3ad19eb04d7e93669c9fa0b43040b56a9d6`。保存済み20件のうち、CF7として検出した6件で現れた構成を、実サイトへ送信せず検証する。

今回は独自に記述したsynthetic HTML fixtureと回帰テストを追加した。productionの版allowlist、解析上限、送信経路、Human承認、API、UI、DB、migration、feature flagは変更していない。CF7 6.1.6の実サイト対応・送信契約の完成ではない。

## 公式ソース比較

上流 `rocklobster-in/contact-form-7` のタグをGitHub APIで確認した。

| タグ | Commit |
| --- | --- |
| v6.1.4 | 165278e868387ec393569ecd2dbfda37e8b5b950 |
| v6.1.6 | 3decbc4d7a230d8331e77243a6747b5ec6807d78 |

[上流比較](https://github.com/rocklobster-in/contact-form-7/compare/v6.1.4...v6.1.6)の変更ファイルは `includes/css/styles.css`、`includes/mail.php`、`package-lock.json`、`package.json`、`readme.txt`、`wp-contact-form-7.php`。フォーム生成、REST受付、reCAPTCHAのファイルはこの比較で変更されていない。メール処理は変更されており、HTML構造の共通性だけで送信結果・受理・到達の互換性を保証しない。

[固定commitのフォーム生成](https://github.com/rocklobster-in/contact-form-7/blob/3decbc4d7a230d8331e77243a6747b5ec6807d78/includes/contact-form.php)は基本hidden 6項目、nonceの条件付き追加、追加hidden用filterを持つ。[reCAPTCHAモジュール](https://github.com/rocklobster-in/contact-form-7/blob/3decbc4d7a230d8331e77243a6747b5ec6807d78/modules/recaptcha/recaptcha.php)と[REST受付](https://github.com/rocklobster-in/contact-form-7/blob/3decbc4d7a230d8331e77243a6747b5ec6807d78/includes/rest-api.php)も参考確認した。

上流コードのコピー・dependency追加・PHP実行はしていない。fixtureはLeadHiveのテスト用に独立して記述したもので、WordPressが実際に生成した出力や実サイトの保存HTMLではない。

## 保存データの観測

異なる日時の保存ページを使った静的観測であり、同一条件でのBefore/After改善率ではない。個別URL・会社・hidden値はGitへ含めない。

| 項目 | 件数 |
| --- | ---: |
| CF7検出 | 6 |
| 既存隔離解析で構造確認 | 4 |
| サイズ上限停止 | 2 |
| HTML記載6.1.6 | 2 |
| HTML記載6.2.1 | 1 |
| HTML記載6.1.7 | 1 |
| 版未確認 | 2 |
| CAPTCHA検出 | 3 |
| 必須項目マッピング不明 | 3 |
| 構造確認済みで追加hiddenあり | 4 |
| 既存検証済み版との一致 | 0 |

理由は重複する。未解析2件を追加hiddenなしと解釈しない。Humanレビュー0、検証済み送信可能件数0、Human適合率null。HTMLに書かれた版は未信頼データであり、実際のプラグイン版の証明ではない。

## 追加テスト

`backend/tests/fixtures/cf7-616-managed.html` と `backend/tests/test_cf7_616_static_fixture.py` を追加。

- 6.1.6のマーカー・基本hidden・同一origin REST rootを観測するが、旧契約や送信権限へ昇格させない。
- reCAPTCHA、nonce、未知hiddenを追加項目として数え、値を返さない。空のreCAPTCHA tokenもHuman Requiredを維持する。
- 別origin、base override、file、GET、name欠落、重複hidden、サイズ超過を検証する。
- 旧6.1.4契約へ6.1.6 hiddenを混ぜるケースと、版を6.1.6へ書き換えるケースを拒否する。
- multipartのCF7を通常POSTの対応済みフォームと誤認しない。

関連4ファイルのテスト: **74 passed, 50 subtests passed**。追加テストのRuff lint/format成功。専用テストDB設定で実行した。productionフロントエンド・API・migrationを変更しておらず、今回のローカル検証でそれらの起動・build・migrationを再実行してはいない。

## 安全と次工程

企業サイト追加GET、AI、実データDB書込、Approval作成、メール、Form POSTはすべて0。実送信workerは起動していない。公式GitHubソースのread-only照会のみ行った。

次の工程は、6.1.6用の非実行・固定版候補契約を既存の共通検証部品で構成し、payload hash/version、入力順序、追加hidden、選択肢の扱いを管理下テストで検証すること。今回のテスト成功を理由にproduction allowlistを広げない。6.1.7・6.2.1の流用も認めない。

追加hiddenは意味・値の扱いを確認し、未知のまま包括的に許可しない。CAPTCHAは人の操作が必要。サイズ上限を一律に緩和したり、formだけ切り出してページ全体の安全情報を失ったりしない。

実サイト送信接続には窓口用途・営業可否・抑止・opt-out・送信者・重複・現在構造・Human承認・UNKNOWN保護の別検証が必要。今回の結果でREADY件数の増加は主張しない。
