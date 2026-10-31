"""Loads the trained model and sales history once and keeps them in memory, with a copy of the stock tables."""
import threading

import pandas as pd

from app.ml.features import build_feature_frame
from app.ml.predict import load_model


class MlRuntime:
    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._meta = None
        self._frame: pd.DataFrame | None = None
        # A copy of the stock and master tables, so the planning code (which runs in threads) can read them
        # without a database session. The tables are the truth; app.modules.stock refreshes this after every write.
        self._stock: dict[tuple[int, str], float] = {}
        self._cities: dict[str, str] = {}
        self._skus: dict[int, dict] = {}

    def _ensure(self):
        with self._lock:
            if self._model is None:
                self._model, self._meta = load_model()
            if self._frame is None:
                self._frame = build_feature_frame()

    @property
    def model(self):
        self._ensure()
        return self._model

    @property
    def meta(self) -> dict:
        self._ensure()
        return self._meta

    @property
    def frame(self) -> pd.DataFrame:
        self._ensure()
        return self._frame

    def stock_snapshot(self) -> pd.DataFrame:
        """Stock on hand per SKU x warehouse, from the stock table. Every stocked pair has a row."""
        rows = [{"product_id": p, "warehouse_id": w, "city": self._cities.get(w), "stock_on_hand": q}
                for (p, w), q in sorted(self._stock.items())]
        return pd.DataFrame(rows, columns=["product_id", "warehouse_id", "city", "stock_on_hand"])

    def sku_info(self) -> pd.DataFrame:
        """Name and category per SKU, from the SKU table."""
        rows = [{"product_id": p, "product_name": v["product_name"], "category": v["category"]}
                for p, v in sorted(self._skus.items())]
        return pd.DataFrame(rows, columns=["product_id", "product_name", "category"])

    def set_stock(self, stock: dict[tuple[int, str], float]) -> None:
        """Replaces the whole set at once so readers never see a half-updated view."""
        self._stock = dict(stock)

    def set_master(self, skus: dict[int, dict], cities: dict[str, str]) -> None:
        self._skus, self._cities = dict(skus), dict(cities)

    def stock_count(self) -> int:
        return len(self._stock)

    def reset(self):
        with self._lock:
            self._frame = None

    def reload(self):
        """Forget the model and the history so the next request reads the files again (after a retrain)."""
        with self._lock:
            self._model = None
            self._meta = None
            self._frame = None


runtime = MlRuntime()
