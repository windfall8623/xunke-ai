ALTER TABLE users MODIFY openid VARCHAR(64) NULL;
-- @column users role
ALTER TABLE users ADD role VARCHAR(20) NOT NULL DEFAULT 'learner';

CREATE TABLE IF NOT EXISTS auth_identities (
 identity_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 user_id BIGINT UNSIGNED NOT NULL, provider VARCHAR(24) NOT NULL,
 app_scope VARCHAR(64) NOT NULL DEFAULT '', subject VARCHAR(191) NOT NULL,
 password_hash VARCHAR(255) NULL, recovery_hash CHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_identity (provider,app_scope,subject),
 FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash CHAR(64) PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL,
 csrf_token VARCHAR(64) NOT NULL, expires_at DATETIME(6) NOT NULL,
 revoked_at DATETIME(6) NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY idx_session_user (user_id), FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS auth_rate_limits (
 bucket_hash CHAR(64) PRIMARY KEY, attempts INT NOT NULL, expires_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS auth_link_codes (
 code_hash CHAR(64) PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL,
 app_scope VARCHAR(64) NOT NULL, expires_at DATETIME(6) NOT NULL, used_at DATETIME(6) NULL,
 FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS user_assets (
 asset_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 storage_key VARCHAR(255) NOT NULL, content_type VARCHAR(64) NOT NULL,
 created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- @column quiz_sessions status
ALTER TABLE quiz_sessions
 ADD status VARCHAR(24) NOT NULL DEFAULT 'active', ADD revision INT NOT NULL DEFAULT 0,
 ADD rag_run_id VARCHAR(64) NULL, ADD source_scope_json JSON NULL,
 ADD source_policy VARCHAR(24) NOT NULL DEFAULT 'topic',
 ADD source_status VARCHAR(32) NOT NULL DEFAULT 'legacy_unverified',
 ADD settled_at DATETIME(6) NULL, ADD xp_awarded INT NOT NULL DEFAULT 0,
 ADD origin_task_id VARCHAR(64) NULL, ADD images_status VARCHAR(24) NOT NULL DEFAULT 'not_requested',
 ADD UNIQUE KEY uk_quiz_origin (origin_task_id), ADD UNIQUE KEY uk_quiz_owner (quiz_id,user_id);
CREATE TABLE IF NOT EXISTS quiz_answers (
 quiz_id VARCHAR(64) NOT NULL, question_id VARCHAR(64) NOT NULL, user_id BIGINT UNSIGNED NOT NULL,
 selected_json JSON NOT NULL, is_correct BOOLEAN NOT NULL, duration_ms INT NOT NULL,
 submission_hash CHAR(64) NOT NULL, receipt_json JSON NOT NULL,
 created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(quiz_id,question_id),
 CONSTRAINT fk_answer_owner FOREIGN KEY (quiz_id,user_id) REFERENCES quiz_sessions(quiz_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- @column reports status
ALTER TABLE reports ADD status VARCHAR(24) NOT NULL DEFAULT 'completed',
 ADD error_code VARCHAR(64) NULL, ADD stats_revision INT NOT NULL DEFAULT 0,
 MODIFY report_json JSON NULL;
UPDATE quiz_sessions q LEFT JOIN answer_records a ON a.quiz_id=q.quiz_id
 LEFT JOIN reports r ON r.quiz_id=q.quiz_id SET q.status='settled',q.settled_at=COALESCE(a.created_at,r.created_at)
 WHERE q.settled_at IS NULL AND (a.id IS NOT NULL OR r.id IS NOT NULL);

ALTER TABLE quiz_tasks MODIFY status VARCHAR(24) NOT NULL DEFAULT 'pending';
-- @column quiz_tasks kind
ALTER TABLE quiz_tasks
 ADD kind VARCHAR(24) NOT NULL DEFAULT 'quiz', ADD operation VARCHAR(40) NOT NULL DEFAULT 'quiz.generate',
 ADD mode VARCHAR(20) NOT NULL DEFAULT 'production', ADD request_json JSON NULL,
 ADD request_hash CHAR(64) NULL, ADD idempotency_key VARCHAR(128) NULL,
 ADD scope_json JSON NULL, ADD quiz_id VARCHAR(64) NULL,
 ADD stage VARCHAR(32) NOT NULL DEFAULT 'queued', ADD error_code VARCHAR(64) NULL,
 ADD attempt INT NOT NULL DEFAULT 0, ADD max_attempts INT NOT NULL DEFAULT 2,
 ADD worker_id VARCHAR(64) NULL, ADD lease_token VARCHAR(64) NULL, ADD lease_expires_at DATETIME(6) NULL,
 ADD queued_expires_at DATETIME(6) NULL, ADD deadline_at DATETIME(6) NULL,
 ADD cancel_requested BOOLEAN NOT NULL DEFAULT FALSE, ADD priority INT NOT NULL DEFAULT 10,
 ADD UNIQUE KEY uk_job_idempotency (user_id,operation,idempotency_key),
 ADD KEY idx_job_claim (status,priority,created_at);
UPDATE quiz_tasks SET status='failed',error_code='legacy_unrecoverable',error_message='旧任务缺少完整参数，无法安全恢复'
 WHERE request_json IS NULL AND status IN ('pending','running');
-- @column image_generation_logs operation_id
ALTER TABLE image_generation_logs ADD operation_id VARCHAR(128) NULL,
 ADD UNIQUE KEY uk_image_operation (operation_id);
CREATE TABLE IF NOT EXISTS worker_heartbeats (
 worker_id VARCHAR(64) PRIMARY KEY, role VARCHAR(24) NOT NULL, heartbeat_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;
