import unittest

from watchlist_storage import (
    DEFAULT_WATCHLIST_PARAMS,
    delete_watchlist_symbol,
    get_watchlist_from_firestore,
    save_watchlist_symbol,
)


class FakeSnapshot:
    def __init__(self, exists, data):
        self.exists = exists
        self._data = data

    def to_dict(self):
        return dict(self._data) if isinstance(self._data, dict) else self._data


class FakeDocumentRef:
    def __init__(self, store, path):
        self._store = store
        self._path = tuple(path)
        self._subcollections = {}

    def _node(self):
        return self._store.setdefault(self._path, {"data": None, "exists": False})

    def set(self, data, merge=False):
        node = self._node()
        if merge and isinstance(node["data"], dict):
            merged = dict(node["data"])
            merged.update(data)
            node["data"] = merged
        else:
            node["data"] = dict(data)
        node["exists"] = True

    def get(self):
        node = self._store.get(self._path, {"data": None, "exists": False})
        return FakeSnapshot(node["exists"], node["data"] or {})

    def delete(self):
        node = self._node()
        node["data"] = {}
        node["exists"] = False

    def collection(self, name):
        key = (self._path, name)
        if key not in self._subcollections:
            self._subcollections[key] = FakeCollectionRef(self._store, self._path + (name,))
        return self._subcollections[key]


class FakeCollectionRef:
    def __init__(self, store, path):
        self._store = store
        self._path = tuple(path)
        self._documents = {}

    def document(self, doc_id):
        key = self._path + (doc_id,)
        if key not in self._documents:
            self._documents[key] = FakeDocumentRef(self._store, key)
        return self._documents[key]

    def stream(self):
        prefix = self._path
        for path, node in self._store.items():
            if path[: len(prefix)] != prefix or len(path) != len(prefix) + 1:
                continue
            if node["exists"]:
                yield FakeStreamDocument(path[-1], node["data"] or {})


class FakeStreamDocument:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class FakeDB:
    def __init__(self):
        self._store = {}
        self._collections = {}

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollectionRef(self._store, (name,))
        return self._collections[name]


class WatchlistStorageTests(unittest.TestCase):
    def test_save_uses_subcollection_document(self):
        db = FakeDB()

        ticker = save_watchlist_symbol(db, "290")

        self.assertEqual(ticker, "290")
        data = get_watchlist_from_firestore(db)
        self.assertIn("290", data)
        self.assertEqual(data["290"]["box1_start"], "")
        self.assertEqual(data["290"]["cdm_p1_avg_override"], 0.0)

    def test_delete_removes_subcollection_document(self):
        db = FakeDB()
        save_watchlist_symbol(db, "00290")

        delete_watchlist_symbol(db, "00290")

        self.assertEqual(get_watchlist_from_firestore(db), {})

    def test_legacy_root_document_is_migrated(self):
        db = FakeDB()
        root_doc = db.collection("stock_app").document("watchlist")
        root_doc.set({"00290": {"box1_start": "2026-08-25"}})

        data = get_watchlist_from_firestore(db)

        self.assertIn("00290", data)
        self.assertEqual(data["00290"]["box1_start"], "2026-08-25")
        self.assertTrue(root_doc.get().exists)

    def test_legacy_and_new_storage_are_merged(self):
        db = FakeDB()
        root_doc = db.collection("stock_app").document("watchlist")
        root_doc.set({"00290": {"box1_start": "2026-08-25"}})
        save_watchlist_symbol(db, "2577", {"box1_end": "2026-08-26"})

        data = get_watchlist_from_firestore(db)

        self.assertIn("00290", data)
        self.assertIn("2577", data)

    def test_partial_params_are_normalized(self):
        db = FakeDB()

        save_watchlist_symbol(db, "9630", {"box1_start": "2026-08-20"})

        row = get_watchlist_from_firestore(db)["9630"]
        self.assertEqual(row["box1_start"], "2026-08-20")
        self.assertEqual(set(DEFAULT_WATCHLIST_PARAMS).issubset(row.keys()), True)


if __name__ == "__main__":
    unittest.main()
