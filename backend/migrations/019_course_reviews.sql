-- The complete ALTER is guarded so a crash after DDL remains resumable.
-- @index learning_course_quiz_links ck_course_quiz_kind_v2
ALTER TABLE learning_course_quiz_links
 DROP CHECK ck_course_quiz_kind,
 DROP CHECK ck_course_quiz_parent,
 ADD CONSTRAINT ck_course_quiz_kind_v2 CHECK (kind IN ('initial','review','scheduled_review')),
 ADD CONSTRAINT ck_course_quiz_parent_v2 CHECK (
  (kind IN ('initial','scheduled_review') AND parent_link_id IS NULL)
  OR (kind='review' AND parent_link_id IS NOT NULL));

-- @index learning_course_quiz_links uk_course_quiz_identity
ALTER TABLE learning_course_quiz_links ADD UNIQUE KEY uk_course_quiz_identity
 (link_id,course_id,lesson_id,owner_id,content_version);
-- @index learning_course_quiz_links fk_course_quiz_parent_version
ALTER TABLE learning_course_quiz_links ADD CONSTRAINT fk_course_quiz_parent_version
 FOREIGN KEY (parent_link_id,course_id,lesson_id,owner_id,content_version)
 REFERENCES learning_course_quiz_links(link_id,course_id,lesson_id,owner_id,content_version);

CREATE TABLE IF NOT EXISTS learning_course_review_events (
 event_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 course_id VARCHAR(64) NOT NULL, lesson_id VARCHAR(64) NOT NULL,
 content_version INT NOT NULL, link_id VARCHAR(64) NOT NULL,
 quiz_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 settled_at DATETIME(6) NOT NULL, timezone VARCHAR(64) NOT NULL,
 rule_version VARCHAR(64) NOT NULL DEFAULT 'review-rules-v1',
 processed_at DATETIME(6) NULL, skipped_reason VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_review_event_quiz (owner_id,quiz_id),
 UNIQUE KEY uk_course_review_event_owner (event_id,owner_id),
 KEY idx_course_review_event_pending (processed_at,settled_at,quiz_id),
 FOREIGN KEY (link_id,course_id,lesson_id,owner_id,content_version)
  REFERENCES learning_course_quiz_links(link_id,course_id,lesson_id,owner_id,content_version),
 FOREIGN KEY (quiz_id,owner_id) REFERENCES quiz_sessions(quiz_id,user_id),
 CONSTRAINT ck_course_review_event_version CHECK (content_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_review_states (
 owner_id BIGINT UNSIGNED NOT NULL, course_id VARCHAR(64) NOT NULL,
 lesson_id VARCHAR(64) NOT NULL, content_version INT NOT NULL,
 schedule_seq INT NOT NULL DEFAULT 0, revision INT NOT NULL DEFAULT 0,
 stage INT NOT NULL DEFAULT 0,
 last_activity_local_date DATE NULL, last_success_local_date DATE NULL,
 last_question_versions_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
 seen_question_versions_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
 due_at DATETIME(6) NULL, last_settled_at DATETIME(6) NULL,
 last_quiz_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 last_event_id VARCHAR(64) NULL,
 rule_version VARCHAR(64) NOT NULL DEFAULT 'review-rules-v1',
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (owner_id,lesson_id,content_version),
 FOREIGN KEY (lesson_id,course_id,owner_id)
  REFERENCES learning_course_lessons(lesson_id,course_id,owner_id),
 FOREIGN KEY (last_event_id,owner_id) REFERENCES learning_course_review_events(event_id,owner_id),
 CONSTRAINT ck_course_review_state_version CHECK (content_version >= 1 AND schedule_seq >= 0 AND revision >= 0),
 CONSTRAINT ck_course_review_state_stage CHECK (stage BETWEEN 0 AND 4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_reviews (
 review_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 course_id VARCHAR(64) NOT NULL, lesson_id VARCHAR(64) NOT NULL,
 content_version INT NOT NULL, schedule_seq INT NOT NULL,
 due_at DATETIME(6) NOT NULL, timezone VARCHAR(64) NOT NULL,
 rule_version VARCHAR(64) NOT NULL DEFAULT 'review-rules-v1',
 reason VARCHAR(80) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'scheduled',
 revision INT NOT NULL DEFAULT 1, is_current TINYINT NULL DEFAULT 1,
 active_link_id VARCHAR(64) NULL, completed_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_review_owner (review_id,owner_id),
 UNIQUE KEY uk_course_review_schedule (owner_id,lesson_id,content_version,schedule_seq),
 UNIQUE KEY uk_course_review_current (owner_id,lesson_id,content_version,is_current),
 UNIQUE KEY uk_course_review_active_link (owner_id,active_link_id),
 KEY idx_course_review_due (owner_id,is_current,due_at,review_id),
 FOREIGN KEY (owner_id,lesson_id,content_version)
  REFERENCES learning_course_review_states(owner_id,lesson_id,content_version),
 FOREIGN KEY (lesson_id,course_id,owner_id)
  REFERENCES learning_course_lessons(lesson_id,course_id,owner_id),
 FOREIGN KEY (active_link_id,course_id,lesson_id,owner_id,content_version)
  REFERENCES learning_course_quiz_links(link_id,course_id,lesson_id,owner_id,content_version),
 CONSTRAINT ck_course_review_revision CHECK (content_version >= 1 AND schedule_seq >= 1 AND revision >= 1),
 CONSTRAINT ck_course_review_current CHECK (is_current IS NULL OR is_current=1),
 CONSTRAINT ck_course_review_status CHECK (status IN ('scheduled','generating','ready','failed','completed','superseded','source_revoked')),
 CONSTRAINT ck_course_review_binding CHECK (status NOT IN ('generating','ready','failed') OR active_link_id IS NOT NULL),
 CONSTRAINT ck_course_review_completed CHECK (status<>'completed' OR completed_at IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
