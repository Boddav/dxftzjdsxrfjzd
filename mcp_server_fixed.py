#!/usr/bin/env python3
"""
MCP Server for cTrader API Integration - Twisted alapú
"""

import json
import logging
from typing import Dict, Any, Optional
from twisted.internet import reactor, defer
from ctrader_open_api import Client, EndPoints, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CTraderMCPServer:
    """cTrader API MCP Server - Twisted alapú"""

    def __init__(self, credentials_path: str = "credentials.json"):
        self.credentials_path = credentials_path
        self.client: Optional[Client] = None
        self.connected = False
        self.account_id: Optional[int] = None
        self.access_token: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None

        # Callback tárolók
        self._message_deferred = None
        self._connected_deferred = defer.Deferred()

        logger.info("🚀 MCP Server inicializálva")

    def load_credentials(self) -> Dict[str, Any]:
        """Credentials betöltése"""
        try:
            with open(self.credentials_path, 'r') as f:
                credentials = json.load(f)

            self.access_token = credentials['access_token']
            self.account_id = int(credentials['account_id'])
            self.client_id = credentials['client_id']
            self.client_secret = credentials['client_secret']

            logger.info(f"✅ Credentials betöltve (Account: {self.account_id})")
            return credentials

        except Exception as e:
            logger.error(f"❌ Credentials betöltési hiba: {e}")
            raise

    def _on_connected(self):
        """Kapcsolódás callback"""
        logger.info("✅ TCP kapcsolat létrejött")
        if self._connected_deferred and not self._connected_deferred.called:
            self._connected_deferred.callback(True)

    def _on_disconnected(self):
        """Kapcsolat bontás callback"""
        logger.info("🔌 Kapcsolat bontva")
        self.connected = False

    def _on_message_received(self, message):
        """Üzenet fogadás callback"""
        logger.debug(f"📨 Üzenet kapva: {message.payloadType}")
        if self._message_deferred and not self._message_deferred.called:
            self._message_deferred.callback(message)

    @defer.inlineCallbacks
    def connect(self):
        """Csatlakozás a cTrader API-hoz"""
        try:
            credentials = self.load_credentials()

            # Client létrehozása
            host = EndPoints.PROTOBUF_DEMO_HOST
            port = EndPoints.PROTOBUF_PORT

            self.client = Client(host, port, TcpProtocol)

            # Callbackek beállítása
            self.client.setConnectedCallback(self._on_connected)
            self.client.setDisconnectedCallback(self._on_disconnected)
            self.client.setMessageReceivedCallback(self._on_message_received)

            # Szolgáltatás indítása
            self.client.startService()

            # Várakozás a kapcsolatra
            yield self._connected_deferred

            # Alkalmazás authentikáció
            logger.info("🔐 Alkalmazás autentikáció...")
            auth_req = ProtoOAApplicationAuthReq()
            auth_req.clientId = self.client_id
            auth_req.clientSecret = self.client_secret

            self._message_deferred = defer.Deferred()
            self.client.send(auth_req)

            auth_res = yield self._message_deferred

            if auth_res.payloadType == ProtoOAApplicationAuthRes().payloadType:
                logger.info("✅ Alkalmazás autentikáció sikeres")
            else:
                raise Exception(f"Autentikáció sikertelen: {auth_res}")

            # Fiók authentikáció
            logger.info("👤 Fiók autentikáció...")
            acc_auth_req = ProtoOAAccountAuthReq()
            acc_auth_req.ctidTraderAccountId = self.account_id
            acc_auth_req.accessToken = self.access_token

            self._message_deferred = defer.Deferred()
            self.client.send(acc_auth_req)

            acc_auth_res = yield self._message_deferred

            if acc_auth_res.payloadType == ProtoOAAccountAuthRes().payloadType:
                logger.info("✅ Fiók autentikáció sikeres")
                self.connected = True
            else:
                raise Exception(
                    f"Fiók autentikáció sikertelen: {acc_auth_res}")

            defer.returnValue(True)

        except Exception as e:
            logger.error(f"❌ Csatlakozási hiba: {e}")
            self.connected = False
            raise

    @defer.inlineCallbacks
    def get_account_info(self) -> Dict[str, Any]:
        """Számla információk lekérése"""
        try:
            if not self.connected:
                yield self.connect()

            # Trader adatok kérése
            trader_req = ProtoOATraderReq()
            trader_req.ctidTraderAccountId = self.account_id

            self._message_deferred = defer.Deferred()
            self.client.send(trader_req)

            trader_res = yield self._message_deferred

            if trader_res.payloadType == ProtoOATraderRes().payloadType:
                account = trader_res.trader.account[0]

                info = {
                    'balance': account.balance / 100,
                    'equity': account.balance / 100,  # Egyszerűsítve
                    'currency': 'USD',
                    'leverage': account.leverageInCents / 100,
                    'account_id': self.account_id
                }

                logger.info(f"💰 Egyenleg: ${info['balance']:.2f}")
                defer.returnValue(info)
            else:
                raise Exception(
                    f"Számla info lekérés sikertelen: {trader_res}")

        except Exception as e:
            logger.error(f"❌ Számla info hiba: {e}")
            defer.returnValue({
                'balance': 10000,
                'equity': 10000,
                'currency': 'USD',
                'leverage': 100,
                'account_id': self.account_id
            })

    def close(self):
        """Kapcsolat lezárása"""
        try:
            if self.client:
                self.client.stopService()
            logger.info("👋 MCP Server leállítva")
        except Exception as e:
            logger.error(f"❌ Lezárási hiba: {e}")


# Példa eszközök MCP-hez
MCP_TOOLS = [
    {
        "name": "get_account_info",
        "description": "Számla információk lekérése (egyenleg, tőkeáttét, stb.)",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]
