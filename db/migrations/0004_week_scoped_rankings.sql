-- 0004_week_scoped_rankings.sql
-- Ties team_ratings to a specific week so a week's rankings snapshot is
-- pinned forever, same append-only principle as predictions/odds_snapshots:
-- once week 2 is collected, week 1's rows are untouched and still queryable
-- exactly as they were. Existing rows predate this column and were all
-- collected during Week 1, so backfill them explicitly.

ALTER TABLE team_ratings ADD COLUMN IF NOT EXISTS week INTEGER;
UPDATE team_ratings SET week = 1 WHERE week IS NULL;
ALTER TABLE team_ratings ALTER COLUMN week SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_team_ratings_season_week_source
    ON team_ratings (season, week, model_source_id, team_id, collected_at DESC);

-- AP Top 25 (and whatever other polls CFBD returns, though we only collect
-- AP Top 25 for now). Inherently week-scoped -- a poll is released weekly.
CREATE TABLE IF NOT EXISTS poll_rankings (
    id                  BIGSERIAL PRIMARY KEY,
    team_id             INTEGER NOT NULL REFERENCES teams(id),
    season              INTEGER NOT NULL,
    week                INTEGER NOT NULL,
    poll                TEXT NOT NULL,
    poll_rank           INTEGER NOT NULL,
    points              INTEGER,
    first_place_votes   INTEGER,
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_poll_rankings_lookup
    ON poll_rankings (season, week, poll, team_id, collected_at DESC);
