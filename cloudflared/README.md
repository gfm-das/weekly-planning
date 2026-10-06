# cloudflared/ (the Cloudflare tunnel)

What it is: an optional container that connects this computer to the mission's own Cloudflare tunnel, so the portal can be reached from
the internet at the mission's web name (for example `https://example.org`). Without it, the portal works on the local network only.

## How it gets installed
The installer asks for the tunnel token in step 5 of its form (or the terminal questions). The token needs the public web name from step 4. A blank
token skips all of this. With a token, the installer writes `cloudflared/.env` (the secret; ignored by Git), starts the container with
`docker compose -p gfm-cloudflared -f cloudflared/compose.yml up -d`, and writes `cloudflared/ROUTES.txt`.
The container restarts by itself whenever Docker starts, so it needs no administrator rights and no separate service on Windows, Mac or Linux.

## The routes: set them once in Cloudflare
A token only connects the computer to the tunnel. Which public name goes to which part is set in Cloudflare (Zero Trust, Networks,
Tunnels, your tunnel, Public hostnames): one line per row of `cloudflared/ROUTES.txt` (type HTTP). The portal is the one that matters; the other
names are for Dashboards, Presentations and DA Management, and they open from the portal.

## Check and operate
- `bash health.sh` has a row "Cloudflare tunnel": OK when the tunnel is connected, WARNING when it is not (it never makes the system fail: the
  office network works without it), SKIPPED when there is no tunnel.
- Log: `docker logs gfm-cloudflared`. Stop for a while: `docker stop gfm-cloudflared`. Remove: `docker compose -p gfm-cloudflared -f cloudflared/compose.yml down`,
  then delete `cloudflared/.env`.
- A new token: replace the value in `cloudflared/.env`, then `docker compose -p gfm-cloudflared -f cloudflared/compose.yml up -d --force-recreate`.
- The Frankfurt server uses a Windows service called `cloudflared` instead (docs/handoff/round10); this folder is not used there.
