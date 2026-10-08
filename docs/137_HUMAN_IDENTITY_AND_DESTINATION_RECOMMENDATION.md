# Phase B3a — Human Identity / Official Site Evidence and Destination Recommendation

## ゴールと範囲

既存100店舗で不足していた、企業・店舗と公式サイトをHumanが照合して記録する経路を追加する。
窓口推奨は保存済み情報のREADY候補だけから行う。DM READY、送信承認、dispatchとは別。
公式サイトの自動発見・既存LeadSiteEvidenceは維持する。CRM追加、外部Agent、AI API、配送接続は行わない。

## 照合の条件

owner/editorのHumanのみ。公開公式ページの名称と、番地を含む住所または9〜15桁の電話を登録済み情報と照合する。
名称＋domainだけ、地域名だけ、住所/電話の矛盾では422。AIやconfirmed=trueだけでは確定できない。
電話は区切り・全角を正規化。住所は6文字以上の全体を要求し、数値を含む一致だけを照合根拠として扱う。
根拠URLは登録公式サイトと同domainの公開URL。private literal/localhost、credentials、query/fragment、別domainは拒否。
この記録はHumanの公開情報確認の陳述。アプリが根拠ページをGETして検証したという意味ではない。
公開情報の抜粋を10〜1000文字で保存し、HTML/命令として実行しない。秘密情報は入力しない。

## Model / Migration / API

- SiteIdentityReviewEvent: Project、歴史的Company/actor UUID、version、CONFIRMED/REVOKED、identity_hash、source_url、observed_name/address/phone、抜粋、照合理由、created_at、expires_at。
- additive revision `15fcce21f276`、parent `e49867e60dcd`。旧Migrationは変更しない。
- DB triggerでProject所属・Human owner/editor・版の連続性を確認。UPDATE/DELETE/TRUNCATEは禁止。
- Company統合/削除後も歴史的IDを保持し、他Companyへ確認を移さない。
- Project削除の既存cascadeのみ許容。Project削除後の証跡保存ポリシーは別課題。非空downgradeは拒否。

| API | 内容 |
| --- | --- |
| GET `/api/companies/{id}/lead-completion` | current identity hash、最新Human記録、照合根拠の種別を返す |
| POST `/api/companies/{id}/site-identity-reviews` | expected hash/version、公開照合情報を検証し追加記録 |
| POST `/api/companies/{id}/site-identity-reviews/revoke` | expected versionで取消イベントを追加 |
| GET `/api/companies/{id}/sendability` | 現在の照合・用途確認・既存安全制御から診断/推奨を返す |

Human CookieとAgent credential混在は拒否。Viewer/他Projectは書込不可。認証情報やAgent scopeを増やさない。
Server側7日上限。UNREVIEWED/CURRENT/STALE/EXPIRED/REVOKEDを読取時に判定し、期限切れで旧レコードを書き換えない。
identity_hashはrecord_type/名称/住所/電話/公式URLにbind。対象変更は409/STALE。project lockとversion unique/triggerで並行更新を直列化。

## 既存証跡との互換性

現在の自動ルールCONFIRMED証跡があればAUTOMATIC_RULE、それ以外で有効なHuman記録があればHUMAN_OBSERVED。
Human取消はHuman証跡を取り消す操作で、自動ルール証跡を上書き/削除しない。別domainや他店舗への流用は不可。
最新Human記録ID/version/typeを用途確認snapshotにも含める。Human照合記録の変更後は用途を再確認する。
照合期限切れはSendabilityのIDENTITY_UNCERTAINでREADYから外れる。用途確認だけで期限切れIdentityを復活させない。

## 窓口推奨

`sendability-b3-v1`。すべての既存条件を満たすREADY候補のみ。
初期の決定的優先順はsales > partnership > business > general。channelには優劣を付けない。
単独の最上位候補なら推奨ID/type/value/purposeと現在のsnapshot hashを返す。同条件複数なら推奨なし、Humanの選択が必要と表示。
HOLD/REVIEW/BLOCKED、共有窓口、禁止、UNKNOWN、送信済み/実行中、CAPTCHA等は推奨しない。
推奨は宛先の確定、payload freeze、Human Approval、送信権限ではない。execution_allowedとdm_readyはfalseを維持。
これは初期ルール。実リストで用途分類・選択の妥当性を検証してから配送へ接続する。

## UI

企業詳細 → リスト完成の根拠 → 企業・店舗と公式サイトを確認する。
公式ページで見た名称・住所/電話・根拠URL・公開情報を入力。「照合確認を記録」「照合確認を取り消す」。
Human記録の状態/版/根拠/確認者/期限を表示。対象hash変更時は入力をリセット。
窓口診断では推奨準備窓口または同条件時の未選択を表示。送信/承認ボタンは追加しない。

## 集計

固定cohortのIdentity/公式サイト証拠診断にも最新の有効Human証跡をbulk取得して反映。
定義は`completion-b3-identity-v1`。対象条件のMATCHED未評価を一致扱いにしない。
DM READY率、Cost per DM READY、後続未評価指標は未判定を維持。Sendability全段階をcohortへ結合するのは次工程。

## 検証・運用境界

合成専用DBで照合、不十分/矛盾、Agent/Viewer/他Project、版競合、失効、取消、改変禁止、削除互換、Migration差分を検証。
既存B1/B2/A1/A2関連回帰、mypy/Ruff、Frontend typecheck/lint/build、PC/mobile E2E、最終HEADのCIを確認する。
ローカル結果：関連回帰40件＋新規18件成功、mypy 7ファイル成功、Ruff成功、Frontend typecheck/lint/build成功、desktop/mobile E2E 2件成功（1.5分）。
稼働中100店舗のDB/コンテナ/停止worker、配布packageは変更しない。実サイトアクセス、検索/AI API、SMTP/Form POST、実送信は実行しない。

## 次のゴール B3b

固定cohortへ窓口診断・独立Destination数・理由を一貫して反映し、READY窓口と文面完成のDM READYを分けて計測する。
Humanによる同条件窓口の確定選択は、snapshot/versionと対象範囲にbindした別の準備証跡として設計する。
その後、Phase Cのテンプレート＋個別化Evidence、Phase DのHuman Approval/既存配送結合へ進む。
