ALTER TABLE kb_documents MODIFY status VARCHAR(24) NOT NULL DEFAULT 'processing';
-- @column kb_documents purpose
ALTER TABLE kb_documents
 ADD purpose VARCHAR(24) NOT NULL DEFAULT 'production', ADD namespace VARCHAR(128) NOT NULL DEFAULT 'legacy',
 ADD active_version_id VARCHAR(64) NULL, ADD active_build_id VARCHAR(64) NULL,
 ADD deleted_at DATETIME(6) NULL, ADD document_revision INT NOT NULL DEFAULT 1,
 ADD authorization_revision INT NOT NULL DEFAULT 1, ADD error_code VARCHAR(64) NULL,
 ADD lineage_json JSON NULL, ADD UNIQUE KEY uk_doc_owner (doc_id,user_id),
 ADD KEY idx_docs_purpose (user_id,purpose,deleted_at);
CREATE TABLE IF NOT EXISTS kb_document_versions (
 version_id VARCHAR(64) PRIMARY KEY, doc_id VARCHAR(64) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 source_sha256 CHAR(64) NOT NULL, storage_key VARCHAR(255) NOT NULL,
 file_type VARCHAR(16) NOT NULL, file_bytes INT NOT NULL,
 created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_version_owner (version_id,doc_id,owner_id),
 FOREIGN KEY (doc_id,owner_id) REFERENCES kb_documents(doc_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS kb_index_builds (
 build_id VARCHAR(64) PRIMARY KEY, doc_id VARCHAR(64) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 version_id VARCHAR(64) NOT NULL, namespace VARCHAR(128) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'building',
 parse_artifact_id VARCHAR(80) NULL, canonical_artifact_key VARCHAR(500) NULL,
 index_profile_id VARCHAR(64) NOT NULL, index_profile_hash CHAR(64) NULL,
 manifest_json JSON NULL, published_attempt_id VARCHAR(64) NULL, node_count INT NOT NULL DEFAULT 0,
 expected_document_revision INT NOT NULL, lease_token VARCHAR(64) NULL,
 created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_build_owner (build_id,doc_id,owner_id,version_id),
 FOREIGN KEY (version_id,doc_id,owner_id) REFERENCES kb_document_versions(version_id,doc_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- @index kb_documents fk_active_version
ALTER TABLE kb_documents ADD CONSTRAINT fk_active_version
 FOREIGN KEY (active_version_id,doc_id,user_id) REFERENCES kb_document_versions(version_id,doc_id,owner_id);
-- @index kb_documents fk_active_build
ALTER TABLE kb_documents ADD CONSTRAINT fk_active_build
 FOREIGN KEY (active_build_id,doc_id,user_id,active_version_id) REFERENCES kb_index_builds(build_id,doc_id,owner_id,version_id);
CREATE TABLE IF NOT EXISTS kb_nodes (
 node_id VARCHAR(80) PRIMARY KEY, build_id VARCHAR(64) NOT NULL, attempt_id VARCHAR(64) NOT NULL,
 doc_id VARCHAR(64) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL, version_id VARCHAR(64) NOT NULL,
 parent_id VARCHAR(80) NULL, text_hash CHAR(64) NOT NULL, storage_key VARCHAR(500) NOT NULL,
 locator_json JSON NOT NULL, UNIQUE KEY uk_node_attempt (node_id,build_id,attempt_id),
 FOREIGN KEY (build_id,doc_id,owner_id,version_id) REFERENCES kb_index_builds(build_id,doc_id,owner_id,version_id),
 FOREIGN KEY (parent_id,build_id,attempt_id) REFERENCES kb_nodes(node_id,build_id,attempt_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS rag_runs (
 run_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL, mode VARCHAR(24) NOT NULL,
 namespace VARCHAR(128) NOT NULL, pipeline_hash CHAR(64) NOT NULL, manifest_json JSON NOT NULL,
 status VARCHAR(24) NOT NULL, evidence_artifact_key VARCHAR(500) NULL, evidence_hash CHAR(64) NULL,
 debug_artifact_key VARCHAR(500) NULL, debug_hash CHAR(64) NULL, debug_expires_at DATETIME(6) NULL,
 usage_json JSON NULL, created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
