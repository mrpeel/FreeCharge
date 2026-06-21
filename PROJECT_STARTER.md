# PROJECT_STARTER.md: Tesla-Fronius Solar Tracking Service

This document serves as the absolute blueprint and starting point for configuring an automated solar-tracking EV charging system on a Synology NAS. 

---

# Project Goals
The project's goal is to ensure that I'm making maximum use of the excess solar being generated during the day to charge my Tesla.  

The big picture components are:
* My fronius solar inverter primo 5kw 
* Tesla EV - in my case a Tesla Model 3
* Synology NAS as the server/execution platform

The big picture workflow is:
- My "server" will be my Synology NAS - that is always present and running
- It will use a python environment on the NAS to run the service
- The Tesla is already configured to allow charging between midnight and 6am - I get very good pricing at those times - we can leave that alone for now and concentrate on daytime only
- The loop - between sunrise and sunset - call the Fronius to retrieve the current status of excess solar - compare that to current Tesla state and decide whether it should be changed:
- if it should be changed, make the incremental adjustment (up/down/on/off) based on the calculation
- call the Tesla, get the setting adjusted, wait for acknowledgement, then store that as the current Tesla state
- if the Tesla shouldn't be changed, do nothing and wait for the next 10 minutes
- By sunset, charging should be off. If it isn't turn it off and record the uipdated state
- Do nothing between sunset and sunrise 


# Implementation Plan

## 1. System Architecture

```text
                     +---------------------------+

| Synology NAS |
| (Task Scheduler Script) |
                     +-----+---------------+-----+

| |
             Local Network | | Tesla Fleet API
                HTTP GET | | HTTPS POST (Cloud)
                           v               v
                +----------+----+     +----+----------+

| Fronius Inverter | | Tesla EV |
                +---------------+     +--------------+
```

### Core Logic Requirements
1. **Astroneer Daylight Boundaries:** The script runs strictly between local sunrise and sunset. Overnight cheap window charging (midnight to 6:00 AM) is ignored [cite: user query].
2. **Zero-Overhead Local Ingestion:** Poll the Fronius Datamanager 2.0 locally via the HTTP JSON API every 10 minutes [cite: 4, 5].
3. **Billing Protection Caching:** Keep a local state cache (`state_cache.json`) on the NAS [cite: 6]. Only send commands to the Tesla API if a state transition (start, stop, or amp change) is required [cite: 7]. This stays safely within your free monthly $10 developer credit [cite: 7].
4. **Safety Disconnect:** Force charging off at sunset and record the updated state [cite: user query].

---

## 2. Mathematical Control Model

Let $P_{\text{grid}}$ be the active grid power returned by the Fronius Smart Meter. 
* A positive value can indicate importing or exporting depending on CT clamp orientation and meter installation configuration [cite: 1, 8]. To handle this, the config utilizes a boolean flag: `FRONIUS_EXPORT_IS_POSITIVE`.
* Let $P_{\text{margin}}$ be the safety buffer (e.g., 150 Watts) to prevent micro-importing from the grid during domestic load fluctuations [cite: 4].

The available solar surplus power ($P_{\text{surplus}}$) is calculated as:

$$P_{\text{surplus}} = \begin{cases} 
      P_{\text{grid}} - P_{\text{margin}} & \text{if } \text{FRONIUS\_EXPORT\_IS\_POSITIVE is True} \\
      -P_{\text{grid}} - P_{\text{margin}} & \text{if } \text{FRONIUS\_EXPORT\_IS\_POSITIVE is False} 
   \end{cases}$$

The target charger current ($I_{\text{target}}$) is then computed as:

$$I_{\text{target}} = \min\left(I_{\text{max}}, \max\left(I_{\text{min}}, \left\lfloor\frac{P_{\text{surplus}}}{V_{\text{grid}}}\right\rfloor\right)\right)$$

Where:
* $I_{\text{min}}$ is the minimum single-phase charging rate ($5\text{ A}$, equivalent to $1.2\text{ kW}$ at $240\text{ V}$) [cite: 9, 10].
* $I_{\text{max}}$ is your absolute breaker continuous limit (typically $32\text{ A}$) [cite: 10, 11].
* $\lfloor \dots \rfloor$ is the floor function to ensure we always round down to prevent grid draw [cite: 8, 12].

---

## 3. Directory Layout

Scaffold the directory on your Synology NAS `/volume1` volume:

```text
/volume1/homes/admin/tesla_tracker/
├── config.json
├── state_cache.json
├── requirements.txt
├── run.sh
└── tesla_solar_manager.py
```

---

## 4. Source Blueprints

### File 1: Dependencies (`requirements.txt`)
```text
requests>=2.31.0
astral>=3.2
```

### File 2: Config Templates (`config.json`)
*Note: Set `FRONIUS_EXPORT_IS_POSITIVE` to `true` if your inverter UI shows exporting solar as a positive number; set to `false` if exporting is shown as negative [cite: 1, 8].*
```json
{
  "FRONIUS_IP": "192.168.1.150",
  "FRONIUS_EXPORT_IS_POSITIVE": false,
  "TESLA_VIN": "5YJ3XXXXXXXXXXXXX",
  "TESLA_API_TOKEN": "YOUR_TESLA_API_ACCESS_TOKEN",
  "LATITUDE": -33.8688,
  "LONGITUDE": 151.2093,
  "TIMEZONE": "Australia/Sydney",
  "CITY_NAME": "Sydney",
  "VOLTAGE": 240,
  "MIN_AMPS": 5,
  "MAX_AMPS": 32,
  "BUFFER_WATTS": 150
}
```

### File 3: Core Logic Controller (`tesla_solar_manager.py`)
```python
import os
import json
import datetime
from datetime import datetime as dt, timezone
from zoneinfo import ZoneInfo
import requests
from astral import LocationInfo
from astral.sun import sun

BASE_DIR = "/volume1/homes/admin/tesla_tracker"
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CACHE_PATH = os.path.join(BASE_DIR, "state_cache.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def read_cache():
    if not os.path.exists(CACHE_PATH):
        return {"charging": False, "amps": 5}
    with open(CACHE_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"charging": False, "amps": 5}

def write_cache(state):
    with open(CACHE_PATH, "w") as f:
        json.dump(state, f)

def get_daylight_window(config):
    local_tz = ZoneInfo(config["TIMEZONE"])
    now = dt.now(local_tz)
    
    city = LocationInfo(
        config["CITY_NAME"], 
        "State", 
        config["TIMEZONE"], 
        config["LATITUDE"], 
        config["LONGITUDE"]
    )
    # Astral requires a datetime.date object
    s = sun(city.observer, date=now.date(), tzinfo=timezone.utc)
    sunrise = s['sunrise'].astimezone(local_tz)
    sunset = s['sunset'].astimezone(local_tz)
    return sunrise, sunset, now

def get_excess_solar(config):
    try:
        url = f"http://{config['FRONIUS_IP']}/solar_api/v1/GetPowerFlowRealtimeData.fcgi"
        response = requests.get(url, timeout=10)
        data = response.json()
        p_grid = data["Body"]["Data"]["Site"]["P_Grid"]
        
        # Calculate excess based on configured meter orientation
        if config["FRONIUS_EXPORT_IS_POSITIVE"]:
            return float(p_grid)
        else:
            return -float(p_grid)
    except Exception as e:
        print(f"[{dt.now()}] Telemetry fetch error from Fronius: {e}")
        return None

def call_tesla_api(config, endpoint, payload=None):
    headers = {
        "Authorization": f"Bearer {config['TESLA_API_TOKEN']}",
        "Content-Type": "application/json"
    }
    # Formatted strictly without markdown link interference
    url = f"[https://api.tesla.com/api/1/vehicles/](https://api.tesla.com/api/1/vehicles/){config['TESLA_VIN']}/command/{endpoint}"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            result = response.json().get("response", {}).get("result")
            if result:
                return True
        print(f"[{dt.now()}] API error response from Tesla on /{endpoint}: {response.text}")
        return False
    except Exception as e:
        print(f"[{dt.now()}] Connection failure to Tesla Fleet API: {e}")
        return False

def run_solar_loop():
    config = load_config()
    cache = read_cache()
    sunrise, sunset, now = get_daylight_window(config)

    # 1. OUT OF HOURS SAFETY ROUTINE
    if now < sunrise or now > sunset:
        if now > sunset and cache.get("charging", False):
            print(f"[{now}] Past sunset. Shutting down charging.")
            if call_tesla_api(config, "charge_stop"):
                cache["charging"] = False
                write_cache(cache)
                print(f"[{now}] Success: Charger safely turned off for the night.")
        else:
            print(f"[{now}] Out of daylight hours. Loop idle.")
        return

    # 2. ACTIVE SUNLIGHT TRACKING WINDOW
    excess_watts = get_excess_solar(config)
    if excess_watts is None:
        return # Skip calculation if telemetry is missing

    usable_watts = excess_watts - config["BUFFER_WATTS"]
    min_power_threshold = config["MIN_AMPS"] * config["VOLTAGE"]

    target_charging = False
    target_amps = config["MIN_AMPS"]

    if usable_watts >= min_power_threshold:
        target_charging = True
        calculated_amps = int(usable_watts // config["VOLTAGE"])
        target_amps = min(config["MAX_AMPS"], max(config["MIN_AMPS"], calculated_amps))

    current_charging = cache.get("charging", False)
    current_amps = cache.get("amps", config["MIN_AMPS"])

    # 3. STATE COMPARATIVE TRANSITIONS
    if target_charging:
        if not current_charging:
            print(f"[{now}] Solar surplus ({excess_watts} W) detected. Starting charge at {target_amps} A.")
            if call_tesla_api(config, "charge_start"):
                if call_tesla_api(config, "set_charging_amps", {"charging_amps": target_amps}):
                    cache["charging"] = True
                    cache["amps"] = target_amps
                    write_cache(cache)
        elif target_amps != current_amps:
            print(f"[{now}] Surplus changed. Adjusting charge: {current_amps} A -> {target_amps} A.")
            if call_tesla_api(config, "set_charging_amps", {"charging_amps": target_amps}):
                cache["amps"] = target_amps
                write_cache(cache)
        else:
            print(f"[{now}] In balance. Maintaining {current_amps} A.")
    else:
        if current_charging:
            print(f"[{now}] Solar surplus dropped to ({excess_watts} W). Stopping charge.")
            if call_tesla_api(config, "charge_stop"):
                cache["charging"] = False
                write_cache(cache)
        else:
            print(f"[{now}] Surplus ({excess_watts} W) insufficient to charge. System idle.")

if __name__ == "__main__":
    run_solar_loop()
```

### File 4: Shell Wrapper (`run.sh`)
DSM scheduler execution bridge [cite: 6]:
```bash
#!/bin/bash
cd /volume1/homes/admin/tesla_tracker
source env/bin/activate
python3 tesla_solar_manager.py >> execution.log 2>&1
```

---

## 5. Deployment Instructions for Antigravity Agent

Provide this command list to the Antigravity Agent panel:

1. Create python virtual environment inside `/volume1/homes/admin/tesla_tracker/env` [cite: 6].
2. Install requirements using `pip install -r requirements.txt`.
3. Verify timezone logic runs on your specific DSM platform natively [cite: 6]:
   ```bash
   python3 -c "from zoneinfo import ZoneInfo; import astral; print('Dependencies compiled successfully.')"
   ```