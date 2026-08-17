"""LLM-drafted matchup previews.

Usage:
    python -m summarize.generate --season 2026 --week 1
    python -m summarize.generate --season 2026 --week 1 --game-id 401628455
    python -m summarize.generate --season 2026 --week 1 --publish
    python -m summarize.generate --season 2026 --week 1 --force

Kill switch: this refuses to run at all unless LLM_SUMMARIES_ENABLED=true is
set in the environment (config.py reads it). Unset it (or set it to
anything else) and every invocation exits immediately -- no DB connection,
no API call, no cost.

For each game in the given week that doesn't already have a summary file,
this makes one Claude API call with the web_search tool enabled so the
model grounds the preview in real, current search results rather than
inventing one. The response is constrained to a JSON schema (summary body +
the sources actually cited) so it's not free-text scraped for links.

Writes content/summaries/<season>/week-<NN>/<game_id>.md with
generated_by: llm. Per content/summaries/README.md, status defaults to
draft -- invisible on the site -- unless --publish is passed. Existing
files are never touched unless --force is passed, and files already
authored by a human (generated_by: human, or the default when omitted) are
never overwritten even with --force.
"""
import argparse
import sys

import anthropic
import yaml

import build
import config
import db

MODEL = config.LLM_SUMMARY_MODEL

SYSTEM_PROMPT = """You are writing a short factual preview of a single college \
football matchup for a sports website that sits next to prediction-model \
numbers and betting lines -- readers can already see the numbers, they come \
to this text for context the numbers don't carry.

Ground every claim in real web search results. Call the web_search tool as \
needed to find current, relevant news about these two specific teams and \
this specific game: recent form, roster or coaching storylines, injury or \
availability news, what's at stake, series history if it's relevant. Never \
invent a fact, a statistic, a quote, or a source URL.

Write 3 to 5 sentences, beat-writer style. Any claim about a specific \
player's injury or availability must carry an inline markdown link to the \
outlet reporting it, e.g. "(<a href=...>Outlet Name</a>)" written as \
markdown: [Outlet Name](https://...).

If you cannot find any real, relevant, recent articles about this specific \
matchup or these two teams' current season, do not pad with generic or \
invented color -- write 1-2 neutral sentences about the game's logistics \
only (kickoff, venue, what kind of matchup it is) and return an empty \
sources list. A short honest preview beats a fabricated detailed one.

Do not state any superlative, record, or historical claim -- "first ever,"
"largest," a specific all-time series record, "since <year>," a streak,
etc. -- unless a search result you are citing states that exact fact. If
you're not certain a number or superlative is correct, cut it or phrase it
generically (e.g. "the two programs have met several times" instead of a
specific won-loss record) rather than risk stating something false.

Return your final answer as JSON matching the provided schema:
- "summary": the markdown body text, with inline links as described above.
- "sources": every URL you actually cited in the summary, and only URLs you \
actually retrieved via web_search -- never a URL you did not search for."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "outlet": {"type": "string"},
                },
                "required": ["title", "url", "outlet"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "sources"],
    "additionalProperties": False,
}


def existing_summary_status(path) -> str | None:
    """Returns generated_by of an existing file, or None if there isn't one."""
    if not path.exists():
        return None
    text = path.read_text()
    if not text.startswith("---"):
        return "unknown"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "unknown"
    frontmatter = yaml.safe_load(parts[1]) or {}
    return frontmatter.get("generated_by", "human")


def build_prompt(game: dict, season: int, week: int) -> str:
    kickoff = build.eastern_kickoff(game["start_date"])
    venue = game.get("venue") or "TBD"
    neutral = " (neutral site)" if game.get("neutral_site") else ""
    return (
        f"Matchup: {game['away_school']} at {game['home_school']}\n"
        f"Kickoff: {kickoff}\n"
        f"Venue: {venue}{neutral}\n"
        f"Season: {season}, Week {week}\n\n"
        "Research this specific matchup and write the preview now."
    )


def generate_draft(client: anthropic.Anthropic, game: dict, season: int, week: int) -> dict:
    """Returns {"summary": str, "sources": list[dict]} or raises on API/parse
    failure -- the caller decides whether that's fatal for the whole batch."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        thinking={"type": "disabled"},
        tools=[{"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": build_prompt(game, season, week)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {response.stop_details}")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no text block in response (stop_reason={response.stop_reason})")
    import json
    return json.loads(text)


def write_summary_file(path, game_id: int, draft: dict, status: str) -> None:
    frontmatter = {
        "game_id": game_id,
        "author": "Claude",
        "generated_by": "llm",
        "sources": draft["sources"],
        "status": status,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{yaml_block}---\n\n{draft['summary'].strip()}\n")


def run(season: int, week: int, game_id: int | None, publish: bool, force: bool) -> int:
    if not config.LLM_SUMMARIES_ENABLED:
        print(
            "[summarize] LLM_SUMMARIES_ENABLED is not \"true\" -- refusing to run. "
            "Set it in .env (or as a repo variable/secret in CI) to enable.",
            file=sys.stderr,
        )
        return 1
    if not config.ANTHROPIC_API_KEY:
        print("[summarize] ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    conn = db.get_connection()
    games = build.fetch_week_games(conn, season, week)
    if game_id is not None:
        games = [g for g in games if g["id"] == game_id]

    status = "published" if publish else "draft"
    week_dir = build.SUMMARIES_DIR / str(season) / f"week-{week:02d}"

    generated, skipped, failed = 0, 0, 0
    for game in games:
        path = week_dir / f"{game['id']}.md"
        existing = existing_summary_status(path)
        if existing is not None and not force:
            print(f"[summarize] {game['id']} ({game['away_school']} @ {game['home_school']}): "
                  f"skipping, file already exists ({existing})")
            skipped += 1
            continue
        if existing == "human":
            print(f"[summarize] {game['id']} ({game['away_school']} @ {game['home_school']}): "
                  f"skipping, existing file is human-authored, --force does not override this")
            skipped += 1
            continue

        print(f"[summarize] {game['id']} ({game['away_school']} @ {game['home_school']}): generating...")
        try:
            draft = generate_draft(client, game, season, week)
        except Exception as exc:
            print(f"[summarize] {game['id']}: FAILED -- {exc}", file=sys.stderr)
            failed += 1
            continue

        write_summary_file(path, game["id"], draft, status)
        print(f"[summarize] {game['id']}: wrote {path.relative_to(build.ROOT)} (status={status}, "
              f"{len(draft['sources'])} sources)")
        generated += 1

    print(f"[summarize] done: {generated} generated, {skipped} skipped, {failed} failed")
    return 1 if failed and not generated else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--game-id", type=int, default=None, help="Only generate for this game.")
    parser.add_argument("--publish", action="store_true", help="Write status: published instead of draft.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing LLM-authored drafts (never human-authored files).")
    args = parser.parse_args()
    return run(args.season, args.week, args.game_id, args.publish, args.force)


if __name__ == "__main__":
    sys.exit(main())
