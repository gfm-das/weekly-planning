# Studio startup measurement (test only)

Measures "click Edit → the editor is editable" in a real browser, against the real manager and the real Slidev in a
throw-away container. Stand-ins replace Supabase Auth and portal-api (the person is always a manager); nothing touches
the live system or its decks (a read-only copy of one example deck is the only thing taken from the live volume).

```
docker volume create gfm-test-studio-nm     # once: a writable COPY of the live node_modules (cp -a from the live volume)
sh slidev/tests/studio-perf/run-container.sh [-e SLIDEV_WARMUP=0]   # ports 18581 (manager), 18589 (decks), 18599 (control)
```

Sign the browser in with the `TOKEN` line of `docker logs gfm-test-studio-perf` (`POST /api/session`, Authorization:
Bearer <token>), then open `http://127.0.0.1:18581/studio/small`. Read `window.GFM_PERF` on that page (marks in ms from
the click, the editor's own marks and resource counts, the server's timings), or the manager log lines
`[GFM STUDIO STARTUP: <deck>]` (server), `[GFM STUDIO OPEN: <deck>]` and `[GFM STUDIO CLIENT: <deck>]` (what the browser
saw; real people's pages write it too). `GET http://127.0.0.1:18599/kill` stops the running Slidev process: the next open is
a cold process with a warm Vite cache. `kill-editor.sh` does the same from the shell. Removing the volume
`gfm-test-studio-decks` makes the next start fully cold.

Remove afterwards: `docker rm -f gfm-test-studio-perf`, `docker volume rm gfm-test-studio-nm gfm-test-studio-decks`.
