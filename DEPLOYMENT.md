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

The only state that matters is the SQLite database at `/opt/ego-os/ego_os/ego_os.db` and any generated documents under `/opt/ego-os/ego_os/generated/`. Everything else (`.env` aside) is reproducible from git.

**Manual backup** (unchanged, always available):

```
ssh root@150.251.138.149 "sqlite3 /opt/ego-os/ego_os/ego_os.db '.backup /tmp/ego_os_backup.db'"
scp root@150.251.138.149:/tmp/ego_os_backup.db ./ego_os_backup_$(date +%Y%m%d).db
```

(Using SQLite's own `.backup` rather than `cp` avoids copying a database mid-write.)

**Automated backup (proposed, v0.4.1 — not yet installed on production):** `scripts/backup.sh` wraps the same `.backup` mechanism plus a tarball of `ego_os/generated/`, writing timestamped files to a backup directory and pruning anything older than `EGO_OS_BACKUP_RETENTION_DAYS` (default 14). Verified locally (tar + retention logic) against a throwaway test database; the `sqlite3 .backup` call itself uses the exact command already used above, but hasn't been re-run end-to-end on this exact script on a machine with the `sqlite3` CLI installed (not present on the Windows dev box this was written on) — smoke-test it once on the VPS before scheduling.

To install as a daily systemd timer (not applied automatically — this is a proposal for the Owner to apply):

```ini
# /etc/systemd/system/ego-os-backup.service
[Unit]
Description=Ego OS backup

[Service]
Type=oneshot
User=egoos
Environment=EGO_OS_BACKUP_DIR=/opt/ego-os-backups
ExecStart=/opt/ego-os/scripts/backup.sh
```

```ini
# /etc/systemd/system/ego-os-backup.timer
[Unit]
Description=Daily Ego OS backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Then `mkdir -p /opt/ego-os-backups && chown egoos:egoos /opt/ego-os-backups`, `systemctl daemon-reload && systemctl enable --now ego-os-backup.timer`. `/opt/ego-os-backups` is deliberately outside `/opt/ego-os` so a mistake in the app's own directory (e.g. a bad `git clean`) can't also destroy the backups. This is still a single-VPS backup — a full disk/VPS loss would take the backups with it; off-box replication (e.g. periodic `scp` to another host) is a real known gap, not solved here.

**Restore procedure:**

```
systemctl stop ego-os
cp /opt/ego-os-backups/ego_os_<timestamp>.db /opt/ego-os/ego_os/ego_os.db
tar -xzf /opt/ego-os-backups/generated_<timestamp>.tar.gz -C /opt/ego-os/ego_os/
chown -R egoos:egoos /opt/ego-os/ego_os/ego_os.db /opt/ego-os/ego_os/generated
systemctl start ego-os
systemctl status ego-os --no-pager
```

Verify afterward: `curl -s -o /dev/null -w '%{http_code}\n' -u <owner>:<password> https://os.fiveseven.ru/dashboard` should return 200, and the dashboard's task list/cost should match the restored backup's point in time, not whatever was live before the restore.

## Production `.env`

Location: `/opt/ego-os/.env` on the server only, mode `600`, owned by `egoos`. Contains `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `TAVILY_API_KEY`, `PRESENTATIONS_DIR`, and (v0.4.1) `OWNER_USERNAME`/`OWNER_PASSWORD` — the app now fails closed (every request gets 401) if either of the last two is unset, so this deploy step is no longer optional. This file is not in git (`.gitignore`'d) and must never be committed or pasted into chat/tooling — if a key or the Owner password ever needs to change, edit this file directly over SSH.

## Runtime components (v0.4.1)

- **Owner authentication** — HTTP Basic Auth (`OWNER_USERNAME`/`OWNER_PASSWORD`) is now required on every route in this app. The published presentation sites under `/p/<site_name>/` are served directly by nginx, outside this app entirely, and are unaffected — they stay public. Any external monitoring/health-check hitting a route inside the app (not `/p/`) needs these credentials from now on.
- **Background worker** — `POST /tasks` now only validates and enqueues; the actual Task Lifecycle runs on an in-process background thread started at app startup (`ego_os/worker.py`). No new service, no new port, no Redis/Celery — it lives inside the same `ego-os.service` process and needs no separate deployment step. A task interrupted by a restart (`systemctl restart ego-os` mid-task) is marked `failed` with a clear reason on the next boot rather than staying stuck.

## Presentation Website publishing (v0.4)

The `build_presentation_site` tool publishes static sites to the directory named by the `PRESENTATIONS_DIR` env var (defaults to a local `ego_os/generated/_presentations/` for dev). In production this is set to `/var/www/ego-presentations`, owned by `egoos:www-data` with group read/execute so nginx can serve it, and exposed at `https://os.fiveseven.ru/p/<site_name>/` via one added `location /p/` block in the existing `/etc/nginx/sites-available/os.fiveseven.ru` (an `alias` to that directory, `autoindex off`) — no new DNS record, certificate, or nginx site was needed since it reuses the already-issued `os.fiveseven.ru` certificate.

A real slide deck (a multi-MB `.pdf`, or a large `.zip`) needs two nginx defaults raised on this site, both applied directly on the server (not tracked in this repo, since they live in `/etc/nginx/sites-available/os.fiveseven.ru`):

- `client_max_body_size 100m;` (server block) — the 1MB default silently 413'd any realistically-sized deck.
- `proxy_read_timeout 300s; proxy_send_timeout 300s;` (the `location /` block) — a heavy deck (many pages, PDF rendering, multiple LLM calls including a possible QA revision) can genuinely take over the 60s default; the request still completes server-side past that point, but the client saw a dead connection with nothing to show for it.

If this nginx site is ever rebuilt from scratch, re-apply both.
