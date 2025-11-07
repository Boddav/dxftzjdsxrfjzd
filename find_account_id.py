#!/usr/bin/env python3
"""
cTrader Account ID lekérése
"""

import json
from twisted.internet import reactor
from ctrader_open_api import Client, EndPoints, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *


class AccountIDFinder:
    """Account ID-k lekérése"""

    def __init__(self):
        self.client = None

        # Credentials betöltése
        with open('credentials.json', 'r') as f:
            creds = json.load(f)

        self.client_id = creds['client_id']
        self.client_secret = creds['client_secret']
        self.access_token = creds['access_token']

        print("=" * 60)
        print("🔍 cTrader Account ID Keresése")
        print("=" * 60)

    def on_connected(self, client):
        """Kapcsolódás sikeres"""
        print("✅ Kapcsolódva")
        print("🔐 Autentikáció...")

        # Alkalmazás auth
        auth_req = ProtoOAApplicationAuthReq()
        auth_req.clientId = self.client_id
        auth_req.clientSecret = self.client_secret
        self.client.send(auth_req)

    def on_disconnected(self, client, reason):
        """Kapcsolat bontva"""
        if reactor.running:
            reactor.stop()

    def on_message_received(self, client, message):
        """Üzenet fogadva"""
        payload_type = message.payloadType

        # Alkalmazás auth válasz
        if payload_type == ProtoOAApplicationAuthRes().payloadType:
            print("✅ Alkalmazás auth OK")
            print("📋 Account-ok lekérése...")

            # Accountok kérése (NEM account auth, hanem account list!)
            # Használjuk a GetAccountListReq-t
            acc_list_req = ProtoOAGetAccountListByAccessTokenReq()
            acc_list_req.accessToken = self.access_token
            self.client.send(acc_list_req)

        # Account lista válasz
        elif payload_type == ProtoOAGetAccountListByAccessTokenRes().payloadType:
            print("=" * 60)
            print("📊 Elérhető Trading Account-ok:")
            print("=" * 60)

            if hasattr(message.payload, 'ctidTraderAccount'):
                accounts = message.payload.ctidTraderAccount

                for acc in accounts:
                    account_type = "LIVE" if acc.isLive else "DEMO"
                    print(f"\n  🏦 Account ID: {acc.ctidTraderAccountId}")
                    print(f"     Típus: {account_type}")
                    print(f"     Broker: {acc.brokerName}")

                    # Mentés (első demo account)
                    if not acc.isLive:
                        creds = json.load(open('credentials.json'))
                        creds['account_id'] = acc.ctidTraderAccountId

                        with open('credentials.json', 'w') as f:
                            json.dump(creds, f, indent=2)

                        print(
                            f"\n💾 Demo Account ID mentve: {acc.ctidTraderAccountId}")
                        break

                print("\n" + "=" * 60)
                print("✅ Kész! Most már használhatod a botot!")
                print("=" * 60)
            else:
                print("❌ Nem találhatók account-ok")

            reactor.callLater(1, self.stop)

        # Hiba
        elif payload_type == ProtoOAErrorRes().payloadType:
            print(f"❌ Hiba: {message.payload}")
            reactor.callLater(1, self.stop)

    def start(self):
        """Indítás"""
        try:
            self.client = Client(EndPoints.PROTOBUF_DEMO_HOST,
                                 EndPoints.PROTOBUF_PORT, TcpProtocol)

            self.client.setConnectedCallback(self.on_connected)
            self.client.setDisconnectedCallback(self.on_disconnected)
            self.client.setMessageReceivedCallback(self.on_message_received)

            self.client.startService()
            reactor.run()

        except Exception as e:
            print(f"❌ Hiba: {e}")
            import traceback
            traceback.print_exc()

    def stop(self):
        """Leállítás"""
        if self.client:
            self.client.stopService()
        if reactor.running:
            reactor.stop()


if __name__ == "__main__":
    finder = AccountIDFinder()
    finder.start()
