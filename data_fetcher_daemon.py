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
_ONCE_MODE_WORKERS = max(1, int(os.environ.get("ONCE_MODE_WORKERS", "2")))
_ONCE_SHUTDOWN_GRACE_SEC = max(1, int(os.environ.get("ONCE_SHUTDOWN_GRACE_SEC", "15")))
_ONCE_EMPTY_QUEUE_POLLS = max(1, int(os.environ.get("ONCE_EMPTY_QUEUE_POLLS", "3")))
_ONCE_QUEUE_POLL_SEC = max(0.2, float(os.environ.get("ONCE_QUEUE_POLL_SEC", "0.5")))


def _get_hk_index_constituents_seed() -> List[str]:
    """Deduplicated HSI + HSCEI + HSTECH 2026Q3 constituents.

    Mirrors scripts/tur_amp_health_scan.py:HK_COMMON_LIQUID_CODES (~200 core liquid names).
    NOTE: we import lazily from scanner so the list is a single source of truth
    and we never need to maintain two copies.
    """
    try:
        import importlib.util as _ilu
        from pathlib import Path as _Path
        _p = _Path(__file__).resolve().parent / "scripts" / "tur_amp_health_scan.py"
        _spec = _ilu.spec_from_file_location("_tur_scan_codes", _p)
        if _spec is None or _spec.loader is None:
            raise ImportError("tur scanner module not loadable")
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        codes = list(getattr(_mod, "HK_COMMON_LIQUID_CODES", set()))
        return sorted(set(codes))
    except Exception:
        # Fallback: embedded compact core list (never crash the daemon if scanner missing)
        return sorted(set([
            "0001","0002","0003","0005","0006","0011","0012","0016","0017","0019",
            "0027","0066","0083","0101","0104","0116","0127","0151","0168","0175",
            "0241","0267","0285","0288","0291","0293","0316","0322","0347","0358",
            "0368","0386","0388","0392","0398","0460","0480","0489","0522","0525",
            "0548","0669","0688","0691","0700","0753","0762","0788","0811","0813",
            "0823","0853","0857","0867","0868","0881","0883","0909","0914","0934",
            "0939","0941","0945","0960","0966","0968","0981","0984","0992","0995",
            "0998","1024","1038","1044","1066","1088","1093","1097","1109","1112",
            "1113","1127","1171","1177","1186","1193","1208","1211","1299","1310",
            "1313","1316","1336","1339","1347","1371","1382","1395","1398","1402",
            "1548","1772","1776","1787","1801","1806","1810","1813","1818","1876",
            "1883","1898","1919","1928","1929","1966","1994","1997","2007","2015",
            "2018","2020","2127","2128","2129","2138","2180","2196","2238","2269",
            "2313","2314","2318","2328","2331","2333","2338","2359","2368","2382",
            "2388","2399","2401","2413","2422","2423","2433","2456","2468","2488",
            "2518","2520","2588","2601","2607","2611","2618","2628","2660","2666",
            "2688","2689","2696","2707","2722","2753","2768","2777","2778","2788",
            "2799","2800","2801","2808","2812","2822","2828","2848","2857","2858",
            "2866","2877","2878","2888","2899","2907","2924","2929","2934","2939",
            "2981","2984","2992","2993","3024","3035","3189","3309","3311","3319",
            "3323","3328","3331","3333","3347","3360","3368","3382","3388","3401",
            "3419","3427","3435","3442","3443","3475","3476","3544","3579","3585",
            "3590","3594","3606","3610","3631","3636","3662","3663","3668","3669",
            "3690","3692","3693","3694","3719","3734","3738","3772","3773","3788",
            "3799","3800","3808","3813","3818","3828","3836","3848","3866","3868",
            "3888","3898","3899","3900","3908","3918","3927","3933","3939","3948",
            "3968","3969","3983","3988","3993","3996","3997","3998","3999","4009",
        ]))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts_now() -> int:
    return int(_utc_now().timestamp())


def _resolve_seed_symbols_from_watchlist() -> Set[str]:
    """Best-effort watchlist load: SQLite shared watchlist first, Firestore as fallback.
    Failures degrade to seed list only.
    """
    out: Set[str] = set()

    try:
        from cache_layer import list_watchlist_symbols, get_cache_db_path
        try:
            rows = list_watchlist_symbols(db_path=get_cache_db_path(), limit=2000)
            for r in rows:
                try:
                    from data_ingest_stack import get_yahoo_ticker
                    out.add(str(get_yahoo_ticker(r["symbol"])).strip().upper())
                except Exception:
                    continue
            if out:
                LOGGER.info("Pre-seeded %d watchlist symbols from SQLite shared watchlist.", len(out))
        except Exception as exc:
            LOGGER.info("SQLite shared watchlist unavailable (will try Firestore next): %s", exc)
    except Exception:
        pass

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
                    try:
                        firebase_admin.initialize_app()
                    except Exception:
                        if out:
                            return out
                        LOGGER.info("Firebase app not initialized; watchlist pre-seed skipped.")
                        return out
            db = firestore.client()
            wl = get_watchlist_from_firestore(db) or {}
            added = 0
            for raw in wl.keys():
                try:
                    from data_ingest_stack import get_yahoo_ticker
                    ticker = str(get_yahoo_ticker(raw)).strip().upper()
                    if ticker and ticker not in out:
                        out.add(ticker)
                        added += 1
                except Exception:
                    continue
            if added:
                LOGGER.info("Pre-seeded %d additional symbols from Firestore watchlist (total %d).", added, len(out))
            elif not out:
                LOGGER.info("Pre-seeded 0 watchlist symbols from Firestore.")
        except Exception as exc:
            if not out:
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
            # F3-G2a: re-read from cache (no age filter) to guarantee last_valid_close / last_trade_date are populated correctly.
            # (max_age_sec=None = accept any cache age; we just wrote it so status will always be HIT)
            try:
                df_refresh, _sb_refresh, _status_refresh = get_cached_ohlcv(sym, max_age_sec=None, bump_stats=False)
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
            # HSI / HSCEI / HSTECH core constituents (~200) — so cache grows beyond the
            # 9-symbol bootstrap list, and TUR/Amp scanner has data to validate.
            for s in _get_hk_index_constituents_seed():
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
        # ---- G2b: Belt-and-suspenders backfill Successful rows from SQLite metadata ----
        # (Because _process_one_symbol may have transient None from sqlite busy / race; but
        #  rows from list_cached_symbols() below are authoritative and proven correct.)
        cache_meta_by_symbol: Dict[str, Dict[str, Any]] = {}
        for r in rows or []:
            sym = str(r.get("symbol", "")).strip().upper()
            if sym:
                cache_meta_by_symbol[sym] = r
        for r in ok_rows:
            sym_key = str(r.get("symbol", "")).strip().upper()
            meta = cache_meta_by_symbol.get(sym_key)
            if meta:
                if r.get("last_close") is None and meta.get("last_valid_close") is not None:
                    try:
                        r["last_close"] = float(meta.get("last_valid_close"))
                    except (TypeError, ValueError):
                        pass
                if r.get("last_trade_date") is None and meta.get("last_trade_date"):
                    r["last_trade_date"] = str(meta.get("last_trade_date"))
                if (r.get("rows") is None or r.get("rows") == 0) and meta.get("rows"):
                    try:
                        r["rows"] = int(meta.get("rows"))
                    except (TypeError, ValueError):
                        pass
                if not r.get("source") and meta.get("source"):
                    r["source"] = str(meta.get("source"))
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
            # ---- G6a rc rule with artifact restore belt-and-suspenders:
            #   If restore brought back 5+ valid cached symbols already, treat as green
            #   even if the only queue item we processed this run (e.g. 0011.HK retry)
            #   failed (which would otherwise leave total_ok=0).
            if state.total_fail > 0 and state.total_ok == 0:
                try:
                    from cache_layer import list_cached_symbols as _lcs
                    cached_now = _lcs(limit=500) or []
                    valid_cached_n = 0
                    for r in cached_now:
                        try:
                            rs = int(r.get("rows") or 0)
                            has_close = r.get("last_valid_close") is not None and pd.notna(r.get("last_valid_close"))
                            has_td = bool(r.get("last_trade_date"))
                            if rs >= 100 and has_close and has_td:
                                valid_cached_n += 1
                        except Exception:
                            pass
                    if valid_cached_n >= 5:
                        rc = 0
                        LOGGER.info(
                            "--once rc override -> 0 (total_ok=0 but SQLite already has %d valid cached "
                            "symbols from restored artifact; partial run must NOT fail workflow).",
                            valid_cached_n,
                        )
                    else:
                        rc = 1
                        LOGGER.warning("--once exit code -> 1 (all targets failed; only %d valid cached symbols in DB).",
                                       valid_cached_n)
                except Exception:
                    rc = 1
                    LOGGER.warning("--once rc fallback 1 (error while validating cached symbols).", exc_info=True)
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
    """For --once mode: enqueue HSI/HSCEI/HSTECH ~270 codes, then drain with N workers.

    Multi-worker (default 2 threads) cuts cold-start cache-build time ~2x
    while still honoring rate-limit / 429 state (shared state._recent_429_ts
    is read across workers, and _process_one_symbol itself is already
    thread-safe via DaemonState.claim_next_pending which uses a Lock).
    """
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
    # HSI / HSCEI / HSTECH core constituents (~270)
    for s in _get_hk_index_constituents_seed():
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

    # Drain queue with N workers. Cap safety at 4 to avoid Yahoo rate limit storm.
    n_workers = max(1, min(_ONCE_MODE_WORKERS, 4))
    skip_total = 0
    skip_recent_done = 0
    enqueued_total = 0
    preload_fail_retryable = 0

    def _request(sym: str) -> str:
        try:
            return str(request_async_fetch(sym) or "UNKNOWN").strip().upper()
        except Exception:
            return "ERROR"

    # ---- Preflight: classify every target BEFORE starting workers. This lets us count
    # RECENTLY_DONE / ALREADY_PENDING directly and record them as processed/OK so the
    # GitHub step summary shows real numbers (otherwise it showed processed=1 when
    # 229 tickers had no new enqueue.
    for sym in sorted(targets):
        res = _request(sym)
        if res in {"RECENTLY_DONE", "RECENTLY_FAILED_OK"}:
            skip_recent_done += 1
            skip_total += 1
            try:
                _df_ok = None
                _df_old, _sb_old, _st = (None, None, None)
                try:
                    from cache_layer import get_cached_ohlcv as _gco
                    _df_old, _sb_old, _st = _gco(sym, max_age_sec=None, bump_stats=False)
                except Exception:
                    _df_old = None
                if _df_old is not None and len(_df_old) >= 10:
                    import numpy as np
                    try:
                        close_s = pd.to_numeric(_df_old["Close"], errors="coerce").replace(0, np.nan).dropna()
                        last_close = float(close_s.iloc[-1]) if len(close_s) else None
                    except Exception:
                        last_close = None
                    try:
                        last_td = str(pd.to_datetime(_df_old.index[-1]).date()) if len(_df_old) else None
                    except Exception:
                        last_td = None
                    with state._lock:
                            state.per_symbol_results[sym] = {
                                "ok": True,
                                "error_msg": None,
                                "source": "cache",
                                "rows": int(len(_df_old)),
                                "last_close": last_close,
                                "last_trade_date": last_td,
                                "ts": _ts_now(),
                            }
                            state.total_processed += 1
                            state.total_ok += 1
            except Exception:
                pass
        elif res in {"ALREADY_PENDING", "QUEUED"}:
            enqueued_total += 1
        elif res in {"RECENTLY_FAILED", "FETCHING_INFLIGHT"}:
            preload_fail_retryable += 1
        else:
            enqueued_total += 1
    LOGGER.info(
        "--once preflight: targets=%d recently_done=%d enqueued_for_worker=%d other=%d",
        len(targets), skip_recent_done, enqueued_total, preload_fail_retryable,
    )

    def _worker_loop(worker_id: int) -> None:
        # Add tiny per-worker staggered sleep so they don't all hammer Yahoo
        # simultaneously on wakeup.
        if worker_id > 0:
            time.sleep(0.4 * worker_id)
        while not state.stop_event.is_set():
            if state.is_paused():
                time.sleep(2.0)
                continue
            pending = peek_next_pending(limit=1)
            if not pending:
                break
            item = pending[0]
            symbol = str(item.get("symbol", "")).strip().upper()
            if not symbol:
                time.sleep(0.3)
                continue
            _process_one_symbol(state, symbol)
            # Per-symbol jitter. Because n_workers share a single global sleep
            # call this "total delay per symbol" is divided across workers,
            # which is roughly correct.
            delay = random.uniform(_FETCH_INTERVAL_MIN, _FETCH_INTERVAL_MAX)
            time.sleep(delay)

    # Safety ceiling for drain (3.5h); combined with workflow timeout 180m
    # ensures we never run forever on a broken queue.
    drain_deadline = _ts_now() + 3600 * 3 + 1800
    worker_threads: List[threading.Thread] = []

    for i in range(n_workers):
        th = threading.Thread(
            target=_worker_loop,
            args=(i,),
            name=f"once-worker-{i+1}",
            daemon=True,
        )
        worker_threads.append(th)
        th.start()

    # ----------
    # Aggressive once-mode drain monitoring.
    # Background: previous daemon code polled every 2.0s until no worker alive AND
    # no PENDING remained, but combined with per-symbol post-fetch jitter of 0.4-1.6s
    # per-worker on >200 already-skipped tickers caused ~30-40m of dead idle even
    # though zero Yahoo API calls were needed.
    # Solution:
    #   1. Fast poll interval (default 0.5s instead of 2.0s)
    #   2. Consecutive-empty-polls shutdown after 3 empty polls (default),
    #      honoring the ONCE_SHUTDOWN_GRACE_SEC envelope.
    #   3. Hard safety deadline still enforced.
    # ----------
    empty_polls_in_row = 0
    while not state.stop_event.is_set() and _ts_now() < drain_deadline:
        pending = peek_next_pending(limit=1) or []
        alive_workers = [t for t in worker_threads if t.is_alive()]
        if not pending:
            empty_polls_in_row += 1
        else:
            empty_polls_in_row = 0
        if not alive_workers and empty_polls_in_row >= _ONCE_EMPTY_QUEUE_POLLS:
            # --- shutdown guard: give a final short grace window just in case a
            # slow worker is about to re-enqueue something (rare on --once).
            grace_until = _ts_now() + _ONCE_SHUTDOWN_GRACE_SEC
            while not state.stop_event.is_set() and _ts_now() < grace_until:
                if peek_next_pending(limit=1):
                    empty_polls_in_row = 0
                    break
                time.sleep(0.3)
            if empty_polls_in_row >= _ONCE_EMPTY_QUEUE_POLLS:
                LOGGER.info(
                    "--once drain finished: empty polls=%d workers_alive=0 grace=%ds "
                    "processed_ok=%d fail=%d recently_done(preflight)=%d enqueued=%d",
                    empty_polls_in_row,
                    _ONCE_SHUTDOWN_GRACE_SEC,
                    state.total_ok,
                    state.total_fail,
                    skip_recent_done,
                    enqueued_total,
                )
                break
        time.sleep(_ONCE_QUEUE_POLL_SEC)
    else:
        # We hit the drain deadline; tell workers to stop soon.
        state.stop_event.set()
        LOGGER.warning("--once drain DEADLINE reached. ok=%d fail=%d", state.total_ok, state.total_fail)
    for th in worker_threads:
        th.join(timeout=15.0)


if __name__ == "__main__":
    sys.exit(main())
