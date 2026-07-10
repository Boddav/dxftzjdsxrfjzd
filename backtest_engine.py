#!/usr/bin/env python3
"""
Backtesting motor: a teljes (technikai szabályok + ML szignál) kereskedési
stratégia szimulált lefuttatása historikus gyertyákon, P&L-lel.

Ez a verzió az EthanAlgoX/LLM-TradeBot (nyílt forráskódú, kripto-fókuszú LLM
kereskedési bot) backtest motorjának néhány realizmus-javítását vette át és
adaptálta forex/CFD kontextusra:
- Kereskedési költség (spread/pip-alapú commission) és csúszás (slippage)
  szimulációja - nélküle a backtest szisztematikusan túlbecsüli a valós
  teljesítményt.
- Equity-alapú (nem csak pip-alapú) max drawdown SZÁZALÉKBAN, mert a nyers
  pip-drawdown nem összehasonlítható szimbólumok között.
- Sharpe/Sortino/Calmar arányok, hogy a kockázattal korrigált teljesítmény is
  látható legyen, ne csak a nyers P&L.
- Long/short bontású statisztika (győzelmi arány és P&L irányonként), átlagos
  tartási idő, átlagos/legnagyobb nyereség és veszteség.
- Minimum tartási idő (min_hold_bars) a túlkereskedés elkerülésére - az
  LLM-TradeBot "min_hold_hours" realizmus-javításának megfelelője.

Amit SZÁNDÉKOSAN NEM vettünk át az LLM-TradeBot motorjából, mert nem
illeszkedik forex/CFD (cTrader) kontextusra:
- Binance-specifikus tőkeáttétel-szintek, likvidációs díj, "inverse"
  (érme-alapú) szerződések, margin-tier táblák - ezek kripto derivatíva
  sajátosságok, cTraderen nincs ilyen mechanizmus.
- LLM/Agent-alapú szignál a backteszt magjában - az élő bot Claude döntése
  túl sok kontextust (hírek, korrelált pozíciók) használ ahhoz, hogy
  determinisztikusan és gyorsan reprodukálható legyen egy backtesztben; ez
  változatlanul kimarad (lásd korábbi döntés lent).

FONTOS KORLÁTOK (átláthatóság kedvéért, továbbra is érvényesek):
- A Claude AI döntéshozó NEM szerepel a backtesztben (a felhasználó explicit
  kérésére) - ez egy determinisztikus, szabály-alapú közelítése annak, amit
  élesben a technikai analízis + ML szignál sugall. A valós élő bot ennél
  árnyaltabb, mert Claude több kontextust (hírek, korrelált pozíciók, már
  nyitott pozíció kezelése) is figyelembe vesz.
- Nincs valós historikus bid/ask spread adatunk - a záróárakat használjuk
  belépési/kilépési árnak is; a lenti spread_pips/slippage_pips paraméterek
  egy becsült, fix költséggel közelítik ennek hatását, de nem helyettesítik a
  valós tick-szintű adatot.
- A stop-loss/take-profit kiértékelés az adott gyertya high/low értékén
  alapul; ha egy gyertyán belül mindkettő elérhető lett volna, konzervatívan
  a stop-loss-t vesszük elsőnek (worst-case feltételezés).
"""
import logging
import math
from typing import Dict, List, Optional, Any

from ai_trading_advisor import TechnicalIndicators
from ml_predictor import MLPredictor

logger = logging.getLogger(__name__)

MIN_STOP_PIPS = 10
DEFAULT_STOP_LOSS_PIPS = 20
DEFAULT_TAKE_PROFIT_PIPS = 40
DEFAULT_SPREAD_PIPS = 1.5  # tipikus major forex pár spread-becslés
DEFAULT_SLIPPAGE_PIPS = 0.5
DEFAULT_MIN_HOLD_BARS = 0  # 0 = kikapcsolva (nincs minimum tartási idő)
WARMUP_BARS = 50  # SMA50-hez kell ennyi előzmény, mielőtt szignált generálnánk

# Évesítéshez szükséges gyertyaszám/év, idősíkonként (252 kereskedési nap *
# 24 óra becsléssel - forex/CFD piac majdnem folyamatosan nyitva van hétköznap).
# FONTOS: ha a hívó nem az itt felsorolt idősíkok egyikét adja át, a Sharpe/
# Sortino arányt nem számoljuk (None), mert az évesítés torzítana.
BARS_PER_YEAR_BY_TIMEFRAME = {
    'M1': 252 * 24 * 60,
    'M5': 252 * 24 * 12,
    'M15': 252 * 24 * 4,
    'M30': 252 * 24 * 2,
    'H1': 252 * 24,
    'H4': 252 * 6,
    'D1': 252,
}


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


def _stdev(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def _compute_risk_ratios(equity_curve: List[Dict[str, Any]], timeframe: Optional[str]) -> Dict[str, Optional[float]]:
    """Sharpe/Sortino/Calmar - az LLM-TradeBot metrics.py-jának egyszerűsített
    (külső pandas/numpy függőség nélküli) megfelelője. A gyertyánkénti equity
    értékekből számolt hozam-sorozatból indulunk ki, és az ÁTADOTT idősíknak
    megfelelő gyertya/év szorzóval évesítünk. Ha a timeframe nem ismert
    (BARS_PER_YEAR_BY_TIMEFRAME-ben nincs), a Sharpe/Sortino-t szándékosan
    None-ra állítjuk, mert helytelen évesítés félrevezető lenne - a Calmar
    (nem évesített, csak a teljes időszak hozama/drawdownja) ettől
    függetlenül számolható."""
    if len(equity_curve) < 3:
        return {'sharpe_ratio': None, 'sortino_ratio': None, 'calmar_ratio': None}

    equities = [p['equity'] for p in equity_curve]
    returns = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        if prev == 0:
            continue
        returns.append((equities[i] - prev) / abs(prev))

    bars_per_year = BARS_PER_YEAR_BY_TIMEFRAME.get((timeframe or '').upper())

    if not returns:
        return {'sharpe_ratio': None, 'sortino_ratio': None, 'calmar_ratio': None}

    mean_return = sum(returns) / len(returns)
    std_return = _stdev(returns)
    downside_returns = [r for r in returns if r < 0]
    downside_std = _stdev(downside_returns) if len(downside_returns) >= 2 else 0.0

    if bars_per_year:
        annualization = math.sqrt(bars_per_year)
        sharpe = (mean_return / std_return * annualization) if std_return > 0 else None
        sortino = (mean_return / downside_std * annualization) if downside_std > 0 else None
    else:
        sharpe = None
        sortino = None

    total_return_pct = (equities[-1] - equities[0]) / equities[0] if equities[0] else 0.0
    peak = equities[0]
    max_dd_pct = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - e) / peak)
    calmar = (total_return_pct / max_dd_pct) if max_dd_pct > 0 else None

    return {
        'sharpe_ratio': round(sharpe, 2) if sharpe is not None else None,
        'sortino_ratio': round(sortino, 2) if sortino is not None else None,
        'calmar_ratio': round(calmar, 2) if calmar is not None else None,
    }


def run_backtest(
    symbol: str,
    candles: List[Dict[str, Any]],
    stop_loss_pips: float = DEFAULT_STOP_LOSS_PIPS,
    take_profit_pips: float = DEFAULT_TAKE_PROFIT_PIPS,
    initial_balance: float = 10000.0,
    spread_pips: float = DEFAULT_SPREAD_PIPS,
    slippage_pips: float = DEFAULT_SLIPPAGE_PIPS,
    min_hold_bars: int = DEFAULT_MIN_HOLD_BARS,
    timeframe: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Args:
        symbol: a szimbólum neve (pip-méret meghatározásához)
        candles: historikus OHLC gyertyák időrendben (legrégebbi elöl)
        stop_loss_pips / take_profit_pips: fix pip-távolságok (nem az AI
            szabja meg, mert nincs AI a backtesztben)
        initial_balance: az equity-görbe induló egyenlege (pénznemben, nem
            pip-ben - ez teszi lehetővé a helyes %-os drawdown számítást)
        spread_pips: becsült fix spread-költség belépéskor/kilépéskor
            (LLM-TradeBot "commission" koncepciójának forex-megfelelője)
        slippage_pips: becsült fix csúszás-költség belépéskor/kilépéskor
        min_hold_bars: új pozíció csak ennyi gyertyával a lezárás után
            nyitható (túlkereskedés elleni fék - LLM-TradeBot
            "min_hold_hours" mintájára)
        timeframe: a gyertyák idősíkja (pl. "M5", "H1") - a Sharpe/Sortino
            helyes évesítéséhez kell; ismeretlen/hiányzó timeframe esetén
            ezek None-ként térnek vissza a félrevezető évesítés helyett.

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
    round_trip_cost_pips = max(0.0, spread_pips) + max(0.0, slippage_pips)

    # track_quality=False: izolált példány - sem az élő modellt, sem a
    # ml_quality_log.json-ban tárolt élő szignál-minőség statisztikát nem
    # szennyezi a szimulált (nem valós idejű) predikciókkal.
    ml_predictor = MLPredictor(track_quality=False)
    indicators = TechnicalIndicators()

    position: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    equity_ccy = initial_balance
    equity_curve: List[Dict[str, Any]] = []
    peak_equity_ccy = initial_balance
    max_drawdown_ccy = 0.0
    max_drawdown_pct = 0.0
    running_pnl_pips = 0.0
    last_close_bar_index: Optional[int] = None

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
                pnl_pips -= round_trip_cost_pips  # spread + csúszás levonása
                running_pnl_pips += pnl_pips
                equity_ccy = initial_balance + running_pnl_pips * pip_value
                trades.append({
                    'direction': position['direction'],
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': bar.get('timestamp'),
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'pnl_pips': round(pnl_pips, 1),
                    'holding_bars': i - position['entry_bar_index'],
                })
                position = None
                last_close_bar_index = i

        # 2) Ha nincs nyitott pozíció, nézzük meg, nyitnánk-e most (minimum
        #    tartási/hűtési idő figyelembevételével, ha be van állítva)
        if position is None:
            cooldown_ok = (
                min_hold_bars <= 0
                or last_close_bar_index is None
                or (i - last_close_bar_index) >= min_hold_bars
            )
            signal = _generate_signal(analysis, ml_signal) if cooldown_ok else None
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
                    'entry_bar_index': i,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                }

        peak_equity_ccy = max(peak_equity_ccy, equity_ccy)
        drawdown_ccy = peak_equity_ccy - equity_ccy
        max_drawdown_ccy = max(max_drawdown_ccy, drawdown_ccy)
        if peak_equity_ccy > 0:
            max_drawdown_pct = max(max_drawdown_pct, drawdown_ccy / peak_equity_ccy)
        equity_curve.append({
            'timestamp': bar.get('timestamp'),
            'pnl_pips': round(running_pnl_pips, 1),
            'equity': round(equity_ccy, 2),
        })

    # Nyitva maradt pozíció lezárása az utolsó gyertya záróárán (mark-to-market)
    if position is not None:
        last_close = candles[-1]['close']
        if position['direction'] == 'BUY':
            pnl_pips = (last_close - position['entry_price']) / pip_value
        else:
            pnl_pips = (position['entry_price'] - last_close) / pip_value
        pnl_pips -= round_trip_cost_pips
        running_pnl_pips += pnl_pips
        trades.append({
            'direction': position['direction'],
            'entry_time': position['entry_time'],
            'entry_price': position['entry_price'],
            'exit_time': candles[-1].get('timestamp'),
            'exit_price': last_close,
            'exit_reason': 'open_at_backtest_end',
            'pnl_pips': round(pnl_pips, 1),
            'holding_bars': (len(candles) - 1) - position['entry_bar_index'],
        })
        # A kényszerített zárás a running_pnl_pips-et módosítja, de az
        # equity_curve utolsó pontja ezt még nem tükrözi - anélkül, hogy itt
        # frissítenénk, a végső equity/drawdown/Sharpe-Sortino-Calmar (mind az
        # equity_curve-ből számol) inkonzisztens lenne a total_pnl_pips
        # végeredménnyel. Frissítjük az utolsó pontot, majd a peak/drawdown
        # követést is lezárjuk ugyanazzal az értékkel.
        equity_ccy = initial_balance + running_pnl_pips * pip_value
        peak_equity_ccy = max(peak_equity_ccy, equity_ccy)
        drawdown_ccy = peak_equity_ccy - equity_ccy
        max_drawdown_ccy = max(max_drawdown_ccy, drawdown_ccy)
        if peak_equity_ccy > 0:
            max_drawdown_pct = max(max_drawdown_pct, drawdown_ccy / peak_equity_ccy)
        if equity_curve:
            equity_curve[-1] = {
                'timestamp': candles[-1].get('timestamp'),
                'pnl_pips': round(running_pnl_pips, 1),
                'equity': round(equity_ccy, 2),
            }
        else:
            equity_curve.append({
                'timestamp': candles[-1].get('timestamp'),
                'pnl_pips': round(running_pnl_pips, 1),
                'equity': round(equity_ccy, 2),
            })

    wins = [t for t in trades if t['pnl_pips'] > 0]
    losses = [t for t in trades if t['pnl_pips'] <= 0]
    total_win_pips = sum(t['pnl_pips'] for t in wins)
    total_loss_pips = abs(sum(t['pnl_pips'] for t in losses))

    long_trades = [t for t in trades if t['direction'] == 'BUY']
    short_trades = [t for t in trades if t['direction'] == 'SELL']
    long_wins = [t for t in long_trades if t['pnl_pips'] > 0]
    short_wins = [t for t in short_trades if t['pnl_pips'] > 0]

    risk_ratios = _compute_risk_ratios(equity_curve, timeframe)

    return {
        'symbol': symbol,
        'candle_count': len(candles),
        'period_start': candles[WARMUP_BARS].get('timestamp'),
        'period_end': candles[-1].get('timestamp'),
        'stop_loss_pips': stop_loss_pips,
        'take_profit_pips': take_profit_pips,
        'spread_pips': spread_pips,
        'slippage_pips': slippage_pips,
        'min_hold_bars': min_hold_bars,
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / len(trades), 3) if trades else None,
        'total_pnl_pips': round(running_pnl_pips, 1),
        'profit_factor': round(total_win_pips / total_loss_pips, 2) if total_loss_pips > 0 else None,
        'max_drawdown_pips': round(max_drawdown_ccy / pip_value, 1) if pip_value else None,
        'max_drawdown_pct': round(max_drawdown_pct * 100, 2),
        'sharpe_ratio': risk_ratios['sharpe_ratio'],
        'sortino_ratio': risk_ratios['sortino_ratio'],
        'calmar_ratio': risk_ratios['calmar_ratio'],
        'avg_win_pips': round(total_win_pips / len(wins), 1) if wins else None,
        'avg_loss_pips': round(-total_loss_pips / len(losses), 1) if losses else None,
        'largest_win_pips': round(max((t['pnl_pips'] for t in wins), default=0.0), 1) if wins else None,
        'largest_loss_pips': round(min((t['pnl_pips'] for t in losses), default=0.0), 1) if losses else None,
        'avg_holding_bars': round(sum(t['holding_bars'] for t in trades) / len(trades), 1) if trades else None,
        'long_trades': len(long_trades),
        'short_trades': len(short_trades),
        'long_win_rate': round(len(long_wins) / len(long_trades), 3) if long_trades else None,
        'short_win_rate': round(len(short_wins) / len(short_trades), 3) if short_trades else None,
        'long_pnl_pips': round(sum(t['pnl_pips'] for t in long_trades), 1) if long_trades else 0.0,
        'short_pnl_pips': round(sum(t['pnl_pips'] for t in short_trades), 1) if short_trades else 0.0,
        'trades': trades[-200:],  # ne fújjuk fel a válaszméretet nagyon hosszú backteszteknél
        'equity_curve': equity_curve[::max(1, len(equity_curve) // 300)],  # max ~300 pont a grafikonhoz
        'disclaimer': (
            'Ez a backteszt NEM tartalmazza a Claude AI döntéshozót, csak a technikai '
            'szabály + ML szignál determinisztikus közelítését. A spread/csúszás egy '
            'fix pip-becsléssel (nem valós tick-szintű adatból) van beépítve a P&L-be. '
            'A Sharpe/Sortino csak ismert idősíkokon (M1/M5/M15/M30/H1/H4/D1) évesített; '
            'egyéb esetben "-" jelenik meg, hogy a hibás évesítés ne legyen félrevezető.'
        ),
    }
