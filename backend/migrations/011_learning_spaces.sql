-- Learning IDs use binary collation. Legacy document IDs retain their parent collation.
-- Both revision pointers are filled before the create transaction commits.
CREATE TABLE IF NOT EXISTS learning_spaces (
 space_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 title VARCHAR(80) NOT NULL, timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
 status VARCHAR(24) NOT NULL DEFAULT 'active', active_scope_revision INT NULL,
 title_scope_revision INT NULL, revision INT NOT NULL DEFAULT 1,
 idempotency_key VARCHAR(128) NULL, request_hash CHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_space_owner (space_id,owner_id),
 UNIQUE KEY uk_learning_space_create (owner_id,idempotency_key),
 KEY idx_learning_space_list (owner_id,status,updated_at,space_id),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT ck_learning_space_status CHECK (status IN ('active','archived')),
 CONSTRAINT ck_learning_space_revision CHECK (revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Scope JSON and fingerprint are immutable source facts, not the current catalog.
CREATE TABLE IF NOT EXISTS learning_scope_revisions (
 space_id VARCHAR(64) NOT NULL, revision INT NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 scope_json JSON NOT NULL, scope_fingerprint CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (space_id,revision),
 UNIQUE KEY uk_learning_scope_owner (space_id,revision,owner_id),
 FOREIGN KEY (space_id,owner_id) REFERENCES learning_spaces(space_id,owner_id),
 CONSTRAINT ck_learning_scope_revision CHECK (revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- @index learning_spaces fk_learning_active_scope
ALTER TABLE learning_spaces ADD CONSTRAINT fk_learning_active_scope
 FOREIGN KEY (space_id,active_scope_revision,owner_id)
 REFERENCES learning_scope_revisions(space_id,revision,owner_id);
-- @index learning_spaces fk_learning_title_scope
ALTER TABLE learning_spaces ADD CONSTRAINT fk_learning_title_scope
 FOREIGN KEY (space_id,title_scope_revision,owner_id)
 REFERENCES learning_scope_revisions(space_id,revision,owner_id);

CREATE TABLE IF NOT EXISTS learning_scope_sources (
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 doc_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 document_version_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 parse_artifact_id VARCHAR(80) COLLATE utf8mb4_unicode_ci NOT NULL,
 index_build_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 authorization_revision INT NOT NULL, source_sha256 CHAR(64) NOT NULL,
 canonical_text_hash CHAR(64) NOT NULL,
 section_catalog_revision VARCHAR(80) NULL, section_ids_json JSON NOT NULL,
 PRIMARY KEY (space_id,scope_revision,doc_id),
 KEY idx_learning_scope_source_owner (owner_id,doc_id,document_version_id,authorization_revision),
 KEY idx_learning_scope_source_build (owner_id,doc_id,index_build_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 FOREIGN KEY (index_build_id,doc_id,owner_id,document_version_id)
  REFERENCES kb_index_builds(build_id,doc_id,owner_id,version_id),
 CONSTRAINT ck_learning_source_authorization CHECK (authorization_revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_goals (
 goal_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL, title VARCHAR(80) NOT NULL,
 deadline DATE NULL, daily_minutes INT NOT NULL DEFAULT 30,
 status VARCHAR(24) NOT NULL DEFAULT 'planned', revision INT NOT NULL DEFAULT 1,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_goal_space_owner (goal_id,space_id,owner_id),
 KEY idx_learning_goals (owner_id,space_id,status,goal_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_goal_minutes CHECK (daily_minutes BETWEEN 5 AND 240),
 CONSTRAINT ck_learning_goal_status CHECK (status IN ('planned','active','completed','paused')),
 CONSTRAINT ck_learning_goal_revision CHECK (revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_units (
 unit_id VARCHAR(64) PRIMARY KEY, goal_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, space_id VARCHAR(64) NOT NULL,
 scope_revision INT NOT NULL, title VARCHAR(80) NOT NULL,
 section_selection_json JSON NOT NULL, position INT NOT NULL DEFAULT 0,
 status VARCHAR(24) NOT NULL DEFAULT 'planned', revision INT NOT NULL DEFAULT 1,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_unit_space_owner (unit_id,space_id,owner_id),
 UNIQUE KEY uk_learning_unit_position (goal_id,position),
 FOREIGN KEY (goal_id,space_id,owner_id) REFERENCES learning_goals(goal_id,space_id,owner_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_unit_position CHECK (position >= 0),
 CONSTRAINT ck_learning_unit_status CHECK (status IN ('planned','active','completed','paused')),
 CONSTRAINT ck_learning_unit_revision CHECK (revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- scope_revision records title provenance. Bindings may use later authorized scopes.
CREATE TABLE IF NOT EXISTS learning_concepts (
 concept_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL, title VARCHAR(80) NOT NULL,
 revision INT NOT NULL DEFAULT 1,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_concept_space_owner (concept_id,space_id,owner_id),
 KEY idx_learning_concepts (owner_id,space_id,concept_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_concept_revision CHECK (revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
