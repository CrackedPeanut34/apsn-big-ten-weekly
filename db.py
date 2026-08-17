"""Thin Postgres connection helper. No ORM -- schema lives in db/migrations/."""
import psycopg
from psycopg.rows import dict_row

import config


def get_connection():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
