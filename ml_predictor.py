#!/usr/bin/env python3
"""
XGBoost-alapú KIEGÉSZÍTŐ technikai szignál.

FONTOS - ez NEM helyettesíti a Claude AI döntését, és nem önálló kereskedési
motor: csak egy további, gépi tanulásos jelzést ad hozzá a Claude promptjához
(rövid távú irány-előrejelzés valószínűsége), amit Claude a többi szignállal
(trend, RSI, Bollinger, hír/volatilitás) együtt mérlegel.

Miért csak kiegészítő és nem önálló döntéshozó:
- Nincs külső historikus adatbázisunk - a modellt minden szimbólumra
  elkülönítve, a frissen lekért (élő) M5 gyertyákból tanítjuk újra
  időről időre. Ez self-supervised felállás: a célváltozó "ment-e feljebb
  az ár LOOKAHEAD gyertyával később", nincs kézzel címkézett adat.
- 100 gyertyányi ablakból ~lookahead-nyi minta esik ki tanításra - ez kevés
  egy önálló kereskedési döntéshez, de elég egy irány-súlyozó jelzéshez.
- Emiatt a predikciót mindig "alacsony megbízhatóságú, kis mintás"
  jelzésként adjuk tovább, sosem parancsként.
"""
import time
import logging
import numpy as np
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive, csomag hiánya esetén nem áll el a bot
    XGBOOST_AVAILABLE = False
    logger.warning("⚠️ xgboost csomag nem elérhető - az ML kiegészítő szignál kikapcsolva")


class MLPredictor:
    """Szimbólumonkénti, memóriában tartott XGBoost modell egyszerű
    momentum/gyertya-alakzat feature-ökön, rövid távú irány-előrejelzéshez."""

    LOOKAHEAD = 3         # hány M5 gyertyával előre próbáljuk megjósolni az irányt
    MIN_CANDLES = 40      # ennyi gyertya alatt nincs elég adat tanításhoz
    MIN_TRAIN_SAMPLES = 20
    RETRAIN_INTERVAL_SEC = 1800  # 30 percenként újratanítjuk (nem minden ciklusban - drága lenne)

    def __init__(self):
        self._models: Dict[str, Any] = {}
        self._last_trained: Dict[str, float] = {}
        self._sample_counts: Dict[str, int] = {}

    @property
    def available(self) -> bool:
        return XGBOOST_AVAILABLE

    @staticmethod
    def _build_features(candles: List[Dict]) -> np.ndarray:
        """Egyszerű, gyertyánkénti feature-ök: hozam, high-low range,
        gyertyatest iránya/mérete, rövid és közepes momentum."""
        closes = np.array([c['close'] for c in candles], dtype=float)
        highs = np.array([c['high'] for c in candles], dtype=float)
        lows = np.array([c['low'] for c in candles], dtype=float)
        opens = np.array([c['open'] for c in candles], dtype=float)

        safe_closes = np.where(closes == 0, 1e-9, closes)
        safe_opens = np.where(opens == 0, 1e-9, opens)

        returns = np.zeros_like(closes)
        returns[1:] = (closes[1:] - closes[:-1]) / safe_closes[:-1]

        range_pct = (highs - lows) / safe_closes
        body_pct = (closes - opens) / safe_opens

        momentum_3 = np.zeros_like(closes)
        momentum_3[3:] = (closes[3:] - closes[:-3]) / safe_closes[:-3]

        momentum_10 = np.zeros_like(closes)
        momentum_10[10:] = (closes[10:] - closes[:-10]) / safe_closes[:-10]

        return np.column_stack([returns, range_pct, body_pct, momentum_3, momentum_10])

    def _train(self, symbol: str, candles: List[Dict]) -> Optional[Any]:
        features = self._build_features(candles)
        closes = np.array([c['close'] for c in candles], dtype=float)

        X: List[np.ndarray] = []
        y: List[int] = []
        n = len(candles)
        # A legelső ~20 gyertyát kihagyjuk (momentum_10 feature-nek kell a
        # felfutási idő), és az utolsó LOOKAHEAD-et sem tudjuk címkézni
        # (nincs "jövőbeli" áruk).
        for i in range(20, n - self.LOOKAHEAD):
            future_return = (closes[i + self.LOOKAHEAD] - closes[i]) / closes[i]
            X.append(features[i])
            y.append(1 if future_return > 0 else 0)

        if len(X) < self.MIN_TRAIN_SAMPLES or len(set(y)) < 2:
            # Túl kevés minta, vagy csak egyetlen irány fordul elő ebben az
            # ablakban - nem lehet (és nem is érdemes) rá modellt tanítani.
            return None

        model = XGBClassifier(
            n_estimators=60,
            max_depth=3,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric='logloss',
            verbosity=0,
        )
        model.fit(np.array(X), np.array(y))
        self._models[symbol] = model
        self._last_trained[symbol] = time.time()
        self._sample_counts[symbol] = len(X)
        return model

    def predict(self, symbol: str, candles: List[Dict]) -> Optional[Dict[str, Any]]:
        """Visszaadja a rövid távú (LOOKAHEAD gyertyás) irány-előrejelzést
        egy dict-ben, vagy None-t, ha xgboost nincs telepítve, vagy nincs
        elég/megbízható adat a predikcióhoz."""
        if not XGBOOST_AVAILABLE or not candles or len(candles) < self.MIN_CANDLES:
            return None

        try:
            model = self._models.get(symbol)
            needs_retrain = (
                model is None
                or time.time() - self._last_trained.get(symbol, 0) > self.RETRAIN_INTERVAL_SEC
            )
            if needs_retrain:
                model = self._train(symbol, candles)
            if model is None:
                return None

            features = self._build_features(candles)
            latest = features[-1].reshape(1, -1)
            proba_up = float(model.predict_proba(latest)[0][1])

            if proba_up >= 0.6:
                signal = 'BUY'
            elif proba_up <= 0.4:
                signal = 'SELL'
            else:
                signal = 'NEUTRAL'

            return {
                'signal': signal,
                'probability_up': round(proba_up, 3),
                'lookahead_candles': self.LOOKAHEAD,
                'trained_samples': self._sample_counts.get(symbol, 0),
            }
        except Exception as e:
            logger.warning(f"⚠️ [{symbol}] ML predikció hiba: {e}")
            return None
