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
import os
import json
import time
import uuid
import logging
import threading
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

QUALITY_LOG_FILE = 'ml_quality_log.json'
MAX_QUALITY_LOG_ENTRIES = 2000
# Egy folyamaton belüli minden MLPredictor példány (élő bot + admin API
# route-ok, pl. /api/ml-quality) ugyanazt a fájlt olvassa/írja - egy közös
# lockkal védjük a read-modify-write ciklust, hogy egyidejű hívások ne
# írják felül egymás módosítását ("last writer wins" adatvesztés).
_quality_log_lock = threading.Lock()


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"⚠️ ML minőség-napló olvasási hiba ({path}): {e}")
        return default


def _write_json_atomic(path: str, data) -> None:
    """Atomikus írás (tmp fájl + rename), hogy egy félbeszakadt írás ne
    hagyjon sérült JSON-t egy másik szál/folyamat számára olvasva."""
    tmp_path = f"{path}.tmp-{uuid.uuid4().hex}"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)

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

    def __init__(self, track_quality: bool = True):
        self._models: Dict[str, Any] = {}
        self._last_trained: Dict[str, float] = {}
        self._sample_counts: Dict[str, int] = {}
        # track_quality=False -> izolált (pl. backteszt/historikus eval)
        # használatra, hogy NE írjon/olvasson a megosztott élő
        # ml_quality_log.json fájlba, és ne szennyezze az élesben kiadott
        # jelzések minőségi statisztikáját szimulált predikciókkal.
        self._track_quality = track_quality
        # Élő szignál-minőség nyomkövetés: minden predikciót elmentünk egy
        # "pending" bejegyzésként (még nem tudjuk, bejött-e), majd amikor
        # legközelebb elég friss gyertya érkezik ugyanahhoz a szimbólumhoz
        # (a predikció utáni LOOKAHEAD-edik gyertya lezárt), lezárjuk
        # ("resolved") a tényleges irány alapján. Ez teszi lehetővé, hogy a
        # dashboardon látható legyen, mennyire megbízható valójában az ML
        # jelzés élesben, nem csak a betanításkor mért (túltanulásra
        # hajlamos) pontosság.
    # ------------------------------------------------------------------
    # Élő szignál-minőség nyomkövetés
    #
    # Több MLPredictor példány is olvashatja/írhatja ugyanazt a
    # ml_quality_log.json-t egyidejűleg (az élő bot háttérszála + a
    # /api/ml-quality admin route egy friss példányt hoz létre). Emiatt
    # SOSEM tartunk saját, hosszú életű másolatot memóriában a
    # pending/resolved listákról - minden mutáció a közös lock alatt
    # frissen betölt a lemezről, módosít, majd ír vissza, hogy két
    # egyidejű hívás ne írja felül egymás eredményét ("last writer wins").
    # ------------------------------------------------------------------
    @staticmethod
    def _load_quality_log() -> Dict[str, List[Dict[str, Any]]]:
        data = _read_json(QUALITY_LOG_FILE, {'pending': [], 'resolved': []})
        return {'pending': data.get('pending', []), 'resolved': data.get('resolved', [])}

    @staticmethod
    def _save_quality_log(data: Dict[str, List[Dict[str, Any]]]) -> None:
        try:
            _write_json_atomic(QUALITY_LOG_FILE, {
                'pending': data['pending'],
                'resolved': data['resolved'][-MAX_QUALITY_LOG_ENTRIES:],
            })
        except OSError as e:
            logger.warning(f"⚠️ ML minőség-napló mentési hiba: {e}")

    @staticmethod
    def _candle_interval_seconds(candles: List[Dict]) -> float:
        """A gyertyák közti időköz becslése az utolsó két gyertya
        timestampjéből (pl. M5 -> 300s). 300s-re esik vissza, ha nem
        számolható (túl kevés gyertya vagy hibás timestamp)."""
        if len(candles) < 2:
            return 300.0
        try:
            t1 = datetime.fromisoformat(candles[-2]['timestamp'])
            t2 = datetime.fromisoformat(candles[-1]['timestamp'])
            delta = (t2 - t1).total_seconds()
            return delta if delta > 0 else 300.0
        except (KeyError, ValueError, TypeError):
            return 300.0

    def _resolve_pending(self, symbol: str, candles: List[Dict]) -> None:
        """Megnézi, van-e olyan függőben lévő predikció ehhez a
        szimbólumhoz, aminek időközben lezárult a LOOKAHEAD-edik gyertyája
        a most kapott friss adatokban - ha igen, kiértékeli és lezárja.
        Backteszt/historikus eval példányoknál (track_quality=False) ez
        no-op, hogy a szimulált predikciók ne szennyezzék az élő naplót."""
        if not self._track_quality or not candles:
            return
        candle_by_ts = {c.get('timestamp'): c for c in candles if c.get('timestamp')}
        with _quality_log_lock:
            log = self._load_quality_log()
            still_pending = []
            for entry in log['pending']:
                if entry.get('symbol') != symbol:
                    still_pending.append(entry)
                    continue
                target_candle = candle_by_ts.get(entry.get('target_timestamp'))
                if target_candle is None:
                    # Még nem érkezett meg a célgyertya - ha viszont már túl
                    # régi (pl. a bot sokáig állt, vagy a gyertya kikerült a
                    # sliding window-ból anélkül, hogy elkaptuk volna),
                    # eldobjuk, nehogy örökre felgyülemeljenek a
                    # feloldhatatlan bejegyzések.
                    try:
                        age_hours = (
                            datetime.now(timezone.utc) - datetime.fromisoformat(entry['created_at'])
                        ).total_seconds() / 3600
                    except (KeyError, ValueError):
                        age_hours = 0
                    if age_hours < 48:
                        still_pending.append(entry)
                    continue

                actual_up = target_candle['close'] > entry['reference_close']
                if entry['signal'] == 'NEUTRAL':
                    correct = None  # a NEUTRAL-t nem "helyes/helytelen" irányként mérjük
                else:
                    predicted_up = entry['signal'] == 'BUY'
                    correct = predicted_up == actual_up

                log['resolved'].append({
                    **entry,
                    'resolved_at': datetime.now(timezone.utc).isoformat(),
                    'actual_up': actual_up,
                    'correct': correct,
                })
            log['pending'] = still_pending
            self._save_quality_log(log)

    def _log_prediction(self, symbol: str, candles: List[Dict], signal: str, proba_up: float) -> None:
        if not self._track_quality:
            return
        last_candle = candles[-1]
        interval_sec = self._candle_interval_seconds(candles)
        try:
            reference_dt = datetime.fromisoformat(last_candle['timestamp'])
            target_dt = reference_dt + timedelta(seconds=interval_sec * self.LOOKAHEAD)
            target_timestamp = target_dt.isoformat()
        except (KeyError, ValueError, TypeError):
            target_timestamp = None

        if target_timestamp is None:
            return  # timestamp nélkül nem tudnánk később feloldani - kihagyjuk

        with _quality_log_lock:
            log = self._load_quality_log()
            log['pending'].append({
                'id': uuid.uuid4().hex,
                'symbol': symbol,
                'signal': signal,
                'probability_up': round(proba_up, 3),
                'reference_timestamp': last_candle.get('timestamp'),
                'reference_close': last_candle['close'],
                'target_timestamp': target_timestamp,
                'created_at': datetime.now(timezone.utc).isoformat(),
            })
            self._save_quality_log(log)

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
            self._resolve_pending(symbol, candles)
        except Exception as e:
            logger.warning(f"⚠️ [{symbol}] ML minőség-feloldási hiba: {e}")

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

            try:
                self._log_prediction(symbol, candles, signal, proba_up)
            except Exception as e:
                logger.warning(f"⚠️ [{symbol}] ML minőség-naplózási hiba: {e}")

            return {
                'signal': signal,
                'probability_up': round(proba_up, 3),
                'lookahead_candles': self.LOOKAHEAD,
                'trained_samples': self._sample_counts.get(symbol, 0),
            }
        except Exception as e:
            logger.warning(f"⚠️ [{symbol}] ML predikció hiba: {e}")
            return None

    def get_quality_stats(self, symbol: Optional[str] = None, recent_n: int = 50) -> Dict[str, Any]:
        """Élő szignál-minőség összesítő: hány feloldott predikció volt,
        ebből hány volt helyes irány (a NEUTRAL jelzéseket kihagyva az
        irány-pontosságból, mert azoknál nincs "helyes irány" állítás).
        Ha symbol=None, minden szimbólumra összesítve adja vissza, plusz
        szimbólumonkénti bontásban is. Mindig frissen a lemezről olvas
        (lásd a fájl tetején lévő megjegyzést a közös lockról)."""
        with _quality_log_lock:
            log = self._load_quality_log()
        all_resolved = log['resolved']
        all_pending = log['pending']
        resolved = [r for r in all_resolved if r['symbol'] == symbol] if symbol else all_resolved

        def _summarize(entries: List[Dict]) -> Dict[str, Any]:
            directional = [e for e in entries if e.get('correct') is not None]
            correct = sum(1 for e in directional if e['correct'])
            recent = directional[-recent_n:]
            recent_correct = sum(1 for e in recent if e['correct'])
            return {
                'resolved_count': len(entries),
                'directional_count': len(directional),
                'correct_count': correct,
                'accuracy': round(correct / len(directional), 3) if directional else None,
                'recent_accuracy': round(recent_correct / len(recent), 3) if recent else None,
                'recent_n': len(recent),
            }

        result = _summarize(resolved)
        result['pending_count'] = len([p for p in all_pending if not symbol or p['symbol'] == symbol])
        result['by_symbol'] = {}
        if not symbol:
            symbols = sorted({r['symbol'] for r in all_resolved})
            for sym in symbols:
                result['by_symbol'][sym] = _summarize([r for r in all_resolved if r['symbol'] == sym])
        return result

    def evaluate_historical(self, symbol: str, candles: List[Dict], test_fraction: float = 0.3) -> Optional[Dict[str, Any]]:
        """Historikus (időrendi) train/test szétválasztás: a modellt csak a
        gyertyák korábbi (train) részén tanítjuk, majd a kihagyott, később
        következő (test) részen mérjük az irány-előrejelzés pontosságát.
        Ez ELTÉR az élő nyomkövetéstől (ami a ténylegesen élesben kiadott
        jelzéseket méri) - itt egy izolált, egyszeri kiértékelés, nem
        szennyezi/nem használja a memóriában futó élő modellt."""
        if not XGBOOST_AVAILABLE:
            return None
        n = len(candles)
        if n < self.MIN_CANDLES + 20:
            return None

        split_idx = int(n * (1 - test_fraction))
        # A tanításhoz legalább MIN_TRAIN_SAMPLES-nyi felhasználható mintának
        # kell maradnia a train szakaszban (lásd _train 20..n-LOOKAHEAD ablak).
        if split_idx < 20 + self.MIN_TRAIN_SAMPLES + self.LOOKAHEAD:
            return None
        if n - split_idx < self.LOOKAHEAD + 5:
            return None

        train_candles = candles[:split_idx]
        model = self._train(f"__eval__{symbol}", train_candles)
        if model is None:
            return None

        features = self._build_features(candles)
        closes = np.array([c['close'] for c in candles], dtype=float)

        y_true: List[int] = []
        y_pred: List[int] = []
        for i in range(split_idx, n - self.LOOKAHEAD):
            future_return = (closes[i + self.LOOKAHEAD] - closes[i]) / closes[i]
            actual_up = 1 if future_return > 0 else 0
            proba_up = float(model.predict_proba(features[i].reshape(1, -1))[0][1])
            predicted_up = 1 if proba_up >= 0.5 else 0
            y_true.append(actual_up)
            y_pred.append(predicted_up)

        # Ideiglenes eval-modell eltávolítása, hogy ne maradjon a memóriában
        self._models.pop(f"__eval__{symbol}", None)
        self._last_trained.pop(f"__eval__{symbol}", None)
        self._sample_counts.pop(f"__eval__{symbol}", None)

        if not y_true:
            return None

        true_pos = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
        false_pos = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
        false_neg = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
        correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
        precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else None
        recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else None
        # Fontos: `if precision and recall` hamis lenne 0.0 értékekre is
        # (mert a 0.0 "falsy" Pythonban), pedig 0.0 pontosság/recall esetén
        # az F1-nek is korrekt módon 0.0-nak kell lennie, nem None-nak.
        if precision is None or recall is None:
            f1 = None
        elif (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0

        return {
            'symbol': symbol,
            'train_candles': len(train_candles),
            'test_candles': n - split_idx,
            'test_samples': len(y_true),
            'accuracy': round(correct / len(y_true), 3),
            'precision': round(precision, 3) if precision is not None else None,
            'recall': round(recall, 3) if recall is not None else None,
            'f1': round(f1, 3) if f1 is not None else None,
            'baseline_up_rate': round(sum(y_true) / len(y_true), 3),
        }
