"""Persist compatibility reason codes and expand CAPTCHA types."""

import sqlalchemy as sa
from alembic import op

revision = "b835e71a20c4"
down_revision = "ff61aab29a10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "form_profiles",
        sa.Column(
            "compatibility_reason_code", sa.String(length=50), server_default="", nullable=False
        ),
    )
    op.drop_constraint("ck_form_profile_captcha_type", "form_profiles", type_="check")
    op.create_check_constraint(
        "ck_form_profile_captcha_type",
        "form_profiles",
        "captcha_type IN ('CAPTCHA_NONE', 'CAPTCHA_RECAPTCHA', 'CAPTCHA_RECAPTCHA_V2', "
        "'CAPTCHA_RECAPTCHA_V3', 'CAPTCHA_CF7_RECAPTCHA', 'CAPTCHA_HCAPTCHA', "
        "'CAPTCHA_TURNSTILE', 'CAPTCHA_IMAGE', 'CAPTCHA_OTHER')",
    )
    op.execute(
        """
        UPDATE form_profiles
        SET compatibility_reason_code = CASE review_reason
            WHEN 'POST形式ではないためCodex支援が必要です。' THEN 'NON_POST_METHOD'
            WHEN 'ファイル送信用フォームはCodex支援が必要です。'
                THEN 'MULTIPART_OR_FILE'
            WHEN 'multipart形式の送信経路は未検証です。ブラウザでの確認が必要です。'
                THEN 'MULTIPART_OR_FILE'
            WHEN '外部サイトへ送信するフォームです。' THEN 'EXTERNAL_ACTION'
            WHEN '安全でない通信へ送信するフォームです。' THEN 'INSECURE_ACTION'
            WHEN 'Contact Form 7の送信経路は未対応です。ブラウザで確認してください。'
                THEN 'CONTACT_FORM_7'
            WHEN 'JavaScript・非同期の送信経路は未検証です。ブラウザでの確認が必要です。'
                THEN 'ASYNC_SUBMISSION'
            WHEN '確認・送信ボタンがJavaScript操作を必要とします。確認経路は未検証です。'
                THEN 'JAVASCRIPT_CONFIRMATION'
            WHEN '送信ボタンに独自処理または送信先の上書きがあります。ブラウザでの確認が必要です。'
                THEN 'CUSTOM_SUBMIT_HANDLER'
            WHEN '複数選択項目は人による確認が必要です。' THEN 'MULTIPLE_SELECT'
            WHEN '同名の複数入力項目は人による確認が必要です。' THEN 'DUPLICATE_INPUTS'
            WHEN 'ファイルまたはパスワード入力があるためCodex支援が必要です。'
                THEN CASE WHEN EXISTS (
                    SELECT 1 FROM form_profile_fields f
                    WHERE f.form_profile_id = form_profiles.id AND f.field_type = 'file'
                ) THEN 'MULTIPART_OR_FILE' ELSE 'PASSWORD_FIELD' END
            WHEN '送信項目にname属性がないためブラウザ操作が必要です。'
                THEN 'MISSING_NAME_ATTRIBUTE'
            WHEN '入力項目がないため人による確認が必要です。' THEN 'NO_INPUT_FIELDS'
            WHEN '標準の送信ボタンを確認できません。ブラウザ操作が必要です。'
                THEN 'NO_NATIVE_SUBMIT'
            ELSE ''
        END
        WHERE compatibility_reason_code = ''
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE form_profiles SET captcha_type = CASE
            WHEN captcha_type IN ('CAPTCHA_RECAPTCHA_V2', 'CAPTCHA_RECAPTCHA_V3',
                                  'CAPTCHA_CF7_RECAPTCHA') THEN 'CAPTCHA_RECAPTCHA'
            WHEN captcha_type = 'CAPTCHA_IMAGE' THEN 'CAPTCHA_OTHER'
            ELSE captcha_type
        END
        """
    )
    op.drop_constraint("ck_form_profile_captcha_type", "form_profiles", type_="check")
    op.create_check_constraint(
        "ck_form_profile_captcha_type",
        "form_profiles",
        "captcha_type IN ('CAPTCHA_NONE', 'CAPTCHA_RECAPTCHA', 'CAPTCHA_HCAPTCHA', "
        "'CAPTCHA_TURNSTILE', 'CAPTCHA_OTHER')",
    )
    op.drop_column("form_profiles", "compatibility_reason_code")
