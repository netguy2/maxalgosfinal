import sys
import os
from dotenv import load_dotenv

# Add workspace root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load env file
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env")))

from database.engine_factory import create_db_engine
create_db_engine()

from database.auth_db import Auth, decrypt_token
import requests

def inspect():
    # Get active Sharekhan session
    session_obj = Auth.query.filter_by(broker="sharekhan", is_revoked=False).first()
    if not session_obj:
        print("No active Sharekhan session found!")
        return
        
    auth_token = decrypt_token(session_obj.auth)
    access_token = auth_token.split(":::", 1)[0]
    
    # Get credentials
    from database.user_db import UserBrokerCredential
    cred = UserBrokerCredential.query.filter_by(broker_name="sharekhan").first()
    if not cred:
        print("No Sharekhan credentials in DB!")
        return
    full_api_key = decrypt_token(cred.broker_api_key)
    api_key = full_api_key.split(":::", 1)[0].strip()

    
    url = "https://api.sharekhan.com/skapi/services/master/MX"
    headers = {
        "api-key": api_key,
        "access-token": access_token,
        "Content-type": "application/json"
    }
    
    print("Fetching master list from Sharekhan...")
    try:
        r = requests.get(url, headers=headers)
        print("Response status:", r.status_code)
        data = r.json()
        print("Full response payload:", data)
        rows = data.get("data", [])
        print("Number of rows:", len(rows))

        if rows:
            print("\nFirst row keys and values:")
            for k, v in rows[0].items():
                print(f"  {k}: {v} (type: {type(v).__name__})")
            
            print("\nA few more rows:")
            for idx in range(min(5, len(rows))):
                row = rows[idx]
                print(f"Row {idx}: code={row.get('scripCode')} symbol={row.get('tradingSymbol')} name={row.get('companyName')} instType={row.get('instrumentType')} optType={row.get('optionType')} strike={row.get('strikePrice')} expiry={row.get('expiry')}")
    except Exception as e:
        print("Error fetching master:", e)

if __name__ == "__main__":
    inspect()
