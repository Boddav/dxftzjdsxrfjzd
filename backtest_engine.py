#!/usr/bin/env python3
"""
Backtesting motor: a teljes (technikai szabályok + ML szignál) kereskedési
stratégia szimulált lefuttatása historikus gyertyákon, P&L-lel.

FONTOS KORLÁTOK (átláthatóság kedvéért):
- A Claude AI döntéshozó NEM szerepel a backtesztben (a felhasználó explicit
  kérésére) - ez egy determinisztikus, szabály-alapú közelítése annak, amit
  élesben a technikai analízis + ML szignál sugall. A valós élő bot ennél
  árnyaltabb, mert Claude több kontextust (hírek, korrelált pozíciók, már
  nyitott pozíció kezelése) is figyelembe vesz.
- Nincs valós historikus bid/ask spread adatunk - a záróárakat használjuk
  belépési/kilépési árnak is, ami optimistább eredményt adhat, mint az élő
  kereskedés (spread/csúszás nélkül).
- A stop-loss/take-profit kiértékelés az adott gyertya high/low értékén
  alapul; ha egy gyertyán belül mindkettő elérhető lett volna, konzervatívan
  a stop-loss-t vesszük elsőnek (worst-case feltételezés).
"""
import logging
from typing import Dict, List, Optional, Any

from ai_trading_advisor import TechnicalIndicators
from ml_predictor import MLPredictor

logger = logging.getLogger(__name__)

MIN_STOP_PIPS = 10
DEFAULT_STOP_LOSS_PIPS = 20
DEFAULT_TAKE_PROFIT_PIPS = 40
WARMUP_BARS = 50  # SMA50-hez kell ennyi előzmény, mielőtt szignált generálnánk


def _pip_value(symbol: str) -> float:
    """Ugyanaz a közelítés, mint ai_trading_advisor._pip_value - itt
    külön másolva, hogy a backtest ne függjön az AITradingAdvisor
    (Anthropic kliens, cTrader kapcsolat) inicializálásától."""
    symbol = symbol.upper()
    if 'XAU' in symbol or 'XAG' in symbol:
        return 0.1
    if 'JPY' in symbol:
        return 0.01
    if symbol.startswith('BTC') or symbol.startswith('ETH'):
        return 1.0
    return 0.0001


def _generate_signal(analysis: Dict[str, Any], ml_signal: Optional[Dict[str, Any]]) -> Optional[str]:
    """Egyszerű, determinisztikus szabály - a Claude promptban is szereplő
    "trend + RSI szélsőérték + ML megerősítés" logika leegyszerűsített
    változata: csak akkor nyit pozíciót, ha a trend, az RSI és az ML jelzés
    (ha van) mind egy irányba mutat, hogy elkerüljük a túlkereskedést."""
    trend = analysis['trend']
    rsi = analysis['rsi']
    ml_ok_buy = ml_signal is None or ml_signal['signal'] != 'SELL'
    ml_ok_sell = ml_signal is None or ml_signal['signal'] != 'BUY'

    if trend == 'BULLISH' and rsi < 40 and ml_ok_buy:
        return 'BUY'
    if trend == 'BEARISH' and rsi > 60 and ml_ok_sell:
        return 'SELL'
    return None


def run_backtest(
    symbol: str,
    candles: List[Dict[str, Any]],
    stop_loss_pips: float = DEFAULT_STOP_LOSS_PIPS,
    take_profit_pips: float = DEFAULT_TAKE_PROFIT_PIPS,
    initial_balance: float = 10000.0,
) -> Dict[str, Any]:
    """
    Args:
        symbol: a szimbólum neve (pip-méret meghatározásához)
        candles: historikus OHLC gyertyák időrendben (legrégebbi elöl)
        stop_loss_pips / take_profit_pips: fix pip-távolságok (nem az AI
            szabja meg, mert nincs AI a backtesztben)
        initial_balance: csak az equity-görbe skálázásához (nincs valós
            lot-méretezés/margin szimuláció ebben az egyszerűsített motorban)

    Returns:
        Dict: összesítő statisztikák + trade lista + equity görbe
    """
    if len(candles) < WARMUP_BARS + 10:
        raise ValueError(
            f"Túl kevés gyertya a backteszthez ({len(candles)}) - minimum {WARMUP_BARS + 10} szükséges."
        )

    pip_value = _pip_value(symbol)
    sl_distance = max(stop_loss_pips, MIN_STOP_PIPS) * pip_value
    tp_distance = max(take_profit_pips, MIN_STOP_PIPS) * pip_value

    # track_quality=False: izolált példány - sem az élő modellt, sem a
    # ml_quality_log.json-ban tárolt élő szignál-minőség statisztikát nem
    # szennyezi a szimulált (nem valós idejű) predikciókkal.
    ml_predictor = MLPredictor(track_quality=False)
    indicators = TechnicalIndicators()

    position: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    equity = initial_balance
    equity_curve: List[Dict[str, Any]] = []
    peak_equity = initial_balance
    max_drawdown_pips = 0.0
    running_pnl_pips = 0.0

    for i in range(WARMUP_BARS, len(candles)):
        window = candles[:i + 1]
        bar = candles[i]
        close_prices = [c['close'] for c in window]

        sma_20 = indicators.sma(close_prices, 20)
        sma_50 = indicators.sma(close_prices, 50)
        rsi = indicators.rsi(close_prices, 14)
        trend = 'BULLISH' if sma_20 > sma_50 else 'BEARISH'
        analysis = {'trend': trend, 'rsi': rsi}

        try:
            ml_signal = ml_predictor.predict(symbol, window)
        except Exception as e:
            logger.warning(f"⚠️ [{symbol}] Backteszt ML hiba a(z) {i}. gyertyánál: {e}")
            ml_signal = None

        # 1) Ha van nyitott pozíció, először nézzük meg, kilépett-e SL/TP-n
        if position is not None:
            hit_sl = (
                bar['low'] <= position['stop_loss'] if position['direction'] == 'BUY'
                else bar['high'] >= position['stop_loss']
            )
            hit_tp = (
                bar['high'] >= position['take_profit'] if position['direction'] == 'BUY'
                else bar['low'] <= position['take_profit']
            )
            exit_price = None
            exit_reason = None
            if hit_sl:
                exit_price = position['stop_loss']
                exit_reason = 'stop_loss'
            elif hit_tp:
                exit_price = position['take_profit']
                exit_reason = 'take_profit'

            if exit_price is not None:
                if position['direction'] == 'BUY':
                    pnl_pips = (exit_price - position['entry_price']) / pip_value
                else:
                    pnl_pips = (position['entry_price'] - exit_price) / pip_value
                running_pnl_pips += pnl_pips
                trades.append({
                    'direction': position['direction'],
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': bar.get('timestamp'),
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'pnl_pips': round(pnl_pips, 1),
                })
                position = None

        # 2) Ha nincs nyitott pozíció, nézzük meg, nyitnánk-e most
        if position is None:
            signal = _generate_signal(analysis, ml_signal)
            if signal:
                entry_price = bar['close']
                if signal == 'BUY':
                    stop_loss = entry_price - sl_distance
                    take_profit = entry_price + tp_distance
                else:
                    stop_loss = entry_price + sl_distance
                    take_profit = entry_price - tp_distance
                position = {
                    'direction': signal,
                    'entry_time': bar.get('timestamp'),
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                }

        peak_equity = max(peak_equity, initial_balance + running_pnl_pips * pip_value)
        drawdown_pips = (peak_equity - (initial_balance + running_pnl_pips * pip_value)) / pip_value
        max_drawdown_pips = max(max_drawdown_pips, drawdown_pips)
        equity_curve.append({
            'timestamp': bar.get('timestamp'),
            'pnl_pips': round(running_pnl_pips, 1),
        })

    # Nyitva maradt pozíció lezárása az utolsó gyertya záróárán (mark-to-market)
    if position is not None:
        last_close = candles[-1]['close']
        if position['direction'] == 'BUY':
            pnl_pips = (last_close - position['entry_price']) / pip_value
        else:
            pnl_pips = (position['entry_price'] - last_close) / pip_value
        running_pnl_pips += pnl_pips
        trades.append({
            'direction': position['direction'],
            'entry_time': position['entry_time'],
            'entry_price': position['entry_price'],
            'exit_time': candles[-1].get('timestamp'),
            'exit_price': last_close,
            'exit_reason': 'open_at_backtest_end',
            'pnl_pips': round(pnl_pips, 1),
        })

    wins = [t for t in trades if t['pnl_pips'] > 0]
    losses = [t for t in trades if t['pnl_pips'] <= 0]
    total_win_pips = sum(t['pnl_pips'] for t in wins)
    total_loss_pips = abs(sum(t['pnl_pips'] for t in losses))

    return {
        'symbol': symbol,
        'candle_count': len(candles),
        'period_start': candles[WARMUP_BARS].get('timestamp'),
        'period_end': candles[-1].get('timestamp'),
        'stop_loss_pips': stop_loss_pips,
        'take_profit_pips': take_profit_pips,
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / len(trades), 3) if trades else None,
        'total_pnl_pips': round(running_pnl_pips, 1),
        'profit_factor': round(total_win_pips / total_loss_pips, 2) if total_loss_pips > 0 else None,
        'max_drawdown_pips': round(max_drawdown_pips, 1),
        'trades': trades[-200:],  # ne fújjuk fel a válaszméretet nagyon hosszú backteszteknél
        'equity_curve': equity_curve[::max(1, len(equity_curve) // 300)],  # max ~300 pont a grafikonhoz
        'disclaimer': (
            'Ez a backteszt NEM tartalmazza a Claude AI döntéshozót, csak a technikai '
            'szabály + ML szignál determinisztikus közelítését, és nem számol '
            'spreaddel/csúszással - az élő eredmény ettől eltérhet.'
        ),
    }
