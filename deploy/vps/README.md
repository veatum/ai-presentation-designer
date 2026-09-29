# VPS deployment

The VPS runs the complete Python application, including PPTX generation and
LibreOffice PDF export. GitHub Pages remains a separate static demo.

## Current layout

- Ubuntu 24.04; source checkout: `/opt/presentation-designer/src`.
- Docker Compose project: `presentation-designer`.
- Environment secrets: `/etc/presentation-designer/app.env` (root only).
- Nginx Basic Auth credentials: `/etc/presentation-designer/htpasswd`.
- Public URL: `https://139.100.239.187`.
- Nginx terminates TLS and authenticates every application request.
- The application listens only on host loopback, `127.0.0.1:8080`.
- Generated files are stored in Docker volume `presentation-designer_presentations`.
- Docker starts on boot; the application uses `restart: unless-stopped`.
- Firewall permits inbound TCP 22, 80 and 443. HTTP redirects to HTTPS;
  ACME challenges on port 80 are served without authentication.

The root `index.html` belongs to the Pages demo. Run the Docker application to
serve the full interface at `/`; do not configure Nginx to serve the repository
as static files.

## Update and inspect

```bash
cd /opt/presentation-designer/src
git pull --ff-only
docker compose -p presentation-designer -f deploy/vps/compose.yaml up -d --build
docker compose -p presentation-designer -f deploy/vps/compose.yaml ps
docker compose -p presentation-designer -f deploy/vps/compose.yaml logs --tail=100 app
```

Ordinary container updates preserve the named volume. Do not use `down -v`
unless you intend to delete the generated files. Persistence is not a backup;
copy the volume to separate storage if its contents need to be retained.

Edit `app.env` on the VPS to change the Cloud.ru key, then run `up -d` again.
Do not commit real keys, passwords or certificate private keys to Git.
To change the website password, run `htpasswd /etc/presentation-designer/htpasswd sheikh`.

## TLS without a domain

Certbot 5.8.0 is installed in `/opt/certbot`. Let's Encrypt issues an IP
certificate under the `shortlived` profile. The systemd timer checks for renewal
every six hours. The saved deploy hook validates and reloads Nginx after renewal.

```bash
systemctl list-timers presentation-cert-renew.timer
systemctl status presentation-cert-renew.service
/opt/certbot/bin/certbot renew --dry-run --run-deploy-hooks
```

The `nginx.conf` in this directory is specific to this VPS IP. To move the
application, obtain a certificate for the new address, update the IP and
certificate paths in that file, validate with `nginx -t`, then reload Nginx.

## Deployment verification (2026-09-29)

The public HTTPS endpoint passed certificate validation and returned 401 without
credentials. Authenticated health, interface and diagnostics requests succeeded.
One real Cloud.ru generation of three slides across all three built-in templates
and three layouts produced nine PPTX and nine PDF files in 75 seconds.
The downloaded bundle was checked for valid PPTX containers with three slides
each and PDF signatures. This checks deployment and export, not slide quality:
the application's content/layout audit still reports findings on some variants.
