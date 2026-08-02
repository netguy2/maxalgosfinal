import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

db_path = "db/maxalgos.db"
engine = create_engine(f"sqlite:///{db_path}")
Session = sessionmaker(bind=engine)
session = Session()

try:
    from sqlalchemy import text
    # Query distinct instrument types
    types = session.execute(text("SELECT distinct instrumenttype FROM symtoken LIMIT 20")).fetchall()
    print("Distinct instrument types:")
    for t in types:
         print(f"  Type: {t[0]}")
         
    # Let's find some rows where instrumenttype is CE, PE, FUT, FUTIDX, OPTIDX, etc.
    fo_rows = session.execute(text("SELECT symbol, brsymbol, name, exchange, expiry, instrumenttype FROM symtoken WHERE instrumenttype IN ('CE', 'PE', 'FUT', 'FUTIDX', 'OPTIDX', 'FUTSTK', 'OPTSTK') LIMIT 15")).fetchall()
    print("\nSample F&O rows:")
    for row in fo_rows:
        print(f"  Symbol: {row[0]}, BrSymbol: {row[1]}, Name: {row[2]}, Exchange: {row[3]}, Expiry: {row[4]}, Type: {row[5]}")
        
except Exception as e:
    print(f"Error: {e}")
finally:
    session.close()
