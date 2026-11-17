-- =============================================================================
-- NiFi IoT DataHub - MariaDB schema (runs on first container boot)
-- Two roles for the same DB:
--   1. SOURCE : device_registry is read by NiFi over JDBC
--               (ExecuteSQL / QueryDatabaseTable) to enrich incoming telemetry.
--   2. SINK   : telemetry_enriched + ingest_audit + alerts are written by NiFi
--               over JDBC (PutDatabaseRecord / PutSQL).
-- =============================================================================

-- --------------------------------------------------------------------------
-- Device registry (JDBC SOURCE - joined against every telemetry event)
-- --------------------------------------------------------------------------
CREATE TABLE device_registry (
    device_id     VARCHAR(64) PRIMARY KEY,
    device_type   VARCHAR(32)  NOT NULL,          -- temperature | gateway
    site_name     VARCHAR(64)  NOT NULL,
    latitude      DECIMAL(9,6) NOT NULL,          -- used by the weather enrichment flow
    longitude     DECIMAL(9,6) NOT NULL,
    firmware      VARCHAR(32),
    registered_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO device_registry (device_id, device_type, site_name, latitude, longitude, firmware) VALUES
    ('temp-001', 'temperature', 'Warehouse A', 48.8566,   2.3522,  '1.4.2'),
    ('temp-002', 'temperature', 'Warehouse B', 51.5074,  -0.1278,  '1.4.2'),
    ('gw-001',   'gateway',     'HQ Rooftop',  47.3769,   8.5417,  '3.1.0');

-- --------------------------------------------------------------------------
-- Enriched telemetry (JDBC SINK - written by PutDatabaseRecord, JSON -> SQL)
-- --------------------------------------------------------------------------
CREATE TABLE telemetry_enriched (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id     VARCHAR(64)   NOT NULL,
    metric        VARCHAR(64)   NOT NULL,         -- e.g. temperature_c, humidity_pct
    value         DECIMAL(12,4) NOT NULL,
    event_time    DATETIME      NOT NULL,
    site_name     VARCHAR(64),
    outdoor_temp  DECIMAL(8,2),                   -- from the weather REST API
    weather_code  INTEGER,
    ingested_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Alert log (JDBC SINK - written by the threshold routing branch)
-- --------------------------------------------------------------------------
CREATE TABLE alerts (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id   VARCHAR(64) NOT NULL,
    rule        VARCHAR(64) NOT NULL,             -- e.g. temp_above_30
    metric      VARCHAR(64),
    value       DECIMAL(12,4),
    event_time  DATETIME,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Audit trail for file ingestions (CSV / LOG / binary), written by NiFi
-- --------------------------------------------------------------------------
CREATE TABLE ingest_audit (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    filename     VARCHAR(255) NOT NULL,
    media_type   VARCHAR(64),                     -- text/csv, text/plain, application/octet-stream ...
    device_id    VARCHAR(64),
    byte_size    BIGINT,
    archive_path TEXT,                            -- where PutFile/PutSFTP stored it
    received_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_telemetry_device_time ON telemetry_enriched (device_id, event_time DESC);
CREATE INDEX idx_alerts_created ON alerts (created_at DESC);

-- --------------------------------------------------------------------------
-- Read-only user for Grafana (datasource: mariadb-iotdb)
-- NOTE: this init script only runs on FIRST MariaDB boot; on an existing
-- volume apply it manually once (see README).
-- --------------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'grafana'@'%' IDENTIFIED BY 'grafana_ro_2026';
GRANT SELECT ON iotdb.* TO 'grafana'@'%';
FLUSH PRIVILEGES;
