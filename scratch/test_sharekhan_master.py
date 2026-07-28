import sys
import os
import pandas as pd
from dotenv import load_dotenv

# Add workspace root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load env file
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env")))

from database.engine_factory import create_db_engine
create_db_engine()

from database.auth_db import Auth, decrypt_token
import requests

def _format_strike(strike) -> str:
    try:
        val = float(strike)
    except (TypeError, ValueError):
        return ""
    return str(int(val)) if val == int(val) else str(val)

def _build_symbol(row: dict) -> str:
    instrument_type = (row.get("instrumenttype") or "").upper()
    name = row.get("name") or ""
    expiry = row.get("expiry") or ""

    if instrument_type in ("FS", "FI", "FUTCUR", "FUT", "FUTIDX", "FUTSTK"):
        return f"{name}{expiry}FUT"
    if instrument_type in ("OS", "OI", "OPTCUR", "CE", "PE", "OPTIDX", "OPTSTK"):
        option_type = row.get("optiontype") or instrument_type
        if option_type not in ("CE", "PE"):
            if "CE" in row.get("brsymbol", ""):
                option_type = "CE"
            elif "PE" in row.get("brsymbol", ""):
                option_type = "PE"
            else:
                return row.get("brsymbol") or name
        return f"{name}{expiry}{_format_strike(row.get('strike'))}{option_type}"
    return name or row.get("brsymbol") or ""

def test_parser():
    session_obj = Auth.query.filter_by(broker="sharekhan", is_revoked=False).first()
    if not session_obj:
        print("No active Sharekhan session found!")
        return
        
    auth_token = decrypt_token(session_obj.auth)
    access_token = auth_token.split(":::", 1)[0]
    
    from database.user_db import UserBrokerCredential
    cred = UserBrokerCredential.query.filter_by(broker_name="sharekhan").first()
    api_key = decrypt_token(cred.broker_api_key).split(":::", 1)[0].strip()
    
    url = "https://api.sharekhan.com/skapi/services/master/MX"
    headers = {
        "api-key": api_key,
        "access-token": access_token,
        "Content-type": "application/json"
    }
    
    print("Fetching master list from Sharekhan...")
    r = requests.get(url, headers=headers)
    data = r.json().get("data", [])
    print(f"Total rows fetched: {len(data)}")
    
    parsed_records = []
    for row in data[:1000]:  # inspect first 1000 rows
        scrip_code = row.get("scripCode") or row.get("scrip_code") or row.get("code")
        trading_symbol = row.get("tradingSymbol") or row.get("symbol") or row.get("scripName")
        if not scrip_code or not trading_symbol:
            continue

        trading_symbol_str = str(trading_symbol).strip()
        base_symbol = trading_symbol_str.split()[0].upper()

        expiry_raw = row.get("expiry") or row.get("expiryDate") or ""
        expiry = ""
        if expiry_raw and str(expiry_raw) != "0":
            try:
                expiry = pd.to_datetime(expiry_raw, dayfirst=True).strftime("%d%b%y").upper()
            except (ValueError, TypeError):
                expiry = str(expiry_raw)

        instrument_type = row.get("instType") or row.get("instrumentType") or row.get("instrument_type") or "EQ"
        strike = row.get("strike") or row.get("strikePrice") or row.get("strike_price") or 0.0

        record = {
            "symbol": "",
            "brsymbol": trading_symbol_str,
            "name": base_symbol,
            "exchange": "NFO",
            "brexchange": "MX",
            "token": str(scrip_code),
            "expiry": expiry,
            "strike": float(strike) if strike else 0.0,
            "lotsize": int(row.get("lotSize") or row.get("lot_size") or 1),
            "instrumenttype": instrument_type,
            "tick_size": float(row.get("tickSize") or row.get("tick_size") or 0.05),
            "optiontype": row.get("optionType") or row.get("option_type") or ""
        }
        record["symbol"] = _build_symbol(record)
        parsed_records.append(record)
        
    print("\nSample parsed options/futures:")
    options = [r for r in parsed_records if r["instrumenttype"] in ("OPTIDX", "OPTSTK", "OS", "OI")]
    for o in options[:5]:
        print(f"TradingSymbol: {o['brsymbol']} -> Parsed Symbol: {o['symbol']}, InstType: {o['instrumenttype']}, Expiry: {o['expiry']}, Strike: {o['strike']}")
        
    futures = [r for r in parsed_records if r["instrumenttype"] in ("FUTIDX", "FUTSTK", "FS", "FI", "FUT")]
    for f in futures[:5]:
        print(f"TradingSymbol: {f['brsymbol']} -> Parsed Symbol: {f['symbol']}, InstType: {f['instrumenttype']}, Expiry: {f['expiry']}, Strike: {f['strike']}")

if __name__ == "__main__":
    test_parser()
