from __future__ import annotations

import io
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "ohlcv_cache.sqlite"
)
_DEFAULT_CACHE_TTL_SEC = 15 * 60
_FETCH_TIMEOUT_SEC = 6 * 60
_MAX_QUEUE_ATTEMPTS = 3

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv_cache (
    symbol            TEXT PRIMARY KEY,
    df_parquet        BLOB NOT NULL,
    share_base        REAL,
    last_refresh_ts   INTEGER NOT NULL,
    source            TEXT,
    rows              INTEGER NOT NULL DEFAULT 0,
    last_valid_close  REAL,
    last_trade_date   TEXT
);

CREATE TABLE IF NOT EXISTS async_fetch_queue (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol            TEXT UNIQUE NOT NULL,
    requested_ts      INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'PENDING'
                      CHECK (status IN ('PENDING','FETCHING','DONE','FAILED','TIMEOUT')),
    attempt           INTEGER NOT NULL DEFAULT 0,
    error_msg         TEXT,
    last_attempt_ts   INTEGER,
    completed_ts      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON async_fetch_queue(status, requested_ts);

CREATE TABLE IF NOT EXISTS fetcher_stats (
    metric     TEXT PRIMARY KEY,
    value      INTEGER NOT NULL DEFAULT 0,
    updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol       TEXT PRIMARY KEY,
    params_json  TEXT,
    added_ts     INTEGER NOT NULL,
    updated_ts   INTEGER NOT NULL,
    source       TEXT DEFAULT 'manual'
);
"""


_LOCK = threading.RLock()
_CONN_CACHE: Dict[int, sqlite3.Connection] = {}


def _utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def get_cache_db_path(override: Optional[str] = None) -> str:
    path = override or os.environ.get("OHLCV_CACHE_DB", _DEFAULT_DB_PATH)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


@contextmanager
def get_db(db_path: Optional[str] = None):
    path = get_cache_db_path(db_path)
    tid = threading.get_ident()
    with _LOCK:
        conn = _CONN_CACHE.get(tid)
        if conn is None:
            conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            _CONN_CACHE[tid] = conn
    try:
        yield conn
    except Exception:
        raise


def ensure_schema(db_path: Optional[str] = None) -> None:
    with get_db(db_path) as conn:
        cur = conn.executescript(_SCHEMA_SQL)
        cur.close()


def _df_to_parquet_blob(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    work = df.copy(deep=False)
    work.index = pd.to_datetime(work.index)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c in work.columns:
            work[c] = pd.to_numeric(work[c], errors="coerce")
    work.to_parquet(buf, engine="pyarrow" if False else "auto", index=True)
    return buf.getvalue()


def _parquet_blob_to_df(blob: bytes) -> pd.DataFrame:
    df = pd.read_parquet(io.BytesIO(blob))
    df.index = pd.to_datetime(df.index)
    return df


def _bump_stat(conn: sqlite3.Connection, metric: str, delta: int = 1) -> None:
    now = _utc_now_ts()
    conn.execute(
        "INSERT INTO fetcher_stats(metric,value,updated_ts) VALUES(?,?,?) "
        "ON CONFLICT(metric) DO UPDATE SET value=value+?, updated_ts=?",
        (metric, delta, now, delta, now),
    )


def get_all_stats(db_path: Optional[str] = None) -> Dict[str, int]:
    ensure_schema(db_path)
    result: Dict[str, int] = {}
    with get_db(db_path) as conn:
        for row in conn.execute("SELECT metric,value FROM fetcher_stats"):
            result[row["metric"]] = int(row["value"])
    return result


def get_stat(metric: str, default: Any = None, db_path: Optional[str] = None) -> Any:
    ensure_schema(db_path)
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM fetcher_stats WHERE metric=?",
            (str(metric),),
        ).fetchone()
    if row is None:
        return default
    raw = row["value"]
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return raw


def set_stat(metric: str, value: Any, db_path: Optional[str] = None) -> None:
    ensure_schema(db_path)
    now = _utc_now_ts()
    if isinstance(value, (dict, list, tuple)) or value is None:
        stored = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, (int, float)):
        stored = value
    else:
        stored = json.dumps(value, ensure_ascii=False)
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO fetcher_stats(metric,value,updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(metric) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            (str(metric), stored, now),
        )


def upsert_ohlcv(
    symbol: str,
    df: pd.DataFrame,
    share_base: Any = None,
    source: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    if df is None or not isinstance(df, pd.DataFrame) or len(df) < 2:
        raise ValueError("df empty or too short for cache upsert")
    ensure_schema(db_path)
    symbol = str(symbol).strip().upper()
    blob = _df_to_parquet_blob(df)
    now = _utc_now_ts()
    close_s = pd.to_numeric(df["Close"], errors="coerce").replace(0, float("nan")).dropna()
    last_valid_close = float(close_s.iloc[-1]) if len(close_s) else None
    last_trade_date = (
        df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])
    )
    sb = float(share_base) if share_base is not None and pd.notna(share_base) and float(share_base) > 0 else None
    with get_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO ohlcv_cache(symbol,df_parquet,share_base,last_refresh_ts,source,rows,last_valid_close,last_trade_date)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                    df_parquet=excluded.df_parquet,
                    share_base=excluded.share_base,
                    last_refresh_ts=excluded.last_refresh_ts,
                    source=excluded.source,
                    rows=excluded.rows,
                    last_valid_close=excluded.last_valid_close,
                    last_trade_date=excluded.last_trade_date
                """,
                (
                    symbol,
                    blob,
                    sb,
                    now,
                    source,
                    int(len(df)),
                    last_valid_close,
                    last_trade_date,
                ),
            )
            conn.execute(
                "DELETE FROM async_fetch_queue WHERE symbol=? AND status IN ('PENDING','FETCHING')",
                (symbol,),
            )
            conn.execute(
                """
                INSERT INTO async_fetch_queue(symbol,requested_ts,status,attempt,completed_ts)
                VALUES(?,?, 'DONE', 0, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    status='DONE', attempt=attempt, error_msg=NULL, completed_ts=?
                """,
                (symbol, now, now, now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def get_cached_ohlcv(
    symbol: str,
    end_date: Any = None,
    max_age_sec: int = _DEFAULT_CACHE_TTL_SEC,
    db_path: Optional[str] = None,
    bump_stats: bool = True,
) -> Tuple[Optional[pd.DataFrame], Any, str]:
    """Returns (df, share_base, status) where status in {'HIT','STALE','MISS'}"""
    ensure_schema(db_path)
    symbol = str(symbol).strip().upper()
    now = _utc_now_ts()
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT df_parquet,share_base,last_refresh_ts FROM ohlcv_cache WHERE symbol=?",
            (symbol,),
        ).fetchone()
        if row is None:
            if bump_stats:
                _bump_stat(conn, "cache_miss", 1)
            return None, None, "MISS"
        age = now - int(row["last_refresh_ts"])
        if max_age_sec is None or age <= max_age_sec:
            status = "HIT"
            if bump_stats:
                _bump_stat(conn, "cache_hit", 1)
        else:
            status = "STALE"
            if bump_stats:
                _bump_stat(conn, "cache_stale", 1)
        try:
            df = _parquet_blob_to_df(row["df_parquet"])
        except Exception:
            if bump_stats:
                _bump_stat(conn, "cache_corrupt", 1)
            return None, None, "MISS"
    if end_date is not None:
        try:
            ed = pd.to_datetime(end_date)
            if len(df) and df.index.max() > ed:
                df = df[df.index <= ed].copy(deep=False)
        except Exception:
            pass
    sb = row["share_base"] if row["share_base"] is not None else None
    return df, sb, status


def request_async_fetch(
    symbol: str,
    db_path: Optional[str] = None,
) -> str:
    """Returns one of {'QUEUED','ALREADY_PENDING','FETCHING_INFLIGHT','RECENTLY_DONE','RECENTLY_FAILED'}"""
    ensure_schema(db_path)
    symbol = str(symbol).strip().upper()
    now = _utc_now_ts()
    with get_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT status,attempt,completed_ts,last_attempt_ts FROM async_fetch_queue WHERE symbol=?",
                (symbol,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO async_fetch_queue(symbol,requested_ts,status,attempt) VALUES(?,?, 'PENDING',0)",
                    (symbol, now),
                )
                _bump_stat(conn, "queue_enqueue", 1)
                conn.execute("COMMIT")
                return "QUEUED"
            st = str(row["status"])
            if st in ("PENDING",):
                conn.execute(
                    "UPDATE async_fetch_queue SET requested_ts=? WHERE symbol=? AND status='PENDING'",
                    (now, symbol),
                )
                conn.execute("COMMIT")
                return "ALREADY_PENDING"
            if st == "FETCHING":
                la = row["last_attempt_ts"] or 0
                if now - la < _FETCH_TIMEOUT_SEC:
                    conn.execute("COMMIT")
                    return "FETCHING_INFLIGHT"
                conn.execute(
                    "UPDATE async_fetch_queue SET status='TIMEOUT', error_msg='previous inflight timeout' WHERE symbol=?",
                    (symbol,),
                )
                conn.execute(
                    "INSERT INTO async_fetch_queue(symbol,requested_ts,status,attempt) VALUES(?,?, 'PENDING',0) "
                    "ON CONFLICT(symbol) DO UPDATE SET status='PENDING', requested_ts=?, attempt=0, error_msg=NULL",
                    (symbol, now, now),
                )
                conn.execute("COMMIT")
                return "QUEUED"
            if st == "DONE":
                ct = row["completed_ts"] or 0
                if now - ct < max(60, int(_DEFAULT_CACHE_TTL_SEC * 0.5)):
                    conn.execute("COMMIT")
                    return "RECENTLY_DONE"
                conn.execute(
                    "UPDATE async_fetch_queue SET status='PENDING', requested_ts=?, attempt=0, error_msg=NULL WHERE symbol=?",
                    (now, symbol),
                )
                _bump_stat(conn, "queue_enqueue", 1)
                conn.execute("COMMIT")
                return "QUEUED"
            if st in ("FAILED", "TIMEOUT"):
                attempt = int(row["attempt"] or 0)
                if attempt < _MAX_QUEUE_ATTEMPTS:
                    conn.execute(
                        "UPDATE async_fetch_queue SET status='PENDING', requested_ts=?, error_msg=NULL WHERE symbol=?",
                        (now, symbol),
                    )
                    _bump_stat(conn, "queue_retry", 1)
                    conn.execute("COMMIT")
                    return "QUEUED"
                conn.execute("COMMIT")
                return "RECENTLY_FAILED"
            conn.execute("COMMIT")
            return "QUEUED"
        except Exception:
            conn.execute("ROLLBACK")
            raise


def peek_next_pending(
    db_path: Optional[str] = None,
    limit: int = 1,
) -> List[Dict[str, Any]]:
    ensure_schema(db_path)
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT id,symbol,requested_ts,attempt FROM async_fetch_queue "
            "WHERE status='PENDING' ORDER BY requested_ts ASC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def claim_pending(
    symbol: str,
    db_path: Optional[str] = None,
) -> bool:
    ensure_schema(db_path)
    now = _utc_now_ts()
    with get_db(db_path) as conn:
        cur = conn.execute(
            "UPDATE async_fetch_queue SET status='FETCHING', attempt=attempt+1, last_attempt_ts=? "
            "WHERE symbol=? AND status='PENDING'",
            (now, str(symbol).strip().upper()),
        )
        return bool(cur.rowcount and cur.rowcount > 0)


def mark_fetch_done(
    symbol: str,
    db_path: Optional[str] = None,
) -> None:
    ensure_schema(db_path)
    now = _utc_now_ts()
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE async_fetch_queue SET status='DONE', error_msg=NULL, completed_ts=? WHERE symbol=?",
            (now, str(symbol).strip().upper()),
        )
        _bump_stat(conn, "fetch_ok", 1)


def mark_fetch_failed(
    symbol: str,
    error_msg: str,
    db_path: Optional[str] = None,
) -> None:
    ensure_schema(db_path)
    sym = str(symbol).strip().upper()
    msg = (str(error_msg) or "")[:512]
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT attempt FROM async_fetch_queue WHERE symbol=?", (sym,)
        ).fetchone()
        attempt = int(row["attempt"]) if row is not None else 0
        final_status = "FAILED" if attempt >= _MAX_QUEUE_ATTEMPTS else "FAILED"
        conn.execute(
            "UPDATE async_fetch_queue SET status=?, error_msg=?, completed_ts=? WHERE symbol=?",
            (final_status, msg, _utc_now_ts(), sym),
        )
        _bump_stat(conn, "fetch_fail", 1)
        if any(k in msg for k in ("429", "Too Many Requests", "RateLimit")):
            _bump_stat(conn, "fetch_429", 1)


def get_fetch_status(
    symbol: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    ensure_schema(db_path)
    with get_db(db_path) as conn:
        r_queue = conn.execute(
            "SELECT status,attempt,error_msg,requested_ts,last_attempt_ts,completed_ts FROM async_fetch_queue WHERE symbol=?",
            (str(symbol).strip().upper(),),
        ).fetchone()
        r_cache = conn.execute(
            "SELECT last_refresh_ts,source,rows,last_valid_close,last_trade_date FROM ohlcv_cache WHERE symbol=?",
            (str(symbol).strip().upper(),),
        ).fetchone()
    return {
        "queue": dict(r_queue) if r_queue is not None else None,
        "cache": dict(r_cache) if r_cache is not None else None,
    }


def get_queue_depth(db_path: Optional[str] = None) -> Dict[str, int]:
    ensure_schema(db_path)
    out = {"PENDING": 0, "FETCHING": 0, "DONE": 0, "FAILED": 0, "TIMEOUT": 0, "TOTAL_CACHED": 0}
    with get_db(db_path) as conn:
        for r in conn.execute("SELECT status,COUNT(*) c FROM async_fetch_queue GROUP BY status"):
            out[str(r["status"])] = int(r["c"])
        rc = conn.execute("SELECT COUNT(*) c FROM ohlcv_cache").fetchone()
        if rc is not None:
            out["TOTAL_CACHED"] = int(rc["c"])
    return out


def list_cached_symbols(
    db_path: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    ensure_schema(db_path)
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol,last_refresh_ts,source,rows,last_valid_close,last_trade_date FROM ohlcv_cache "
            "ORDER BY last_refresh_ts DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_watchlist_symbol(
    symbol: str,
    params: Optional[Dict[str, Any]] = None,
    source: str = "app",
    db_path: Optional[str] = None,
) -> str:
    """Upsert one symbol into local SQLite watchlist table. Returns normalized symbol."""
    ensure_schema(db_path)
    sym = str(symbol).strip().upper()
    params_json = json.dumps(params or {}, ensure_ascii=False) if params is not None else None
    now_ts = _utc_now_ts()
    with _LOCK:
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT added_ts FROM watchlist WHERE symbol=?", (sym,)
            ).fetchone()
            added = int(row["added_ts"]) if row is not None else now_ts
            conn.execute(
                "INSERT INTO watchlist(symbol,params_json,added_ts,updated_ts,source) VALUES(?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET params_json=excluded.params_json, "
                "updated_ts=excluded.updated_ts, source=excluded.source",
                (sym, params_json, added, now_ts, str(source or "app")[:32]),
            )
    return sym


def delete_watchlist_symbol(
    symbol: str,
    db_path: Optional[str] = None,
) -> bool:
    """Returns True if a row was deleted."""
    ensure_schema(db_path)
    sym = str(symbol).strip().upper()
    with _LOCK:
        with get_db(db_path) as conn:
            cur = conn.execute("DELETE FROM watchlist WHERE symbol=?", (sym,))
            return int(cur.rowcount or 0) > 0


def list_watchlist_symbols(
    db_path: Optional[str] = None,
    limit: int = 1000,
    include_params: bool = False,
) -> Any:
    """Returns list of dicts: [{symbol,added_ts,updated_ts,source,params?}] sorted by added_ts DESC."""
    ensure_schema(db_path)
    cols = ["symbol", "added_ts", "updated_ts", "source"]
    if include_params:
        cols.insert(1, "params_json")
    sql = f"SELECT {', '.join(cols)} FROM watchlist ORDER BY updated_ts DESC LIMIT ?"
    with get_db(db_path) as conn:
        rows = conn.execute(sql, (int(limit),)).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        item: Dict[str, Any] = {
            "symbol": str(r["symbol"]),
            "added_ts": int(r["added_ts"] or 0),
            "updated_ts": int(r["updated_ts"] or 0),
            "source": str(r["source"] or ""),
        }
        if include_params:
            raw_p = r["params_json"] if "params_json" in r.keys() else None
            try:
                item["params"] = json.loads(str(raw_p)) if raw_p else {}
            except Exception:
                item["params"] = {}
        out.append(item)
    return out
