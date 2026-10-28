# Deployment

Target domain: `grok.codex.rodion.pro`

Target app directory: `/var/www/grok.codex.rodion.pro`

The app is a FastAPI service that should run on `127.0.0.1:8000`.
Nginx terminates HTTPS, serves the browser UI from `static/index.html`, serves `/static/` directly, and proxies REST and WebSocket traffic to uvicorn.

## Install files

For the first certificate issue, install the bootstrap HTTP config:

```bash
sudo cp deploy/systemd/grok.codex.rodion.pro.service /etc/systemd/system/grok.codex.rodion.pro.service
sudo cp deploy/nginx/grok.codex.rodion.pro.bootstrap.conf /etc/nginx/sites-available/grok.codex.rodion.pro
sudo ln -sf /etc/nginx/sites-available/grok.codex.rodion.pro /etc/nginx/sites-enabled/grok.codex.rodion.pro
```

## Prepare the app

```bash
cd /var/www/grok.codex.rodion.pro
python3 -m venv .venv
. .venv/bin/activate
pip install fastapi uvicorn pydantic python-dotenv pyyaml websockets
sudo chown -R www-data:www-data /var/www/grok.codex.rodion.pro
```

## Enable the backend

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now grok.codex.rodion.pro
sudo systemctl status grok.codex.rodion.pro --no-pager
```

## Issue TLS certificate

```bash
sudo mkdir -p /var/www/_letsencrypt
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/_letsencrypt -d grok.codex.rodion.pro
```

After certbot creates `/etc/letsencrypt/live/grok.codex.rodion.pro/`, install the final HTTPS config and reload nginx:

```bash
sudo cp deploy/nginx/grok.codex.rodion.pro.conf /etc/nginx/sites-available/grok.codex.rodion.pro
sudo nginx -t
sudo systemctl reload nginx
```

## Verify

```bash
curl -fsS https://grok.codex.rodion.pro/api/health
```
