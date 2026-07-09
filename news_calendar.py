#!/usr/bin/env python3
"""
Gazdasági naptár - nyilvános, kulcs nélküli ForexFactory JSON feed
(https://nfs.faireconomy.media/ff_calendar_thisweek.json) alapján.

Ez NEM igényel API kulcsot/integrációt: a ForexFactory nyilvánosan,
autentikáció nélkül publikálja az aktuális heti gazdasági naptárat, amit
sok kereskedési eszköz (pl. MT4/5 indikátorok) is így használ.

Cél: az AI-nak explicit jelezni, ha egy szimbólum devizáihoz (pl. EURUSD =
EUR+USD) tartozó, közepes/magas hatású hír van a közelmúltban vagy a
közeljövőben - hogy a pozíció-menedzsment és az új belépés döntése ezt
figyelembe tudja venni, ne csak az árfolyam utólagos kilengéséből
következtessen rá.
"""

import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Melyik devizákat érinti az adott szimbólum - a naptár 'country' mezője
# ISO devizakódot ad (EUR, USD, GBP, JPY, stb.), nem szimbólumot.
SYMBOL_CURRENCIES = {
    'XAUUSD': {'USD'},   # az arany USD-ben jegyzett, elsősorban a USD hírek mozgatják
    'XAGUSD': {'USD'},
    'EURUSD': {'EUR', 'USD'},
    'GBPUSD': {'GBP', 'USD'},
    'USDJPY': {'USD', 'JPY'},
    'AUDUSD': {'AUD', 'USD'},
    'USDCAD': {'USD', 'CAD'},
    'USDCHF': {'USD', 'CHF'},
    'NZDUSD': {'NZD', 'USD'},
}

# Csak ezeket a hatás-szinteket tekintjük "hír-eseménynek" - a Low hatású
# tételek (pl. "MI Inflation Gauge") gyakorlatilag zaj, ezek figyelembe
# vétele csak feleslegesen ijesztgetné az AI-t minden ciklusban.
RELEVANT_IMPACTS = {'Medium', 'High'}


class NewsCalendar:
    """
    A heti gazdasági naptár cache-elt letöltése és lekérdezése.

    A ForexFactory feed óránként frissül a valóságban, ezért nem kell minden
    trading cikluson (ami percenkénti) újra letölteni - ez feleslegesen
    terhelné a nyilvános szolgáltatást, és lassítaná a ciklust.
    """

    REFRESH_INTERVAL = timedelta(hours=1)

    # Ha egy letöltés sikertelen (pl. az endpoint átmenetileg nem
    # elérhető), ne próbálkozzunk újra minden egyes szimbólum minden
    # ciklusában - egy 4 szimbólumos, kiesett feed melletti ciklus
    # egyébként 4x a teljes 10s timeoutot várná meg, jelentősen lassítva a
    # trading loopot. Sikertelen próbálkozás után ennyit várunk, mielőtt
    # újra próbálkoznánk.
    RETRY_BACKOFF = timedelta(minutes=10)

    def __init__(self):
        self._events: List[Dict] = []
        self._last_fetch: Optional[datetime] = None
        self._last_fetch_failed_at: Optional[datetime] = None

    def _fetch_sync(self) -> List[Dict]:
        response = requests.get(CALENDAR_URL, timeout=10)
        response.raise_for_status()
        return response.json()

    @property
    def is_stale(self) -> bool:
        """True, ha még sosem sikerült letölteni a naptárat."""
        return self._last_fetch is None

    async def _ensure_fresh(self, now: datetime):
        if self._last_fetch and (now - self._last_fetch) < self.REFRESH_INTERVAL:
            return
        if self._last_fetch_failed_at and (now - self._last_fetch_failed_at) < self.RETRY_BACKOFF:
            # Még a backoff ablakban vagyunk egy korábbi hiba után - nem
            # próbálkozunk újra, a régi (esetleg üres) cache-sel megyünk
            # tovább, hogy egy tartós kiesés ne lassítsa minden ciklusban
            # minden szimbólum feldolgozását.
            return
        import asyncio
        try:
            raw_events = await asyncio.to_thread(self._fetch_sync)
            self._events = raw_events
            self._last_fetch = now
            self._last_fetch_failed_at = None
            logger.info(f"📰 Gazdasági naptár frissítve ({len(raw_events)} esemény)")
        except Exception as e:
            # Ha a naptár nem érhető el, ne állítsuk le a trading loopot -
            # a hír-figyelmeztetés csak egy kiegészítő jelzés, nem
            # kritikus függőség. A régi (esetleg üres) cache-sel megyünk tovább,
            # de a hibát megjegyezzük a backoffhoz és a staleness jelzéshez.
            self._last_fetch_failed_at = now
            age = f", utolsó sikeres letöltés: {now - self._last_fetch}" if self._last_fetch else " (SOSEM sikerült még letölteni)"
            logger.warning(f"⚠️ Gazdasági naptár frissítési hiba: {e}{age}")

    @staticmethod
    def _parse_event_time(event: Dict) -> Optional[datetime]:
        date_str = event.get('date')
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            return None

    async def get_relevant_events(
        self,
        symbol: str,
        now: datetime,
        lookback: timedelta = timedelta(hours=1),
        lookahead: timedelta = timedelta(hours=2)
    ) -> List[Dict]:
        """
        Az adott szimbólum devizáihoz tartozó, közepes/magas hatású
        események a [now-lookback, now+lookahead] ablakban.

        Args:
            symbol: Trading szimbólum (pl. EURUSD)
            now: Aktuális időpont (tz-aware, a hívó adja át - lásd
                get_ai_decision komment, miért nem itt hívunk datetime.now()-t)
            lookback: Mennyi ideje megjelent hírt vegyünk még figyelembe
                (pl. friss NFP, ami magyarázza az elmúlt fél óra mozgását)
            lookahead: Mennyi idő múlva esedékes hírt jelezzünk előre
                (hogy az AI óvatosabb legyen belépés előtt)

        Returns:
            List[Dict]: [{'title', 'country', 'impact', 'minutes_from_now'}]
                időrendben, a legközelebbi (abszolút értékben) elöl
        """
        await self._ensure_fresh(now)

        currencies = SYMBOL_CURRENCIES.get(symbol.upper())
        if not currencies:
            return []

        window_start = now - lookback
        window_end = now + lookahead

        relevant = []
        for event in self._events:
            if event.get('country') not in currencies:
                continue
            if event.get('impact') not in RELEVANT_IMPACTS:
                continue
            event_time = self._parse_event_time(event)
            if not event_time or not (window_start <= event_time <= window_end):
                continue
            relevant.append({
                'title': event.get('title'),
                'country': event.get('country'),
                'impact': event.get('impact'),
                'minutes_from_now': round((event_time - now).total_seconds() / 60),
                'forecast': event.get('forecast'),
                'previous': event.get('previous'),
            })

        relevant.sort(key=lambda e: abs(e['minutes_from_now']))
        return relevant
