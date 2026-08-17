-- 0001_init.sql
-- Core schema. Append-only for anything time-varying (predictions, odds_snapshots):
-- never UPDATE a row in those two tables, only INSERT.

CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY,        -- CFBD team id
    school          TEXT NOT NULL,
    abbreviation    TEXT,
    conference      TEXT,
    division        TEXT,
    logo_url        TEXT,
    logo_dark_url   TEXT,
    color           TEXT,
    alt_color       TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY,        -- CFBD game id
    season          INTEGER NOT NULL,
    week            INTEGER NOT NULL,
    season_type     TEXT NOT NULL,
    start_date      TIMESTAMPTZ,
    tv              TEXT,
    home_team_id    INTEGER NOT NULL REFERENCES teams(id),
    away_team_id    INTEGER NOT NULL REFERENCES teams(id),
    neutral_site    BOOLEAN NOT NULL DEFAULT FALSE,
    venue           TEXT,
    home_points     INTEGER,                    -- null until played
    away_points     INTEGER,                    -- null until played
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_games_season_week ON games (season, week);

CREATE TABLE IF NOT EXISTS model_sources (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    family          TEXT,                       -- hand-labeled lineage tag; not used in v1 logic
    homepage_url    TEXT,
    output_type     TEXT NOT NULL CHECK (output_type IN ('power_rating', 'spread', 'win_prob', 'projected_score')),
    hfa             NUMERIC,                     -- home-field advantage in points, per source
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
    id                  BIGSERIAL PRIMARY KEY,
    game_id             INTEGER NOT NULL REFERENCES games(id),
    model_source_id     INTEGER NOT NULL REFERENCES model_sources(id),
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_value           NUMERIC,                 -- exactly as published; never overwritten
    raw_type            TEXT,                    -- mirrors model_sources.output_type
    raw_payload         JSONB,                   -- full source response for this row
    margin_home         NUMERIC,                 -- derived
    win_prob_home       NUMERIC,                 -- derived
    conversion_version  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_game ON predictions (game_id);
CREATE INDEX IF NOT EXISTS idx_predictions_source ON predictions (model_source_id);
CREATE INDEX IF NOT EXISTS idx_predictions_game_source_collected
    ON predictions (game_id, model_source_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    game_id             INTEGER NOT NULL REFERENCES games(id),
    provider            TEXT NOT NULL,
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    spread_home         NUMERIC,
    spread_open         NUMERIC,
    over_under          NUMERIC,
    over_under_open     NUMERIC,
    moneyline_home      INTEGER,
    moneyline_away      INTEGER,
    margin_home         NUMERIC,                 -- derived
    win_prob_home       NUMERIC,                 -- derived, de-vigged
    conversion_version  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_odds_game ON odds_snapshots (game_id);
CREATE INDEX IF NOT EXISTS idx_odds_game_provider_collected
    ON odds_snapshots (game_id, provider, collected_at DESC);

CREATE TABLE IF NOT EXISTS submissions (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    name        TEXT,
    email       TEXT,
    message     TEXT
);
