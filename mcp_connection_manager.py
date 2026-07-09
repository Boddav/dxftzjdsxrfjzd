#!/usr/bin/env python3
"""
Megosztott (singleton) cTrader MCP kapcsolat kezelő az admin API végpontokhoz.

Cél: elkerülni, hogy minden /api/positions, /api/test-position stb. hívás
saját, új WebSocket kapcsolatot nyisson és hitelesítsen a cTrader API felé
(ez feleslegesen sok kapcsolatot hozott létre -> keepalive ping timeout,
"Nincs elérhető gyertyaadat" hibák).

Megoldás: egy dedikált háttérszálon futó saját asyncio event loop, amin
egyetlen, újrahasznált CTraderMCPServer kapcsolat él. Az admin route-ok
(szinkron Flask függvények) ezen a megosztott loop-on futtatják a
coroutine-jaikat, és a kapcsolatot nem zárják le hívások között.
"""

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError

from mcp_server import CTraderMCPServer

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()

_server: CTraderMCPServer | None = None
_server_lock: asyncio.Lock | None = None

# Egy hívás max. ennyi ideig futhat, mielőtt hibát dobunk (mp)
CALL_TIMEOUT = 30


def _ensure_loop_running():
    """Elindítja a megosztott háttér event loop-ot, ha még nem fut."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop_thread is not None and _loop_thread.is_alive():
            return
        _loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _loop_thread = threading.Thread(target=_run, name="mcp-shared-loop", daemon=True)
        _loop_thread.start()
        logger.info("🧵 Megosztott MCP event loop szál elindítva")


async def _get_server_locked() -> CTraderMCPServer:
    """A megosztott loopon belül futva biztosítja a kapcsolódott szervert."""
    global _server, _server_lock
    if _server_lock is None:
        _server_lock = asyncio.Lock()

    async with _server_lock:
        if _server is None:
            _server = CTraderMCPServer()

        if not _server.connected or not _server.authenticated:
            try:
                await _server.connect()
            except Exception:
                # Ha a csatlakozás sikertelen, zárjuk le a (részlegesen) megnyitott
                # socketet, majd dobjuk el a szervert, hogy legközelebb tiszta
                # lappal induljon az újrapróbálkozás (ne szivárogjon a kapcsolat).
                broken = _server
                _server = None
                try:
                    await broken.close()
                except Exception:
                    pass
                raise

        return _server


async def _invalidate_server():
    """Elrontott/lezárt kapcsolat eldobása, hogy a következő hívás újra csatlakozzon."""
    global _server
    if _server is not None:
        try:
            await _server.close()
        except Exception:
            pass
        _server = None


# Hibák, amelyek kapcsolat-/authentikáció-szintű problémára utalnak, és
# ezért indokolják az újracsatlakozást + egyszeri újrapróbálkozást.
# Üzleti logikai hibákat (pl. NOT_ENOUGH_MONEY) szándékosan NEM ismétlünk meg itt,
# mert azokat a hívó (pl. place_order eredménye) már kezeli, és nem
# kapcsolat-hiba.
_RECONNECT_EXCEPTIONS = (
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
)


def _looks_like_connection_error(exc: Exception) -> bool:
    if isinstance(exc, _RECONNECT_EXCEPTIONS):
        return True
    # A websockets könyvtár és a mcp_server saját kapcsolat-hibái jellemzően
    # ezekkel a kulcsszavakkal írják le a problémát.
    text = str(exc).lower()
    return any(k in text for k in ("connection", "websocket", "closed", "auth", "timeout"))


async def _run_with_shared_server(func):
    """
    func: async callable, amely egy CTraderMCPServer-t vár paraméterként,
    és a visszatérési értékét adjuk vissza.

    Egyszer próbálkozik a meglévő (vagy újonnan létrehozott) megosztott
    kapcsolattal; ha a hiba kapcsolat-/authentikáció-jellegűnek tűnik, egyszer
    megpróbálja friss kapcsolattal is, mielőtt továbbdobja a hibát. Egyéb
    (pl. üzleti logikai) hibákat azonnal továbbdob, nem próbálkozik újra.
    """
    server = await _get_server_locked()
    try:
        return await func(server)
    except Exception as e:
        if not _looks_like_connection_error(e):
            raise
        logger.warning(f"⚠️ Megosztott MCP kapcsolat hívás sikertelen, újracsatlakozás: {e}")
        await _invalidate_server()
        server = await _get_server_locked()
        return await func(server)


def run_shared(func):
    """
    Szinkron belépési pont Flask route-okból.

    func: async callable, amely egy CTraderMCPServer-t vár paraméterként.
    Visszaadja a func eredményét, vagy továbbdobja a kivételt.

    Timeout esetén a háttérben futó coroutine-t megpróbáljuk megszakítani,
    és a megosztott kapcsolatot érvénytelenítjük, hogy egy beragadt hívás
    ne akassza meg a következő kéréseket.
    """
    _ensure_loop_running()
    future = asyncio.run_coroutine_threadsafe(_run_with_shared_server(func), _loop)
    try:
        return future.result(timeout=CALL_TIMEOUT)
    except FuturesTimeoutError:
        future.cancel()
        asyncio.run_coroutine_threadsafe(_invalidate_server(), _loop)
        raise TimeoutError(
            f"cTrader MCP hívás túllépte a {CALL_TIMEOUT} másodperces időkorlátot"
        )
