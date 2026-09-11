CREATE TABLE IF NOT EXISTS eval_retention_holds (
 run_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 operator VARCHAR(120) NOT NULL, reason VARCHAR(500) NOT NULL,
 basis VARCHAR(40) NOT NULL, authorization_sha256 CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY(run_id) REFERENCES eval_runs(run_id), FOREIGN KEY(owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS maintenance_actions (
 action_id CHAR(64) PRIMARY KEY, kind VARCHAR(32) NOT NULL, target_id VARCHAR(191) NOT NULL,
 owner_id BIGINT UNSIGNED NULL, storage_root_hash CHAR(64) NOT NULL,
 storage_keys_json JSON NOT NULL, metadata_json JSON NOT NULL,
 operator VARCHAR(120) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'pending',
 attempts INT NOT NULL DEFAULT 0, error_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 completed_at DATETIME(6) NULL,
 KEY idx_maintenance_pending (storage_root_hash,status,owner_id),
 FOREIGN KEY(owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
