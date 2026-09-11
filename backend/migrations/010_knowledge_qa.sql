CREATE TABLE IF NOT EXISTS qa_sessions (
 session_id VARCHAR(64) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL,
 title VARCHAR(80) NOT NULL, scope_revision INT NOT NULL DEFAULT 1,
 next_sequence INT NOT NULL DEFAULT 1, active_task_id VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_qa_session_owner (session_id,owner_id),
 KEY idx_qa_owner_updated (owner_id,updated_at),
 FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_scope_revisions (
 session_id VARCHAR(64) NOT NULL, revision INT NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 scope_json JSON NOT NULL, scope_fingerprint CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (session_id,revision),
 FOREIGN KEY (session_id,owner_id) REFERENCES qa_sessions(session_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_messages (
 message_id VARCHAR(64) PRIMARY KEY, session_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, sequence INT NOT NULL,
 role VARCHAR(16) NOT NULL, content TEXT NOT NULL, scope_revision INT NOT NULL,
 task_id VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL,
 error_code VARCHAR(64) NULL, started_at DATETIME(6) NULL, finished_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_qa_message_sequence (session_id,sequence),
 UNIQUE KEY uk_qa_task_role (task_id,role),
 FOREIGN KEY (session_id,owner_id) REFERENCES qa_sessions(session_id,owner_id),
 FOREIGN KEY (session_id,scope_revision) REFERENCES qa_scope_revisions(session_id,revision),
 FOREIGN KEY (task_id) REFERENCES quiz_tasks(task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_answers (
 answer_id VARCHAR(64) PRIMARY KEY, session_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, message_id VARCHAR(64) NOT NULL,
 task_id VARCHAR(64) NOT NULL, scope_revision INT NOT NULL,
 artifact_json JSON NULL, artifact_hash CHAR(64) NOT NULL, usage_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_qa_answer_message (message_id), UNIQUE KEY uk_qa_answer_task (task_id),
 FOREIGN KEY (session_id,owner_id) REFERENCES qa_sessions(session_id,owner_id),
 FOREIGN KEY (message_id) REFERENCES qa_messages(message_id),
 FOREIGN KEY (task_id) REFERENCES quiz_tasks(task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_answer_sources (
 answer_id VARCHAR(64) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 doc_id VARCHAR(64) NOT NULL, document_version_id VARCHAR(64) NOT NULL,
 authorization_revision INT NOT NULL,
 PRIMARY KEY (answer_id,doc_id,document_version_id),
 KEY idx_qa_source_owner (owner_id,doc_id),
 FOREIGN KEY (answer_id) REFERENCES qa_answers(answer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_feedback (
 feedback_id VARCHAR(64) PRIMARY KEY, answer_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, rating VARCHAR(16) NOT NULL,
 reason VARCHAR(24) NULL, comment TEXT NOT NULL, evaluation_consent BOOLEAN NOT NULL DEFAULT FALSE,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_qa_feedback_owner (answer_id,owner_id),
 FOREIGN KEY (answer_id) REFERENCES qa_answers(answer_id),
 FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
