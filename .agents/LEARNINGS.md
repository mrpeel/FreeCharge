# Learnings: FreeCharge (Tesla-Fronius Solar Tracking Service)

This document captures resolved bugs, architectural changes, key logical findings, and historical evaluation scorecards across development sessions.

---

## 💡 Technical Decisions & Discoveries

1. **Hybrid Configuration Strategy (June 21, 2026)**:
   - **Context**: Need to support secret tokens and IP addresses while keeping configuration clean and safe from git leaks.
   - **Decision**: Adopted a hybrid approach:
     - `config.json` tracks non-sensitive settings (like GPS coordinates, safety margin, voltage, min/max amps, timezone).
     - `.env` stores sensitive tokens and local IP addresses (like `FRONIUS_IP`, `TESLA_API_TOKEN`, `TESLA_VIN`), which is kept git-ignored.

2. **Tesla Fleet API Base URL Routing (June 26, 2026)**:
   - **Context**: Real Tesla Fleet API requests fail if routed to defunct `api.tesla.com` endpoints.
   - **Decision**: Introduced a configurable `TESLA_API_BASE_URL` in `.env` (defaulting to the regional `https://fleet-api.prd.na.vn.cloud.tesla.com` appropriate for AP/NA user tokens) and updated controller logic and test suites to construct endpoints dynamically.

3. **Automated Tesla Token Refresh (June 26, 2026)**:
   - **Context**: Access tokens expire after 8 hours, causing `401` authentication errors.
   - **Decision**: Added `offline_access` to authorization scopes, implemented a token refresh handler that POSTs to `https://auth.tesla.com/oauth2/v3/token` when a request fails with `401`, and rewrites the updated `TESLA_API_TOKEN` and `TESLA_REFRESH_TOKEN` directly back to `.env` to sustain runs indefinitely.

4. **Tesla Vehicle Wake-Up Integration (June 27, 2026)**:
   - **Context**: When the vehicle goes offline or asleep, `/vehicle_data` queries fail with `vehicle unavailable: vehicle is offline or asleep`, causing the solar tracker control loop to abort regulation updates.
   - **Decision**: Implemented `wake_up_vehicle(config)` which sends a `POST /wake_up` command to the vehicle, handling potential token refreshes. It polls the vehicle status in a loop (up to 10 attempts, 5 seconds apart) until the state is `online`. Integrated this routine directly inside `get_tesla_vehicle_data` to automatically resolve offline states before retrying telemetry fetches.

5. **Single-File Codebase Structure Decision (June 27, 2026)**:
   - **Context**: Codebase length grew to over 600 lines, prompting a design review on modularity vs. deployability.
   - **Decision**: Decided to maintain the single-file layout to avoid import resolution and environment setup complexity on the Synology NAS. Maintaining a single file ensures seamless execution directly via Synology Task Scheduler and the simple shell runner without managing modular Python package paths.


