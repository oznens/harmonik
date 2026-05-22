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

    UNIQUE (symbol, interval, pattern_name, x_time, a_time, b_time, c_time, d_time)
);

CREATE INDEX IF NOT EXISTS idx_setups_lookup
    ON setups (symbol, interval, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_setups_d_time
    ON setups (symbol, interval, d_time DESC);
