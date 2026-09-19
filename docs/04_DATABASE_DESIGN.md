# LeadHive V2 - Database Design

## 1. 基本方針

旧LeadHiveのDBをそのまま移行しない。
V2用DBを新規設計する。

## 2. users

- id
- email
- password_hash
- created_at
- updated_at

## 3. projects

- id
- user_id
- project_name
- target_profile_id
- sales_objective
- region
- status
- created_at
- updated_at

## 4. target_profiles

- id
- user_id nullable
- profile_name
- description
- search_keywords JSON
- positive_keywords JSON
- negative_keywords JSON
- exclusion_keywords JSON
- scoring_rules JSON
- ai_instruction TEXT
- default_regions JSON
- is_system BOOLEAN
- active BOOLEAN
- created_at
- updated_at

## 5. companies

- id
- project_id
- company_name
- website_url
- domain
- address
- prefecture
- city
- phone
- email
- contact_url
- instagram_url
- x_url
- tiktok_url
- facebook_url
- youtube_url
- line_url
- business_summary
- website_text
- source
- source_keyword
- score
- rank
- ai_summary
- ai_reason
- ai_strengths JSON
- ai_concerns JSON
- ai_recommended_approach
- status
- notes
- created_at
- updated_at

## 6. collection_jobs

- id
- project_id
- source
- keyword
- region
- status
- found_count
- saved_count
- duplicate_count
- error_count
- created_at
- finished_at

## 7. activities

- id
- company_id
- activity_type
- note
- created_at

## 8. 重複排除

優先順位:

1. domain
2. website_url
3. corporate_number（将来追加）
4. company_name + address

同一プロジェクト内では同一企業を重複登録しない。

別プロジェクトでは同じ企業を登録可能とする。

## 9. 将来追加候補

必要になったら追加:
- organizations
- memberships
- contacts
- deals
- messages
- scheduled_tasks
- external_integrations
- billing
