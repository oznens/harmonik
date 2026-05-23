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
    source            TEXT NOT NULL DEFAULT 'live',  -- 'live' veya 'backtest'
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


-- ============================================================
-- Faz 5: Parite Karakter Tanıma Laboratuvarı
-- ============================================================

-- Her lab koşusu için tek satır.
CREATE TABLE IF NOT EXISTS karakter_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    INTEGER NOT NULL,
    finished_at   INTEGER,
    bars_per_pair INTEGER NOT NULL,
    symbols       TEXT,            -- JSON dizi
    intervals     TEXT,            -- JSON dizi
    sample_count  INTEGER,
    notes         TEXT
);

-- Her tek setup outcome'u için bir satır (lab içinde tespit edilen).
CREATE TABLE IF NOT EXISTS karakter_samples (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL,
    symbol         TEXT NOT NULL,
    interval       TEXT NOT NULL,
    pattern_name   TEXT NOT NULL,
    direction      TEXT NOT NULL,  -- 'bull'/'bear'
    d_time         INTEGER NOT NULL,
    d_price        REAL    NOT NULL,
    entry          REAL    NOT NULL,
    stop           REAL    NOT NULL,
    tp1            REAL    NOT NULL,
    q_score        INTEGER,
    outcome        TEXT NOT NULL,  -- 'TP','STOP','EO','ZI','Aday','Aktif'
    entered_at     INTEGER,        -- Aktif olduğu mum (open_time)
    exited_at      INTEGER,        -- terminal duruma geçtiği mum
    ambiguous      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES karakter_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_karakter_samples_lookup
    ON karakter_samples (symbol, interval, pattern_name, outcome);

-- Aggregate skor tablosu (sample'lardan computed). direction='all' tüm bull+bear,
-- direction='bull' veya 'bear' özel kırılım.
CREATE TABLE IF NOT EXISTS karakter_scores (
    symbol         TEXT NOT NULL,
    interval       TEXT NOT NULL,
    pattern_name   TEXT NOT NULL,
    direction      TEXT NOT NULL,
    sample_count   INTEGER NOT NULL,
    tp_count       INTEGER NOT NULL,
    stop_count     INTEGER NOT NULL,
    eo_count       INTEGER NOT NULL,
    zi_count       INTEGER NOT NULL,
    open_count     INTEGER NOT NULL,
    win_rate       REAL,
    karakter_score REAL,
    updated_at     INTEGER NOT NULL,
    PRIMARY KEY (symbol, interval, pattern_name, direction)
);

CREATE INDEX IF NOT EXISTS idx_karakter_scores_top
    ON karakter_scores (karakter_score DESC);


-- ============================================================
-- Faz 7: Learning Journal + Kiraz (AI notları)
-- ============================================================

CREATE TABLE IF NOT EXISTS journal_entries (
    date              TEXT PRIMARY KEY,  -- YYYY-MM-DD UTC
    detected_count    INTEGER NOT NULL,
    closed_count      INTEGER NOT NULL,
    tp_count          INTEGER NOT NULL,
    stop_count        INTEGER NOT NULL,
    eo_count          INTEGER NOT NULL,
    zi_count          INTEGER NOT NULL,
    win_rate          REAL,
    metrics_json      TEXT NOT NULL,     -- tüm kırılımlar
    best_pattern      TEXT,
    worst_pattern     TEXT,
    ai_yorum          TEXT,
    ai_ders           TEXT,
    ai_yarin_risk     TEXT,
    ai_model          TEXT,
    written_at        INTEGER NOT NULL
);


-- ============================================================
-- Faz 8: Outcome denetim (manuel doğrulama)
-- ============================================================

-- Bir setup'ın otomatik outcome'unu manuel olarak override etmek için.
-- Aynı setup birden fazla kez override edilebilir (audit izi); en yeni geçerli.
CREATE TABLE IF NOT EXISTS outcome_overrides (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id          INTEGER NOT NULL,
    original_state    TEXT NOT NULL,
    override_state    TEXT NOT NULL,
    reason            TEXT,
    created_at        INTEGER NOT NULL,
    FOREIGN KEY (setup_id) REFERENCES setups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_outcome_overrides_setup
    ON outcome_overrides (setup_id, created_at DESC);
