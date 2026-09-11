-- A user has one password identity. Other providers retain their existing
-- app-scoped uniqueness because their generated value is NULL.
-- The migration runner rejects existing duplicate password identities first.
-- @column auth_identities password_user_id
ALTER TABLE auth_identities ADD password_user_id BIGINT UNSIGNED
 GENERATED ALWAYS AS (CASE WHEN provider='password' THEN user_id ELSE NULL END) STORED;
-- @index auth_identities uk_password_user
ALTER TABLE auth_identities ADD UNIQUE KEY uk_password_user (password_user_id);
