-- terminalMiraz veritabanı şeması v1 (Faz 1: sadece kline tablosu)

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
