# broker/sharekhan/api/baseurl.py
#
# Central place for Sharekhan (SKAPI) API hosts.
# All REST endpoints for orders, positions, holdings, funds and the scrip
# master are served from https://api.sharekhan.com/skapi/...
#
# Authentication is OAuth-like:
#   1. Redirect user to https://api.sharekhan.com/skapi/auth/login.html?api_key=...
#   2. After login, Sharekhan redirects to callback URL with an AES-GCM
#      encrypted request_token query parameter.
#   3. Decrypt request_token, swap RequestId/CustomerId, re-encrypt, POST to
#      /skapi/auth/token.json to get the access token (JWT).
#
# Every authenticated API request must include:
#   api-key    : the application api_key (from BROKER_API_KEY, no prefix)
#   access-token / Authorization : the JWT access token from step 3
#   vendor-key : (optional) vendor api key, if registered as a third-party vendor

# Main REST API origin — used by the broker_keepalive_service to keep the
# pooled HTTP connection warm so orders placed after idle gaps skip the
# TCP+TLS handshake penalty (~100ms).
ROOT_URL = "https://api.sharekhan.com"

# Authentication and login
LOGIN_URL = f"{ROOT_URL}/skapi/auth/login.html"
ACCESS_TOKEN_URL = f"{ROOT_URL}/skapi/auth/token.json"

# Orders
ORDER_URL = f"{ROOT_URL}/skapi/services/orders"
ORDER_STATUS_URL = f"{ROOT_URL}/skapi/services/order/{{order_id}}"
ORDER_BOOK_URL = f"{ROOT_URL}/skapi/services/orders/history"
TRADE_BOOK_URL = f"{ROOT_URL}/skapi/services/orders/trades"

# Positions and holdings
POSITIONS_URL = f"{ROOT_URL}/skapi/services/portfolio/positions"
HOLDINGS_URL = f"{ROOT_URL}/skapi/services/portfolio/holdings"

# Funds and limits
FUNDS_URL = f"{ROOT_URL}/skapi/services/limits"

# Scrip master — per exchange (NC=NSE Cash, BC=BSE Cash, MX=MCX, etc.)
MASTER_URL = f"{ROOT_URL}/skapi/services/master/{{exchange}}"

# Historical candle data
HISTORICAL_URL = f"{ROOT_URL}/skapi/services/historical/{{scripcode}}/{{resolution}}"
