from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

import pandas as pd

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine
except ImportError:  # Local smoke tests may run before requirements are installed.
    create_engine = None
    text = None
    Engine = Any


ORDER_COLUMNS = [
    "order_date", "order_id", "order_status", "item_status", "fulfillment_channel", "asin",
    "qty", "item_price", "shipping", "promotion", "ship_promotion", "net_revenue", "row_hash",
]


def create_storage(database_url: str, root: Path) -> tuple[Engine | sqlite3.Connection, bool]:
    """Return an engine and whether it is a durable remote backend."""
    remote = bool(database_url)
    if not database_url:
        data_dir = root / "data"
        data_dir.mkdir(exist_ok=True)
        engine = sqlite3.connect(data_dir / "report.db", check_same_thread=False)
    else:
        if create_engine is None:
            raise RuntimeError("Thiếu SQLAlchemy. Hãy cài requirements.txt để dùng database production.")
        engine = create_engine(database_url, pool_pre_ping=True)
    initialize_database(engine)
    return engine, remote


def initialize_database(engine: Engine | sqlite3.Connection) -> None:
    statements = ["""
            CREATE TABLE IF NOT EXISTS import_history (
                batch_id VARCHAR(36) PRIMARY KEY,
                imported_at VARCHAR(40) NOT NULL,
                file_names TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                skipped_duplicates INTEGER NOT NULL,
                locked INTEGER NOT NULL DEFAULT 1
            )
        """, """
            CREATE TABLE IF NOT EXISTS order_data (
                row_hash VARCHAR(64) PRIMARY KEY,
                batch_id VARCHAR(36) NOT NULL,
                order_date VARCHAR(50) NOT NULL,
                order_id TEXT,
                order_status TEXT,
                item_status TEXT,
                fulfillment_channel TEXT,
                asin TEXT,
                qty DOUBLE PRECISION,
                item_price DOUBLE PRECISION,
                shipping DOUBLE PRECISION,
                promotion DOUBLE PRECISION,
                ship_promotion DOUBLE PRECISION,
                net_revenue DOUBLE PRECISION
            )
        """]
    if isinstance(engine, sqlite3.Connection):
        with engine:
            for statement in statements:
                engine.execute(statement)
    else:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))


def load_orders(engine: Engine | sqlite3.Connection) -> pd.DataFrame:
    try:
        query = "SELECT * FROM order_data" if isinstance(engine, sqlite3.Connection) else text("SELECT * FROM order_data")
        df = pd.read_sql(query, engine)
    except Exception:
        return pd.DataFrame(columns=ORDER_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=ORDER_COLUMNS)
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh")
    for column in ["qty", "item_price", "shipping", "promotion", "ship_promotion", "net_revenue"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    return df[ORDER_COLUMNS].dropna(subset=["order_date"])


def append_orders(engine: Engine | sqlite3.Connection, orders: pd.DataFrame, file_names: list[str]) -> dict[str, object]:
    batch_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat()
    query = "SELECT row_hash FROM order_data" if isinstance(engine, sqlite3.Connection) else text("SELECT row_hash FROM order_data")
    existing = set(pd.read_sql(query, engine)["row_hash"].astype(str))
    incoming = orders.drop_duplicates("row_hash").copy()
    new_rows = incoming[~incoming["row_hash"].isin(existing)].copy()
    skipped = len(incoming) - len(new_rows)
    new_rows["batch_id"] = batch_id
    new_rows["order_date"] = new_rows["order_date"].map(lambda value: value.isoformat())
    ordered = ["row_hash", "batch_id", "order_date", "order_id", "order_status", "item_status", "fulfillment_channel", "asin", "qty", "item_price", "shipping", "promotion", "ship_promotion", "net_revenue"]
    if isinstance(engine, sqlite3.Connection):
        with engine:
            if not new_rows.empty:
                new_rows[ordered].to_sql("order_data", engine, if_exists="append", index=False, method="multi")
            engine.execute(
                """INSERT INTO import_history
                    (batch_id, imported_at, file_names, row_count, skipped_duplicates, locked)
                    VALUES (?, ?, ?, ?, ?, 1)""",
                (batch_id, imported_at, json.dumps(file_names, ensure_ascii=False), int(len(new_rows)), int(skipped)),
            )
    else:
        with engine.begin() as conn:
            if not new_rows.empty:
                new_rows[ordered].to_sql("order_data", conn, if_exists="append", index=False, method="multi")
            conn.execute(
                text("""INSERT INTO import_history
                    (batch_id, imported_at, file_names, row_count, skipped_duplicates, locked)
                    VALUES (:batch_id, :imported_at, :file_names, :row_count, :skipped, 1)"""),
                {"batch_id": batch_id, "imported_at": imported_at, "file_names": json.dumps(file_names, ensure_ascii=False),
                 "row_count": int(len(new_rows)), "skipped": int(skipped)},
            )
    return {"batch_id": batch_id, "row_count": len(new_rows), "skipped_duplicates": skipped}


def import_history(engine: Engine | sqlite3.Connection) -> pd.DataFrame:
    query = "SELECT * FROM import_history ORDER BY imported_at DESC" if isinstance(engine, sqlite3.Connection) else text("SELECT * FROM import_history ORDER BY imported_at DESC")
    result = pd.read_sql(query, engine)
    if result.empty:
        return result
    result["Files"] = result["file_names"].map(lambda value: ", ".join(json.loads(value)))
    result["Imported At"] = pd.to_datetime(result["imported_at"], errors="coerce", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh")
    result["Locked"] = result["locked"].astype(bool)
    return result.rename(columns={"batch_id": "Batch ID", "row_count": "Rows", "skipped_duplicates": "Duplicates"})[
        ["Batch ID", "Imported At", "Files", "Rows", "Duplicates", "Locked"]
    ]


def delete_batch(engine: Engine | sqlite3.Connection, batch_id: str) -> int:
    if isinstance(engine, sqlite3.Connection):
        with engine:
            count = engine.execute("SELECT COUNT(*) FROM order_data WHERE batch_id = ?", (batch_id,)).fetchone()[0]
            engine.execute("DELETE FROM order_data WHERE batch_id = ?", (batch_id,))
            engine.execute("DELETE FROM import_history WHERE batch_id = ?", (batch_id,))
    else:
        with engine.begin() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM order_data WHERE batch_id = :batch_id"), {"batch_id": batch_id}).scalar_one()
            conn.execute(text("DELETE FROM order_data WHERE batch_id = :batch_id"), {"batch_id": batch_id})
            conn.execute(text("DELETE FROM import_history WHERE batch_id = :batch_id"), {"batch_id": batch_id})
    return int(count)

