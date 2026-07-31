# 26 - Traffic Logs

## Introduction

Traffic Logs in Max Algos provide a detailed record of all API requests, webhooks, and system interactions. This is essential for debugging, auditing, and understanding your trading system's behavior.

## Accessing Traffic Logs

Navigate to **Logs** in the sidebar.

## Log Interface

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Traffic Logs                            [Today] [Refresh] [Export] [Clear] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Filters: [All Types ▾] [All Sources ▾] [All Status ▾] [Search...]         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 10:30:15 │ POST │ /api/v1/placeorder │ 200 │ 156ms │ TradingView    │   │
│  │          │ Request: {"symbol":"SBIN","action":"BUY","quantity":"100"}│   │
│  │          │ Response: {"status":"success","orderid":"12345"}         │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │ 10:30:10 │ POST │ /api/v1/positions │ 200 │ 45ms │ Dashboard        │   │
│  │          │ Request: {"apikey":"***"}                                 │   │
│  │          │ Response: {"status":"success","data":[...]}              │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │ 10:29:55 │ POST │ /api/v1/placeorder │ 400 │ 12ms │ Python Script   │   │
│  │          │ Request: {"symbol":"INVALID","action":"BUY"}             │   │
│  │          │ Response: {"status":"error","message":"Symbol not found"}│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Showing 1-50 of 1,234 entries           [< Prev] [1] [2] [3] [Next >]     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Log Entry Details

### Entry Components

| Field | Description |
|-------|-------------|
| Timestamp | Date and time of request |
| Method | HTTP method (GET, POST) |
| Endpoint | API endpoint called |
| Status | HTTP status code |
| Latency | Request processing time |
| Source | Origin of request |
| Request | Incoming request data |
| Response | Server response data |

### Status Codes

| Code | Meaning | Color |
|------|---------|-------|
| 200 | Success | 🟢 Green |
| 201 | Created | 🟢 Green |
| 400 | Bad Request | 🟡 Yellow |
| 401 | Unauthorized | 🟡 Yellow |
| 403 | Forbidden | 🟡 Yellow |
| 404 | Not Found | 🟡 Yellow |
| 500 | Server Error | 🔴 Red |

## Filtering Logs

### By Type

| Type | Description |
|------|-------------|
| Orders | Place, modify, cancel orders |
| Positions | Position queries |
| Holdings | Holdings queries |
| Webhooks | External webhook requests |
| Authentication | Login, API key validation |
| System | Internal system calls |

### By Source

| Source | Description |
|--------|-------------|
| TradingView | TradingView webhook alerts |
| Amibroker | Amibroker HTTP requests |
| Python | Python library requests |
| Dashboard | Web interface actions |
| API | Direct API calls |
| Flow | Flow visual builder |

### By Status

- Success (2xx)
- Client Error (4xx)
- Server Error (5xx)
- All

### Search

Search within logs for:
- Symbol names
- Order IDs
- Strategy names
- Error messages

## Detailed Log View

Click on any log entry to see full details:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Log Details                                                      [Close]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Timestamp:    2025-01-21 10:30:15.234                                      │
│  Method:       POST                                                         │
│  Endpoint:     /api/v1/placeorder                                          │
│  Status:       200 OK                                                       │
│  Latency:      156ms                                                        │
│  Source:       TradingView                                                  │
│  IP Address:   52.89.214.238                                               │
│  User Agent:   TradingView/1.0                                             │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  REQUEST HEADERS                                                            │
│  ─────────────────                                                          │
│  Content-Type: application/json                                             │
│  Host: your-maxalgos-url.com                                               │
│                                                                              │
│  REQUEST BODY                                                               │
│  ────────────                                                               │
│  {                                                                          │
│    "apikey": "abc***xyz",                                                   │
│    "strategy": "MA_Crossover",                                              │
│    "symbol": "SBIN",                                                        │
│    "exchange": "NSE",                                                       │
│    "action": "BUY",                                                         │
│    "quantity": "100",                                                       │
│    "pricetype": "MARKET",                                                   │
│    "product": "MIS"                                                         │
│  }                                                                          │
│                                                                              │
│  RESPONSE BODY                                                              │
│  ─────────────                                                              │
│  {                                                                          │
│    "status": "success",                                                     │
│    "orderid": "230125000012345",                                            │
│    "message": "Order placed successfully"                                   │
│  }                                                                          │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  PROCESSING TIMELINE                                                        │
│  ───────────────────                                                        │
│  10:30:15.234 │ Request received                                           │
│  10:30:15.236 │ API key validated                                          │
│  10:30:15.240 │ Request validated                                          │
│  10:30:15.245 │ Order created                                              │
│  10:30:15.380 │ Broker API called                                          │
│  10:30:15.389 │ Broker response received                                   │
│  10:30:15.390 │ Response sent                                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Common Log Patterns

### Successful Order Flow

```
10:30:15.234 │ POST │ /api/v1/placeorder    │ 200 │ Webhook received
10:30:15.390 │ POST │ broker/place_order    │ 200 │ Order sent to broker
10:30:15.450 │ ---  │ order_callback        │ --- │ Order confirmed
```

### Failed Order

```
10:30:15.234 │ POST │ /api/v1/placeorder    │ 400 │ Invalid symbol
             │      │ Error: Symbol "INVALID" not found in master contract
```

### Authentication Failure

```
10:30:15.234 │ POST │ /api/v1/placeorder    │ 401 │ Invalid API key
             │      │ Error: API key not found or expired
```

## Debugging with Logs

### Finding Order Issues

1. Filter by "Orders"
2. Search for symbol or order ID
3. Check request/response
4. Identify error message

### Webhook Debugging

1. Filter by "Webhooks"
2. Find specific webhook call
3. Verify request payload
4. Check if it matched expected format

### Performance Analysis

1. Filter by endpoint
2. Sort by latency
3. Identify slow requests
4. Check processing timeline

## Log Statistics

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Today's Statistics                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Total Requests:     1,234                                                  │
│  Successful:         1,180 (95.6%)                                          │
│  Client Errors:      48 (3.9%)                                              │
│  Server Errors:      6 (0.5%)                                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  REQUESTS BY ENDPOINT                                                │   │
│  │  ─────────────────────                                               │   │
│  │  /api/v1/placeorder     ████████████████████ 450                    │   │
│  │  /api/v1/positions      ██████████████ 320                          │   │
│  │  /api/v1/orders         █████████ 200                               │   │
│  │  /api/v1/holdings       ████ 100                                    │   │
│  │  Other                  ███████ 164                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  REQUESTS BY SOURCE                                                  │   │
│  │  ──────────────────                                                  │   │
│  │  TradingView   ██████████████████ 400                               │   │
│  │  Dashboard     ████████████████ 350                                 │   │
│  │  Python        ██████████ 230                                       │   │
│  │  Amibroker     ██████ 150                                           │   │
│  │  Other         ████ 104                                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Exporting Logs

### Export to CSV

1. Click **Export**
2. Select format: CSV
3. Choose date range
4. Select fields to include
5. Download file

### Export to JSON

1. Click **Export**
2. Select format: JSON
3. Choose date range
4. Download file

### Export Fields

| Field | Description |
|-------|-------------|
| timestamp | Date and time |
| method | HTTP method |
| endpoint | API endpoint |
| status | Status code |
| latency | Processing time |
| source | Request source |
| request | Request body |
| response | Response body |

## Log Retention

### Default Settings

| Period | Action |
|--------|--------|
| Last 7 days | Full details |
| 7-30 days | Summarized |
| >30 days | Deleted |

### Configuring Retention

1. Go to **Settings** → **Logs**
2. Set retention period
3. Choose archival options
4. Save settings

## Security Considerations

### Sensitive Data

Logs mask sensitive information:
- API keys: `abc***xyz`
- Passwords: `***`
- Tokens: `***`

### Access Control

- Logs are user-specific
- Admin can view all logs
- Export requires authentication

## Best Practices

### 1. Regular Review

- Check logs daily
- Look for error patterns
- Monitor unusual activity

### 2. Use Filters Effectively

- Focus on specific issues
- Filter by error status
- Search for patterns

### 3. Export Important Logs

- Keep records of issues
- Document resolutions
- Maintain audit trail

### 4. Monitor Error Rates

- Track error percentage
- Set up alerts for spikes
- Investigate recurring errors

### 5. Check Latency Trends

- Review slow requests
- Identify bottlenecks
- Optimize where needed

---

**Previous**: [25 - Latency Monitor](../25-latency-monitor/README.md)

**Next**: [27 - Security Settings](../27-security-settings/README.md)
