# Active Context: FreeCharge (Tesla-Fronius Solar Tracking Service)

This file defines the system objectives, feature backlog catalog, active technical approach, and verification methods.

---

## 🎯 System Objectives
*   **Active Phase**: Phase 1: Local Ingestion, Control Calculations & Mocking
*   **High-Level Vision**: FreeCharge is a low-overhead, automated solar-tracking EV charging service running on a Synology NAS. It monitors excess solar production from a Fronius Smart Inverter locally and dynamically scales Tesla EV charging current (amps) and state (start/stop) to maximize green self-consumption, minimizing grid import while operating safely within the Tesla Fleet API free tier usage limits.

---

## 🛠️ Technical Approach
*   **Synology NAS Hosting**: Runs as a scheduled Python job/daemon triggered by DSM Task Scheduler.
*   **Local Ingestion**: Polls Fronius Datamanager 2.0 (`GetPowerFlowRealtimeData.fcgi`) and Tesla Wall Connector Gen 3 (`/api/1/vitals`) directly over local LAN for $0.00 cost.
*   **Tesla Quota Protection**:
    - **Zero-Surplus Inaction**: If car is not charging and solar surplus is below threshold, skips all Tesla Cloud calls.
    - **Physical Gating**: If Wall Connector indicates `vehicle_connected == False`, bypasses all Tesla Cloud calls and stays idle.
    - **Wake Rate Limiting**: Enforces a configurable 60-minute wake cooldown and 15-minute telemetry refresh interval.
*   **Billing Protection Cache**: Stores current charging state, rolling solar history, Wall Connector state, and last command execution timestamp in `state_cache.json` to prevent unnecessary calls and enforce a 10-minute command throttle limit.
*   **Daylight Boundaries**: Restricts active regulation to local sunrise/sunset windows calculated using the `astral` library. Forces charging off at sunset.
*   **Control Algorithm**: Calculates surplus power dynamically based on the median of the rolling history, and floors the charging current to standard levels ($5\text{ A}$ to $32\text{ A}$ at $240\text{ V}$) with a safety buffer.
*   **Mocking Layer**: Mocks the Tesla Fleet API and Wall Connector with realistic response data for development and dry runs without making real-world vehicle updates.

---

## 📋 Feature Catalog & Backlog

| Feature ID | Feature Name | Description | Status | Verification Method |
|---|---|---|---|---|
| F-001 | Repository Setup | Git initialization, .gitignore, virtual environment, and dependency management setup | **Completed** | Directory check & git status |
| F-007 | Tesla Gating Checks | Verify if the Tesla is at home, plugged in, and not fully charged before regulating charger state | **Completed** | Proximity checks and E2E integration safety disconnect tests |
| F-008 | Rolling Averages & Throttle | Smooth out solar fluctuations via 10-minute median and throttle cloud requests to 10-minute intervals | **Completed** | Sliding window and throttling integration tests |
| F-009 | Log Rotation & Cleanup | Direct print statements to daily logs and automatically prune logs older than 30 days | **Completed** | Age-based pruning and directory isolation unit tests |
| F-010 | Wall Connector & Quota Guard | Local Wall Connector vitals ingestion, zero-surplus inaction, and wake throttling | **Completed** | Unit & E2E integration tests |
| F-006 | Scheduled Runner | Shell script wrapper for Synology DSM task scheduler execution and logs | Backlog | Manual runner verification |

---

## 🧪 Verification & Testing

### 1. Automated Verification
*   **Unit Tests**: Standard Python unit tests (`env/bin/python3 -m unittest discover -s tests -v`) verifying Wall Connector parsing, zero-surplus gating, solar control math, cache updates, and state transitions.

### 2. Dry-Run Mode
*   Running `tesla_solar_manager.py` in dry-run/mock mode to output projected actions to execution logs without making outbound API requests to Tesla Cloud.
