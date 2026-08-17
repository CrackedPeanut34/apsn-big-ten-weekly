-- 0003_team_ratings.sql
-- Team-level power ratings, independent of any one game. predictions rows
-- only exist for games we collect this week, and collect_power_rating_source
-- skips a game entirely if either side lacks a rating -- so a Big Ten team
-- whose Week 1 opponent isn't covered by a source (an FCS team SP+/Elo/FPI
-- don't rate) would otherwise never get its own rating captured anywhere.
-- This table stores every team a source publishes a rating for, each week,
-- regardless of who they're playing. Append-only, same as predictions.

CREATE TABLE IF NOT EXISTS team_ratings (
    id                  BIGSERIAL PRIMARY KEY,
    team_id             INTEGER NOT NULL REFERENCES teams(id),
    model_source_id     INTEGER NOT NULL REFERENCES model_sources(id),
    season              INTEGER NOT NULL,
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_value           NUMERIC,                 -- exactly as published; never overwritten
    raw_payload         JSONB,                   -- full source response for this team
    conversion_version  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_team_ratings_team ON team_ratings (team_id);
CREATE INDEX IF NOT EXISTS idx_team_ratings_season_source_collected
    ON team_ratings (season, model_source_id, team_id, collected_at DESC);
