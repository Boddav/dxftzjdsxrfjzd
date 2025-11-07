# cTrader API Troubleshooting Guide

## Common Authentication Issues

### 1. Invalid Access Token Error

**Symptom:**
```
❌ Account authentication failed: CH_ACCESS_TOKEN_INVALID
```

**Causes:**
- The access token doesn't match the account ID
- The token has expired
- The OAuth flow didn't complete properly
- Wrong account was selected during OAuth

**Solution:**
```bash
# Remove old credentials
rm credentials.json

# Run OAuth setup again
python ctrader_oauth_setup.py

# IMPORTANT: In the browser, make sure to SELECT a trading account
# The account selector appears after you click "Authorize"
```

### 2. Missing Credentials

**Symptom:**
```
❌ ERROR: Missing credentials!
```

**Solution:**

**Option 1: OAuth Setup (Recommended)**
```bash
python ctrader_oauth_setup.py
```
This will:
- Start a local server on port 8080
- Open your browser for cTrader OAuth
- Automatically create `credentials.json`
- Fetch and save your account ID

**Option 2: Manual .env File**
```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your credentials:
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret
ACCESS_TOKEN=your_access_token
ACCOUNT_ID=your_account_id
```

### 3. Connection Timeout

**Symptom:**
```
Error: Connection timeout
```

**Possible Causes:**
- No internet connection
- Firewall blocking port 5035
- cTrader API is down

**Solution:**
```bash
# Test internet connectivity
ping demo.ctraderapi.com

# Check if port 5035 is accessible
telnet demo.ctraderapi.com 5035

# Try switching between demo and live endpoints
# Edit your script and change:
# EndPoints.PROTOBUF_DEMO_HOST  # for demo
# EndPoints.PROTOBUF_LIVE_HOST  # for live
```

### 4. Account ID Not Found

**Symptom:**
```
❌ Nincs elérhető account a tokenhez
❌ No accounts available for this token
```

**Causes:**
- The access token is not associated with any trading account
- Account was deleted or suspended

**Solution:**
1. Go to [cTrader Open API](https://openapi.ctrader.com/)
2. Check your connected accounts
3. If no accounts are listed, create or connect a demo account
4. Run the OAuth setup again: `python ctrader_oauth_setup.py`

### 5. Port Already in Use (OAuth Setup)

**Symptom:**
```
OSError: [Errno 48] Address already in use
```

**Solution:**
```bash
# Kill the process using port 8080
lsof -ti:8080 | xargs kill -9

# OR change the port in ctrader_oauth_setup.py
# Edit the file and change: PORT = 8081
```

### 6. Module Not Found Errors

**Symptom:**
```
ModuleNotFoundError: No module named 'ctrader_open_api'
```

**Solution:**
```bash
# Install all dependencies
pip install -r requirements.txt

# Or install specific packages:
pip install ctrader-open-api twisted protobuf==3.20.1
```

## Testing Your Connection

### Quick Connection Test

```bash
# Test with improved client (auto account discovery)
python ctrader_client_improved.py
```

**Expected Output:**
```
✅ TCP kapcsolat létrejött
✅ Alkalmazás autentikáció sikeres
✅ Fiók autentikáció sikeres!
🎉 SIKERES CSATLAKOZÁS!
```

### Live Price Stream Test

```bash
# Test live price streaming
python test_live_stream.py
```

**Expected Output:**
```
Connected
App authenticated
Account authenticated
Requesting symbol list...
Symbols received
EURUSD -> SymbolID 1
XAUUSD -> SymbolID 2
Subscribing to price streams...
Price update: EURUSD Bid 1.05123 Ask 1.05125
Price update: XAUUSD Bid 2650.50 Ask 2650.80
...
```

### Simple Connection Test

```bash
# Basic connection test (no price streaming)
python test_ctrader_twisted.py
```

## Debugging Tips

### Enable Detailed Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Add this at the top of your Python script to see detailed log messages.

### Check Credentials Format

Your `credentials.json` should look like this:
```json
{
  "client_id": "your_client_id_here",
  "client_secret": "your_client_secret_here",
  "access_token": "your_access_token_here",
  "refresh_token": "your_refresh_token_here",
  "account_id": 12345678
}
```

### Verify Account ID

To find your account ID manually:
```bash
python find_account_id.py
```

This script will list all accounts associated with your access token.

## Demo vs Live Accounts

### Demo Account (Recommended for Testing)
- Endpoint: `demo.ctraderapi.com`
- Port: `5035`
- Use for: Testing, development, learning
- No real money involved

### Live Account (Real Trading)
- Endpoint: `live.ctraderapi.com`
- Port: `5035`
- Use for: Real trading with real money
- ⚠️ **BE CAREFUL** - Real money at risk

To switch between demo and live:
```python
# For demo:
host = EndPoints.PROTOBUF_DEMO_HOST

# For live:
host = EndPoints.PROTOBUF_LIVE_HOST
```

## Getting Help

If you're still having issues:

1. **Check the logs**: Look for detailed error messages
2. **Verify credentials**: Make sure all credentials are correct
3. **Try OAuth again**: `rm credentials.json && python ctrader_oauth_setup.py`
4. **Check cTrader status**: Visit [cTrader Open API Portal](https://openapi.ctrader.com/)
5. **Review documentation**: [cTrader Open API Docs](https://help.ctrader.com/open-api/)

## Security Reminders

- ✅ **DO**: Use demo accounts for testing
- ✅ **DO**: Keep credentials in `.gitignore`
- ✅ **DO**: Use environment variables or credentials.json
- ❌ **DON'T**: Commit credentials to git
- ❌ **DON'T**: Share your access tokens
- ❌ **DON'T**: Use live accounts until thoroughly tested

## Quick Checklist

Before running any cTrader script, verify:

- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Credentials file exists (`credentials.json` or `.env`)
- [ ] Account ID is correct
- [ ] Access token is valid (not expired)
- [ ] Internet connection is working
- [ ] Using correct endpoint (demo vs live)

---

**Need more help?** Check the main [README.md](README.md) for complete setup instructions.
