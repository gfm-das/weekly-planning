#!/bin/sh
# TEST ONLY: stops the running Slidev editor process in the measurement container (the manager starts a new one on demand).
docker exec gfm-test-studio-perf sh -c 'kill $(ps | grep "[n]ode_modules/.bin/slidev" | sed "s/^ *\([0-9]*\).*/\1/")'
sleep 1
