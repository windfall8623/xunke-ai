-- Per-user LLM provider credentials, API keys are AES-GCM ciphertext only.
CREATE TABLE user_llm_configs (
    owner_id BIGINT UNSIGNED PRIMARY KEY,
    provider VARCHAR(24) NOT NULL,
    model VARCHAR(128) NOT NULL,
    base_url VARCHAR(512) NOT NULL,
    api_key_cipher TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_user_llm_owner FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;
