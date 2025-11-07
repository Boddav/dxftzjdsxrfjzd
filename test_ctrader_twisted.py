#!/usr/bin/env python3
"""
cTrader API Connection Test - Twisted alapú
A hivatalos dokumentáció alapján: https://m-ahmadi.github.io/ctoa/
"""

import json
import sys
from twisted.internet import reactor, defer
from ctrader_open_api import Client, EndPoints, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *


class CTraderTest:
    """Egyszerű cTrader API teszt"""

    def __init__(self):
        self.client = None
        self.authenticated = False

        # Credentials betöltése
        with open('credentials.json', 'r') as f:
            creds = json.load(f)

        self.client_id = creds['client_id']
        self.client_secret = creds['client_secret']
        self.access_token = creds['access_token']
        self.account_id = int(creds['account_id'])

        print("=" * 60)
        print("🤖 cTrader API Kapcsolat Teszt (Twisted)")
        print("=" * 60)
        print(f"🏦 Account ID: {self.account_id}")
        print()

    def on_connected(self, client):
        """Kapcsolódás sikeres callback"""
        print("✅ TCP kapcsolat létrejött")
        print("🔐 Alkalmazás autentikáció...")

        # Alkalmazás auth
        auth_req = ProtoOAApplicationAuthReq()
        auth_req.clientId = self.client_id
        auth_req.clientSecret = self.client_secret
        self.client.send(auth_req)

    def on_disconnected(self, client, reason):
        """Kapcsolat bontva callback"""
        print("🔌 Kapcsolat bontva")
        reactor.stop()

    def on_message_received(self, client, message):
        """Üzenet fogadva callback"""
        payload_type = message.payloadType

        # Alkalmazás auth válasz
        if payload_type == ProtoOAApplicationAuthRes().payloadType:
            print("✅ Alkalmazás autentikáció sikeres")
            print("👤 Fiók autentikáció...")

            # Fiók auth
            acc_auth_req = ProtoOAAccountAuthReq()
            acc_auth_req.ctidTraderAccountId = self.account_id
            acc_auth_req.accessToken = self.access_token
            self.client.send(acc_auth_req)

        # Fiók auth válasz
        elif payload_type == ProtoOAAccountAuthRes().payloadType:
            print("✅ Fiók autentikáció sikeres")
            print("📋 Számla információk kérése...")

            self.authenticated = True

            # Trader info kérése
            trader_req = ProtoOATraderReq()
            trader_req.ctidTraderAccountId = self.account_id
            self.client.send(trader_req)

        # Trader info válasz
        elif payload_type == ProtoOATraderRes().payloadType:
            print("=" * 60)
            print("📊 Számla Információk:")
            print("=" * 60)

            trader = message.trader
            for account in trader.account:
                account_type = "LIVE" if account.live else "DEMO"
                balance = account.balance / 100
                leverage = account.leverageInCents / 100

                print(f"  🏦 Account ID: {account.accountId}")
                print(f"     Típus: {account_type}")
                print(f"     Egyenleg: ${balance:.2f}")
                print(f"     Tőkeáttét: 1:{leverage:.0f}")
                print(f"     Broker: {account.brokerName}")

            print("=" * 60)
            print("🎉 SIKERES KAPCSOLAT!")
            print("=" * 60)
            print("✅ cTrader API működik!")
            print("✅ Most már használhatod a trading botot!")
            print("=" * 60)

            # Leállítás 2 másodperc múlva
            reactor.callLater(2, self.stop)

        # Hiba
        elif payload_type == ProtoOAErrorRes().payloadType:
            error_msg = message.payload
            print(f"❌ Hiba válasz kapva: {error_msg}")
            reactor.callLater(1, self.stop)

        else:
            print(f"📨 Ismeretlen üzenet típus: {payload_type}")

    def start(self):
        """Teszt indítása"""
        try:
            # Client létrehozása
            host = EndPoints.PROTOBUF_DEMO_HOST
            port = EndPoints.PROTOBUF_PORT

            print(f"📡 Csatlakozás: {host}:{port}")

            self.client = Client(host, port, TcpProtocol)

            # Callbackek beállítása
            self.client.setConnectedCallback(self.on_connected)
            self.client.setDisconnectedCallback(self.on_disconnected)
            self.client.setMessageReceivedCallback(self.on_message_received)

            # Szolgáltatás indítása
            self.client.startService()

            # Reactor indítása
            reactor.run()

        except Exception as e:
            print(f"❌ Hiba: {e}")
            import traceback
            traceback.print_exc()

    def stop(self):
        """Leállítás"""
        if self.client:
            self.client.stopService()
        reactor.stop()


if __name__ == "__main__":
    test = CTraderTest()
    test.start()
