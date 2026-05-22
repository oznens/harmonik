-- terminalMiraz veritabanı şeması
-- Faz 1: klines tablosu
-- Faz 2: setups tablosu

CREATE TABLE IF NOT EXISTS klines (
    symbol       TEXT    NOT NULL,
    interval     TEXT    NOT NULL,
    open_time    INTEGER NOT NULL,  -- ms
    close_time   INTEGER NOT NULL,  -- ms
    open         REAL    NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    close        REAL    NOT NULL,
    volume       REAL    NOT NULL,
    quote_volume REAL,
    PRIMARY KEY (symbol, interval, open_time)
);

CREATE INDEX IF NOT EXISTS idx_klines_lookup
    ON klines (symbol, interval, open_time DESC);


-- Tespit edilen harmonik formasyon + işlem seviyeleri.
-- (symbol, interval, pattern_name, X-A-B-C-D pivot zamanları) tekil.
CREATE TABLE IF NOT EXISTS setups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT    NOT NULL,
    interval     TEXT    NOT NULL,
    pattern_name TEXT    NOT NULL,
    direction    TEXT    NOT NULL,  -- 'bull' veya 'bear'

    -- 5 pivot (open_time + price)
    x_time  INTEGER NOT NULL, x_price REAL NOT NULL,
    a_time  INTEGER NOT NULL, a_price REAL NOT NULL,
    b_time  INTEGER NOT NULL, b_price REAL NOT NULL,
    c_time  INTEGER NOT NULL, c_price REAL NOT NULL,
    d_time  INTEGER NOT NULL, d_price REAL NOT NULL,

    -- oran ölçümleri
    b_ratio         REAL NOT NULL,
    c_ratio         REAL NOT NULL,
    d_ratio         REAL NOT NULL,
    bc_proj         REAL NOT NULL,
    cd_ab_ratio     REAL NOT NULL,
    ab_cd_equivalent INTEGER NOT NULL,  -- 0/1

    -- PRZ + işlem seviyeleri
    prz_low        REAL NOT NULL,
    prz_high       REAL NOT NULL,
    prz_components TEXT NOT NULL,  -- JSON
    entry          REAL NOT NULL,
    stop           REAL NOT NULL,
    tp1            REAL NOT NULL,
    tp2            REAL NOT NULL,

    detected_at    INTEGER NOT NULL,

    -- Faz 4: Q skoru + HTF/LTF
    q_score        INTEGER,
    q_category     TEXT,
    q_components   TEXT,                  -- JSON
    htf_interval   TEXT,
    htf_trend      TEXT,
    htf_aligned    INTEGER,               -- 0/1/NULL (NULL = neutral veya HTF yok)
    elenen         INTEGER NOT NULL DEFAULT 0,

    UNIQUE (symbol, interval, pattern_name, x_time, a_time, b_time, c_time, d_time)
);

CREATE INDEX IF NOT EXISTS idx_setups_lookup
    ON setups (symbol, interval, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_setups_d_time
    ON setups (symbol, interval, d_time DESC);


-- Setup yaşam döngüsü: setup başına tek satır, durum değişince güncellenir.
-- state: 'Aday', 'Aktif', 'TP', 'STOP', 'ZI', 'EO'
CREATE TABLE IF NOT EXISTS setup_lifecycle (
    setup_id          INTEGER PRIMARY KEY,
    state             TEXT NOT NULL,
    state_changed_at  INTEGER NOT NULL,
    entered_at        INTEGER,   -- Aktif başlangıcı (entry tetiklendiği an)
    exited_at         INTEGER,   -- terminal durum (TP/STOP/ZI/EO) zamanı
    exit_reason       TEXT,
    notified_aday     INTEGER NOT NULL DEFAULT 0,
    notified_aktif    INTEGER NOT NULL DEFAULT 0,
    notified_exit     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (setup_id) REFERENCES setups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_state ON setup_lifecycle (state);


-- Tüm durum geçişleri için audit log.
CREATE TABLE IF NOT EXISTS setup_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id      INTEGER NOT NULL,
    event_time    INTEGER NOT NULL,  -- ms (tetikleyen mum open_time)
    prev_state    TEXT,
    new_state     TEXT NOT NULL,
    trigger_price REAL,
    notes         TEXT,
    FOREIGN KEY (setup_id) REFERENCES setups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_setup
    ON setup_events (setup_id, event_time);
