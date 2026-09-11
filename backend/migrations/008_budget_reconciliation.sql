CREATE TABLE IF NOT EXISTS budget_reconciliations (
 call_id VARCHAR(128) NOT NULL, resource_type VARCHAR(32) NOT NULL,
 actual_cny DECIMAL(18,6) NOT NULL, evidence_sha256 CHAR(64) NOT NULL,
 receipt_reference VARCHAR(256) NOT NULL, operator VARCHAR(128) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (call_id,resource_type),
 FOREIGN KEY (call_id) REFERENCES provider_calls(call_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
