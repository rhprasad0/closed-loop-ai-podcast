from __future__ import annotations

import os

import psycopg2
import psycopg2.extensions


def get_connection() -> psycopg2.extensions.connection:
    """Create a new Postgres connection using DB_CONNECTION_STRING env var.

    Uses sslmode=require. Returns a psycopg2 connection object.
    Callers are responsible for closing the connection.
    """
    conn_str = os.environ["DB_CONNECTION_STRING"]
    return psycopg2.connect(conn_str, sslmode="require")


def query(sql: str, params: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
    """Execute a SELECT query and return all rows.

    Opens a connection, executes the query, fetches all rows, closes connection.
    Returns rows as a list of tuples (column values in select order).
    For INSERT...RETURNING queries that need a result row, use this function.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows: list[tuple[object, ...]] = cur.fetchall()
            return rows
    finally:
        conn.close()


def execute(sql: str, params: tuple[object, ...] | None = None) -> int:
    """Execute an INSERT/UPDATE/DELETE statement.

    Opens a connection, executes the statement, commits, closes connection.
    Returns the rowcount (number of affected rows).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rowcount: int = cur.rowcount
        conn.commit()
        return rowcount
    finally:
        conn.close()
