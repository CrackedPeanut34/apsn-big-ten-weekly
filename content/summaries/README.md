# Summaries

One markdown file per game: `content/summaries/<season>/week-<NN>/<game_id>.md`.

`<game_id>` is the CFBD game id (the `games.id` column -- check the DB or
the site's per-card anchor, `#game-<id>`, once a week has been built).
`<NN>` is zero-padded (`week-01`, not `week-1`).

A missing file is fine and expected -- the card just renders without a
summary block. Not every game needs one, and early-season weeks (18 B1G
games, everyone nonconference) will have gaps.

## Format

```markdown
---
game_id: 401628455
author: Levi
generated_by: human
sources:
  - title: <headline>
    url: https://...
    outlet: <outlet name>
status: published
---

Three to five sentences. Injury and availability news attributed to its
outlet with an inline link. What's at stake. The one thing worth watching.
```

Rules the build enforces (`build.py:parse_summary`), not just convention:

- `status: draft` never renders on the site. Only `status: published` does.
  This is the gate for the LLM-generated path in `summarize/generate.py` --
  drafts stay invisible until a human flips the status (or the script is
  run with `--publish`).
- `generated_by` defaults to `human` if omitted. Set it to `llm` and the
  card gets a visible "AI-generated, verify before acting" label -- it does
  not change whether the card renders, only how it's labeled.

Any claim about a player's availability must carry an inline markdown link
to the outlet reporting it. This isn't build-enforced (there's no reliable
way to lint "is this claim about availability"), so it's on the author.

See `_template.md` in this directory for a blank copy of the frontmatter.
