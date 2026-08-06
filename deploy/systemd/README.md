# Plain2Metta systemd deployment

This template runs the Flask app under the existing unprivileged `openclaw`
account, restarts it if it exits, and starts it during normal boot.  It is a
template unit so two exact-address instances can run on the same port without
opening the service to the general LAN:

- `127.0.0.1:8080` for the Pop!_OS browser;
- `100.72.218.34:8080` for the Pop!_OS Tailscale interface.

From this repository checkout, an administrator installs it with:

```bash
sudo install -o root -g root -m 0644 deploy/systemd/plain2metta-webapp@.service /etc/systemd/system/plain2metta-webapp@.service
sudo systemctl daemon-reload
sudo systemctl enable --now plain2metta-webapp@127.0.0.1.service plain2metta-webapp@100.72.218.34.service
```

Verify without exposing anything publicly:

```bash
systemctl status plain2metta-webapp@127.0.0.1 plain2metta-webapp@100.72.218.34
curl --fail http://127.0.0.1:8080/
curl --fail http://100.72.218.34:8080/docs
```

The Tailscale endpoint is encrypted by Tailscale transport but is HTTP at the
application layer. Tailscale Serve HTTPS is preferable if the Tailnet
administrator enables it; do not use Tailscale Funnel for this private app.

To stop and disable both instances:

```bash
sudo systemctl disable --now plain2metta-webapp@127.0.0.1.service plain2metta-webapp@100.72.218.34.service
```
