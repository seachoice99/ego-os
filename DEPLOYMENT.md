# Deployment

Ego OS runs as a permanent service on a shared Ubuntu 24.04 VPS, reverse-proxied by the box's existing nginx installation. This is intentionally simple: one systemd unit running `uvicorn` directly, SQLite on local disk, nginx + Let's Encrypt for TLS. No Docker, no queue, no separate database server — none of that is needed yet.

## Server

| | |
|---|---|
| Host | `150.251.138.149` (`os.fiveseven.ru`) |
| OS | Ubuntu 24.04 |
| App directory | `/opt/ego-os` |
| Service user | `egoos` (system user, no login shell, owns `/opt/ego-os`) |
| Python | system `python3` (3.12) + venv at `/opt/ego-os/.venv` |
| Process manager | systemd unit `ego-os.service` |
| Reverse proxy | nginx site `/etc/nginx/sites-available/os.fiveseven.ru` |
| TLS | Let's Encrypt via certbot, auto-renewed by `certbot.timer` |

This VPS also hosts other unrelated services (`n8n.fiveseven.ru`, `food.fiveseven.ru`, a Discord bot, Docker containers) — nothing in this deployment touches their configuration.

## Initial deployment (already done)

1. Created dedicated system user: `useradd --system --create-home --home-dir /opt/ego-os --shell /usr/sbin/nologin egoos`
2. Cloned the repo into `/opt/ego-os`, owned by `egoos`.
3. Created a venv and installed dependencies:
   ```
   sudo -u egoos python3 -m venv /opt/ego-os/.venv
   sudo -u egoos /opt/ego-os/.venv/bin/pip install -r /opt/ego-os/requirements.txt
   ```
4. Created `/opt/ego-os/.env` (mode `600`, owned by `egoos`) with the real `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, and `TAVILY_API_KEY` values, copied in manually — **never committed, never passed through chat/tooling**.
5. Created the systemd unit `/etc/systemd/system/ego-os.service`:
   ```ini
   [Unit]
   Description=Ego OS (FastAPI)
   After=network.target

   [Service]
   Type=simple
   User=egoos
   Group=egoos
   WorkingDirectory=/opt/ego-os
   ExecStart=/opt/ego-os/.venv/bin/python -m uvicorn ego_os.main:app --host 127.0.0.1 --port 8000
   Restart=on-failure
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```
   The app's existing `load_dotenv()` finds `/opt/ego-os/.env` automatically via `WorkingDirectory` — no systemd `EnvironmentFile=` needed.
6. `systemctl daemon-reload && systemctl enable --now ego-os`
7. Added an nginx site (`/etc/nginx/sites-available/os.fiveseven.ru`, symlinked into `sites-enabled`) proxying to `127.0.0.1:8000`, then ran `certbot --nginx -d os.fiveseven.ru` to issue the certificate and add the HTTPS server block + HTTP→HTTPS redirect (same pattern as the existing `n8n` site).

## Update procedure

To deploy a new commit from `main`:

```
ssh root@150.251.138.149
cd /opt/ego-os
sudo -u egoos git pull origin main
sudo -u egoos /opt/ego-os/.venv/bin/pip install -r requirements.txt
systemctl restart ego-os
systemctl status ego-os --no-pager
```

If `requirements.txt` didn't change, the `pip install` step is a harmless no-op — safe to always run it.

## Restart / control commands

```
systemctl restart ego-os     # restart the app
systemctl stop ego-os        # stop it
systemctl start ego-os       # start it
systemctl status ego-os      # current state
systemctl is-enabled ego-os  # confirm it starts on boot (should be "enabled")
```

## Logs

```
journalctl -u ego-os -n 100 --no-pager     # last 100 lines
journalctl -u ego-os -f                    # follow live
journalctl -u ego-os --since "1 hour ago"  # time-windowed
```

nginx access/error logs for this site are in the shared nginx log files (`/var/log/nginx/access.log`, `/var/log/nginx/error.log`) — not split per-site on this box.

## TLS / certificate renewal

Certbot's systemd timer (`certbot.timer`, already enabled) renews automatically; nothing to do manually. To verify renewal still works without actually renewing:

```
certbot renew --dry-run
```

Certificate: `/etc/letsencrypt/live/os.fiveseven.ru/` (managed entirely by certbot — don't edit the nginx `# managed by Certbot` blocks by hand).

## Backups

The only state that matters is the SQLite database at `/opt/ego-os/ego_os/ego_os.db` and any generated documents under `/opt/ego-os/ego_os/generated/`. Everything else (`.env` aside) is reproducible from git. There is no automated backup job yet — for now, back up manually when needed:

```
ssh root@150.251.138.149 "sqlite3 /opt/ego-os/ego_os/ego_os.db '.backup /tmp/ego_os_backup.db'"
scp root@150.251.138.149:/tmp/ego_os_backup.db ./ego_os_backup_$(date +%Y%m%d).db
```

(Using SQLite's own `.backup` rather than `cp` avoids copying a database mid-write.)

## Production `.env`

Location: `/opt/ego-os/.env` on the server only, mode `600`, owned by `egoos`. Contains `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `TAVILY_API_KEY`. This file is not in git (`.gitignore`'d) and must never be committed or pasted into chat/tooling — if a key ever needs to change, edit this file directly over SSH.
