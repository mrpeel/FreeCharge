# Local Setup & Testing Guide

This guide explains how to set up the development environment locally on your computer (macOS/Linux/Windows) and run tests to verify the control logic.

## Prerequisites
* Python 3.9 or newer installed on your computer.

---

## 1. Setup the Virtual Environment

To prevent the `externally-managed-environment` error and avoid conflicts with other python installations, set up a virtual environment:

### macOS / Linux:
```bash
# Navigate to project directory
cd /path/to/FreeCharge

# Create virtual environment
python3 -m venv env

# Activate the virtual environment
source env/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Windows (PowerShell):
```powershell
# Navigate to project directory
cd C:\path\to\FreeCharge

# Create virtual environment
python -m venv env

# Activate the virtual environment
.\env\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Configure Environment Variables

Create a `.env` file in the root of the project. You can copy the template from `.env.example`:

```bash
cp .env.example .env
```

Open `.env` and fill in your details:
```ini
# Local Fronius Inverter IP Address
FRONIUS_IP=192.168.1.150

# Precise location coordinates (safe from Git tracking)
LATITUDE=-33.8688
LONGITUDE=151.2093

# Tesla API credentials (not needed if mocking is enabled)
TESLA_VIN=5YJ3XXXXXXXXXXXXX
TESLA_API_TOKEN=YOUR_TESLA_API_ACCESS_TOKEN

# Simulation Config (keep True for dry-running)
MOCK_TESLA=True
MOCK_VEHICLE_HOME=True
MOCK_VEHICLE_PLUGGED=True
MOCK_VEHICLE_SOC=75
MOCK_VEHICLE_CHARGE_LIMIT=90
```

---

## 3. Running the Service Locally

Once the virtual environment is activated and `.env` is configured, execute the manager:

```bash
python tesla_solar_manager.py
```

### Direct Execution (without activation)
You can also run it directly without activating the virtual environment in your terminal shell:
```bash
env/bin/python tesla_solar_manager.py
```

---

## 4. Running the Tests

To verify that the control math, daylight calculations, location gating checks, and caching behaviors are all working correctly, execute the automated test suite:

```bash
# Activate the environment first
source env/bin/activate

# Run tests
python -m unittest tests/test_solar_manager.py
```

Or execute directly:
```bash
env/bin/python -m unittest tests/test_solar_manager.py
```
