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


def _load_legacy_watchlist(db) -> Dict[str, Dict[str, Any]]:
    legacy_watchlist: Dict[str, Dict[str, Any]] = {}
    root_doc = _root_doc_ref(db).get()
    raw = root_doc.to_dict() if root_doc.exists else {}
    if not isinstance(raw, dict) or not raw:
        return legacy_watchlist

    for raw_key, raw_value in raw.items():
        ticker = clean_watchlist_symbol(raw_key)
        if not ticker:
            continue
        legacy_watchlist[ticker] = normalize_watchlist_params(raw_value)

    return legacy_watchlist


def _sync_legacy_watchlist_to_items(db, legacy_watchlist: Dict[str, Dict[str, Any]]) -> None:
    items_ref = _items_collection_ref(db)
    for ticker, params in legacy_watchlist.items():
        try:
            items_ref.document(ticker).set(
                {
                    "ticker": ticker,
                    "params": params,
                },
                merge=True,
            )
        except Exception:
            # Legacy data should still be readable even if background sync fails.
            continue


def get_watchlist_from_firestore(db) -> Dict[str, Dict[str, Any]]:
    watchlist: Dict[str, Dict[str, Any]] = {}

    try:
        for doc in _items_collection_ref(db).stream():
            payload = doc.to_dict() or {}
            ticker = clean_watchlist_symbol(payload.get("ticker") or doc.id)
            if not ticker:
                continue
            params = payload.get("params", payload)
            watchlist[ticker] = normalize_watchlist_params(params)
    except Exception:
        pass

    try:
        legacy_watchlist = _load_legacy_watchlist(db)
        if legacy_watchlist:
            _sync_legacy_watchlist_to_items(db, legacy_watchlist)
        for ticker, params in legacy_watchlist.items():
            watchlist.setdefault(ticker, params)
    except Exception:
        pass

    return watchlist


def save_watchlist_symbol(db, symbol: object, params: Any = None) -> str:
    ticker = clean_watchlist_symbol(symbol)
    if not ticker:
        raise ValueError("Ticker is empty.")

    normalized_params = normalize_watchlist_params(params)

    root_ok = False
    try:
        _root_doc_ref(db).set({ticker: normalized_params}, merge=True)
        root_ok = True
    except Exception:
        root_ok = False

    try:
        _items_collection_ref(db).document(ticker).set(
            {
                "ticker": ticker,
                "params": normalized_params,
            },
            merge=True,
        )
    except Exception:
        pass

    if not root_ok:
        raise RuntimeError(
            "Failed to write watchlist to Firestore root document. "
            "Subcollection write may also have been skipped silently."
        )

    return ticker


def delete_watchlist_symbol(db, symbol: object) -> str:
    ticker = clean_watchlist_symbol(symbol)
    if not ticker:
        raise ValueError("Ticker is empty.")

    root_ok = False
    try:
        from firebase_admin import firestore as _firestore

        _root_doc_ref(db).update({ticker: _firestore.DELETE_FIELD})
        root_ok = True
    except Exception:
        root_ok = False

    try:
        _items_collection_ref(db).document(ticker).delete()
    except Exception:
        pass

    if not root_ok:
        raise RuntimeError(
            "Failed to delete watchlist from Firestore root document. "
            "Subcollection delete may also have been skipped silently."
        )

    return ticker
