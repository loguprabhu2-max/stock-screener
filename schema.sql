-- Stock Screener Database Schema
-- This is run automatically by START.bat on first run.

DROP TABLE IF EXISTS stock_prices CASCADE;
DROP TABLE IF EXISTS sector_prices CASCADE;
DROP TABLE IF EXISTS index_prices CASCADE;
DROP TABLE IF EXISTS stocks_master CASCADE;
DROP TABLE IF EXISTS sectors_master CASCADE;
DROP TABLE IF EXISTS indexes_master CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    user_id        SERIAL PRIMARY KEY,
    username       VARCHAR(50) UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL,
    role           VARCHAR(10) NOT NULL CHECK (role IN ('admin', 'normal')),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE indexes_master (
    index_name VARCHAR(100) PRIMARY KEY
);

-- Simplified: just sector names, no index mapping
CREATE TABLE sectors_master (
    sector_name VARCHAR(100) PRIMARY KEY
);

CREATE TABLE stocks_master (
    stock_symbol VARCHAR(50) PRIMARY KEY,
    stock_name   VARCHAR(200) NOT NULL,
    sector       VARCHAR(100) NOT NULL,
    indexes      TEXT NOT NULL
);

CREATE TABLE stock_prices (
    date          DATE NOT NULL,
    stock_symbol  VARCHAR(50) NOT NULL,
    open          NUMERIC(15, 4) NOT NULL,
    high          NUMERIC(15, 4) NOT NULL,
    low           NUMERIC(15, 4) NOT NULL,
    close         NUMERIC(15, 4) NOT NULL,
    PRIMARY KEY (date, stock_symbol)
);
CREATE INDEX idx_stock_prices_symbol_date ON stock_prices(stock_symbol, date);

CREATE TABLE sector_prices (
    date         DATE NOT NULL,
    sector_name  VARCHAR(100) NOT NULL,
    open         NUMERIC(15, 4) NOT NULL,
    high         NUMERIC(15, 4) NOT NULL,
    low          NUMERIC(15, 4) NOT NULL,
    close        NUMERIC(15, 4) NOT NULL,
    PRIMARY KEY (date, sector_name)
);
CREATE INDEX idx_sector_prices_name_date ON sector_prices(sector_name, date);

CREATE TABLE index_prices (
    date        DATE NOT NULL,
    index_name  VARCHAR(100) NOT NULL,
    open        NUMERIC(15, 4) NOT NULL,
    high        NUMERIC(15, 4) NOT NULL,
    low         NUMERIC(15, 4) NOT NULL,
    close       NUMERIC(15, 4) NOT NULL,
    PRIMARY KEY (date, index_name)
);
CREATE INDEX idx_index_prices_name_date ON index_prices(index_name, date);
