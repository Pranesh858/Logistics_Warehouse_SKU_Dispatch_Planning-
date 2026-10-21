"""Loads the trained model and sales history once and keeps them in memory."""
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
        self._live_stock: dict[tuple[int, str], float] = {}     # stock reported by the WMS, wins over the sales history

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
        """Latest stock_on_hand per SKU x warehouse."""
        latest = self.frame.sort_values("date").groupby(["product_id", "warehouse_id"], as_index=False).tail(1)
        snap = latest[["product_id", "warehouse_id", "city", "stock_on_hand"]].reset_index(drop=True)
        live = self._live_stock
        if live:
            keys = list(zip(snap["product_id"], snap["warehouse_id"]))
            snap["stock_on_hand"] = [live.get(k, v) for k, v in zip(keys, snap["stock_on_hand"])]
        return snap

    def set_live_stock(self, stock: dict[tuple[int, str], float]) -> None:
        """Stock from the WMS. Replaces the whole set at once so readers never see a half-updated view."""
        self._live_stock = dict(stock)

    def live_stock_count(self) -> int:
        return len(self._live_stock)

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
