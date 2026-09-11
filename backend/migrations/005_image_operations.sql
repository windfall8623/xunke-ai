CREATE TABLE IF NOT EXISTS image_operations (
 operation_id VARCHAR(128) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 quiz_id VARCHAR(64) NOT NULL, question_id VARCHAR(64) NOT NULL,
 status VARCHAR(24) NOT NULL, request_hash CHAR(64) NOT NULL,
 result_json JSON NULL, error_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_image_question (quiz_id,question_id),
 FOREIGN KEY (quiz_id,owner_id) REFERENCES quiz_sessions(quiz_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
ALTER TABLE image_generation_logs MODIFY question_id VARCHAR(64) NULL;
-- @column user_assets source_scope_json
ALTER TABLE user_assets ADD source_scope_json JSON NULL;
