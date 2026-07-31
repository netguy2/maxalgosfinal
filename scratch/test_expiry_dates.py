import os
import sys

# Add root folder to python path
sys.path.append(os.getcwd())

from services.expiry_service import get_expiry_dates

print("Testing get_expiry_dates for NIFTY options...")
success, data, code = get_expiry_dates(symbol="NIFTY", exchange="NFO", instrumenttype="options")
print("Success:", success)
print("Status Code:", code)
print("Data:", data)

print("\nTesting get_expiry_dates for BANKNIFTY options...")
success, data, code = get_expiry_dates(symbol="BANKNIFTY", exchange="NFO", instrumenttype="options")
print("Success:", success)
print("Status Code:", code)
print("Data:", data)
