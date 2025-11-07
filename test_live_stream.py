#!/usr/bin/env python3
"""
cTrader Live Price Stream Client
---------------------------------
This script demonstrates real-time price streaming from cTrader API using Twisted framework.

Features:
- Application and account authentication
- Symbol list retrieval
- Real-time price updates for multiple symbols (EURUSD, XAUUSD, USDCNH, XAGUSD)
- Automatic credential loading from credentials.json or .env

Usage:
1. Setup credentials:
   python ctrader_oauth_setup.py  (RECOMMENDED)
   OR
   Create .env file with your credentials

2. Run the script:
   python test_live_stream.py

The script will:
- Connect to cTrader API
- Authenticate your app and account
- Subscribe to price streams
- Print real-time bid/ask prices
"""

from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
import ctrader_open_api.messages.OpenApiMessages_pb2 as OA
import os
import sys
import json
from twisted.internet import reactor
from dotenv import load_dotenv

load_dotenv()

# Try to load credentials from credentials.json first, fallback to .env
def load_credentials():
    """Load credentials from credentials.json or .env file"""
    try:
        # Try credentials.json first (created by ctrader_oauth_setup.py)
        with open('credentials.json', 'r') as f:
            creds = json.load(f)
            print("📄 Using credentials from credentials.json")
            
            # Safe account_id extraction with proper None handling
            account_id_value = creds.get('account_id') or creds.get('accountId')
            if account_id_value is None:
                print("\n❌ ERROR: account_id is missing from credentials.json")
                print("Please run: python ctrader_oauth_setup.py")
                return None
            
            return {
                "clientId": creds.get('client_id') or creds.get('clientId'),
                "clientSecret": creds.get('client_secret') or creds.get('clientSecret'),
                "accessToken": creds.get('access_token') or creds.get('accessToken'),
                "accountId": int(account_id_value)
            }
    except FileNotFoundError:
        # Fallback to .env
        print("📄 Using credentials from .env file")
        client_id = os.getenv("CLIENT_ID")
        client_secret = os.getenv("CLIENT_SECRET")
        access_token = os.getenv("ACCESS_TOKEN")
        account_id = os.getenv("ACCOUNT_ID")
        
        if not all([client_id, client_secret, access_token, account_id]):
            print("\n❌ ERROR: Missing credentials!")
            print("\nPlease either:")
            print("1. Run: python ctrader_oauth_setup.py (RECOMMENDED)")
            print("2. Create a .env file with CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID")
            print("\nSee .env.example for the template.")
            return None
            
        return {
            "clientId": client_id,
            "clientSecret": client_secret,
            "accessToken": access_token,
            "accountId": int(account_id)
        }

credentials = load_credentials()
if not credentials:
    sys.exit(1)

client = Client(EndPoints.PROTOBUF_LIVE_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
PROTO_OA_ERROR_RES_PAYLOAD_TYPE = OA.ProtoOAErrorRes().payloadType

tickers = ["EURUSD", "XAUUSD", "USDCNH", "XAGUSD"]
symbol_ids = {}

def onAccAuth(message):
    if message.payloadType == PROTO_OA_ERROR_RES_PAYLOAD_TYPE:
        print("Account authentication failed:", Protobuf.extract(message))
        reactor.stop()
        return
    print("Account authenticated")
    print("Requesting symbol list...")
    req = OA.ProtoOASymbolsListReq()
    req.ctidTraderAccountId = credentials["accountId"]
    deferred = client.send(req)
    deferred.addCallbacks(onSymbolsList, onError)

def onSymbolsList(message):
    response = Protobuf.extract(message)
    print("Symbols received")
    for symbol in response.symbol:
        if symbol.symbolName in tickers:
            symbol_ids[symbol.symbolName] = symbol.symbolId
            print(f"{symbol.symbolName} -> SymbolID {symbol.symbolId}")
    subscribeToPrices()

def subscribeToPrices():
    print("Subscribing to price streams...")
    req = OA.ProtoOASubscribeSpotsReq()
    req.ctidTraderAccountId = credentials["accountId"]
    # Setup ID list
    req.symbolId.extend(symbol_ids.values())
    client.send(req)

def onMsg(client, message):
    if message.payloadType == OA.ProtoOASpotEvent().payloadType:
        response = Protobuf.extract(message)
        symbolName = next((n for n, sid in symbol_ids.items() if sid == response.symbolId), str(response.symbolId))
        print(f"Price update: {symbolName} Bid {response.bid} Ask {response.ask}")

def onAppAuth(message):
    if message.payloadType == PROTO_OA_ERROR_RES_PAYLOAD_TYPE:
        print("App authentication failed:", Protobuf.extract(message))
        reactor.stop()
        return
    print("App authenticated")
    req = OA.ProtoOAAccountAuthReq()
    req.ctidTraderAccountId = credentials["accountId"]
    req.accessToken = credentials["accessToken"]
    deferred = client.send(req)
    deferred.addCallbacks(onAccAuth, onError)

def onError(failure):
    print("Error:", repr(failure.value))
    reactor.stop()

def connected(client):
    print("Connected")
    req = OA.ProtoOAApplicationAuthReq()
    req.clientId = credentials["clientId"]
    req.clientSecret = credentials["clientSecret"]
    deferred = client.send(req, responseTimeoutInSeconds=20)
    deferred.addCallbacks(onAppAuth, onError)

def disconnected(client, reason):
    print("Disconnected:", reason)
    reactor.stop()

client.setConnectedCallback(connected)
client.setDisconnectedCallback(disconnected)
client.setMessageReceivedCallback(onMsg)

if __name__ == "__main__":
    print("=" * 70)
    print("🤖 cTrader Live Price Stream Client")
    print("=" * 70)
    print()
    print(f"📡 Connecting to: {EndPoints.PROTOBUF_LIVE_HOST}:{EndPoints.PROTOBUF_PORT}")
    print(f"🏦 Account ID: {credentials['accountId']}")
    print(f"📊 Symbols: {', '.join(tickers)}")
    print()
    print("Press Ctrl+C to stop...")
    print("=" * 70)
    print()
    
    try:
        client.startService()
        reactor.run()
    except KeyboardInterrupt:
        print("\n\n⚠️  Stopping... (Ctrl+C pressed)")
        print("👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
