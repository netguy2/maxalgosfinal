import os
import sqlite3

# Try to find the DB path
db_path = "/app/db/sharekhan_symtoken.db"
if not os.path.exists(db_path):
    # Fallback to local path relative to master_contract_db.py
    db_path = os.path.join(os.path.dirname(__file__), "..", "database", "sharekhan_symtoken.db")
    # Resolve absolute path relative to workspace
    db_path = "c:\\Users\\megan\\OneDrive\\Desktop\\algo platforms\\algo-trading-platform\\broker\\sharekhan\\database\\sharekhan_symtoken.db"

print(f"Checking database at: {db_path}")
if not os.path.exists(db_path):
    print("Database file does not exist!")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check total rows
    cursor.execute("SELECT COUNT(*) FROM symtoken")
    print(f"Total rows: {cursor.fetchone()[0]}")
    
    # Check distinct instrument types
    cursor.execute("SELECT DISTINCT instrumenttype FROM symtoken")
    print("Distinct instrument types:", cursor.fetchall())
    
    # Check distinct exchanges
    cursor.execute("SELECT DISTINCT exchange FROM symtoken")
    print("Distinct exchanges:", cursor.fetchall())
    
    # Print sample Equity (EQ) rows
    cursor.execute("SELECT symbol, brsymbol, name, exchange, token, instrumenttype FROM symtoken WHERE instrumenttype='EQ' LIMIT 5")
    print("\nSample EQ rows:")
    for row in cursor.fetchall():
        print(row)
        
    # Print sample Futures (FUT) rows
    cursor.execute("SELECT symbol, brsymbol, name, exchange, token, instrumenttype FROM symtoken WHERE instrumenttype='FUT' LIMIT 5")
    print("\nSample FUT rows:")
    for row in cursor.fetchall():
        print(row)

    # Print sample Option (CE/PE) rows
    cursor.execute("SELECT symbol, brsymbol, name, exchange, token, instrumenttype FROM symtoken WHERE instrumenttype IN ('CE', 'PE') LIMIT 5")
    print("\nSample CE/PE rows:")
    for row in cursor.fetchall():
        print(row)

    conn.close()
