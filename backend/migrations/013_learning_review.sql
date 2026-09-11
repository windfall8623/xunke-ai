CREATE TABLE IF NOT EXISTS learner_concept_state (
 owner_id BIGINT UNSIGNED NOT NULL, space_id VARCHAR(64) NOT NULL,
 concept_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 rule_version VARCHAR(64) NOT NULL DEFAULT 'review-rules-v1', evidence_count INT NOT NULL DEFAULT 0,
 stage INT NOT NULL DEFAULT 0, last_activity_local_date DATE NULL, last_success_local_date DATE NULL,
 last_question_versions_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
 seen_question_versions_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
 rule_due_at DATETIME(6) NULL, due_at DATETIME(6) NULL, override_due_at DATETIME(6) NULL,
 paused BOOLEAN NOT NULL DEFAULT FALSE, revision INT NOT NULL DEFAULT 0,
 assessment_set_hash CHAR(64) NULL, last_completion_id VARCHAR(64) NULL,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (owner_id,space_id,concept_id,scope_revision),
 FOREIGN KEY (concept_id,space_id,owner_id) REFERENCES learning_concepts(concept_id,space_id,owner_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 FOREIGN KEY (last_completion_id,owner_id) REFERENCES learning_activity_completions(completion_id,owner_id),
 CONSTRAINT ck_learning_state_stage CHECK (stage BETWEEN 0 AND 4),
 CONSTRAINT ck_learning_state_counts CHECK (evidence_count >= 0 AND revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- A nullable current slot admits many historical occurrences but at most one current one.
-- Rebuilding rule_due_at never clears manual overrides, pause state or a running binding.
CREATE TABLE IF NOT EXISTS review_tasks (
 review_task_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 space_id VARCHAR(64) NOT NULL, concept_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 schedule_seq INT NOT NULL, revision INT NOT NULL DEFAULT 1, is_current TINYINT NULL DEFAULT 1,
 rule_version VARCHAR(64) NOT NULL DEFAULT 'review-rules-v1',
 status VARCHAR(24) NOT NULL DEFAULT 'scheduled', paused BOOLEAN NOT NULL DEFAULT FALSE,
 rule_due_at DATETIME(6) NULL, due_at DATETIME(6) NOT NULL, override_due_at DATETIME(6) NULL,
 task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 origin_kind VARCHAR(16) NULL, origin_id VARCHAR(64) NULL,
 claimed_at DATETIME(6) NULL, completed_at DATETIME(6) NULL, last_error_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_review_owner (review_task_id,owner_id),
 UNIQUE KEY uk_learning_review_occurrence (owner_id,space_id,concept_id,scope_revision,schedule_seq),
 UNIQUE KEY uk_learning_review_current (owner_id,space_id,concept_id,scope_revision,is_current),
 KEY idx_learning_review_due (owner_id,is_current,paused,status,due_at,review_task_id),
 KEY idx_learning_review_origin (owner_id,origin_kind,origin_id),
 FOREIGN KEY (owner_id,space_id,concept_id,scope_revision)
  REFERENCES learner_concept_state(owner_id,space_id,concept_id,scope_revision),
 FOREIGN KEY (task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 CONSTRAINT ck_learning_review_revision CHECK (schedule_seq >= 1 AND revision >= 1),
 CONSTRAINT ck_learning_review_current CHECK (is_current IS NULL OR is_current=1),
 CONSTRAINT ck_learning_review_status CHECK (status IN ('scheduled','claimed','running','completed','failed','cancelled')),
 CONSTRAINT ck_learning_review_origin CHECK (origin_kind IS NULL OR origin_kind IN ('quiz','practice')),
 CONSTRAINT ck_learning_review_origin_pair CHECK (origin_id IS NULL OR origin_kind IS NOT NULL),
 CONSTRAINT ck_learning_review_claim CHECK (status NOT IN ('claimed','running') OR (task_id IS NOT NULL AND is_current IS NOT NULL AND is_current=1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Append-only manual operations and claim history shared by quiz and practice.
CREATE TABLE IF NOT EXISTS review_task_events (
 event_id VARCHAR(64) PRIMARY KEY, review_task_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, actor_id BIGINT UNSIGNED NULL,
 event_type VARCHAR(24) NOT NULL, revision INT NOT NULL,
 task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 origin_kind VARCHAR(16) NULL, origin_id VARCHAR(64) NULL,
 previous_due_at DATETIME(6) NULL, due_at DATETIME(6) NULL,
 idempotency_key VARCHAR(128) NULL, request_hash CHAR(64) NULL, payload_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_review_event_revision (review_task_id,revision),
 UNIQUE KEY uk_learning_review_event_key (owner_id,review_task_id,idempotency_key),
 FOREIGN KEY (review_task_id,owner_id) REFERENCES review_tasks(review_task_id,owner_id),
 FOREIGN KEY (task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 FOREIGN KEY (actor_id) REFERENCES users(id),
 CONSTRAINT ck_learning_review_event_actor CHECK (actor_id IS NULL OR actor_id=owner_id),
 CONSTRAINT ck_learning_review_event_revision CHECK (revision >= 1),
 CONSTRAINT ck_learning_review_event_origin CHECK (origin_kind IS NULL OR origin_kind IN ('quiz','practice')),
 CONSTRAINT ck_learning_review_event_kind CHECK (event_type IN ('scheduled','rule_updated','pause','resume','reschedule','claim','retry','failed','cancelled','completed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
