"""LLM summary generation -- the seam, not the feature. Not implemented in
v1 (see build brief section 8). This module exists so the interface is
already in place when it is:

    draft = generate_draft(game, articles)
    # write draft to content/summaries/<season>/week-<NN>/<game_id>.md
    # with frontmatter status: draft, generated_by: llm

A human then reviews the file and flips status to published. build.py
already refuses to render anything but status: published, so wiring this up
can never accidentally put unreviewed text on the site.

What the real version needs, not yet built:
  - Per-team RSS/news feeds (or a news API) to pull recent articles for
    both teams in a matchup.
  - Matchup relevance filtering -- most per-team articles won't be about
    this game; something has to decide which ones are.
  - Per-claim source links. Every injury/availability claim in the output
    needs an inline link to the specific article it came from, the same
    hard rule that applies to human-written summaries (see
    content/summaries/README.md). That likely means the generation prompt
    has to carry article URLs alongside their content and be constrained to
    cite them, not just write fluent prose.
"""
from typing import Any


def generate_draft(game: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    """Returns a draft summary as markdown body text (no frontmatter --
    the caller is responsible for writing the file with status: draft and
    generated_by: llm).

    game: a row shaped like build.fetch_week_games()'s output.
    articles: recent per-team articles/news items to draw from, shape TBD
        once a news source is chosen.
    """
    raise NotImplementedError("LLM summary generation is not implemented in v1")
