# Learnings: FreeCharge (Tesla-Fronius Solar Tracking Service)

This document captures resolved bugs, architectural changes, key logical findings, and historical evaluation scorecards across development sessions.

---

## 💡 Technical Decisions & Discoveries

1. **Tesla Vehicle Wake-Up Integration (June 27, 2026)**:
   - **Context**: When the vehicle goes offline or asleep, `/vehicle_data` queries fail with `vehicle unavailable: vehicle is offline or asleep`, causing the solar tracker control loop to abort regulation updates.
   - **Decision**: Implemented `wake_up_vehicle(config)` which sends a `POST /wake_up` command to the vehicle, handling potential token refreshes. It polls the vehicle status in a loop (up to 10 attempts, 5 seconds apart) until the state is `online`. Integrated this routine directly inside `get_tesla_vehicle_data` to automatically resolve offline states before retrying telemetry fetches.

2. **Single-File Codebase Structure Decision (June 27, 2026)**:
   - **Context**: Codebase length grew to over 600 lines, prompting a design review on modularity vs. deployability.
   - **Decision**: Decided to maintain the single-file layout to avoid import resolution and environment setup complexity on the Synology NAS. Maintaining a single file ensures seamless execution directly via Synology Task Scheduler and the simple shell runner without managing modular Python package paths.

3. **Location Proximity Diagnostics & 1-Hour Full Charge Throttling (June 28, 2026)**:
   - **Context**: Inaccurate proximity matches resulted in false "not at home" gating failures. Additionally, if the vehicle was full, checking telemetry every 10 minutes needlessly woke up the vehicle.
   - **Decision**: (1) Upgraded `is_vehicle_at_home` to calculate and log the exact vehicle/home coordinates and estimated distance in meters on failure. (2) Configured the offline/away telemetry check throttle to automatically increase from 10 minutes to 60 minutes if the car is fully charged (`is_full` is True).

4. **Telemetry Deadlock Resolution (July 10, 2026)**:
   - **Context**: When the car was plugged in and charging outside FreeCharge's active regulation, it drew massive power, causing a negative surplus. Since we only refreshed telemetry when charging or when surplus was positive, the cache kept showing "Disconnected", keeping the system idle.
   - **Decision**: Configured the telemetry refresh to check unconditionally when stale (every 10 or 60 minutes), but passed `allow_wake_up=False` to `get_tesla_vehicle_data` if not actively charging or attempting to charge. This checks the API status without waking the vehicle from sleep, but successfully syncs the charging state and updates check times if the car is already online/charging.

5. **Pure-Python Command Signing & Telemetry Retries (July 17, 2026)**:
   - **Context**: Enabling real API execution caused (1) transient timeout failures in telemetry query loops, and (2) command protocol rejection errors because newer vehicle firmware requires cryptographically signed protobuf commands (Tesla Vehicle Command Protocol) instead of standard REST.
   - **Decision**: (1) Upgraded telemetry checks to capture `"timeout"` responses from Tesla API, treating them as asleep/offline triggers, and implemented a 3-attempt retry loop with a 5-second backoff. (2) Integrated `tesla-fleet-api` and `cryptography` libraries to perform in-memory command signing (`secp256r1`) directly in Python using the local `tesla_private_key.pem` file. This resolves the command protocol errors natively without the overhead of running a Docker command proxy container on the NAS.

6. **Feedback Loop Charging Draw Compensation (July 17, 2026)**:
   - **Context**: When the car was actively charging, the Fronius smart meter reported the net grid export (which drops by the amount the charger is consuming). The script evaluated this raw grid export directly against the 1200W minimum threshold, falsely concluding that there was insufficient excess solar and shutting down the charging loop.
   - **Decision**: Adjusted the `excess_watts` calculation to add the car's active charging draw back to the grid export reading when the charger is active. This represents the true available solar surplus (generation minus home load), stabilizing the control loop and preventing the system from immediately stopping a charge that it just initiated.


