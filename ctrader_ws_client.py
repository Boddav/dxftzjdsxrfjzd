#!/usr/bin/env python3
"""
Async WebSocket alapú cTrader kliens (JSON keret)
-------------------------------------------------
Ez a modul a felhasználó által küldött minimál példa (payloadType 2100/2101 és 2102/2103)
alapján épül fel, extra hibakezeléssel, opcionális account discovery próbálkozással és
token frissítés vázával.

FIGYELEM / INKONZISZTENCIA:
 - A Twisted/protobuf alapú kliensben a 2102 üzenet = "GetAccountsByAccessTokenReq" és a válasz 2150.
 - A felhasználó által küldött WebSocket JSON példa viszont 2102-t az "account authentication" kérésére
   használja és 2103 választ vár.
 - Emiatt itt rugalmas logikát alkalmazunk: ha van accountId akkor 2102-et küldünk, 2103-at várunk;
   ha nincs accountId, megpróbálunk egy (feltételezett) account listing hívást küldeni (payloadType 2102
   accountId nélkül), és ha 2150 érkezik, kiválasztunk egy accountot, majd újra próbáljuk az autentikációt.

Ha a valós protokollban eltérnek a számok, igazítsd a PAYLOAD konstansokat.

Teendők / Bővíthető:
 - Valós token refresh (OAuth /apps/token endpoint) implementálása
 - Heartbeat / reconnect logika
 - Üzenetküldő réteg kiterjesztése (pl. order placement)
"""

import json
import asyncio as aio
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from websockets.asyncio.client import connect

# PayloadType konstansok – igazítsd dokumentáció szerint ha szükséges
PAYLOAD_APP_AUTH_REQ = 2100
PAYLOAD_APP_AUTH_RES = 2101
PAYLOAD_ACCOUNT_AUTH_REQ = 2102           # User snippet szerint
PAYLOAD_ACCOUNT_AUTH_RES = 2103           # User snippet szerint
PAYLOAD_ACCOUNTS_LIST_RES = 2150          # Twisted kliensben látott válasz


@dataclass
class Credentials:
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: Optional[str] = None
    account_id: Optional[int] = None


def load_credentials(path: str = "credentials.json") -> Credentials:
    with open(path, 'r') as f:
        raw = json.load(f)
    return Credentials(
        client_id=raw.get('client_id') or raw.get('clientId'),
        client_secret=raw.get('client_secret') or raw.get('clientSecret'),
        access_token=raw.get('access_token') or raw.get('accessToken'),
        refresh_token=raw.get('refresh_token') or raw.get('refreshToken'),
        account_id=raw.get('account_id') or raw.get('accountId')
    )


async def send_and_recv(ws, msg: Dict[str, Any], *, expect: Optional[List[int]] = None) -> Dict[str, Any]:
    """Küld egy JSON üzenetet és vár egy választ; opcionálisan ellenőrzi a várt payloadType listát."""
    await ws.send(json.dumps(msg))
    resp_raw = await ws.recv()
    try:
        resp = json.loads(resp_raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Nem JSON válasz: {resp_raw[:120]}")
    if expect and resp.get('payloadType') not in expect:
        raise RuntimeError(f"Váratlan payloadType: {resp.get('payloadType')} (várt: {expect}) - teljes válasz: {resp}")
    return resp


async def application_auth(ws, creds: Credentials) -> None:
    msg = {
        'payloadType': PAYLOAD_APP_AUTH_REQ,
        'payload': {
            'clientId': creds.client_id,
            'clientSecret': creds.client_secret,
        }
    }
    print('▶ Alkalmazás autentikáció küldése (2100)')
    resp = await send_and_recv(ws, msg, expect=[PAYLOAD_APP_AUTH_RES])
    print('✅ Alkalmazás autentikáció sikeres (2101)')
    # Ide helyezhető extra ellenőrzés (error mező vizsgálat), ha a protokoll definiálja.


async def account_auth(ws, creds: Credentials) -> None:
    if creds.account_id is None:
        raise RuntimeError('Nincs account_id – előbb account discovery szükséges vagy add meg kézzel a credentials.json-ben.')
    msg = {
        'payloadType': PAYLOAD_ACCOUNT_AUTH_REQ,
        'payload': {
            'ctidTraderAccountId': creds.account_id,
            'accessToken': creds.access_token,
        }
    }
    print(f'▶ Account autentikáció küldése (2102) account_id={creds.account_id}')
    resp = await send_and_recv(ws, msg, expect=[PAYLOAD_ACCOUNT_AUTH_RES])
    print('✅ Account autentikáció sikeres (2103)')


async def account_discovery(ws, creds: Credentials) -> Optional[int]:
    """Account ID felderítése – Heurisztikus: accountId nélkül küldünk 2102-t és ha 2150 jön (lista), kiválasztjuk.
    FONTOS: Ha a szerver valóban 2102-t account auth-ra várja, lehet hogy ez nem működik. Akkor manuális megadás szükséges.
    """
    msg = {
        'payloadType': PAYLOAD_ACCOUNT_AUTH_REQ,  # ugyanazt küldjük, de accountId nélkül
        'payload': {
            'accessToken': creds.access_token,
        }
    }
    print('🔍 Account discovery próbálkozás (2102 payload, nincs accountId)')
    resp = await send_and_recv(ws, msg, expect=[PAYLOAD_ACCOUNTS_LIST_RES, PAYLOAD_ACCOUNT_AUTH_RES])
    pt = resp.get('payloadType')
    if pt == PAYLOAD_ACCOUNTS_LIST_RES:
        payload = resp.get('payload') or {}
        accounts = payload.get('ctidTraderAccount', [])
        if not accounts:
            print('⚠️ Nincs visszaadott account a tokenhez.')
            return None
        # Prefer demo (isLive False) ellenkező esetben első
        selected = None
        for acc in accounts:
            if acc.get('isLive') is False:
                selected = acc
                break
        if selected is None:
            selected = accounts[0]
        acc_id = selected.get('ctidTraderAccountId')
        print(f'✅ Account kiválasztva discovery alapján: {acc_id}')
        return acc_id
    elif pt == PAYLOAD_ACCOUNT_AUTH_RES:
        # A szerver account auth választ adott – ez azt jelenti hogy az access token implicit módon
        # hozzá van kötve egy egyedi accounthoz amit nem listáz. Ilyenkor a protokoll eltér.
        print('ℹ️ Szerver közvetlen account auth választ küldött – discovery nem támogatott ennél a végpontnál.')
        return None
    else:
        print(f'⚠️ Ismeretlen válasz discovery közben: {resp}')
        return None


async def main():
    creds = load_credentials()
    if not creds.client_id or not creds.client_secret or not creds.access_token:
        raise SystemExit('Hiányzó kötelező mezők a credentials.json-ben (client_id, client_secret, access_token)')

    uri = 'wss://live.ctraderapi.com:5036'
    print(f'🌐 Kapcsolódás: {uri}')
    async with connect(uri) as ws:
        print('✅ WebSocket kapcsolat létrejött')

        # 1) App auth
        await application_auth(ws, creds)

        # 2) Account auth vagy discovery
        if creds.account_id is None:
            print('⚠️ Nincs account_id – megpróbálunk discovery-t...')
            acc_id = await account_discovery(ws, creds)
            if acc_id:
                creds.account_id = acc_id
                # Frissítés visszaírása
                try:
                    with open('credentials.json', 'r') as f:
                        raw = json.load(f)
                    raw['account_id'] = acc_id
                    with open('credentials.json', 'w') as f:
                        json.dump(raw, f, indent=2)
                    print('💾 credentials.json frissítve (account_id mentve)')
                except Exception as e:
                    print(f'⚠️ Nem sikerült menteni az account_id-t: {e}')
            else:
                print('❌ Nem sikerült discovery alapján account ID-t szerezni. Adj meg kézzel egyet a credentials.json-ben.')
                return

        # 3) Account auth normál flow
        await account_auth(ws, creds)

        print('🎉 Teljes autentikáció kész, készen áll a további kommunikációra.')
        print('ℹ️ (Itt implementálhatók további üzenetküldések: árak, megbízások, stb.)')

        # Példa: várakozás megszakításig vagy timeout-ig
        try:
            await aio.sleep(2)  # rövid ideig nyitva tartjuk a kapcsolatot
        except aio.CancelledError:
            pass


if __name__ == '__main__':
    aio.run(main())
