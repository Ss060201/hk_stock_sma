from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

WATCHLIST_COLLECTION = "stock_app"
WATCHLIST_DOCUMENT = "watchlist"
WATCHLIST_ITEMS_SUBCOLLECTION = "items"

DEFAULT_WATCHLIST_PARAMS: Dict[str, Any] = {
    "box1_start": "",
    "box1_end": "",
    "box2_start": "",
    "box2_end": "",
    "interactive_range_start": "",
    "interactive_range_end": "",
    "abc_date_p1_start": "",
    "abc_date_p1_end": "",
    "abc_date_p2_end": "",
    "abc_price_p1_high": 0.0,
    "abc_price_p1_low": 0.0,
    "abc_price_p2_high": 0.0,
    "cdm_p1_avg_override": 0.0,
    "cdm_p2_avg_override": 0.0,
}


def clean_watchlist_symbol(symbol: object) -> str:
    return str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")


def default_watchlist_params() -> Dict[str, Any]:
    return deepcopy(DEFAULT_WATCHLIST_PARAMS)


def normalize_watchlist_params(params: Any) -> Dict[str, Any]:
    normalized = default_watchlist_params()
    if isinstance(params, dict):
        normalized.update(params)
    return normalized


def _root_doc_ref(db):
    return db.collection(WATCHLIST_COLLECTION).document(WATCHLIST_DOCUMENT)


def _items_collection_ref(db):
    return _root_doc_ref(db).collection(WATCHLIST_ITEMS_SUBCOLLECTION)


def _migrate_legacy_watchlist_if_needed(db) -> Dict[str, Dict[str, Any]]:
    migrated: Dict[str, Dict[str, Any]] = {}
    root_doc = _root_doc_ref(db).get()
    raw = root_doc.to_dict() if root_doc.exists else {}
    if not isinstance(raw, dict) or not raw:
        return migrated

    items_ref = _items_collection_ref(db)
    for raw_key, raw_value in raw.items():
        ticker = clean_watchlist_symbol(raw_key)
        if not ticker:
            continue
        params = normalize_watchlist_params(raw_value)
        items_ref.document(ticker).set(
            {
                "ticker": ticker,
                "params": params,
            },
            merge=True,
        )
        migrated[ticker] = params

    return migrated


def get_watchlist_from_firestore(db) -> Dict[str, Dict[str, Any]]:
    watchlist: Dict[str, Dict[str, Any]] = {}

    for doc in _items_collection_ref(db).stream():
        payload = doc.to_dict() or {}
        ticker = clean_watchlist_symbol(payload.get("ticker") or doc.id)
        if not ticker:
            continue
        params = payload.get("params", payload)
        watchlist[ticker] = normalize_watchlist_params(params)

    legacy_watchlist = _migrate_legacy_watchlist_if_needed(db)
    for ticker, params in legacy_watchlist.items():
        watchlist.setdefault(ticker, params)

    return watchlist


def save_watchlist_symbol(db, symbol: object, params: Any = None) -> str:
    ticker = clean_watchlist_symbol(symbol)
    if not ticker:
        raise ValueError("Ticker is empty.")

    _items_collection_ref(db).document(ticker).set(
        {
            "ticker": ticker,
            "params": normalize_watchlist_params(params),
        },
        merge=True,
    )
    return ticker


def delete_watchlist_symbol(db, symbol: object) -> str:
    ticker = clean_watchlist_symbol(symbol)
    if not ticker:
        raise ValueError("Ticker is empty.")

    _items_collection_ref(db).document(ticker).delete()
    return ticker
