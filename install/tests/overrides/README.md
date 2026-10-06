# overrides/ (tests only)

One extra compose file per part, used by `../test-install.sh` through `GFM_OVERRIDE_DIR=install/tests/overrides`
(`install/run-install.sh` and `portal/deploy.sh` add `<part>.yml` to that part's compose files). They give the test copy its own
network (`gfmtest-network`), container names and host ports (2xxxx), and put the names the programs expect inside the network
(`portal-api`, `gfm-beta-supabase-kong-1`, `gfm-beta-supabase-db-1`) on it as aliases. So a test can run next to a live system
without touching it. Never use these files on a real install.
