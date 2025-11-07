#!/usr/bin/env python3
"""
cTrader OAuth Setup Server
Automatikus OAuth flow GitHub Codespaces környezetben
"""

import os
import json
import logging
import webbrowser
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests

# Logging beállítása
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# cTrader API konfiguráció
CLIENT_ID = "13617_NoiIy9DOCJXwKnJEE0mWHGPQZFvkSZfIKDrJ6paJv6cL05JAR5"
CLIENT_SECRET = "M6qpm5h25hDHsq31SFvi4lwxWII0S829sJxeG14cz56QDFrzFC"
PORT = 53123

# API Endpoints
AUTH_URL = "https://openapi.ctrader.com/apps/auth"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
ACCOUNTS_URL = "https://openapi.ctrader.com/apps/accounts"


def detect_codespaces_url() -> str:
    """
    Automatikusan észleli a GitHub Codespaces URL-t

    Returns:
        str: Redirect URI (Codespaces URL vagy localhost)
    """
    # GitHub Codespaces környezeti változók
    codespace_name = os.getenv('CODESPACE_NAME')
    github_codespaces_port_forwarding_domain = os.getenv(
        'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN')

    if codespace_name and github_codespaces_port_forwarding_domain:
        # Codespaces URL formátum: https://{codespace_name}-{port}.{domain}
        redirect_uri = f"https://{codespace_name}-{PORT}.{github_codespaces_port_forwarding_domain}/callback"
        logger.info(f"🚀 GitHub Codespaces észlelve: {redirect_uri}")
        return redirect_uri
    else:
        # Helyi fejlesztés - mindig 127.0.0.1 használata
        redirect_uri = f"http://127.0.0.1:{PORT}/callback"
        logger.info(f"💻 Helyi környezet: {redirect_uri}")
        return redirect_uri


class OAuthHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler az OAuth flow-hoz"""

    authorization_code = None
    access_token = None
    refresh_token = None
    account_id = None

    def do_GET(self):
        """GET kérések kezelése"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/':
            # Kezdőoldal - OAuth kezdeményezés
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()

            redirect_uri = detect_codespaces_url()
            # Több scope az account hozzáféréshez
            auth_url = f"{AUTH_URL}?client_id={CLIENT_ID}&redirect_uri={redirect_uri}&scope=trading+accounts"

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>cTrader OAuth Setup</title>
                <style>
                    * {{
                        margin: 0;
                        padding: 0;
                        box-sizing: border-box;
                    }}
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        padding: 20px;
                    }}
                    .container {{
                        background: white;
                        border-radius: 20px;
                        box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                        padding: 50px;
                        max-width: 600px;
                        width: 100%;
                        text-align: center;
                    }}
                    h1 {{
                        color: #333;
                        margin-bottom: 20px;
                        font-size: 32px;
                    }}
                    .icon {{
                        font-size: 64px;
                        margin-bottom: 20px;
                    }}
                    p {{
                        color: #666;
                        margin-bottom: 30px;
                        line-height: 1.6;
                        font-size: 16px;
                    }}
                    .btn {{
                        display: inline-block;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                        padding: 15px 40px;
                        border-radius: 50px;
                        text-decoration: none;
                        font-weight: bold;
                        font-size: 18px;
                        transition: transform 0.2s, box-shadow 0.2s;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                    }}
                    .btn:hover {{
                        transform: translateY(-2px);
                        box-shadow: 0 6px 20px rgba(0,0,0,0.3);
                    }}
                    .info {{
                        background: #f8f9fa;
                        border-left: 4px solid #667eea;
                        padding: 15px;
                        margin-top: 30px;
                        text-align: left;
                        border-radius: 5px;
                    }}
                    .info strong {{
                        color: #333;
                    }}
                    code {{
                        background: #e9ecef;
                        padding: 2px 6px;
                        border-radius: 3px;
                        font-family: 'Courier New', monospace;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon">🤖📈</div>
                    <h1>AI Trading Advisor</h1>
                    <p>Üdvözöllek a cTrader OAuth beállítóban!</p>
                    <p>Kattints az alábbi gombra a cTrader fiókod csatlakoztatásához.</p>
                    <a href="{auth_url}" class="btn">🔐 Csatlakozás cTrader-hez</a>

                    <div class="info">
                        <strong>ℹ️ Mi fog történni?</strong><br>
                        1. Átirányítás a cTrader bejelentkezési oldalára<br>
                        2. Fiók engedélyezése<br>
                        3. Automatikus <code>credentials.json</code> létrehozás<br>
                        4. Trading bot használatra kész!
                    </div>
                </div>
            </body>
            </html>
            """

            self.wfile.write(html.encode('utf-8'))

        elif parsed_path.path == '/callback':
            # OAuth callback kezelése
            query_params = parse_qs(parsed_path.query)

            if 'code' in query_params:
                OAuthHandler.authorization_code = query_params['code'][0]
                logger.info(
                    f"✅ Authorization code kapva: {OAuthHandler.authorization_code[:20]}...")

                # Token csere
                success = self.exchange_token()

                if success:
                    # Sikeres authentikáció
                    self.send_response(200)
                    self.send_header(
                        'Content-type', 'text/html; charset=utf-8')
                    self.end_headers()

                    html = """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <title>OAuth Sikeres!</title>
                        <style>
                            body {
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
                                display: flex;
                                justify-content: center;
                                align-items: center;
                                min-height: 100vh;
                                margin: 0;
                                padding: 20px;
                            }
                            .container {
                                background: white;
                                border-radius: 20px;
                                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                                padding: 50px;
                                max-width: 600px;
                                text-align: center;
                            }
                            .icon { font-size: 80px; margin-bottom: 20px; }
                            h1 { color: #11998e; margin-bottom: 20px; }
                            p { color: #666; line-height: 1.6; margin-bottom: 15px; }
                            .success-box {
                                background: #d4edda;
                                border: 1px solid #c3e6cb;
                                border-radius: 10px;
                                padding: 20px;
                                margin-top: 20px;
                            }
                            code {
                                background: #f8f9fa;
                                padding: 10px;
                                border-radius: 5px;
                                display: block;
                                margin-top: 10px;
                                font-family: 'Courier New', monospace;
                                text-align: left;
                            }
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="icon">✅</div>
                            <h1>Sikeres Csatlakozás!</h1>
                            <p>A cTrader fiókod sikeresen össze lett kapcsolva.</p>
                            <p><code>credentials.json</code> fájl automatikusan létrehozva!</p>

                            <div class="success-box">
                                <strong>✨ Most már használhatod:</strong><br><br>
                                <code>python ai_trading_advisor.py</code>
                            </div>

                            <p style="margin-top: 30px; color: #999;">Bezárhatod ezt az ablakot és visszatérhetsz a terminálhoz.</p>
                        </div>
                    </body>
                    </html>
                    """

                    self.wfile.write(html.encode('utf-8'))
                else:
                    # Hiba történt
                    self.send_error(500, "Token csere sikertelen")
            else:
                # Nincs authorization code
                self.send_error(400, "Hiányzó authorization code")
        else:
            self.send_error(404, "Az oldal nem található")

    def exchange_token(self) -> bool:
        """
        Authorization code cseréje access token-re

        Returns:
            bool: Sikeres-e a művelet
        """
        try:
            redirect_uri = detect_codespaces_url()

            # Token kérés
            token_data = {
                'grant_type': 'authorization_code',
                'code': OAuthHandler.authorization_code,
                'redirect_uri': redirect_uri,
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET
            }

            logger.info("🔄 Token csere folyamatban...")
            response = requests.post(TOKEN_URL, data=token_data)
            response.raise_for_status()

            token_response = response.json()
            OAuthHandler.access_token = token_response['access_token']
            OAuthHandler.refresh_token = token_response['refresh_token']

            logger.info("✅ Access token kapva!")

            # Account ID lekérése
            self.get_account_id()

            # Credentials mentése
            self.save_credentials()

            return True

        except Exception as e:
            logger.error(f"❌ Token csere hiba: {e}")
            return False

    def get_account_id(self):
        """Trading account ID lekérése"""
        try:
            headers = {
                'Authorization': f'Bearer {OAuthHandler.access_token}'
            }

            response = requests.get(ACCOUNTS_URL, headers=headers)
            response.raise_for_status()

            accounts = response.json()
            if accounts and len(accounts) > 0:
                # Első demo account használata
                for account in accounts:
                    if account.get('live') == False:  # Demo account
                        OAuthHandler.account_id = account['accountId']
                        logger.info(
                            f"✅ Demo Account ID: {OAuthHandler.account_id}")
                        return

                # Ha nincs demo, akkor az első live account
                OAuthHandler.account_id = accounts[0]['accountId']
                logger.info(f"⚠️ Live Account ID: {OAuthHandler.account_id}")
            else:
                logger.warning("⚠️ Nem található trading account")

        except Exception as e:
            logger.error(f"❌ Account lekérési hiba: {e}")

    def save_credentials(self):
        """Credentials mentése JSON fájlba"""
        credentials = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'access_token': OAuthHandler.access_token,
            'refresh_token': OAuthHandler.refresh_token,
            'account_id': OAuthHandler.account_id,
            'redirect_uri': detect_codespaces_url()
        }

        with open('credentials.json', 'w') as f:
            json.dump(credentials, f, indent=2)

        logger.info("💾 credentials.json sikeresen létrehozva!")

    def log_message(self, format, *args):
        """HTTP log üzenetek elnyomása"""
        pass


def main():
    """Főprogram - OAuth szerver indítása"""
    print("=" * 60)
    print("🤖 AI Trading Advisor - cTrader OAuth Setup")
    print("=" * 60)

    redirect_uri = detect_codespaces_url()
    print(f"\n📍 Redirect URI: {redirect_uri}")
    print(f"🌐 Server Port: {PORT}\n")

    # HTTP szerver indítása
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, OAuthHandler)

    print("🚀 OAuth szerver elindult!")
    print(f"👉 Nyisd meg böngészőben: {redirect_uri}\n")
    print("⏳ Várakozás az OAuth flow befejezésére...")
    print("=" * 60)

    try:
        # Böngésző automatikus megnyitása (ha lehet)
        try:
            webbrowser.open(redirect_uri)
        except:
            pass

        httpd.serve_forever()

    except KeyboardInterrupt:
        print("\n\n⚠️ Szerver leállítva")
        httpd.shutdown()


if __name__ == "__main__":
    main()
