from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


LOGGER = logging.getLogger("data_fetcher_daemon")
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


_FETCH_INTERVAL_MIN = float(os.environ.get("FETCH_INTERVAL_MIN_SEC", "0.8"))
_FETCH_INTERVAL_MAX = float(os.environ.get("FETCH_INTERVAL_MAX_SEC", "1.6"))
_REFRESH_INTERVAL_MIN = float(os.environ.get("REFRESH_INTERVAL_MIN", "15"))
_WATCHLIST_REFRESH_MIN = float(os.environ.get("WATCHLIST_REFRESH_MIN", "10"))
_MAX_429_15MIN = int(os.environ.get("MAX_429_15MIN", "4"))
_GLOBAL_PAUSE_SEC_ON_RISK = int(os.environ.get("GLOBAL_PAUSE_SEC_ON_RISK", "600"))
_BOOTSTRAP_EXTRA_SYMBOLS = [s.strip() for s in os.environ.get("BOOTSTRAP_EXTRA_SYMBOLS", "0700,0005,0388,2318,0027,0011,1299,0823,0001").split(",") if s.strip()]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts_now() -> int:
    return int(_utc_now().timestamp())


def _resolve_seed_symbols_from_watchlist() -> Set[str]:
    """Best-effort watchlist load from Firestore. Failures degrade to seed list only."""
    out: Set[str] = set()
    try:
        from watchlist_storage import get_watchlist_from_firestore
        try:
            import firebase_admin  # type: ignore
            from firebase_admin import credentials, firestore  # type: ignore
            if not firebase_admin._apps:
                cred_path = os.environ.get("FIREBASE_ADMIN_CREDENTIAL_JSON")
                if cred_path and os.path.isfile(cred_path):
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                else:
                    # Try GOOGLE_APPLICATION_CREDENTIALS default
                    try:
                        firebase_admin.initialize_app()
                    except Exception:
                        LOGGER.info("Firebase app not initialized; watchlist pre-seed skipped.")
                        return out
            db = firestore.client()
            wl = get_watchlist_from_firestore(db) or {}
            for raw in wl.keys():
                try:
                    from data_ingest_stack import get_yahoo_ticker
                    out.add(str(get_yahoo_ticker(raw)).strip().upper())
                except Exception:
                    continue
            LOGGER.info("Pre-seeded %d watchlist symbols from Firestore.", len(out))
        except Exception as exc:
            LOGGER.warning("Unable to seed from Firestore watchlist: %s", exc)
    except Exception:
        pass
    return out


class DaemonState:
    def __init__(self):
        self.stop_event = threading.Event()
        self.pause_until_ts = 0
        self._lock = threading.RLock()
        self.total_processed = 0
        self.total_ok = 0
        self.total_fail = 0
        self._recent_429_ts: List[int] = []
        # per-symbol result bookkeeping for summaries: {symbol: dict(ok, error_msg, source, rows, last_close, last_trade_date, ts)}
        self.per_symbol_results: Dict[str, Dict[str, Any]] = {}

    def is_paused(self) -> bool:
        return self.pause_until_ts > _ts_now()

    def set_pause(self, duration_sec: int, reason: str = "") -> None:
        with self._lock:
            self.pause_until_ts = max(self.pause_until_ts, _ts_now() + int(duration_sec))
        if reason:
            LOGGER.warning("GLOBAL PAUSE %d sec. Reason: %s", int(duration_sec), reason)

    def record_429(self) -> int:
        now = _ts_now()
        with self._lock:
            self._recent_429_ts.append(now)
            cutoff = now - 15 * 60
            self._recent_429_ts = [t for t in self._recent_429_ts if t >= cutoff]
            return len(self._recent_429_ts)


def _process_one_symbol(state: DaemonState, symbol: str, max_retry: int = 1) -> bool:
    """Claim pending, fetch, cache. Returns True on success."""
    from cache_layer import (
        claim_pending,
        get_cached_ohlcv,
        mark_fetch_done,
        mark_fetch_failed,
        upsert_ohlcv,
    )
    from data_ingest_stack import get_data_stack

    sym = str(symbol).strip().upper()
    if not claim_pending(sym):
        return False  # another worker beat us; not an error

    error_msg: Optional[str] = None
    source_route: Optional[str] = None
    ok = False
    rows_out: Optional[int] = None
    last_close_out: Optional[float] = None
    last_trade_date_out: Optional[str] = None
    try:
        # Bypass cache hit check (queue = caller decided it's time to refresh) but allow fallback.
        df, share_base = get_data_stack(sym, end_date=None)
        if df is None or len(df) < 10 or share_base is None:
            # If pure fetch failed, check if stale cache exists to avoid totally blank state.
            _df_old, _sb_old, status = get_cached_ohlcv(sym, max_age_sec=None, bump_stats=False)
            if df is None and _df_old is not None and len(_df_old) > 10:
                # Do NOT overwrite cache with stale; just log and let status be failed.
                error_msg = "Fetch failed but stale cache exists."
                LOGGER.warning("[%s] fetch failed, stale cache retained (status=%s).", sym, status)
            else:
                error_msg = f"get_data_stack returned short/empty df (rows={0 if df is None else len(df)})"
        else:
            # Try to determine source route for diagnostics.
            try:
                from data_ingest_stack import _NATIVE_DOWNLOAD_STATS
                for key in ("sina_success", "stooq_success", "yf_success", "native_success"):
                    val = _NATIVE_DOWNLOAD_STATS.get(key, 0)
                    prev = _NATIVE_DOWNLOAD_STATS.get(f"__prev_{key}", 0)
                    if val and val > prev:
                        source_route = key.split("_")[0]
                        _NATIVE_DOWNLOAD_STATS[f"__prev_{key}"] = val
                        break
            except Exception:
                source_route = None
            upsert_ohlcv(sym, df, share_base=share_base, source=(source_route or "stack"))
            mark_fetch_done(sym)
            ok = True
            # F3: re-read from cache metadata to guarantee last_valid_close / last_trade_date are populated correctly
            try:
                df_refresh, _sb_refresh, _status_refresh = get_cached_ohlcv(sym, max_age_sec=0, bump_stats=False)
                rows_out = int(len(df_refresh)) if df_refresh is not None else int(len(df))
                close_s = pd.to_numeric(df_refresh["Close"], errors="coerce").replace(0, np.nan).dropna() if df_refresh is not None else pd.Series(dtype=float)
                if len(close_s):
                    last_close_out = float(close_s.iloc[-1])
                elif len(df):
                    close_fb = pd.to_numeric(df["Close"], errors="coerce").replace(0, np.nan).dropna()
                    if len(close_fb):
                        last_close_out = float(close_fb.iloc[-1])
                try:
                    target_df = df_refresh if df_refresh is not None and len(df_refresh) else df
                    if target_df is not None and len(target_df):
                        last_trade_date_out = str(pd.to_datetime(target_df.index[-1]).date())
                except Exception:
                    last_trade_date_out = None
            except Exception:
                rows_out = int(len(df))
                close_fb = pd.to_numeric(df["Close"], errors="coerce").replace(0, np.nan).dropna()
                if len(close_fb):
                    last_close_out = float(close_fb.iloc[-1])
                try:
                    last_trade_date_out = str(pd.to_datetime(df.index[-1]).date())
                except Exception:
                    last_trade_date_out = None
            with state._lock:
                state.total_processed += 1
                state.total_ok += 1
            LOGGER.info("[%s] OK rows=%s close=%s source=%s share_base=%s ltd=%s",
                        sym,
                        rows_out,
                        ("%.2f" % float(last_close_out)) if last_close_out is not None else "None",
                        source_route or "?",
                        f"{float(share_base):.2f}" if share_base is not None else "None",
                        last_trade_date_out or "None")
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)[:300]}"
        LOGGER.exception("[%s] Exception during fetch pipeline.", sym)
    # Fall through = failure path.
    if not ok:
        if error_msg is None:
            error_msg = "unknown failure"
        if any(k in error_msg for k in ("429", "Too Many Requests", "RateLimit")):
            n_429 = state.record_429()
            if n_429 >= _MAX_429_15MIN:
                state.set_pause(_GLOBAL_PAUSE_SEC_ON_RISK,
                                f"{n_429} 429s within 15 min > threshold {_MAX_429_15MIN}.")
        mark_fetch_failed(sym, error_msg)
        with state._lock:
            state.total_processed += 1
            state.total_fail += 1
        LOGGER.warning("[%s] FAIL. %s", sym, error_msg)
    # Record per-symbol bookkeeping (atomic update).
    with state._lock:
        state.per_symbol_results[sym] = {
            "ok": bool(ok),
            "error_msg": None if ok else str(error_msg),
            "source": source_route,
            "rows": rows_out,
            "last_close": last_close_out,
            "last_trade_date": last_trade_date_out,
            "ts": _ts_now(),
        }
    return bool(ok)


def queue_worker_thread(state: DaemonState) -> None:
    from cache_layer import peek_next_pending

    LOGGER.info("Queue worker started. Interval %.1fs~%.1fs between symbols.",
                _FETCH_INTERVAL_MIN, _FETCH_INTERVAL_MAX)

    while not state.stop_event.is_set():
        try:
            if state.is_paused():
                time.sleep(5.0)
                continue

            pending = peek_next_pending(limit=1)
            if not pending:
                time.sleep(2.5)
                continue

            item = pending[0]
            symbol = str(item.get("symbol", "")).strip().upper()
            if not symbol:
                time.sleep(1.0)
                continue

            _process_one_symbol(state, symbol)

            # Throttle between ANY two fetches (success or fail) to preserve IP reputation.
            delay = random.uniform(_FETCH_INTERVAL_MIN, _FETCH_INTERVAL_MAX)
            slept = 0.0
            while slept < delay and not state.stop_event.is_set():
                slice_ = min(0.5, delay - slept)
                time.sleep(slice_)
                slept += slice_
        except Exception as exc:
            LOGGER.exception("Queue worker unexpected error: %s", exc)
            time.sleep(5.0)
    LOGGER.info("Queue worker stopped.")


def scheduled_refresh_thread(state: DaemonState) -> None:
    """Every REFRESH_INTERVAL_MIN, enqueue EVERY cached/watchlist symbol for refresh."""
    from cache_layer import list_cached_symbols, request_async_fetch

    LOGGER.info("Scheduled refresher started. Interval=%.1f min.", _REFRESH_INTERVAL_MIN)
    boot_done = False

    while not state.stop_event.is_set():
        try:
            targets: Set[str] = set()
            # From watchlist (dynamic)
            try:
                targets |= _resolve_seed_symbols_from_watchlist()
            except Exception:
                pass
            # Bootstrap default
            for s in _BOOTSTRAP_EXTRA_SYMBOLS:
                try:
                    from data_ingest_stack import get_yahoo_ticker
                    targets.add(str(get_yahoo_ticker(s)).strip().upper())
                except Exception:
                    continue
            # From currently cached symbols
            try:
                cached = list_cached_symbols(limit=500) or []
                for r in cached:
                    sym = str(r.get("symbol", "")).strip().upper()
                    if sym:
                        targets.add(sym)
            except Exception:
                pass

            queued_count = 0
            for sym in sorted(targets):
                try:
                    res = request_async_fetch(sym)
                    if res in {"QUEUED", "ALREADY_PENDING"}:
                        queued_count += 1
                except Exception:
                    continue
            LOGGER.info("Refresh sweep done. Unique targets=%d newly_queued_or_pending=%d processed_ok=%d fail=%d pause=%ss",
                        len(targets), queued_count, state.total_ok, state.total_fail,
                        max(0, state.pause_until_ts - _ts_now()))
            boot_done = True
        except Exception as exc:
            LOGGER.exception("Scheduled refresher error: %s", exc)

        # Sleep until next round, but wake early on stop.
        sleep_until_ts = _ts_now() + int(max(1.0, _REFRESH_INTERVAL_MIN) * 60)
        if not boot_done:
            sleep_until_ts = _ts_now() + 5  # first run, fast enqueue
        while not state.stop_event.is_set() and _ts_now() < sleep_until_ts:
            time.sleep(5.0)
    LOGGER.info("Scheduled refresher stopped.")


def ip_risk_monitor_thread(state: DaemonState) -> None:
    from cache_layer import get_all_stats

    LOGGER.info("IP risk monitor started. 429 threshold=%d / 15min pause=%d s.",
                _MAX_429_15MIN, _GLOBAL_PAUSE_SEC_ON_RISK)
    while not state.stop_event.is_set():
        try:
            stats = get_all_stats() or {}
            fetch_429 = int(stats.get("fetch_429", 0))
            queue_depth = 0
            try:
                from cache_layer import get_queue_depth
                q = get_queue_depth() or {}
                queue_depth = int(q.get("PENDING", 0) or 0) + int(q.get("FETCHING", 0) or 0)
            except Exception:
                pass
            LOGGER.info("IP monitor stats: fetch_429_total=%d ok=%d fail=%d queue_depth=%d pause=%ss",
                        fetch_429, state.total_ok, state.total_fail, queue_depth,
                        max(0, state.pause_until_ts - _ts_now()))
        except Exception:
            pass
        # Sleep in 10s slices to remain responsive to stop.
        for _ in range(6):
            if state.stop_event.is_set():
                break
            time.sleep(10.0)
    LOGGER.info("IP risk monitor stopped.")


def _install_signal_handlers(state: DaemonState) -> None:
    def _handler(signum, frame):
        LOGGER.info("Signal %s received: requesting graceful shutdown.", signum)
        state.stop_event.set()

    try:
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
    except Exception:
        # Windows / restricted environments may not have all signals.
        pass


def _write_github_step_summary(state: "DaemonState", is_once_mode: bool) -> None:
    """Best-effort GITHUB_STEP_SUMMARY writer. Does nothing outside GHA."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        from cache_layer import (  # noqa: WPS433 lazy local import
            get_all_stats,
            get_cache_db_path,
            list_cached_symbols,
        )
        db = get_cache_db_path()
        stats = get_all_stats(db_path=db) or {}
        rows = list_cached_symbols(db_path=db, limit=20) or []
        n_429_recent = len([t for t in state._recent_429_ts if _ts_now() - t <= 15 * 60])
        pause_left = max(0, state.pause_until_ts - _ts_now())
        # Build per-symbol run results (ok + failures) sorted by ts desc
        ok_rows = [
            {"symbol": k, **v}
            for k, v in state.per_symbol_results.items()
            if bool(v.get("ok"))
        ]
        fail_rows = [
            {"symbol": k, **v}
            for k, v in state.per_symbol_results.items()
            if not bool(v.get("ok"))
        ]
        ok_rows.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
        fail_rows.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
        lines: List[str] = []
        lines.append(f"# Data Fetcher Summary (mode={'once' if is_once_mode else 'daemon'})")
        lines.append("")
        lines.append("## Final process stats")
        lines.append("")
        lines.append(f"- processed = **{state.total_processed}**")
        lines.append(f"- ok = **{state.total_ok}**")
        lines.append(f"- fail = **{state.total_fail}**")
        lines.append(f"- 429_15min_window = **{n_429_recent}**")
        lines.append(f"- global_paused_until_ts = **{state.pause_until_ts}** (left={pause_left}s)")
        lines.append(f"- cache_db = `{db}`")
        lines.append("")
        lines.append(f"## Failed symbols this run ({len(fail_rows)})")
        lines.append("")
        if fail_rows:
            lines.append("| symbol | error_msg | ts |")
            lines.append("| :--- | :--- | ---: |")
            for r in fail_rows[:50]:
                err = str(r.get("error_msg") or "").replace("|", "\\|").replace("\n", " ")
                if len(err) > 200:
                    err = err[:200] + "…"
                lines.append(f"| {r.get('symbol')} | {err} | {r.get('ts')} |")
        else:
            lines.append("_None._")
        lines.append("")
        lines.append(f"## Successful symbols this run ({len(ok_rows)})")
        lines.append("")
        if ok_rows:
            lines.append("| symbol | rows | source | last_close | last_trade_date |")
            lines.append("| :--- | ---: | :--- | ---: | :--- |")
            for r in ok_rows[:50]:
                lines.append(
                    f"| {r.get('symbol')} | {r.get('rows')} | {r.get('source')} | "
                    f"{r.get('last_close')} | {r.get('last_trade_date')} |"
                )
        else:
            lines.append("_None._")
        lines.append("")
        lines.append("## Fetcher stats (from SQLite fetcher_stats)")
        lines.append("")
        if stats:
            lines.append("| metric | value |")
            lines.append("| :--- | ---: |")
            for k, v in sorted(stats.items()):
                lines.append(f"| `{k}` | `{v}` |")
        else:
            lines.append("_no stats collected yet_")
        lines.append("")
        lines.append(f"## Top {len(rows)} cached symbols (SQLite by last_refresh_ts)")
        lines.append("")
        lines.append("| symbol | rows | source | last_valid_close | last_trade_date |")
        lines.append("| :--- | ---: | :--- | ---: | :--- |")
        for r in rows:
            lines.append(
                f"| {r.get('symbol')} | {r.get('rows')} | {r.get('source')} | "
                f"{r.get('last_valid_close')} | {r.get('last_trade_date')} |"
            )
        payload = "\n".join(lines) + "\n"
        try:
            with open(summary_path, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError:
            try:
                with open(summary_path, "w") as fh:
                    fh.write(payload)
            except OSError as exc:
                LOGGER.warning("Unable to write GITHUB_STEP_SUMMARY: %s", exc)
    except Exception as exc:  # noqa: BLE001 never fail CI because of summary
        LOGGER.warning("GITHUB_STEP_SUMMARY build skipped: %s", exc)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HK Stock SMA Data Fetcher Daemon (SQLite cache + queue).")
    parser.add_argument("--once", action="store_true",
                        help="Run one bootstrap refresh then exit (useful for first-time seed).")
    parser.add_argument("--symbol", action="append", default=[],
                        help="Immediately enqueue specific ticker(s) (repeatable).")
    args = parser.parse_args(argv or sys.argv[1:])

    state = DaemonState()
    rc = 0
    is_once_mode = bool(args.once)

    try:
        # Side-effect: ensure cache schema exists ASAP.
        from cache_layer import ensure_schema, request_async_fetch
        ensure_schema(None)

        _install_signal_handlers(state)

        # Side-effect import pandas for the log line in _process_one_symbol (avoid global import).
        global pd
        import pandas as pd  # noqa: F401 (used in closure)

        LOGGER.info("Daemon starting. cache_db=%s refresh_interval=%.1fmin fetch_interval=%.1f~%.1fs",
                    __import__("cache_layer").get_cache_db_path(None),
                    _REFRESH_INTERVAL_MIN, _FETCH_INTERVAL_MIN, _FETCH_INTERVAL_MAX)

        if args.symbol:
            for raw in args.symbol:
                try:
                    from data_ingest_stack import get_yahoo_ticker
                    sym = str(get_yahoo_ticker(raw)).strip().upper()
                    res = request_async_fetch(sym)
                    LOGGER.info("Immediate enqueue %s -> %s", sym, res)
                except Exception as exc:
                    LOGGER.warning("Failed to enqueue symbol %s: %s", raw, exc)

        threads: List[threading.Thread] = []
        if not is_once_mode:
            threads.append(threading.Thread(target=queue_worker_thread, args=(state,), name="queue-worker", daemon=True))
            threads.append(threading.Thread(target=scheduled_refresh_thread, args=(state,), name="scheduler", daemon=True))
            threads.append(threading.Thread(target=ip_risk_monitor_thread, args=(state,), name="risk-monitor", daemon=True))
            for t in threads:
                t.start()

            # Block main thread on stop_event.
            try:
                while not state.stop_event.is_set():
                    time.sleep(2.0)
            except KeyboardInterrupt:
                LOGGER.info("KeyboardInterrupt received.")
                state.stop_event.set()

            for t in threads:
                LOGGER.info("Joining thread %s...", t.name)
                t.join(timeout=15.0)
        else:
            # Bootstrap single run.
            LOGGER.info("--once mode: running single refresh + queue drain.")
            scheduled_refresh_thread_once(state)
            LOGGER.info("--once bootstrap finished. ok=%d fail=%d", state.total_ok, state.total_fail)
            if state.total_fail > 0 and state.total_ok == 0:
                rc = 1
                LOGGER.warning("--once exit code -> 1 (all targets failed or no cache seeded).")
            elif state.total_fail > 0:
                rc = 0
                LOGGER.info("--once partial success, warn-level only (rc stays 0 so artifact uploads): ok=%d fail=%d",
                            state.total_ok, state.total_fail)
            else:
                rc = 0

        LOGGER.info("Daemon main finished. Final stats: processed=%d ok=%d fail=%d",
                    state.total_processed, state.total_ok, state.total_fail)
    except Exception as exc:  # noqa: BLE001 — top-level safety net
        rc = 1
        LOGGER.exception("Fatal exception in main(). rc forced to 1.")
        # Preserve per-symbol failure summary at top of GHA summary for quick debug.
        try:
            state.per_symbol_results["__FATAL__"] = {
                "ok": False,
                "error_msg": f"FATAL {type(exc).__name__}: {str(exc)[:400]}",
                "source": None, "rows": None, "last_close": None, "last_trade_date": None,
                "ts": _ts_now(),
            }
        except Exception:
            pass

    # Always best-effort write summary (even on fatal exception) so we have debug info.
    try:
        _write_github_step_summary(state, is_once_mode)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("summary write skipped: %s", exc)
    LOGGER.info("Daemon exit. rc=%d Final stats: processed=%d ok=%d fail=%d",
                rc, state.total_processed, state.total_ok, state.total_fail)
    return rc


def scheduled_refresh_thread_once(state: DaemonState) -> None:
    """For --once mode: same logic as scheduled loop but single pass + drain queue."""
    from cache_layer import list_cached_symbols, request_async_fetch, peek_next_pending

    targets: Set[str] = set()
    try:
        targets |= _resolve_seed_symbols_from_watchlist()
    except Exception:
        pass
    for s in _BOOTSTRAP_EXTRA_SYMBOLS:
        try:
            from data_ingest_stack import get_yahoo_ticker
            targets.add(str(get_yahoo_ticker(s)).strip().upper())
        except Exception:
            continue
    try:
        cached = list_cached_symbols(limit=500) or []
        for r in cached:
            sym = str(r.get("symbol", "")).strip().upper()
            if sym:
                targets.add(sym)
    except Exception:
        pass
    for sym in sorted(targets):
        try:
            request_async_fetch(sym)
        except Exception:
            continue

    # Drain queue.
    drain_deadline = _ts_now() + 3600 * 6  # safety cap 6h
    while not state.stop_event.is_set() and _ts_now() < drain_deadline:
        if state.is_paused():
            time.sleep(5.0)
            continue
        pending = peek_next_pending(limit=1)
        if not pending:
            break
        item = pending[0]
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol:
            time.sleep(0.5)
            continue
        _process_one_symbol(state, symbol)
        delay = random.uniform(_FETCH_INTERVAL_MIN, _FETCH_INTERVAL_MAX)
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())
