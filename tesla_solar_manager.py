import os
import json
import time
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
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Redefine print to write to daily log files and standard output
def custom_print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    
    # Write to actual stdout terminal
    import sys
    sys.__stdout__.write(message + "\n")
    
    # Write to daily log
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        local_tz = ZoneInfo("Australia/Sydney")
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
                if "TIMEZONE" in cfg:
                    local_tz = ZoneInfo(cfg["TIMEZONE"])
        now = dt.now(local_tz)
    except Exception:
        now = dt.now()
        
    log_file = os.path.join(LOGS_DIR, f"execution_{now.strftime('%Y%m%d')}.log")
    try:
        with open(log_file, "a") as f:
            if message.startswith("[202") or message.startswith("["):
                f.write(message + "\n")
            else:
                f.write(f"[{dt.now()}] {message}\n")
    except Exception as e:
        sys.__stdout__.write(f"[{dt.now()}] Logging write error: {e}\n")

# Override built-in print globally
print = custom_print

# Load environment variables
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

def load_config():
    """Loads non-sensitive configuration parameters from config.json and merges them with .env parameters."""
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    config["FRONIUS_IP"] = os.getenv("FRONIUS_IP", "192.168.1.150")
    config["TESLA_API_BASE_URL"] = os.getenv("TESLA_API_BASE_URL", "https://fleet-api.prd.na.vn.cloud.tesla.com")
    config["TESLA_VIN"] = os.getenv("TESLA_VIN", "5YJ3XXXXXXXXXXXXX")
    config["TESLA_API_TOKEN"] = os.getenv("TESLA_API_TOKEN", "YOUR_TESLA_API_ACCESS_TOKEN")
    config["TESLA_REFRESH_TOKEN"] = os.getenv("TESLA_REFRESH_TOKEN", "")
    config["TESLA_CLIENT_ID"] = os.getenv("TESLA_CLIENT_ID", "")
    config["TESLA_CLIENT_SECRET"] = os.getenv("TESLA_CLIENT_SECRET", "")
    config["LATITUDE"] = float(os.getenv("LATITUDE", "-33.8688"))
    config["LONGITUDE"] = float(os.getenv("LONGITUDE", "151.2093"))
    
    # Mocking behavior flag: defaults to True for safety
    mock_tesla_str = os.getenv("MOCK_TESLA", "True").lower()
    config["MOCK_TESLA"] = mock_tesla_str in ("true", "1", "yes", "on")
    
    # Dry Run commands flag: defaults to True for safety
    dry_run_str = os.getenv("DRY_RUN", "True").lower()
    config["DRY_RUN"] = dry_run_str in ("true", "1", "yes", "on")
    
    # Mock API failure rate (0.0 means always succeed)
    config["MOCK_API_FAILURE_RATE"] = float(os.getenv("MOCK_API_FAILURE_RATE", "0.05"))
    
    return config

def read_cache():
    """Reads current cache state or returns default if not present."""
    defaults = {
        "charging": False, 
        "amps": 5, 
        "last_command_time": None, 
        "solar_history": [],
        "vehicle_state": {},
        "last_telemetry_check_time": None,
        "last_sunrise_reset_date": None
    }
    if not os.path.exists(CACHE_PATH):
        return defaults
    with open(CACHE_PATH, "r") as f:
        try:
            data = json.load(f)
            # Merge with defaults to ensure all keys are present
            for key, val in defaults.items():
                if key not in data:
                    data[key] = val
            return data
        except json.JSONDecodeError:
            return defaults

def write_cache(state):
    """Writes updated state to local cache file."""
    with open(CACHE_PATH, "w") as f:
        json.dump(state, f, indent=2)

def update_env_file(key, value):
    """Updates or adds a key-value pair in the local .env file."""
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, "r") as f:
        lines = f.readlines()
        
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            updated = True
        else:
            new_lines.append(line)
            
    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")
        
    with open(ENV_PATH, "w") as f:
        f.writelines(new_lines)

def refresh_tesla_token(config):
    """Refreshes the Tesla OAuth token using the refresh token and writes the new tokens back to .env."""
    refresh_token = config.get("TESLA_REFRESH_TOKEN")
    client_id = config.get("TESLA_CLIENT_ID")
    client_secret = config.get("TESLA_CLIENT_SECRET")
    
    if not refresh_token or not client_id or not client_secret:
        print(f"[{dt.now()}] Cannot refresh Tesla token: TESLA_REFRESH_TOKEN, TESLA_CLIENT_ID, or TESLA_CLIENT_SECRET is missing.")
        return False
        
    print(f"[{dt.now()}] Attempting to refresh Tesla access token...")
    url = "https://auth.tesla.com/oauth2/v3/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            new_access_token = data.get("access_token")
            new_refresh_token = data.get("refresh_token")
            
            if not new_access_token or not new_refresh_token:
                print(f"[{dt.now()}] Token refresh response was missing access_token or refresh_token.")
                return False
                
            config["TESLA_API_TOKEN"] = new_access_token
            config["TESLA_REFRESH_TOKEN"] = new_refresh_token
            
            update_env_file("TESLA_API_TOKEN", new_access_token)
            update_env_file("TESLA_REFRESH_TOKEN", new_refresh_token)
            
            print(f"[{dt.now()}] Tesla token refreshed successfully.")
            return True
        else:
            print(f"[{dt.now()}] Failed to refresh Tesla token. HTTP {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"[{dt.now()}] Error during Tesla token refresh: {e}")
        return False

def wake_up_vehicle(config, max_attempts=10, delay_seconds=5):
    """Sends wake_up command and polls until the vehicle state is 'online'."""
    headers = {
        "Authorization": f"Bearer {config['TESLA_API_TOKEN']}",
        "Content-Type": "application/json"
    }
    base_url = config.get("TESLA_API_BASE_URL", "https://fleet-api.prd.na.vn.cloud.tesla.com").rstrip("/")
    url = f"{base_url}/api/1/vehicles/{config['TESLA_VIN']}/wake_up"
    
    print(f"[{dt.now()}] Vehicle is asleep or offline. Sending wake_up command...")
    
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, headers=headers, timeout=15)
            # Handle token refresh on 401
            if response.status_code == 401 or (response.status_code != 200 and "invalid authentication" in response.text):
                print(f"[{dt.now()}] Detected Tesla authentication failure on wake_up (HTTP {response.status_code}). Attempting token refresh...")
                if refresh_tesla_token(config):
                    headers["Authorization"] = f"Bearer {config['TESLA_API_TOKEN']}"
                    response = requests.post(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                state_data = response.json().get("response", {})
                state = state_data.get("state")
                print(f"[{dt.now()}] wake_up attempt {attempt}/{max_attempts}: Vehicle state is '{state}'")
                if state == "online":
                    print(f"[{dt.now()}] Vehicle is online and awake.")
                    return True
            else:
                print(f"[{dt.now()}] wake_up attempt {attempt}/{max_attempts} failed. HTTP {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[{dt.now()}] error during wake_up attempt {attempt}: {e}")
            
        if attempt < max_attempts:
            time.sleep(delay_seconds)
            
    print(f"[{dt.now()}] Timed out waiting for vehicle to wake up.")
    return False

def calculate_median(values):
    """Calculates the median value of a numerical list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 != 0:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0

def cleanup_old_logs(logs_dir, max_days):
    """Prunes log files older than max_days in logs_dir."""
    if not os.path.exists(logs_dir):
        return
    now = dt.now()
    cutoff_time = now - datetime.timedelta(days=max_days)
    for filename in os.listdir(logs_dir):
        if filename.startswith("execution_") and filename.endswith(".log"):
            filepath = os.path.join(logs_dir, filename)
            try:
                # Use file modification timestamp
                file_mtime = dt.fromtimestamp(os.path.getmtime(filepath))
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    print(f"Cleaned up old log file: {filename}")
            except Exception as e:
                print(f"Failed to delete log file {filename}: {e}")

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

def is_vehicle_at_home(vehicle_lat, vehicle_lon, home_lat, home_lon, tolerance=0.001):
    """Checks if the vehicle is close to home coordinates."""
    return abs(vehicle_lat - home_lat) < tolerance and abs(vehicle_lon - home_lon) < tolerance

def get_tesla_vehicle_data(config):
    """Fetches real vehicle data or returns mock data depending on configuration."""
    if config["MOCK_TESLA"]:
        # Load mock values from environment or set defaults
        mock_home = os.getenv("MOCK_VEHICLE_HOME", "True").lower() in ("true", "1", "yes", "on")
        mock_plugged = os.getenv("MOCK_VEHICLE_PLUGGED", "True").lower() in ("true", "1", "yes", "on")
        mock_soc = int(os.getenv("MOCK_VEHICLE_SOC", "75"))
        mock_limit = int(os.getenv("MOCK_VEHICLE_CHARGE_LIMIT", "90"))
        
        # Set mock coordinates based on home status
        if mock_home:
            lat = config["LATITUDE"]
            lon = config["LONGITUDE"]
        else:
            lat = config["LATITUDE"] + 0.5
            lon = config["LONGITUDE"] + 0.5
            
        charging_state = "Stopped" if mock_plugged else "Disconnected"
        if mock_soc >= mock_limit:
            charging_state = "Complete"
            
        return {
            "latitude": lat,
            "longitude": lon,
            "charging_state": charging_state,
            "battery_level": mock_soc,
            "charge_limit_soc": mock_limit
        }

    # Real implementation
    headers = {
        "Authorization": f"Bearer {config['TESLA_API_TOKEN']}",
        "Content-Type": "application/json"
    }
    base_url = config.get("TESLA_API_BASE_URL", "https://fleet-api.prd.na.vn.cloud.tesla.com").rstrip("/")
    url = f"{base_url}/api/1/vehicles/{config['TESLA_VIN']}/vehicle_data"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 401 or (response.status_code != 200 and "invalid authentication" in response.text):
            print(f"[{dt.now()}] Detected Tesla authentication failure (HTTP {response.status_code}). Attempting token refresh...")
            if refresh_tesla_token(config):
                headers["Authorization"] = f"Bearer {config['TESLA_API_TOKEN']}"
                response = requests.get(url, headers=headers, timeout=15)
        
        # Check if vehicle is offline or asleep
        is_asleep = False
        if response.status_code != 200:
            try:
                err_data = response.json()
                err_msg = err_data.get("error", "")
                if "offline" in err_msg or "asleep" in err_msg:
                    is_asleep = True
            except Exception:
                if "offline" in response.text or "asleep" in response.text:
                    is_asleep = True
                    
        if is_asleep:
            if wake_up_vehicle(config):
                # Update header in case token refreshed during wake_up
                headers["Authorization"] = f"Bearer {config['TESLA_API_TOKEN']}"
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 401 or (response.status_code != 200 and "invalid authentication" in response.text):
                    print(f"[{dt.now()}] Detected Tesla authentication failure after wake_up (HTTP {response.status_code}). Attempting token refresh...")
                    if refresh_tesla_token(config):
                        headers["Authorization"] = f"Bearer {config['TESLA_API_TOKEN']}"
                        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            data = response.json().get("response", {})
            drive_state = data.get("drive_state", {})
            charge_state = data.get("charge_state", {})
            return {
                "latitude": drive_state.get("latitude", 0.0),
                "longitude": drive_state.get("longitude", 0.0),
                "charging_state": charge_state.get("charging_state", "Disconnected"),
                "battery_level": charge_state.get("battery_level", 0),
                "charge_limit_soc": charge_state.get("charge_limit_soc", 100)
            }
        print(f"[{dt.now()}] API error response from Tesla on /vehicle_data: {response.text}")
        return None
    except Exception as e:
        print(f"[{dt.now()}] Connection failure to Tesla vehicle data API: {e}")
        return None

def call_tesla_api(config, endpoint, payload=None):
    """Calls Tesla Fleet API or simulates it depending on configuration."""
    now_str = dt.now().isoformat()
    
    # If DRY_RUN is enabled, log the action and simulate success without hitting any API.
    if config.get("DRY_RUN", True):
        print(f"[{now_str}] [DRY RUN] Command /{endpoint} would have been executed with payload: {payload}. (Bypassing real API call).")
        return True

    if config["MOCK_TESLA"]:
        # Random but realistic mocking of the data / execution responses
        failure_rate = config.get("MOCK_API_FAILURE_RATE", 0.05)
        is_success = random.random() >= failure_rate
        
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
    base_url = config.get("TESLA_API_BASE_URL", "https://fleet-api.prd.na.vn.cloud.tesla.com").rstrip("/")
    url = f"{base_url}/api/1/vehicles/{config['TESLA_VIN']}/command/{endpoint}"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 401 or (response.status_code != 200 and "invalid authentication" in response.text):
            print(f"[{now_str}] Detected Tesla authentication failure (HTTP {response.status_code}) on /{endpoint}. Attempting token refresh...")
            if refresh_tesla_token(config):
                headers["Authorization"] = f"Bearer {config['TESLA_API_TOKEN']}"
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
    
    print(f"[{dt.now()}] Solar Control Inputs: Excess = {excess_watts} W, Buffer = {config['BUFFER_WATTS']} W, Usable surplus = {usable_watts} W, System Voltage = {config['VOLTAGE']} V")
    
    if usable_watts < min_power_threshold:
        print(f"[{dt.now()}] Solar Control Decision: Usable surplus ({usable_watts} W) is below minimum charge threshold ({min_power_threshold} W).")
        return False, config["MIN_AMPS"]
        
    calculated_amps = int(usable_watts // config["VOLTAGE"])
    target_amps = min(config["MAX_AMPS"], max(config["MIN_AMPS"], calculated_amps))
    print(f"[{dt.now()}] Solar Control Decision: Usable surplus ({usable_watts} W) yields calculated amps = {calculated_amps} A. Target current = {target_amps} A (Bounded: [{config['MIN_AMPS']} A, {config['MAX_AMPS']} A]).")
    return True, target_amps

def run_solar_loop(override_time=None, mock_power=None):
    """Main execution loop for solar tracking logic."""
    config = load_config()
    cleanup_old_logs(LOGS_DIR, config.get("MAX_LOG_DAYS", 30))
    cache = read_cache()
    sunrise, sunset, now = get_daylight_window(config, override_time=override_time)

    # 1. OUT OF HOURS SAFETY ROUTINE
    if now < sunrise or now > sunset:
        if now > sunset and cache.get("charging", False):
            print(f"[{now}] Past sunset. Shutting down charging.")
            if call_tesla_api(config, "charge_stop"):
                cache["charging"] = False
                if cache.get("vehicle_state"):
                    cache["vehicle_state"]["charging_state"] = "Stopped"
                cache["last_command_time"] = now.isoformat()
                write_cache(cache)
                print(f"[{now}] Success: Charger safely turned off for the night.")
        else:
            print(f"[{now}] Out of daylight hours. Loop idle.")
        return

    # Sunrise State Initialization (Start of Day)
    current_date_str = now.date().isoformat()
    if cache.get("last_sunrise_reset_date") != current_date_str:
        print(f"[{now}] New day detected. Performing sunrise state reset.")
        last_soc = 50
        last_limit = 90
        if cache.get("vehicle_state"):
            last_soc = cache["vehicle_state"].get("battery_level", last_soc)
            last_limit = cache["vehicle_state"].get("charge_limit_soc", last_limit)
        
        cache["vehicle_state"] = {
            "latitude": config["LATITUDE"],
            "longitude": config["LONGITUDE"],
            "charging_state": "Stopped",
            "battery_level": last_soc,
            "charge_limit_soc": last_limit
        }
        cache["last_sunrise_reset_date"] = current_date_str
        write_cache(cache)

    if not cache.get("vehicle_state"):
        cache["vehicle_state"] = {
            "latitude": config["LATITUDE"],
            "longitude": config["LONGITUDE"],
            "charging_state": "Stopped",
            "battery_level": 50,
            "charge_limit_soc": 90
        }
        write_cache(cache)

    # 2. SAVED STATE EVALUATION
    saved_state = cache["vehicle_state"]
    is_home = is_vehicle_at_home(
        saved_state["latitude"], 
        saved_state["longitude"], 
        config["LATITUDE"], 
        config["LONGITUDE"], 
        config.get("LOCATION_TOLERANCE", 0.001)
    )
    is_plugged = saved_state["charging_state"] != "Disconnected"
    soc = saved_state["battery_level"]
    charge_limit = saved_state.get("charge_limit_soc", 100)
    is_full = soc >= charge_limit

    # 3. ACTIVE SUNLIGHT TRACKING WINDOW
    excess_watts = get_excess_solar(config, mock_power=mock_power)
    if excess_watts is None:
        return # Skip calculation if telemetry is missing

    # Append to rolling history
    cache["solar_history"].append({"timestamp": now.isoformat(), "watts": excess_watts})
    
    # Filter rolling history to include only elements in the window (window length + 2 min tolerance)
    cutoff = now - datetime.timedelta(minutes=config.get("HISTORY_WINDOW_MINUTES", 15) + 2)
    valid_history = []
    for item in cache["solar_history"]:
        try:
            item_time = dt.fromisoformat(item["timestamp"]).astimezone(now.tzinfo)
            if item_time >= cutoff:
                valid_history.append(item)
        except (ValueError, KeyError):
            pass
            
    # Max size cap based on intervals
    max_size = max(1, config.get("HISTORY_WINDOW_MINUTES", 15) // config.get("POLLING_INTERVAL_MINUTES", 5))
    valid_history = valid_history[-max_size:]
    cache["solar_history"] = valid_history
    write_cache(cache)

    # Compute median surplus
    watts_list = [item["watts"] for item in valid_history]
    median_excess = calculate_median(watts_list)
    print(f"[{now}] Rolling History: {len(valid_history)} readings over last {config.get('HISTORY_WINDOW_MINUTES', 15)} mins. Median = {median_excess:.2f} W. (Readings: {[round(w,1) for w in watts_list]})")

    target_charging, target_amps = calculate_target_amps(median_excess, config)
    current_charging = cache.get("charging", False)
    current_amps = cache.get("amps", config["MIN_AMPS"])

    # Nuance: if saved state is offline/away but surplus says to charge, check live state (at most once every 10 min)
    if (not is_home or not is_plugged) and target_charging:
        last_check_str = cache.get("last_telemetry_check_time")
        can_check = True
        if last_check_str:
            try:
                last_check_dt = dt.fromisoformat(last_check_str).astimezone(now.tzinfo)
                if (now - last_check_dt).total_seconds() / 60.0 < 10.0:
                    can_check = False
            except Exception:
                pass
        
        if can_check:
            print(f"[{now}] Saved state is offline/away, but surplus indicates start charge. Checking live Tesla telemetry...")
            live_data = get_tesla_vehicle_data(config)
            if live_data is not None:
                cache["last_telemetry_check_time"] = now.isoformat()
                cache["vehicle_state"] = live_data
                write_cache(cache)
                saved_state = live_data
                # Update gating check variables
                is_home = is_vehicle_at_home(
                    saved_state["latitude"], 
                    saved_state["longitude"], 
                    config["LATITUDE"], 
                    config["LONGITUDE"], 
                    config.get("LOCATION_TOLERANCE", 0.001)
                )
                is_plugged = saved_state["charging_state"] != "Disconnected"
                soc = saved_state["battery_level"]
                charge_limit = saved_state.get("charge_limit_soc", 100)
                is_full = soc >= charge_limit
            else:
                print(f"[{now}] Failed to fetch live Tesla telemetry. Proceeding with saved offline state.")
        else:
            remaining = 10.0 - ((now - last_check_dt).total_seconds() / 60.0)
            print(f"[{now}] Saved state is offline/away. Surplus indicates charge possible, but live API query throttled. Remaining: {remaining:.1f} mins. System idle.")
            return

    # Check Gating criteria
    if not is_home or not is_plugged or is_full:
        reason = []
        if not is_home:
            reason.append("vehicle not at home")
        if not is_plugged:
            reason.append("vehicle not plugged in")
        if is_full:
            reason.append(f"vehicle charged to limit ({soc}% >= {charge_limit}%)")
            
        print(f"[{now}] Gating criteria failed: {', '.join(reason)}. System idle.")
        
        # Turn off charging if cached state indicates we were charging
        if current_charging:
            print(f"[{now}] Disabling charging due to gate failure. Sending command /charge_stop to Tesla...")
            if call_tesla_api(config, "charge_stop"):
                cache["charging"] = False
                cache["vehicle_state"]["charging_state"] = "Stopped"
                cache["last_command_time"] = now.isoformat()
                write_cache(cache)
        return

    # 4. STATE COMPARATIVE TRANSITIONS
    state_changed = (target_charging != current_charging) or (target_charging and target_amps != current_amps)
    
    if state_changed:
        print(f"[{now}] Calculated action indicates a change (Charging: {current_charging}->{target_charging}, Amps: {current_amps}->{target_amps}). Confirming saved state with live Tesla telemetry...")
        live_data = get_tesla_vehicle_data(config)
        if live_data is None:
            print(f"[{now}] Failed to fetch live Tesla telemetry. Aborting state change.")
            return
            
        cache["last_telemetry_check_time"] = now.isoformat()
        cache["vehicle_state"] = live_data
        write_cache(cache)
        saved_state = live_data

        # Recalculate gating rules on live data
        is_home = is_vehicle_at_home(
            saved_state["latitude"], 
            saved_state["longitude"], 
            config["LATITUDE"], 
            config["LONGITUDE"], 
            config.get("LOCATION_TOLERANCE", 0.001)
        )
        is_plugged = saved_state["charging_state"] != "Disconnected"
        soc = saved_state["battery_level"]
        charge_limit = saved_state.get("charge_limit_soc", 100)
        is_full = soc >= charge_limit

        if not is_home or not is_plugged or is_full:
            reason = []
            if not is_home:
                reason.append("vehicle not at home")
            if not is_plugged:
                reason.append("vehicle not plugged in")
            if is_full:
                reason.append(f"vehicle charged to limit ({soc}% >= {charge_limit}%)")
            print(f"[{now}] Live gating check failed after validation: {', '.join(reason)}. Aborting command.")
            
            if current_charging:
                print(f"[{now}] Disabling charging due to gate failure. Sending command /charge_stop to Tesla...")
                if call_tesla_api(config, "charge_stop"):
                    cache["charging"] = False
                    cache["vehicle_state"]["charging_state"] = "Stopped"
                    cache["last_command_time"] = now.isoformat()
                    write_cache(cache)
            return

        # Check throttling rule (except safety transitions)
        last_cmd = cache.get("last_command_time")
        if last_cmd is not None:
            try:
                last_cmd_dt = dt.fromisoformat(last_cmd).astimezone(now.tzinfo)
                time_since_last_cmd = (now - last_cmd_dt).total_seconds() / 60.0
                throttle_limit = config.get("THROTTLE_INTERVAL_MINUTES", 10)
                if time_since_last_cmd < throttle_limit:
                    remaining = throttle_limit - time_since_last_cmd
                    print(f"[{now}] Throttle Active: Change (Charging: {current_charging}->{target_charging}, Amps: {current_amps}->{target_amps}) throttled. Remaining: {remaining:.1f} mins. Maintaining current state.")
                    return
            except Exception:
                pass

        if target_charging:
            if not current_charging:
                print(f"[{now}] Solar surplus ({median_excess:.1f} W) detected. Starting charge at {target_amps} A. Sending command /charge_start to Tesla...")
                if call_tesla_api(config, "charge_start"):
                    print(f"[{now}] Sending command /set_charging_amps with payload {{'charging_amps': {target_amps}}} to Tesla...")
                    if call_tesla_api(config, "set_charging_amps", {"charging_amps": target_amps}):
                        cache["charging"] = True
                        cache["amps"] = target_amps
                        cache["vehicle_state"]["charging_state"] = "Charging"
                        cache["last_command_time"] = now.isoformat()
                        write_cache(cache)
            elif target_amps != current_amps:
                print(f"[{now}] Surplus changed. Adjusting charge: {current_amps} A -> {target_amps} A. Sending command /set_charging_amps to Tesla...")
                if call_tesla_api(config, "set_charging_amps", {"charging_amps": target_amps}):
                    cache["amps"] = target_amps
                    cache["last_command_time"] = now.isoformat()
                    write_cache(cache)
        else:
            if current_charging:
                print(f"[{now}] Solar surplus dropped to ({median_excess:.1f} W). Stopping charge. Sending command /charge_stop to Tesla...")
                if call_tesla_api(config, "charge_stop"):
                    cache["charging"] = False
                    cache["vehicle_state"]["charging_state"] = "Stopped"
                    cache["last_command_time"] = now.isoformat()
                    write_cache(cache)
    else:
        if target_charging:
            print(f"[{now}] In balance. Maintaining {current_amps} A.")
        else:
            print(f"[{now}] Surplus ({median_excess:.1f} W) insufficient to charge. System idle.")

if __name__ == "__main__":
    run_solar_loop()
