CREATE TABLE IF NOT EXISTS eval_datasets (
 dataset_id VARCHAR(64) NOT NULL, version INT NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 name VARCHAR(200) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'draft', revision INT NOT NULL DEFAULT 1,
 manifest_json JSON NOT NULL, samples_json JSON NOT NULL, checksum CHAR(64) NULL,
 artifact_key VARCHAR(500) NULL, created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(dataset_id,version), FOREIGN KEY(owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS eval_runs (
 run_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 dataset_id VARCHAR(64) NOT NULL, dataset_version INT NOT NULL,
 pipeline_id VARCHAR(64) NOT NULL, manifest_json JSON NOT NULL,
 request_hash CHAR(64) NOT NULL, idempotency_key VARCHAR(128) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'queued', stop_reason VARCHAR(64) NULL,
 repeat_count INT NOT NULL, max_cost_cny DECIMAL(12,4) NOT NULL, spent_cny DECIMAL(12,4) NOT NULL DEFAULT 0,
 reserved_cny DECIMAL(12,4) NOT NULL DEFAULT 0, deadline_at DATETIME(6) NOT NULL,
 created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), UNIQUE KEY uk_eval_idempotency(owner_id,idempotency_key),
 FOREIGN KEY(dataset_id,dataset_version) REFERENCES eval_datasets(dataset_id,version),
 FOREIGN KEY(owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS eval_results (
 result_id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64) NOT NULL, sample_id VARCHAR(128) NOT NULL,
 repeat_index INT NOT NULL, case_type VARCHAR(24) NOT NULL, sample_json JSON NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'queued', prediction_status VARCHAR(24) NOT NULL DEFAULT 'queued',
 artifact_json JSON NULL, artifact_key VARCHAR(500) NULL, metrics_json JSON NULL,
 error_code VARCHAR(64) NULL, attempts_json JSON NULL, review_json JSON NULL, review_revision INT NOT NULL DEFAULT 0,
 scoring_attempt INT NOT NULL DEFAULT 0, scoring_lease_token VARCHAR(64) NULL, scoring_expires_at DATETIME(6) NULL,
 created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_result_identity(run_id,sample_id,repeat_index), FOREIGN KEY(run_id) REFERENCES eval_runs(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS quiz_feedback (
 feedback_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL, quiz_id VARCHAR(64) NOT NULL,
 question_id VARCHAR(64) NOT NULL, rag_run_id VARCHAR(64) NULL, reason VARCHAR(64) NOT NULL,
 comment TEXT NULL, allow_evaluation BOOLEAN NOT NULL DEFAULT FALSE, status VARCHAR(24) NOT NULL DEFAULT 'pending',
 review_json JSON NULL, created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY(quiz_id,owner_id) REFERENCES quiz_sessions(quiz_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS budget_accounts (
 account_key VARCHAR(191) PRIMARY KEY, resource_type VARCHAR(32) NOT NULL,
 quota DECIMAL(18,6) NOT NULL, used DECIMAL(18,6) NOT NULL DEFAULT 0,
 reserved DECIMAL(18,6) NOT NULL DEFAULT 0, revision INT NOT NULL DEFAULT 0,
 CHECK (used>=0), CHECK(reserved>=0)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS budget_reservations (
 operation_id VARCHAR(128) NOT NULL, resource_type VARCHAR(32) NOT NULL,
 accounts_json JSON NOT NULL, reserved DECIMAL(18,6) NOT NULL, actual DECIMAL(18,6) NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'reserved', created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(operation_id,resource_type)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS provider_calls (
 call_id VARCHAR(128) PRIMARY KEY, operation_id VARCHAR(128) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 mode VARCHAR(24) NOT NULL, stage VARCHAR(32) NOT NULL, status VARCHAR(24) NOT NULL,
 usage_json JSON NULL, created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
