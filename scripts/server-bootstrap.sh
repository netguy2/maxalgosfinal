#!/usr/bin/env bash
# =============================================================================
# MaxAlgos — One-time Contabo server bootstrap
#
# Run this ONCE manually on the Contabo VPS before the first CI/CD deploy.
# It creates the deployment directory and a template .env file.
#
# Usage (from your local machine):
#   ssh root@<YOUR_SERVER_IP> 'bash -s' < scripts/server-bootstrap.sh
#
# Or copy to the server and run directly:
#   scp scripts/server-bootstrap.sh root@<IP>:/tmp/
#   ssh root@<IP> 'bash /tmp/server-bootstrap.sh'
# =============================================================================
set -euo pipefail

DEPLOY_DIR="/opt/maxalgos"
ENV_FILE="$DEPLOY_DIR/.env"

echo "=== MaxAlgos Bootstrap ==="

# 1. Create deployment directory
echo "[1/4] Creating deployment directory: $DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# 2. Create a template .env if it doesn't already exist
#    IMPORTANT: Fill in all values before running your first CI deploy!
if [ ! -f "$ENV_FILE" ]; then
  echo "[2/4] Creating template .env at $ENV_FILE"
  cat > "$ENV_FILE" << 'EOF'
# ─────────────────────────────────────────────────────────────────────────────
# MaxAlgos Production .env
# Fill in ALL values before running `docker compose -f docker-compose.prod.yml up`
# ─────────────────────────────────────────────────────────────────────────────

# Flask
FLASK_ENV=production
FLASK_DEBUG=0

# App keys (generate with: python -c "import secrets; print(secrets.token_hex(32))")
APP_KEY=CHANGE_ME
API_KEY_PEPPER=CHANGE_ME

# Database
DATABASE_URL=sqlite:///db/maxalgos.db
LATENCY_DATABASE_URL=sqlite:///db/latency.db
LOGS_DATABASE_URL=sqlite:///db/logs.db

# Valid brokers (comma-separated)
VALID_BROKERS=fivepaisa,fivepaisaxts,aliceblue,angel,arrow,compositedge,dhan,dhan_sandbox,definedge,deltaexchange,firstock,flattrade,fyers,groww,ibulls,iifl,iiflcapital,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,rmoney,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha,bnr

# Host URL — used to build callback/redirect URLs
HOST_SERVER=https://api.maxalgos.com

# Broker redirect URL (update broker name to your active broker)
REDIRECT_URL=https://api.maxalgos.com/<your_broker>/callback

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# Telegram (optional)
# TELEGRAM_TOKEN=
# TELEGRAM_CHAT_ID=

# WhatsApp (optional)
# WHATSAPP_API_KEY=
EOF
  echo "[2/4] Template .env created. Please edit $ENV_FILE with real values."
else
  echo "[2/4] .env already exists at $ENV_FILE — skipping template creation."
fi

# 3. Set permissions on the .env
chmod 600 "$ENV_FILE"

# 4. Print summary
echo ""
echo "=== Bootstrap complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit $ENV_FILE with your real configuration values"
echo "  2. Push to the 'main' branch on GitHub to trigger the CI/CD deploy"
echo "  3. After deploy, configure Nginx to proxy api.maxalgos.com → 127.0.0.1:5001"
echo ""
echo "Nginx config snippet:"
echo "────────────────────────────────────────────────────────────────────────"
cat << 'NGINX'
server {
    listen 80;
    server_name api.maxalgos.com;

    # Redirect HTTP → HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name api.maxalgos.com;

    # SSL certificates (use Certbot / Let's Encrypt)
    ssl_certificate     /etc/letsencrypt/live/api.maxalgos.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.maxalgos.com/privkey.pem;

    # Flask app
    location / {
        proxy_pass         http://127.0.0.1:5001;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # WebSocket upgrade
    location /ws {
        proxy_pass         http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
    }
}
NGINX
echo "────────────────────────────────────────────────────────────────────────"
