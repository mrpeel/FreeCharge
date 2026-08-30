import unittest
import os
import json
import datetime
from datetime import datetime as dt, timezone
from zoneinfo import ZoneInfo
import http.server
import threading
import time
import socket
from unittest.mock import patch, MagicMock

# Import functions to test
import tesla_solar_manager

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TEST_DIR)

# Redirect logs directory globally for test isolation
tesla_solar_manager.LOGS_DIR = os.path.join(TEST_DIR, "temp_test_logs")
if not os.path.exists(tesla_solar_manager.LOGS_DIR):
    os.makedirs(tesla_solar_manager.LOGS_DIR, exist_ok=True)

class TestSolarControlMath(unittest.TestCase):
    def setUp(self):
        self.config = {
            "MIN_AMPS": 5,
            "MAX_AMPS": 32,
            "VOLTAGE": 240,
            "BUFFER_WATTS": 150
        }

    def test_insufficient_solar(self):
        # 5A * 240V = 1200W required. 1000W excess - 150W buffer = 850W usable < 1200W
        charging, amps = tesla_solar_manager.calculate_target_amps(1000, self.config)
        self.assertFalse(charging)
        self.assertEqual(amps, self.config["MIN_AMPS"])

        # Negative excess
        charging, amps = tesla_solar_manager.calculate_target_amps(-500, self.config)
        self.assertFalse(charging)
        self.assertEqual(amps, self.config["MIN_AMPS"])

    def test_sufficient_solar_mid_range(self):
        # 3000W excess - 150W buffer = 2850W usable. 2850 // 240 = 11A
        charging, amps = tesla_solar_manager.calculate_target_amps(3000, self.config)
        self.assertTrue(charging)
        self.assertEqual(amps, 11)

    def test_solar_max_amps_cap(self):
        # 10000W excess - 150W buffer = 9850W usable. 9850 // 240 = 41A, capped at 32A
        charging, amps = tesla_solar_manager.calculate_target_amps(10000, self.config)
        self.assertTrue(charging)
        self.assertEqual(amps, self.config["MAX_AMPS"])

    def test_solar_min_amps_boundary(self):
        # 1400W excess - 150W buffer = 1250W usable. 1250 // 240 = 5A
        charging, amps = tesla_solar_manager.calculate_target_amps(1400, self.config)
        self.assertTrue(charging)
        self.assertEqual(amps, 5)


class TestDaylightChecking(unittest.TestCase):
    def setUp(self):
        self.config = {
            "TIMEZONE": "Australia/Sydney",
            "CITY_NAME": "Sydney",
            "LATITUDE": -33.8688,
            "LONGITUDE": 151.2093
        }

    def test_daylight_calculations(self):
        # Choose a fixed date/time: June 21, 2026 at 12:00 PM AEST
        tz = ZoneInfo(self.config["TIMEZONE"])
        test_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        sunrise, sunset, now = tesla_solar_manager.get_daylight_window(self.config, override_time=test_time)
        
        self.assertEqual(now.year, 2026)
        self.assertEqual(now.month, 6)
        self.assertEqual(now.day, 21)
        self.assertLess(sunrise, now)
        self.assertGreater(sunset, now)


class TestCacheUtility(unittest.TestCase):
    def setUp(self):
        self.original_cache_path = tesla_solar_manager.CACHE_PATH
        tesla_solar_manager.CACHE_PATH = os.path.join(TEST_DIR, "temp_state_cache.json")
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)

    def tearDown(self):
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)
        tesla_solar_manager.CACHE_PATH = self.original_cache_path

    def test_read_empty_cache_returns_defaults(self):
        state = tesla_solar_manager.read_cache()
        self.assertEqual(state["charging"], False)
        self.assertEqual(state["amps"], 5)
        self.assertEqual(state["solar_history"], [])
        self.assertIsNone(state["last_command_time"])

    def test_write_and_read_cache(self):
        test_state = {
            "charging": True,
            "amps": 16,
            "last_command_time": "2026-06-21T12:00:00",
            "solar_history": [{"timestamp": "2026-06-21T12:00:00", "watts": 3000}],
            "vehicle_state": {},
            "wall_connector_state": {},
            "last_telemetry_check_time": None,
            "last_wake_attempt_time": None,
            "last_sunrise_reset_date": None
        }
        tesla_solar_manager.write_cache(test_state)
        read_state = tesla_solar_manager.read_cache()
        self.assertEqual(read_state, test_state)


class TestConfigLoading(unittest.TestCase):
    def setUp(self):
        self.original_config_path = tesla_solar_manager.CONFIG_PATH
        self.temp_config = os.path.join(TEST_DIR, "temp_corrupt_config.json")
        tesla_solar_manager.CONFIG_PATH = self.temp_config

    def tearDown(self):
        if os.path.exists(self.temp_config):
            os.remove(self.temp_config)
        tesla_solar_manager.CONFIG_PATH = self.original_config_path

    def test_load_config_recovers_from_corrupted_json(self):
        # Write corrupted JSON with trailing comma
        with open(self.temp_config, "w") as f:
            f.write('{\n  "VOLTAGE": 240,\n  "MIN_AMPS": 5,\n}')

        config = tesla_solar_manager.load_config()
        self.assertIsNotNone(config)
        self.assertEqual(config["VOLTAGE"], 240)
        self.assertEqual(config["MIN_AMPS"], 5)
        self.assertEqual(config["TESLA_WALL_CONNECTOR_IP"], "192.168.1.60")


class TestTeslaGating(unittest.TestCase):
    def test_is_vehicle_at_home(self):
        home_lat = -33.8688
        home_lon = 151.2093
        tolerance = 0.001
        
        # Vehicle is at home
        self.assertTrue(tesla_solar_manager.is_vehicle_at_home(
            -33.8685, 151.2091, home_lat, home_lon, tolerance
        ))
        # Vehicle is away (lat offset too high)
        self.assertFalse(tesla_solar_manager.is_vehicle_at_home(
            -33.8670, 151.2091, home_lat, home_lon, tolerance
        ))
        # Vehicle is away (lon offset too high)
        self.assertFalse(tesla_solar_manager.is_vehicle_at_home(
            -33.8685, 151.2110, home_lat, home_lon, tolerance
        ))

    @patch.dict(os.environ, {
        "MOCK_VEHICLE_HOME": "False",
        "MOCK_VEHICLE_PLUGGED": "True",
        "MOCK_VEHICLE_SOC": "50",
        "MOCK_VEHICLE_CHARGE_LIMIT": "90"
    })
    def test_mock_vehicle_data_away(self):
        config = {
            "MOCK_TESLA": True,
            "LATITUDE": -33.8688,
            "LONGITUDE": 151.2093
        }
        data = tesla_solar_manager.get_tesla_vehicle_data(config)
        self.assertFalse(tesla_solar_manager.is_vehicle_at_home(
            data["latitude"], data["longitude"], config["LATITUDE"], config["LONGITUDE"]
        ))
        self.assertEqual(data["charging_state"], "Stopped")


class TestDampingAndThrottling(unittest.TestCase):
    def test_calculate_median(self):
        # Odd length
        self.assertEqual(tesla_solar_manager.calculate_median([10, 5, 20]), 10.0)
        # Even length
        self.assertEqual(tesla_solar_manager.calculate_median([10, 20, 30, 40]), 25.0)
        # Empty
        self.assertEqual(tesla_solar_manager.calculate_median([]), 0.0)
        # Single element
        self.assertEqual(tesla_solar_manager.calculate_median([99]), 99.0)


class TestLogRotation(unittest.TestCase):
    def setUp(self):
        self.logs_dir = tesla_solar_manager.LOGS_DIR
        # Clean directory
        for f in os.listdir(self.logs_dir):
            os.remove(os.path.join(self.logs_dir, f))

    def tearDown(self):
        for f in os.listdir(self.logs_dir):
            os.remove(os.path.join(self.logs_dir, f))

    def test_log_cleanup_pruning(self):
        old_file = os.path.join(self.logs_dir, "execution_20200101.log")
        new_file = os.path.join(self.logs_dir, "execution_20260101.log")
        
        # Create dummy log files
        with open(old_file, "w") as f:
            f.write("Old log message")
        with open(new_file, "w") as f:
            f.write("Recent log message")
            
        # Set file modification times (old_file = 40 days ago, new_file = today/recent)
        now_ts = time.time()
        old_ts = now_ts - (40 * 24 * 3600) # 40 days ago
        
        os.utime(old_file, (old_ts, old_ts))
        os.utime(new_file, (now_ts, now_ts))
        
        # Run cleanup
        tesla_solar_manager.cleanup_old_logs(self.logs_dir, max_days=30)
        
        # Verify old file is deleted, new file is kept
        self.assertFalse(os.path.exists(old_file))
        self.assertTrue(os.path.exists(new_file))


# E2E Mock Server Handler
class MockFroniusAPIHandler(http.server.BaseHTTPRequestHandler):
    grid_power = 0.0

    def do_GET(self):
        if "/solar_api/v1/GetPowerFlowRealtimeData.fcgi" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "Body": {
                    "Data": {
                        "Site": {
                            "P_Grid": MockFroniusAPIHandler.grid_power
                        }
                    }
                }
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass # Suppress logging to stdout during tests


class TestE2EIntegration(unittest.TestCase):
    grid_power = -3000.0

    def setUp(self):
        TestE2EIntegration.grid_power = -3000.0
        self.original_cache_path = tesla_solar_manager.CACHE_PATH
        tesla_solar_manager.CACHE_PATH = os.path.join(TEST_DIR, "temp_e2e_state_cache.json")
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)

        # Set up env mocks and test config override
        self.config_patcher = patch('tesla_solar_manager.load_config')
        self.mock_load_config = self.config_patcher.start()
        
        self.test_config = {
            "FRONIUS_IP": "192.168.1.150",
            "FRONIUS_EXPORT_IS_POSITIVE": False,
            "TESLA_VIN": "5YJ3TESTINGVIN123",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com",
            "TESLA_API_TOKEN": "mock_token",
            "MOCK_TESLA": True,
            "MOCK_API_FAILURE_RATE": 0.0,
            "DRY_RUN": True,
            "LATITUDE": -33.8688,
            "LONGITUDE": 151.2093,
            "TIMEZONE": "Australia/Sydney",
            "CITY_NAME": "Sydney",
            "VOLTAGE": 240,
            "MIN_AMPS": 5,
            "MAX_AMPS": 32,
            "BUFFER_WATTS": 150,
            "LOCATION_TOLERANCE": 0.001,
            "HISTORY_WINDOW_MINUTES": 10,
            "POLLING_INTERVAL_MINUTES": 2,
            "THROTTLE_INTERVAL_MINUTES": 10,
            "TELEMETRY_REFRESH_MINUTES": 15,
            "WAKE_COOLDOWN_MINUTES": 60,
            "TESLA_WALL_CONNECTOR_IP": None,
            "MOCK_WALL_CONNECTOR": False
        }
        self.mock_load_config.return_value = self.test_config

        def mock_requests_get(url, *args, **kwargs):
            mock_resp = MagicMock()
            if "/solar_api/v1/GetPowerFlowRealtimeData.fcgi" in url:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "Body": {
                        "Data": {
                            "Site": {
                                "P_Grid": TestE2EIntegration.grid_power
                            }
                        }
                    }
                }
                return mock_resp
            mock_resp.status_code = 404
            return mock_resp

        self.requests_get_patcher = patch('requests.get', side_effect=mock_requests_get)
        self.requests_get_patcher.start()

        # Set default gating mock variables
        os.environ["MOCK_VEHICLE_HOME"] = "True"
        os.environ["MOCK_VEHICLE_PLUGGED"] = "True"
        os.environ["MOCK_VEHICLE_SOC"] = "75"
        os.environ["MOCK_VEHICLE_CHARGE_LIMIT"] = "90"

    def tearDown(self):
        self.requests_get_patcher.stop()
        self.config_patcher.stop()
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)
        tesla_solar_manager.CACHE_PATH = self.original_cache_path

        # Clean env mocks
        for key in ["MOCK_VEHICLE_HOME", "MOCK_VEHICLE_PLUGGED", "MOCK_VEHICLE_SOC", "MOCK_VEHICLE_CHARGE_LIMIT"]:
            if key in os.environ:
                del os.environ[key]

    def test_e2e_solar_loop_surplus_and_charge_trigger(self):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)

        # Case 1: Inverter shows export of 3000W (P_Grid = -3000.0)
        TestE2EIntegration.grid_power = -3000.0
        
        # Verify initial cache is off
        cache = tesla_solar_manager.read_cache()
        self.assertFalse(cache["charging"])

        # Run full loop
        tesla_solar_manager.run_solar_loop(override_time=midday_time)

        # Verify updated cache showing charging started (median of single reading is 3000 -> 11A)
        updated_cache = tesla_solar_manager.read_cache()
        self.assertTrue(updated_cache["charging"])
        self.assertEqual(updated_cache["amps"], 11)
        self.assertIsNotNone(updated_cache["last_command_time"])

    def test_e2e_solar_loop_under_sunset_safety_switch(self):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        night_time = dt(2026, 6, 21, 21, 0, 0, tzinfo=tz)

        # Set cache to show it was charging during the day
        tesla_solar_manager.write_cache({"charging": True, "amps": 10, "last_command_time": None, "solar_history": []})

        # Run loop
        tesla_solar_manager.run_solar_loop(override_time=night_time)

        # Cache should now be safely set to charging=False
        updated_cache = tesla_solar_manager.read_cache()
        self.assertFalse(updated_cache["charging"])

    def test_e2e_solar_loop_away_safety_disconnect(self):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)

        os.environ["MOCK_VEHICLE_HOME"] = "False"
        tesla_solar_manager.write_cache({
            "charging": True, 
            "amps": 10, 
            "last_command_time": None, 
            "solar_history": [],
            "vehicle_state": {
                "latitude": 0.0,
                "longitude": 0.0,
                "charging_state": "Charging",
                "battery_level": 70,
                "charge_limit_soc": 90
            }
        })

        tesla_solar_manager.run_solar_loop(override_time=midday_time)

        updated_cache = tesla_solar_manager.read_cache()
        self.assertFalse(updated_cache["charging"])

    def test_e2e_solar_loop_throttling_behavior(self):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time_1 = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        midday_time_2 = dt(2026, 6, 21, 12, 4, 0, tzinfo=tz) # 4 minutes later (under the 10 min throttle)

        # 1. Trigger first change: starts charging at 11A
        TestE2EIntegration.grid_power = -3000.0
        tesla_solar_manager.run_solar_loop(override_time=midday_time_1)
        
        cache_1 = tesla_solar_manager.read_cache()
        self.assertTrue(cache_1["charging"])
        self.assertEqual(cache_1["amps"], 11)
        last_time_1 = cache_1["last_command_time"]

        # 2. Trigger second change: export spikes to 8000W (calculated 32A) but running only 4 mins later
        TestE2EIntegration.grid_power = -8000.0
        tesla_solar_manager.run_solar_loop(override_time=midday_time_2)

        # Cache should STILL show 11A due to throttle blocking command
        cache_2 = tesla_solar_manager.read_cache()
        self.assertTrue(cache_2["charging"])
        self.assertEqual(cache_2["amps"], 11) # Unchanged!
        self.assertEqual(cache_2["last_command_time"], last_time_1)

    def test_adjusted_excess_solar_includes_car_draw_when_charging(self):
        # Setup cache to show car is already charging at 10A
        tesla_solar_manager.write_cache({
            "charging": True,
            "amps": 10,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Charging",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21",
            "solar_history": []
        })
        
        # Inverter shows export of 500W (P_Grid = -500.0)
        # With 10A draw at 240V active, potential excess = 500W + (10 * 240) = 2900W.
        # Usable surplus = 2900W - 150W = 2750W.
        # Calculated amps = 2750 // 240 = 11A.
        TestE2EIntegration.grid_power = -500.0
        
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        
        with patch('tesla_solar_manager.get_tesla_vehicle_data') as mock_get:
            mock_get.return_value = {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Charging",
                "battery_level": 75,
                "charge_limit_soc": 90
            }
            tesla_solar_manager.run_solar_loop(override_time=midday_time)
            
        updated_cache = tesla_solar_manager.read_cache()
        self.assertTrue(updated_cache["charging"])
        self.assertEqual(updated_cache["amps"], 11)

class TestStateCachingBehavior(unittest.TestCase):
    def setUp(self):
        self.original_cache_path = tesla_solar_manager.CACHE_PATH
        tesla_solar_manager.CACHE_PATH = os.path.join(TEST_DIR, "temp_cache_behavior_test.json")
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)
            
        self.config_patcher = patch('tesla_solar_manager.load_config')
        self.mock_load_config = self.config_patcher.start()
        
        self.test_config = {
            "FRONIUS_IP": "127.0.0.1",
            "FRONIUS_EXPORT_IS_POSITIVE": False,
            "TESLA_VIN": "mock_vin",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com",
            "TESLA_API_TOKEN": "mock_token",
            "MOCK_TESLA": True,
            "MOCK_API_FAILURE_RATE": 0.0,
            "DRY_RUN": True,
            "LATITUDE": -33.8688,
            "LONGITUDE": 151.2093,
            "TIMEZONE": "Australia/Sydney",
            "CITY_NAME": "Sydney",
            "VOLTAGE": 240,
            "MIN_AMPS": 5,
            "MAX_AMPS": 32,
            "BUFFER_WATTS": 150,
            "LOCATION_TOLERANCE": 0.001,
            "HISTORY_WINDOW_MINUTES": 15,
            "POLLING_INTERVAL_MINUTES": 5,
            "THROTTLE_INTERVAL_MINUTES": 10,
            "TELEMETRY_REFRESH_MINUTES": 10,
            "WAKE_COOLDOWN_MINUTES": 60,
            "TESLA_WALL_CONNECTOR_IP": None,
            "MOCK_WALL_CONNECTOR": False
        }
        self.mock_load_config.return_value = self.test_config
        
        # Setup clean environment variables
        os.environ["MOCK_VEHICLE_HOME"] = "True"
        os.environ["MOCK_VEHICLE_PLUGGED"] = "True"
        os.environ["MOCK_VEHICLE_SOC"] = "75"
        os.environ["MOCK_VEHICLE_CHARGE_LIMIT"] = "90"

    def tearDown(self):
        self.config_patcher.stop()
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)
        tesla_solar_manager.CACHE_PATH = self.original_cache_path
        
        for key in ["MOCK_VEHICLE_HOME", "MOCK_VEHICLE_PLUGGED", "MOCK_VEHICLE_SOC", "MOCK_VEHICLE_CHARGE_LIMIT"]:
            if key in os.environ:
                del os.environ[key]

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_sunrise_reset(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        sunrise_time = dt(2026, 6, 21, 8, 0, 0, tzinfo=tz) # morning (after sunrise)
        
        # Initialize cache without sunrise reset date
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": 0.0,
                "longitude": 0.0,
                "charging_state": "Disconnected",
                "battery_level": 40,
                "charge_limit_soc": 80
            },
            "last_sunrise_reset_date": "2026-06-20",
            "last_telemetry_check_time": sunrise_time.isoformat()
        })
        
        # Run solar loop
        tesla_solar_manager.run_solar_loop(override_time=sunrise_time, mock_power=-500.0) # insufficient power -> no charge command
        
        # Verify that state reset to home coordinates and plugged in (Stopped)
        cache = tesla_solar_manager.read_cache()
        self.assertEqual(cache["last_sunrise_reset_date"], "2026-06-21")
        self.assertEqual(cache["vehicle_state"]["latitude"], 0.0)
        self.assertEqual(cache["vehicle_state"]["longitude"], 0.0)
        self.assertEqual(cache["vehicle_state"]["charging_state"], "Disconnected")
        # Kept the old battery state from cached state
        self.assertEqual(cache["vehicle_state"]["battery_level"], 40)
        self.assertEqual(cache["vehicle_state"]["charge_limit_soc"], 80)
        
        # Assert no telemetry calls were made (since no target action change occurred)
        mock_get_vehicle_data.assert_not_called()

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_saved_state_insufficient_solar_no_api_calls(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        
        # Setup initial cache showing car is home/plugged but currently not charging
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Stopped",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21",
            "last_telemetry_check_time": midday_time.isoformat()
        })
        
        # Run loop with low power (100W excess) -> calculated state is still not charging -> no change
        tesla_solar_manager.run_solar_loop(override_time=midday_time, mock_power=-100.0)
        
        # Assert no calls to get_tesla_vehicle_data
        mock_get_vehicle_data.assert_not_called()

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_saved_state_triggers_api_call_on_action_change(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        
        # Mock telemetry to return home/plugged state
        mock_get_vehicle_data.return_value = {
            "latitude": self.test_config["LATITUDE"],
            "longitude": self.test_config["LONGITUDE"],
            "charging_state": "Stopped",
            "battery_level": 75,
            "charge_limit_soc": 90
        }
        
        # Cache has car home/plugged, not charging
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Stopped",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21"
        })
        
        # Run loop with high surplus (4000W excess) -> calculated target is to start charging -> indicates a change
        tesla_solar_manager.run_solar_loop(override_time=midday_time, mock_power=-4000.0)
        
        # Assert live telemetry WAS queried to confirm state
        mock_get_vehicle_data.assert_called_once()
        
        cache = tesla_solar_manager.read_cache()
        self.assertTrue(cache["charging"])
        self.assertEqual(cache["amps"], 16) # (4000 - 150) // 240 = 16A

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_unplugged_telemetry_rate_limit(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        time_1 = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        time_2 = dt(2026, 6, 21, 12, 5, 0, tzinfo=tz) # 5 mins later (under 10 min throttle)
        time_3 = dt(2026, 6, 21, 12, 11, 0, tzinfo=tz) # 11 mins later (exceeds 10 min throttle)
        
        mock_get_vehicle_data.return_value = {
            "latitude": self.test_config["LATITUDE"],
            "longitude": self.test_config["LONGITUDE"],
            "charging_state": "Disconnected",
            "battery_level": 75,
            "charge_limit_soc": 90
        }
        
        # Cache shows vehicle is unplugged ("Disconnected")
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Disconnected",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21",
            "last_telemetry_check_time": None
        })
        
        # 1. Run at time_1 with high surplus. Throttling is inactive (no last check time). It should query Tesla.
        tesla_solar_manager.run_solar_loop(override_time=time_1, mock_power=-4000.0)
        self.assertEqual(mock_get_vehicle_data.call_count, 1)
        
        # 2. Run at time_2 with high surplus. Less than 10 mins since last check. It should NOT query Tesla.
        tesla_solar_manager.run_solar_loop(override_time=time_2, mock_power=-4000.0)
        self.assertEqual(mock_get_vehicle_data.call_count, 1) # Still 1
        
        # 3. Run at time_3 with high surplus. More than 10 mins since last check. It SHOULD query Tesla again.
        tesla_solar_manager.run_solar_loop(override_time=time_3, mock_power=-4000.0)
        self.assertEqual(mock_get_vehicle_data.call_count, 2)

    @patch('requests.post')
    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_dry_run_command_bypassing(self, mock_get_vehicle_data, mock_post):
        # Setup config
        self.test_config["DRY_RUN"] = True
        self.test_config["MOCK_TESLA"] = False # Real mode
        
        # Telemetry is mocked for loop gating
        mock_get_vehicle_data.return_value = {
            "latitude": self.test_config["LATITUDE"],
            "longitude": self.test_config["LONGITUDE"],
            "charging_state": "Stopped",
            "battery_level": 75,
            "charge_limit_soc": 90
        }
        
        # Cache setup
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Stopped",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21"
        })
        
        # Run loop with high power (charging start change indicated)
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        tesla_solar_manager.run_solar_loop(override_time=midday_time, mock_power=-4000.0)
        
        # Verify that requests.post was NOT called because DRY_RUN is active
        mock_post.assert_not_called()
        
        # Verify that the cache still registers charging=True since the command was successfully simulated
        cache = tesla_solar_manager.read_cache()
        self.assertTrue(cache["charging"])
        self.assertEqual(cache["amps"], 16)

    @patch('tesla_solar_manager.update_env_file')
    @patch('requests.post')
    def test_refresh_tesla_token_success(self, mock_post, mock_update_env):
        # Configure mock response for refresh
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token_123",
            "refresh_token": "new_refresh_token_123"
        }
        mock_post.return_value = mock_response

        config = {
            "TESLA_REFRESH_TOKEN": "old_refresh",
            "TESLA_CLIENT_ID": "client_id",
            "TESLA_CLIENT_SECRET": "client_secret"
        }

        success = tesla_solar_manager.refresh_tesla_token(config)
        self.assertTrue(success)
        self.assertEqual(config["TESLA_API_TOKEN"], "new_access_token_123")
        self.assertEqual(config["TESLA_REFRESH_TOKEN"], "new_refresh_token_123")
        mock_update_env.assert_any_call("TESLA_API_TOKEN", "new_access_token_123")
        mock_update_env.assert_any_call("TESLA_REFRESH_TOKEN", "new_refresh_token_123")

    @patch('tesla_solar_manager.refresh_tesla_token')
    @patch('requests.get')
    def test_get_tesla_vehicle_data_auth_retry(self, mock_get, mock_refresh):
        # First call returns 401, second call returns 200
        mock_response_401 = MagicMock()
        mock_response_401.status_code = 401
        
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "response": {
                "drive_state": {"latitude": 10.0, "longitude": 20.0},
                "charge_state": {"charging_state": "Charging", "battery_level": 80, "charge_limit_soc": 90}
            }
        }
        
        mock_get.side_effect = [mock_response_401, mock_response_200]
        mock_refresh.return_value = True

        config = {
            "TESLA_VIN": "test_vin",
            "TESLA_API_TOKEN": "expired_token",
            "MOCK_TESLA": False
        }

        data = tesla_solar_manager.get_tesla_vehicle_data(config)
        self.assertIsNotNone(data)
        self.assertEqual(data["charging_state"], "Charging")
        self.assertEqual(mock_refresh.call_count, 1)
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            "https://fleet-api.prd.na.vn.cloud.tesla.com/api/1/vehicles/test_vin/vehicle_data?endpoints=location_data%3Bcharge_state%3Bdrive_state%3Bvehicle_state",
            headers=unittest.mock.ANY,
            timeout=15
        )

    @patch('requests.post')
    def test_wake_up_vehicle_success(self, mock_post):
        # First call: state = waking, second call: state = online
        mock_resp_1 = MagicMock()
        mock_resp_1.status_code = 200
        mock_resp_1.json.return_value = {"response": {"state": "waking"}}
        
        mock_resp_2 = MagicMock()
        mock_resp_2.status_code = 200
        mock_resp_2.json.return_value = {"response": {"state": "online"}}
        
        mock_post.side_effect = [mock_resp_1, mock_resp_2]
        
        config = {
            "TESLA_VIN": "test_vin",
            "TESLA_API_TOKEN": "token",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com"
        }
        
        success = tesla_solar_manager.wake_up_vehicle(config, max_attempts=5, delay_seconds=0.01)
        self.assertTrue(success)
        self.assertEqual(mock_post.call_count, 2)

    @patch('requests.post')
    def test_wake_up_vehicle_failure(self, mock_post):
        # All calls return offline
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": {"state": "offline"}}
        mock_post.return_value = mock_resp
        
        config = {
            "TESLA_VIN": "test_vin",
            "TESLA_API_TOKEN": "token",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com"
        }
        
        success = tesla_solar_manager.wake_up_vehicle(config, max_attempts=3, delay_seconds=0.01)
        self.assertFalse(success)
        self.assertEqual(mock_post.call_count, 3)

    @patch('tesla_solar_manager.wake_up_vehicle')
    @patch('requests.get')
    def test_get_tesla_vehicle_data_with_wake_up_success(self, mock_get, mock_wake):
        # Initial get: 408 (offline)
        mock_resp_offline = MagicMock()
        mock_resp_offline.status_code = 408
        mock_resp_offline.text = '{"error":"vehicle unavailable: vehicle is offline or asleep"}'
        mock_resp_offline.json.return_value = {"error": "vehicle unavailable: vehicle is offline or asleep"}
        
        # Second get (after wake up): 200 (success)
        mock_resp_success = MagicMock()
        mock_resp_success.status_code = 200
        mock_resp_success.json.return_value = {
            "response": {
                "drive_state": {"latitude": 10.0, "longitude": 20.0},
                "charge_state": {"charging_state": "Stopped", "battery_level": 80, "charge_limit_soc": 90}
            }
        }
        
        mock_get.side_effect = [mock_resp_offline, mock_resp_success]
        mock_wake.return_value = True
        
        config = {
            "TESLA_VIN": "test_vin",
            "TESLA_API_TOKEN": "token",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com",
            "MOCK_TESLA": False
        }
        
        data = tesla_solar_manager.get_tesla_vehicle_data(config)
        self.assertIsNotNone(data)
        self.assertEqual(data["charging_state"], "Stopped")
        mock_wake.assert_called_once()
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            "https://fleet-api.prd.na.vn.cloud.tesla.com/api/1/vehicles/test_vin/vehicle_data?endpoints=location_data%3Bcharge_state%3Bdrive_state%3Bvehicle_state",
            headers=unittest.mock.ANY,
            timeout=15
        )

    @patch('tesla_solar_manager.print')
    def test_is_vehicle_at_home_diagnostics(self, mock_print):
        home_lat = -33.8688
        home_lon = 151.2093
        tolerance = 0.001
        
        # Vehicle is away
        at_home = tesla_solar_manager.is_vehicle_at_home(
            -33.9000, 151.2000, home_lat, home_lon, tolerance
        )
        self.assertFalse(at_home)
        # Ensure print was called with proximity failure message
        mock_print.assert_called_once()
        print_arg = mock_print.call_args[0][0]
        self.assertIn("Vehicle Proximity Check Failed", print_arg)
        self.assertIn("Est. Distance", print_arg)

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_unplugged_telemetry_rate_limit_when_full(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        time_1 = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        time_2 = dt(2026, 6, 21, 12, 30, 0, tzinfo=tz) # 30 mins later (under 60 min throttle)
        time_3 = dt(2026, 6, 21, 13, 1, 0, tzinfo=tz) # 61 mins later (exceeds 60 min throttle)
        
        mock_get_vehicle_data.return_value = {
            "latitude": self.test_config["LATITUDE"],
            "longitude": self.test_config["LONGITUDE"],
            "charging_state": "Disconnected",
            "battery_level": 90,
            "charge_limit_soc": 90
        }
        
        # Cache shows vehicle is unplugged ("Disconnected") and full
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Disconnected",
                "battery_level": 90,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21",
            "last_telemetry_check_time": None
        })
        
        # 1. Run at time_1 with high surplus. Throttling is inactive. It should query Tesla.
        tesla_solar_manager.run_solar_loop(override_time=time_1, mock_power=-4000.0)
        self.assertEqual(mock_get_vehicle_data.call_count, 1)
        
        # Update cache to show vehicle state returned full
        cache = tesla_solar_manager.read_cache()
        cache["vehicle_state"]["battery_level"] = 90
        cache["vehicle_state"]["charge_limit_soc"] = 90
        tesla_solar_manager.write_cache(cache)
        
        # 2. Run at time_2 with high surplus. 30 mins since last check. Full car -> Throttled. It should NOT query Tesla.
        tesla_solar_manager.run_solar_loop(override_time=time_2, mock_power=-4000.0)
        self.assertEqual(mock_get_vehicle_data.call_count, 1) # Still 1
        
        # 3. Run at time_3 with high surplus. 61 mins since last check. Exceeds 60 min throttle -> It SHOULD query Tesla.
        tesla_solar_manager.run_solar_loop(override_time=time_3, mock_power=-4000.0)
        self.assertEqual(mock_get_vehicle_data.call_count, 2)

    @patch('tesla_solar_manager.requests.get')
    @patch('tesla_solar_manager.refresh_tesla_token')
    def test_get_tesla_vehicle_data_no_wake_up_when_asleep(self, mock_refresh, mock_get):
        # Setup real implementation (MOCK_TESLA = False)
        config = self.test_config.copy()
        config["MOCK_TESLA"] = False
        config["TESLA_API_TOKEN"] = "token"
        config["TESLA_VIN"] = "vin"
        
        # Mock response for /vehicle_data to return asleep/offline error
        mock_response = MagicMock()
        mock_response.status_code = 408
        mock_response.json.return_value = {"error": "vehicle unavailable: vehicle is offline or asleep"}
        mock_response.text = '{"error": "vehicle unavailable: vehicle is offline or asleep"}'
        mock_get.return_value = mock_response
        
        # Query with allow_wake_up = False
        data = tesla_solar_manager.get_tesla_vehicle_data(config, allow_wake_up=False)
        
        # Verify it returns {"asleep": True} and does not wake up the car
        self.assertEqual(data, {"asleep": True})

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_solar_loop_zero_surplus_inaction_skips_cloud_telemetry(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        
        # Cache shows vehicle is home but not charging
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Disconnected",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21"
        })
        
        # Run solar loop with low/insufficient power (100W excess) -> Zero surplus inaction
        tesla_solar_manager.run_solar_loop(override_time=midday_time, mock_power=100.0)
        
        # Assert get_tesla_vehicle_data was NOT called at all (Rule 1: Zero-Surplus Inaction)
        mock_get_vehicle_data.assert_not_called()

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_solar_loop_stale_telemetry_check_unplugged_no_wake_up(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        
        mock_get_vehicle_data.return_value = {"asleep": True}
        
        # Cache shows vehicle is unplugged ("Disconnected") and not charging
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Disconnected",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21"
        })
        
        # Run solar loop with high power (4000W surplus). Since vehicle was disconnected, allow_wake_up must be False!
        tesla_solar_manager.run_solar_loop(override_time=midday_time, mock_power=-4000.0)
        
        mock_get_vehicle_data.assert_called_once_with(mock_get_vehicle_data.call_args[0][0], allow_wake_up=False)
        cache = tesla_solar_manager.read_cache()
        self.assertEqual(cache["last_telemetry_check_time"], midday_time.isoformat())

    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_solar_loop_sync_live_charging_state(self, mock_get_vehicle_data):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        
        # Mock get_tesla_vehicle_data to return actively charging state
        mock_get_vehicle_data.return_value = {
            "latitude": self.test_config["LATITUDE"],
            "longitude": self.test_config["LONGITUDE"],
            "charging_state": "Charging",
            "battery_level": 75,
            "charge_limit_soc": 90
        }
        
        # Cache shows vehicle is Disconnected and not charging
        tesla_solar_manager.write_cache({
            "charging": False,
            "amps": 5,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Disconnected",
                "battery_level": 75,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21"
        })
        
        # Run solar loop (high surplus)
        tesla_solar_manager.run_solar_loop(override_time=midday_time, mock_power=-5000.0)
        
        # Cache should now show charging = True, vehicle_state = Charging
        cache = tesla_solar_manager.read_cache()
        self.assertTrue(cache["charging"])
        self.assertEqual(cache["vehicle_state"]["charging_state"], "Charging")


class TestWallConnectorIntegration(unittest.TestCase):
    def setUp(self):
        self.original_cache_path = tesla_solar_manager.CACHE_PATH
        tesla_solar_manager.CACHE_PATH = os.path.join(TEST_DIR, "temp_twc_test_cache.json")
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)

        self.config_patcher = patch('tesla_solar_manager.load_config')
        self.mock_load_config = self.config_patcher.start()

        self.test_config = {
            "FRONIUS_IP": "127.0.0.1",
            "FRONIUS_EXPORT_IS_POSITIVE": False,
            "TESLA_WALL_CONNECTOR_IP": "192.168.1.60",
            "MOCK_WALL_CONNECTOR": False,
            "TESLA_VIN": "test_vin",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com",
            "TESLA_API_TOKEN": "token",
            "MOCK_TESLA": True,
            "MOCK_API_FAILURE_RATE": 0.0,
            "DRY_RUN": True,
            "LATITUDE": -33.8688,
            "LONGITUDE": 151.2093,
            "TIMEZONE": "Australia/Sydney",
            "CITY_NAME": "Sydney",
            "VOLTAGE": 240,
            "MIN_AMPS": 5,
            "MAX_AMPS": 32,
            "BUFFER_WATTS": 150,
            "LOCATION_TOLERANCE": 0.001,
            "HISTORY_WINDOW_MINUTES": 10,
            "POLLING_INTERVAL_MINUTES": 2,
            "THROTTLE_INTERVAL_MINUTES": 10,
            "TELEMETRY_REFRESH_MINUTES": 15,
            "WAKE_COOLDOWN_MINUTES": 60
        }
        self.mock_load_config.return_value = self.test_config

    def tearDown(self):
        self.config_patcher.stop()
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)
        tesla_solar_manager.CACHE_PATH = self.original_cache_path

    @patch('tesla_solar_manager.requests.get')
    def test_get_wall_connector_vitals_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "contactor_closed": False,
            "vehicle_connected": True,
            "vehicle_current_a": 0.0,
            "grid_v": 239.5
        }
        mock_get.return_value = mock_resp

        vitals = tesla_solar_manager.get_wall_connector_vitals(self.test_config)
        self.assertIsNotNone(vitals)
        self.assertTrue(vitals["vehicle_connected"])
        self.assertFalse(vitals["contactor_closed"])
        self.assertEqual(vitals["grid_v"], 239.5)

    @patch('tesla_solar_manager.call_tesla_api')
    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_wall_connector_disconnected_bypasses_cloud_calls(self, mock_get_vehicle_data, mock_call_api):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)

        # Mock Wall Connector to return vehicle_connected = False
        mock_twc = {
            "vehicle_connected": False,
            "contactor_closed": False,
            "vehicle_current_a": 0.0,
            "grid_v": 240.0
        }

        # Run loop with high solar surplus (4000W)
        tesla_solar_manager.run_solar_loop(
            override_time=midday_time, 
            mock_power=-4000.0, 
            mock_twc=mock_twc
        )

        # Assert zero Tesla Cloud calls were made!
        mock_get_vehicle_data.assert_not_called()
        mock_call_api.assert_not_called()

        # Cache should remain not charging
        cache = tesla_solar_manager.read_cache()
        self.assertFalse(cache["charging"])

    @patch('tesla_solar_manager.call_tesla_api')
    @patch('tesla_solar_manager.get_tesla_vehicle_data')
    def test_wall_connector_connected_initiates_charge(self, mock_get_vehicle_data, mock_call_api):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)

        mock_twc = {
            "vehicle_connected": True,
            "contactor_closed": False,
            "vehicle_current_a": 0.0,
            "grid_v": 240.0
        }

        mock_get_vehicle_data.return_value = {
            "latitude": self.test_config["LATITUDE"],
            "longitude": self.test_config["LONGITUDE"],
            "charging_state": "Stopped",
            "battery_level": 70,
            "charge_limit_soc": 90
        }
        mock_call_api.return_value = True

        tesla_solar_manager.run_solar_loop(
            override_time=midday_time, 
            mock_power=-4000.0, 
            mock_twc=mock_twc
        )

        # Should query vehicle data and call charge_start and set_charging_amps
        mock_get_vehicle_data.assert_called_once()
        mock_call_api.assert_any_call(self.test_config, "charge_start")
        mock_call_api.assert_any_call(self.test_config, "set_charging_amps", {"charging_amps": 16})

        cache = tesla_solar_manager.read_cache()
        self.assertTrue(cache["charging"])
        self.assertEqual(cache["amps"], 16)

    @patch('tesla_solar_manager.call_tesla_api')
    def test_wall_connector_unplug_during_active_charge(self, mock_call_api):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)

        # Cache shows currently charging
        tesla_solar_manager.write_cache({
            "charging": True,
            "amps": 16,
            "vehicle_state": {
                "latitude": self.test_config["LATITUDE"],
                "longitude": self.test_config["LONGITUDE"],
                "charging_state": "Charging",
                "battery_level": 70,
                "charge_limit_soc": 90
            },
            "last_sunrise_reset_date": "2026-06-21"
        })

        mock_twc = {
            "vehicle_connected": False,
            "contactor_closed": False,
            "vehicle_current_a": 0.0,
            "grid_v": 240.0
        }
        mock_call_api.return_value = True

        tesla_solar_manager.run_solar_loop(
            override_time=midday_time, 
            mock_power=-4000.0, 
            mock_twc=mock_twc
        )

        # Should send charge_stop command
        mock_call_api.assert_called_once_with(self.test_config, "charge_stop")

        cache = tesla_solar_manager.read_cache()
        self.assertFalse(cache["charging"])
        self.assertEqual(cache["vehicle_state"]["charging_state"], "Disconnected")


class TestTelemetryRetryAndTimeout(unittest.TestCase):
    @patch('tesla_solar_manager.time.sleep')
    @patch('tesla_solar_manager.requests.get')
    def test_get_tesla_vehicle_data_retry_on_timeout_response(self, mock_get, mock_sleep):
        config = {
            "MOCK_TESLA": False,
            "TESLA_VIN": "test_vin",
            "TESLA_API_TOKEN": "token",
            "TESLA_API_BASE_URL": "https://fleet-api.prd.na.vn.cloud.tesla.com"
        }
        
        # 1. Mock response returning a timeout error JSON
        mock_resp_timeout = MagicMock()
        mock_resp_timeout.status_code = 504
        mock_resp_timeout.json.return_value = {"error": '{"error": "timeout"}'}
        mock_resp_timeout.text = '{"error": "{\\"error\\": \\"timeout\\"}"}'
        
        # 2. Mock response returning 200 OK
        mock_resp_success = MagicMock()
        mock_resp_success.status_code = 200
        mock_resp_success.json.return_value = {
            "response": {
                "drive_state": {"latitude": 10.0, "longitude": 20.0},
                "charge_state": {"charging_state": "Stopped", "battery_level": 80, "charge_limit_soc": 90}
            }
        }
        
        # Test timeout parsing (should treat as asleep and return {"asleep": True} when allow_wake_up=False)
        mock_get.return_value = mock_resp_timeout
        data = tesla_solar_manager.get_tesla_vehicle_data(config, allow_wake_up=False)
        self.assertEqual(data, {"asleep": True})
        
        # Test retry loop on request exceptions (2 failures, then 1 success)
        import requests
        mock_get.side_effect = [
            requests.exceptions.ConnectTimeout("Connection timed out"),
            requests.exceptions.ReadTimeout("Read timed out"),
            mock_resp_success
        ]
        
        data = tesla_solar_manager.get_tesla_vehicle_data(config, allow_wake_up=False)
        self.assertIsNotNone(data)
        self.assertEqual(data["charging_state"], "Stopped")
        self.assertEqual(mock_get.call_count, 4) # 1 first check + 3 retries
        self.assertEqual(mock_sleep.call_count, 2) # slept twice between retries


if __name__ == '__main__':
    unittest.main()

