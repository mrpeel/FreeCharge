# Learnings: FreeCharge (Tesla-Fronius Solar Tracking Service)

This document captures resolved bugs, architectural changes, key logical findings, and historical evaluation scorecards across development sessions.

---

## 💡 Technical Decisions & Discoveries

1. **Hybrid Configuration Strategy (June 21, 2026)**:
   - **Context**: Need to support secret tokens and IP addresses while keeping configuration clean and safe from git leaks.
   - **Decision**: Adopted a hybrid approach:
     - `config.json` tracks non-sensitive settings (like GPS coordinates, safety margin, voltage, min/max amps, timezone).
     - `.env` stores sensitive tokens and local IP addresses (like `FRONIUS_IP`, `TESLA_API_TOKEN`, `TESLA_VIN`), which is kept git-ignored.
