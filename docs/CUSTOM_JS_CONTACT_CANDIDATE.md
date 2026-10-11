# 独自JavaScript問い合わせ欄の検出漏れ修正

## 基準と実運用の再検証

- main `35cc89bb45d2d736c748db758180387bbb54f296`（PR #72統合）。
- main CI: [38122006774](https://github.com/team478a/leadhive_codex/actions/runs/38122006774)、全12項目成功。
- staging APIだけを同コミットへ更新。Render deployment `dep-db5jv90473hc73beordg` がLive。
- 許可済み自社サイト `https://stock-business.me/` の既存1件だけを再解析。
- HTMLサイズエラーは解消。解析5,405ms、保存候補1件、入力項目0件で「送信可能なフォームが見つかりません」。
- ブラウザには5入力項目が表示され、構造は `DIV#contactForm`、通常のform要素は0件だった。

保存候補1件は、入力欄を検出した件数ではない。入力、確認画面、送信、Approvalはすべて0件。
PCランナーは未実行。OUTBOUND/LIVE_FORM_INPUTはOFFを維持。
検索・AI APIは使用していない。企業GETの合計は未計測（null）。
再検証メモは当該企業の既存Activityへ保存した。通常営業Projectは変更していない。

## 原因

現行のcontact_pagesとフォーム解析は通常のform要素を前提にする。
DIVなどに入力欄を置き、JavaScriptで送る構造は、ブラウザに入力欄が見えていても解析対象にならない。
PCランナーもform要素を要求し、取得は500KB/resource・2MB/totalまでである。
従って、検出漏れ解消と実フォーム入力成功を別工程として扱う。

## このPRの限定修正

contact_discoveryに独自問い合わせコンテナの観察を追加し、既存解析で項目を保存する。

- id/aria-labelが問い合わせを示す、またはrole=formの限定範囲。
- 有効なemail欄、textarea、送信/確認ボタンがそろい、項目名が一意な場合だけ候補。
- ログイン/検索欄、隠された範囲、他のformへ所属する項目、無名/重複名は採用しない。
- 入れ子は最小の明示範囲にまとめる。候補が複数なら項目を混ぜず未確定を維持。
- 本物の問い合わせformがあれば既存解析を優先する。検索・取得予算は増やさない。
- 既存FormProfile/FormProfileFieldとfingerprintを使う。新規Model/API/Migration/依存なし。
- `form_found=true`は入力構造候補の存在。`delivery_supported=false`、`action_url=""`、確認画面unknownを固定。
- 営業可否をALLOWEDにせずUNCERTAINを維持。禁止表示はPROHIBITED/BLOCKED、連絡禁止へ反映。
- CAPTCHAを保持。AIを使って候補判定・項目推測・承認をしない。
- 解析ログに `CUSTOM_CONTACT_CONTROLS_CANDIDATE` を記録し、要確認理由に独自構造・入力未検証・HTTP未対応を表示。

通常HTTP送信、PCランナー、Human承認、送信制御は変更しない。
このPRを統合しても独自JavaScriptフォームの入力や送信が対応済みになるわけではない。

## 検証

- 新規18ケース: 問い合わせ範囲、必要な項目、隠された範囲、検索/ログイン、他form所属、重複項目、入れ子、複数候補、DB保存、営業NG/CAPTCHA。
- 新規・既存フォーム解析・画像サイズ・問い合わせ探索・互換性・連絡制御: 109 PASS。
- 専用 `_test` DBのみ。pytest fixtureでmigration upgrade/model diff確認。運用DBへ新修正は適用していない。
- 取得済みブラウザDOMの問い合わせ部分をGit管理外へ保存して再検証: formタグ0、独自候補1、入力項目5。
  これは保存DOMの抽出結果であり、HTTP生HTML精度・実入力成功率ではない。追加GETなし。
- Ruff/format、変更範囲mypy、API importを確認。最終コミットの全Backend/E2E等はPRのCIを参照。
- Frontend/DB schema/実行ランナーは変更なし。

再現コマンド（専用TEST_DATABASE_URLとbackendのPYTHONPATH/MYPYPATHを指定）:

```text
python -m pytest backend/tests/test_custom_contact_candidate.py backend/tests/test_form_intelligence.py backend/tests/test_large_form_html.py backend/tests/test_contact_discovery.py backend/tests/test_form_compatibility_corpus.py backend/tests/test_contact_permission.py -q
python -m ruff check backend/app/services/contact_discovery.py backend/app/services/form_intelligence/analyzer.py backend/tests/test_custom_contact_candidate.py
python -m ruff format --check backend/app/services/contact_discovery.py backend/app/services/form_intelligence/analyzer.py backend/tests/test_custom_contact_candidate.py
python -m mypy --check-untyped-defs --follow-imports=silent backend/app/services/contact_discovery.py backend/app/services/form_intelligence/analyzer.py
python -c "from app.main import app; print(app.title)"
```

## 次に残る一工程

独自問い合わせコンテナを入力専用ランナーで扱う限定対応を検討する。
HTML容量の制約、入力範囲の固定、通信凍結、読み戻し、営業NG/CAPTCHA/曖昧な範囲での停止を先に管理下テストで検証する。
その対応後に同じ自社サイトで入力だけを再試行する。送信や確認ボタンは対象外。
今回の新修正の自動マージ・クラウド反映は行わない。
