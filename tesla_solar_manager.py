import os
import json
import datetime
from datetime import datetime as dt, timezone
import random
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
from astral import LocationInfo
from astral.sun import sun

# Set up paths relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CACHE_PATH = os.path.join(BASE_DIR, "state_cache.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

# Load environment variables
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

def load_config():
    """Loads non-sensitive configuration parameters from config.json and merges them with .env parameters."""
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    # Load sensitive config from environment variables
    config["FRONIUS_IP"] = os.getenv("FRONIUS_IP", "192.168.1.150")
    config["TESLA_VIN"] = os.getenv("TESLA_VIN", "5YJ3XXXXXXXXXXXXX")
    config["TESLA_API_TOKEN"] = os.getenv("TESLA_API_TOKEN", "YOUR_TESLA_API_ACCESS_TOKEN")
    
    # Mocking behavior flag: defaults to True for safety
    mock_tesla_str = os.getenv("MOCK_TESLA", "True").lower()
    config["MOCK_TESLA"] = mock_tesla_str in ("true", "1", "yes", "on")
    
    return config

def read_cache():
    """Reads current cache state or returns default if not present."""
    if not os.path.exists(CACHE_PATH):
        return {"charging": False, "amps": 5}
    with open(CACHE_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"charging": False, "amps": 5}

def write_cache(state):
    """Writes updated state to local cache file."""
    with open(CACHE_PATH, "w") as f:
        json.dump(state, f, indent=2)

def get_daylight_window(config, override_time=None):
    """Calculates sunrise and sunset for the current day."""
    local_tz = ZoneInfo(config["TIMEZONE"])
    
    if override_time is not None:
        now = override_time.astimezone(local_tz)
    else:
        now = dt.now(local_tz)
    
    city = LocationInfo(
        config["CITY_NAME"], 
        "State", 
        config["TIMEZONE"], 
        config["LATITUDE"], 
        config["LONGITUDE"]
    )
    s = sun(city.observer, date=now.date(), tzinfo=local_tz)
    sunrise = s['sunrise']
    sunset = s['sunset']
    return sunrise, sunset, now

def get_excess_solar(config, mock_power=None):
    """Fetches real-time excess grid power from Fronius inverter."""
    if mock_power is not None:
        p_grid = mock_power
    else:
        try:
            url = f"http://{config['FRONIUS_IP']}/solar_api/v1/GetPowerFlowRealtimeData.fcgi"
            response = requests.get(url, timeout=10)
            data = response.json()
            p_grid = data["Body"]["Data"]["Site"]["P_Grid"]
        except Exception as e:
            print(f"[{dt.now()}] Telemetry fetch error from Fronius: {e}")
            return None
            
    # Calculate excess based on configured meter orientation
    if config["FRONIUS_EXPORT_IS_POSITIVE"]:
        return float(p_grid)
    else:
        return -float(p_grid)

def call_tesla_api(config, endpoint, payload=None):
    """Calls Tesla Fleet API or simulates it depending on configuration."""
    now_str = dt.now().isoformat()
    if config["MOCK_TESLA"]:
        # Random but realistic mocking of the data / execution responses
        success_rate = 0.95 # 95% API success rate for realism
        is_success = random.random() < success_rate
        
        simulated_soc = random.randint(40, 85)
        
        if not is_success:
            print(f"[{now_str}] [MOCK TESLA] Simulated API failure (timeout/network error) on /{endpoint}")
            return False
            
        print(f"[{now_str}] [MOCK TESLA] Command /{endpoint} succeeded. Payload: {payload}. (Est. Vehicle SoC: {simulated_soc}%)")
        return True

    # Real API implementation
    headers = {
        "Authorization": f"Bearer {config['TESLA_API_TOKEN']}",
        "Content-Type": "application/json"
    }
    url = f"https://api.tesla.com/api/1/vehicles/{config['TESLA_VIN']}/command/{endpoint}"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            result = response.json().get("response", {}).get("result")
            if result:
                return True
        print(f"[{now_str}] API error response from Tesla on /{endpoint}: {response.text}")
        return False
    except Exception as e:
        print(f"[{now_str}] Connection failure to Tesla Fleet API: {e}")
        return False

def calculate_target_amps(excess_watts, config):
    """Calculates charging current target based on excess watts and safety buffer."""
    usable_watts = excess_watts - config["BUFFER_WATTS"]
    min_power_threshold = config["MIN_AMPS"] * config["VOLTAGE"]
    
    if usable_watts < min_power_threshold:
        return False, config["MIN_AMPS"]
        
    calculated_amps = int(usable_watts // config["VOLTAGE"])
    target_amps = min(config["MAX_AMPS"], max(config["MIN_AMPS"], calculated_amps))
    return True, target_amps

def run_solar_loop(override_time=None, mock_power=None):
    """Main execution loop for solar tracking logic."""
    config = load_config()
    cache = read_cache()
    sunrise, sunset, now = get_daylight_window(config, override_time=override_time)

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
    excess_watts = get_excess_solar(config, mock_power=mock_power)
    if excess_watts is None:
        return # Skip calculation if telemetry is missing

    target_charging, target_amps = calculate_target_amps(excess_watts, config)
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
