-- 0005_season_type_scoped_ratings.sql
-- team_ratings and poll_rankings are keyed by (season, week) but not
-- season_type -- postseason weeks (bowls, CFP) restart week numbering
-- from 1, same as the regular season does. Without this column, a
-- postseason week 1 collection would land at the exact same (season,
-- week) key as the real regular-season week 1 snapshot and silently
-- become its "latest" row, corrupting a pinned-forever snapshot that's
-- supposed to never change after the fact. games already has this column
-- (0001_init.sql); this brings the other two week-scoped tables in line.
-- Existing rows all predate postseason collection, so they're all 'regular'.

ALTER TABLE team_ratings ADD COLUMN IF NOT EXISTS season_type TEXT NOT NULL DEFAULT 'regular';
ALTER TABLE poll_rankings ADD COLUMN IF NOT EXISTS season_type TEXT NOT NULL DEFAULT 'regular';

DROP INDEX IF EXISTS idx_team_ratings_season_week_source;
CREATE INDEX idx_team_ratings_season_week_source
    ON team_ratings (season, season_type, week, model_source_id, team_id, collected_at DESC);

DROP INDEX IF EXISTS idx_poll_rankings_lookup;
CREATE INDEX idx_poll_rankings_lookup
    ON poll_rankings (season, season_type, week, poll, team_id, collected_at DESC);
