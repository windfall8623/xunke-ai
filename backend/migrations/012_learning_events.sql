-- Additional context is outside immutable legacy QuizArtifact/CoverageTarget JSON.
CREATE TABLE IF NOT EXISTS learning_quiz_contexts (
 quiz_id VARCHAR(64) COLLATE utf8mb4_unicode_ci PRIMARY KEY,
 owner_id BIGINT UNSIGNED NOT NULL, space_id VARCHAR(64) NOT NULL,
 scope_revision INT NOT NULL, unit_id VARCHAR(64) NULL,
 source_scope_json JSON NOT NULL, scope_fingerprint CHAR(64) NOT NULL,
 objectives_json JSON NOT NULL, coverage_plan_json JSON NOT NULL,
 target_concepts_json JSON NOT NULL, origin_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_quiz_owner (quiz_id,owner_id),
 KEY idx_learning_quiz_space (owner_id,space_id,scope_revision),
 FOREIGN KEY (quiz_id,owner_id) REFERENCES quiz_sessions(quiz_id,user_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 FOREIGN KEY (unit_id,space_id,owner_id) REFERENCES learning_units(unit_id,space_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Polymorphic origins are checked against their real owned quiz/practice parent by services.
CREATE TABLE IF NOT EXISTS question_concepts (
 owner_id BIGINT UNSIGNED NOT NULL, origin_kind VARCHAR(16) NOT NULL,
 origin_id VARCHAR(64) NOT NULL, question_id VARCHAR(64) NOT NULL,
 question_version CHAR(64) NOT NULL, concept_id VARCHAR(64) NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 coverage_target_id VARCHAR(256) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (owner_id,origin_kind,origin_id,question_id,concept_id),
 KEY idx_learning_question_concept (owner_id,space_id,concept_id,scope_revision),
 FOREIGN KEY (concept_id,space_id,owner_id) REFERENCES learning_concepts(concept_id,space_id,owner_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_binding_origin CHECK (origin_kind IN ('quiz','practice'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_attempts (
 attempt_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 origin_kind VARCHAR(16) NOT NULL, origin_id VARCHAR(64) NOT NULL,
 question_id VARCHAR(64) NOT NULL, question_version CHAR(64) NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 answer_kind VARCHAR(24) NOT NULL, answer_json JSON NULL, response_hash CHAR(64) NOT NULL,
 duration_ms INT NOT NULL DEFAULT 0, help_usage VARCHAR(16) NOT NULL DEFAULT 'unknown',
 provenance VARCHAR(24) NOT NULL DEFAULT 'native', occurred_at DATETIME(6) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_attempt_owner (attempt_id,owner_id),
 UNIQUE KEY uk_learning_attempt_first (owner_id,origin_kind,origin_id,question_id),
 KEY idx_learning_attempt_history (owner_id,space_id,occurred_at,attempt_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_attempt_origin CHECK (origin_kind IN ('quiz','practice')),
 CONSTRAINT ck_learning_attempt_kind CHECK (answer_kind IN ('single','multiple','judge','cloze','numeric','short_answer')),
 CONSTRAINT ck_learning_attempt_duration CHECK (duration_ms >= 0),
 CONSTRAINT ck_learning_attempt_help CHECK (help_usage IN ('none','hints','unknown')),
 CONSTRAINT ck_learning_attempt_provenance CHECK (provenance IN ('native','legacy_import'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Append-only grading facts. Bind the serializer's exact Decimal text, never a SQL numeric cast.
-- The canonical scientific form has a one-digit coefficient and a negative exponent.
CREATE TABLE IF NOT EXISTS assessment_records (
 assessment_id VARCHAR(64) PRIMARY KEY, attempt_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, revision INT NOT NULL,
 status VARCHAR(24) NOT NULL, score LONGTEXT CHARACTER SET ascii COLLATE ascii_bin NULL,
 source VARCHAR(24) NOT NULL, confirmation VARCHAR(24) NOT NULL,
 grader_version VARCHAR(64) NOT NULL, rubric_version VARCHAR(64) NOT NULL, rubric_hash CHAR(64) NOT NULL,
 feedback TEXT NULL, evidence_refs_json JSON NULL, criterion_results_json JSON NULL,
 supersedes_assessment_id VARCHAR(64) NULL, independent_eligible BOOLEAN NOT NULL DEFAULT FALSE,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_assessment_revision (attempt_id,revision),
 UNIQUE KEY uk_learning_assessment_owner (assessment_id,attempt_id,owner_id),
 UNIQUE KEY uk_learning_assessment_head (assessment_id,attempt_id,owner_id,revision),
 KEY idx_learning_assessment_owner (owner_id,created_at,assessment_id),
 FOREIGN KEY (attempt_id,owner_id) REFERENCES learning_attempts(attempt_id,owner_id),
 FOREIGN KEY (supersedes_assessment_id,attempt_id,owner_id)
  REFERENCES assessment_records(assessment_id,attempt_id,owner_id),
 CONSTRAINT ck_learning_assessment_revision CHECK (revision >= 1),
 CONSTRAINT ck_learning_assessment_status CHECK (status IN ('graded','needs_review','failed','cancelled')),
 CONSTRAINT ck_learning_assessment_source CHECK (source IN ('deterministic','model','human')),
 CONSTRAINT ck_learning_assessment_confirmation CHECK (confirmation IN ('confirmed','provisional')),
 CONSTRAINT ck_learning_assessment_score CHECK (
  (status='graded' AND score IS NOT NULL) OR (status<>'graded' AND score IS NULL AND confirmation='provisional')),
 CONSTRAINT ck_learning_assessment_score_text CHECK (score IS NULL OR
  REGEXP_LIKE(score,'^(0|1|0[.][0-9]+|1[.]0+|[1-9]([.][0-9]+)?E-[1-9][0-9]*)$','c')),
 CONSTRAINT ck_learning_assessment_deterministic CHECK (source<>'deterministic' OR (status='graded' AND confirmation='confirmed')),
 CONSTRAINT ck_learning_assessment_independent CHECK (independent_eligible=FALSE OR (status='graded' AND confirmation='confirmed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- CAS this mutable pointer under the attempt lock. Never update an assessment fact.
CREATE TABLE IF NOT EXISTS learning_assessment_heads (
 attempt_id VARCHAR(64) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 assessment_id VARCHAR(64) NOT NULL, revision INT NOT NULL,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (attempt_id,owner_id),
 FOREIGN KEY (attempt_id,owner_id) REFERENCES learning_attempts(attempt_id,owner_id),
 FOREIGN KEY (assessment_id,attempt_id,owner_id,revision)
  REFERENCES assessment_records(assessment_id,attempt_id,owner_id,revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_activity_completions (
 completion_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 origin_kind VARCHAR(16) NOT NULL, origin_id VARCHAR(64) NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 attempt_ids_json JSON NOT NULL, answer_set_hash CHAR(64) NOT NULL,
 completed_at DATETIME(6) NOT NULL, effective_timezone VARCHAR(64) NOT NULL,
 activity_local_date DATE NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_completion_origin (owner_id,origin_kind,origin_id),
 UNIQUE KEY uk_learning_completion_owner (completion_id,owner_id),
 KEY idx_learning_completion_history (owner_id,space_id,completed_at,origin_kind,origin_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_completion_origin CHECK (origin_kind IN ('quiz','practice')),
 CONSTRAINT ck_learning_completion_answers CHECK (JSON_TYPE(attempt_ids_json)='ARRAY' AND JSON_LENGTH(attempt_ids_json)>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_annotations (
 annotation_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 attempt_id VARCHAR(64) NOT NULL, author_id BIGINT UNSIGNED NOT NULL,
 kind VARCHAR(24) NOT NULL, payload_json JSON NULL,
 idempotency_key VARCHAR(128) NOT NULL, payload_hash CHAR(64) NOT NULL,
 independent_eligible BOOLEAN NOT NULL DEFAULT FALSE,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_annotation_key (owner_id,attempt_id,idempotency_key),
 FOREIGN KEY (attempt_id,owner_id) REFERENCES learning_attempts(attempt_id,owner_id),
 FOREIGN KEY (author_id) REFERENCES users(id),
 CONSTRAINT ck_learning_annotation_kind CHECK (kind IN ('self_review','wrong_reason')),
 CONSTRAINT ck_learning_annotation_author CHECK (author_id=owner_id),
 CONSTRAINT ck_learning_annotation_independent CHECK (independent_eligible=FALSE)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- @index quiz_tasks uk_learning_task_owner
ALTER TABLE quiz_tasks ADD UNIQUE KEY uk_learning_task_owner (task_id,user_id);

CREATE TABLE IF NOT EXISTS learning_outbox (
 event_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 event_type VARCHAR(40) NOT NULL, origin_kind VARCHAR(16) NOT NULL, origin_id VARCHAR(64) NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 attempt_id VARCHAR(64) NULL, assessment_id VARCHAR(64) NULL, completion_id VARCHAR(64) NULL,
 payload_json JSON NOT NULL, task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 published_at DATETIME(6) NULL, processed_at DATETIME(6) NULL,
 UNIQUE KEY uk_learning_outbox_owner (event_id,owner_id),
 UNIQUE KEY uk_learning_outbox_assessment (event_type,assessment_id),
 UNIQUE KEY uk_learning_outbox_completion (event_type,completion_id),
 KEY idx_learning_outbox_pending (processed_at,created_at,event_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 FOREIGN KEY (assessment_id,attempt_id,owner_id) REFERENCES assessment_records(assessment_id,attempt_id,owner_id),
 FOREIGN KEY (completion_id,owner_id) REFERENCES learning_activity_completions(completion_id,owner_id),
 FOREIGN KEY (task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 CONSTRAINT ck_learning_outbox_origin CHECK (origin_kind IN ('quiz','practice')),
 CONSTRAINT ck_learning_outbox_event CHECK (
  (event_type='learning_assessment' AND assessment_id IS NOT NULL AND attempt_id IS NOT NULL AND completion_id IS NULL)
  OR (event_type='learning_activity_completed' AND completion_id IS NOT NULL AND assessment_id IS NULL AND attempt_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_projection_receipts (
 receipt_id VARCHAR(64) PRIMARY KEY, event_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, completion_id VARCHAR(64) NOT NULL,
 origin_kind VARCHAR(16) NOT NULL, origin_id VARCHAR(64) NOT NULL,
 space_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 assessment_set_hash CHAR(64) NOT NULL, rule_version VARCHAR(64) NOT NULL DEFAULT 'review-rules-v1',
 projection_json JSON NOT NULL, projection_revision INT NOT NULL DEFAULT 1,
 projected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_projection_event (event_id),
 UNIQUE KEY uk_learning_projection_set (owner_id,origin_kind,origin_id,assessment_set_hash,rule_version),
 FOREIGN KEY (event_id,owner_id) REFERENCES learning_outbox(event_id,owner_id),
 FOREIGN KEY (completion_id,owner_id) REFERENCES learning_activity_completions(completion_id,owner_id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
  REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 CONSTRAINT ck_learning_projection_origin CHECK (origin_kind IN ('quiz','practice')),
 CONSTRAINT ck_learning_projection_revision CHECK (projection_revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
