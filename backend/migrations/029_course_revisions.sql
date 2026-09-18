-- Course revision requests and immutable lesson snapshots (B06)
CREATE TABLE IF NOT EXISTS learning_course_revision_requests (
 revision_id VARCHAR(64) PRIMARY KEY,
 course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'preview',
 selection_json JSON NOT NULL,
 impact_json JSON NULL,
 candidates_json JSON NULL,
 instruction TEXT NULL,
 expected_course_revision INT NOT NULL,
 expected_criteria_revision INT NOT NULL,
 error_code VARCHAR(48) NULL,
 revision INT NOT NULL DEFAULT 1,
 idempotency_key VARCHAR(128) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_revision_owner (revision_id,owner_id),
 UNIQUE KEY uk_course_revision_idempotency (owner_id,idempotency_key),
 KEY idx_course_revision_course (owner_id,course_id,created_at),
 FOREIGN KEY (course_id,owner_id) REFERENCES learning_courses(course_id,owner_id),
 CONSTRAINT ck_course_revision_status CHECK (status IN ('preview','generating','ready','failed','cancelled','applied')),
 CONSTRAINT ck_course_revision_expected CHECK (expected_course_revision>=1 AND expected_criteria_revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_lesson_snapshots (
 snapshot_id VARCHAR(64) PRIMARY KEY,
 lesson_id VARCHAR(64) NOT NULL,
 course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 content_version INT NOT NULL,
 content_json JSON NULL,
 evidence_json JSON NULL,
 read_at DATETIME(6) NULL,
 archived_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_lesson_snapshot (lesson_id,owner_id,content_version),
 KEY idx_course_snapshot_course (owner_id,course_id,lesson_id,content_version),
 FOREIGN KEY (lesson_id,course_id,owner_id)
  REFERENCES learning_course_lessons(lesson_id,course_id,owner_id),
 CONSTRAINT ck_course_snapshot_version CHECK (content_version>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
