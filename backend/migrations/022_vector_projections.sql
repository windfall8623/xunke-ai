-- Physical vector projections are separate from immutable logical manifests.
-- @column worker_heartbeats status_json
ALTER TABLE worker_heartbeats ADD COLUMN status_json JSON NULL;

CREATE TABLE IF NOT EXISTS rag_vector_projections (
    projection_key VARCHAR(96) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    backend VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    target_revision VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    owner_id BIGINT UNSIGNED NOT NULL,
    namespace VARCHAR(128) NOT NULL,
    doc_id VARCHAR(64) NOT NULL,
    ref_json JSON NOT NULL,
    archive_json JSON NULL,
    expected_json JSON NULL,
    verified_json JSON NULL,
    source_vectors_hash CHAR(64) NULL,
    target_vectors_hash CHAR(64) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'writing',
    task_id VARCHAR(64) NULL,
    task_attempt INT UNSIGNED NULL,
    worker_id VARCHAR(128) NULL,
    migration_run_id VARCHAR(80) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    verified_at DATETIME(6) NULL,
    PRIMARY KEY (projection_key, backend, target_revision),
    KEY idx_vector_document (owner_id, doc_id, status),
    KEY idx_vector_migration (migration_run_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_vector_operations (
    operation_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    projection_key VARCHAR(96) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    backend VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    target_revision VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    operation_kind VARCHAR(16) NOT NULL,
    batch_hash CHAR(64) NULL,
    task_id VARCHAR(64) NULL,
    task_attempt INT UNSIGNED NULL,
    worker_id VARCHAR(128) NULL,
    provider_operation_id VARCHAR(64) NULL,
    provider_status VARCHAR(32) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'started',
    error_code VARCHAR(64) NULL,
    recovery_json JSON NULL,
    recovered_at DATETIME(6) NULL,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6) NULL,
    KEY idx_vector_operation_projection (projection_key, backend, target_revision, status),
    KEY idx_vector_operation_task (task_id, task_attempt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_execution_receipts (
    receipt_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    attempt INT UNSIGNED NOT NULL,
    worker_id VARCHAR(128) NOT NULL,
    owner_id BIGINT UNSIGNED NOT NULL,
    kind VARCHAR(32) NOT NULL,
    document_ids_json JSON NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'started',
    recovery_json JSON NULL,
    recovered_at DATETIME(6) NULL,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6) NULL,
    UNIQUE KEY uq_vector_execution (task_id, attempt, worker_id),
    KEY idx_vector_execution_owner (owner_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
