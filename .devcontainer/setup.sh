#!/bin/bash
# AI Trading Advisor - Codespaces Setup Script

echo "╔════════════════════════════════════════════╗"
echo "║   AI Trading Advisor - Codespaces Setup   ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Színek
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Python függőségek telepítése
echo -e "${BLUE}📦 Python függőségek telepítése...${NC}"
pip install --upgrade pip
pip install -r requirements.txt --ignore-installed PyJWT
echo -e "${GREEN}✅ Függőségek telepítve${NC}"
echo ""

# 2. .env fájl létrehozása (ha nincs)
if [ ! -f .env ]; then
    echo -e "${BLUE}📝 .env fájl létrehozása...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}⚠️  Állítsd be az ANTHROPIC_API_KEY-t a .env fájlban!${NC}"
    echo ""
fi

# 3. Portok ellenőrzése
echo -e "${BLUE}🔍 Elérhető portok:${NC}"
echo "  - Admin UI: http://localhost:5000"
echo "  - OAuth Server: http://localhost:8080"
echo ""

# 4. Codespaces URL észlelése
if [ -n "$CODESPACE_NAME" ]; then
    echo -e "${GREEN}🚀 GitHub Codespaces észlelve!${NC}"
    ADMIN_URL="https://${CODESPACE_NAME}-5000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
    OAUTH_URL="https://${CODESPACE_NAME}-8080.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"

    echo -e "${BLUE}Codespaces URL-ek:${NC}"
    echo "  - Admin UI: $ADMIN_URL"
    echo "  - OAuth Server: $OAUTH_URL"
else
    echo -e "${YELLOW}⚠️  Nem Codespaces környezet${NC}"
    echo "  - Használd: http://localhost:5000"
fi
echo ""

# 5. Gyors parancsok
echo -e "${BLUE}🎯 Gyors parancsok:${NC}"
echo "  1. Admin felület indítása: ${GREEN}python3 admin_interface.py${NC}"
echo "  2. OAuth setup: ${GREEN}python3 ctrader_oauth_setup.py${NC}"
echo "  3. Trading bot: ${GREEN}python3 ai_trading_advisor.py${NC}"
echo ""

echo -e "${GREEN}✅ Setup befejezve!${NC}"
echo "═════════════════════════════════════════════"
