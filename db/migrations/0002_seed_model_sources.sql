-- 0002_seed_model_sources.sql
-- The five v1 model sources. hfa defaults to 2.5 where the source doesn't
-- publish its own constant -- see conversions.py DEFAULT_HFA.

INSERT INTO model_sources (name, slug, family, homepage_url, output_type, hfa, active, notes)
VALUES
    ('SP+', 'sp-plus', 'sp-plus',
     'https://www.espn.com/college-football/story/_/id/38047037',
     'power_rating', 2.5, TRUE,
     'HFA not published by source; 2.5 is an assumed default.'),

    ('SRS', 'srs', 'srs',
     'https://blog.collegefootballdata.com/talking-tech-bu-2019-computer-rankings-guide/',
     'power_rating', 2.5, TRUE,
     'HFA not published by source; 2.5 is an assumed default.'),

    ('Elo', 'elo', 'elo',
     'https://blog.collegefootballdata.com/introducing-elo-ratings/',
     'power_rating', 2.5, TRUE,
     'HFA not published by source; 2.5 is an assumed default. Elo ratings are converted through the same power-rating -> margin -> normal-CDF pipeline as the other sources for v1, not Elo''s native logistic formula.'),

    ('FPI', 'fpi', 'fpi',
     'https://www.espn.com/college-football/fpi',
     'power_rating', 2.5, TRUE,
     'HFA not published by source; 2.5 is an assumed default.'),

    ('CFBD Pregame Win Probability', 'cfbd-pregame-wp', 'cfbd-wp',
     'https://collegefootballdata.com',
     'win_prob', 2.5, TRUE,
     'Already a probability as published; margin_home is back-derived via the inverse of the same normal-CDF used elsewhere, so the table always has both columns. hfa is unused for this source (win_prob rows do not add HFA).')
ON CONFLICT (slug) DO NOTHING;
