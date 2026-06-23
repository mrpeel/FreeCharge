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
from unittest.mock import patch

# Import functions to test
import tesla_solar_manager

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TEST_DIR)

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
            "solar_history": [{"timestamp": "2026-06-21T12:00:00", "watts": 3000}]
        }
        tesla_solar_manager.write_cache(test_state)
        read_state = tesla_solar_manager.read_cache()
        self.assertEqual(read_state, test_state)


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
    @classmethod
    def setUpClass(cls):
        # Find an open port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        cls.port = s.getsockname()[1]
        s.close()

        # Start mock HTTP server
        cls.server = http.server.HTTPServer(('127.0.0.1', cls.port), MockFroniusAPIHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def setUp(self):
        self.original_cache_path = tesla_solar_manager.CACHE_PATH
        tesla_solar_manager.CACHE_PATH = os.path.join(TEST_DIR, "temp_e2e_state_cache.json")
        if os.path.exists(tesla_solar_manager.CACHE_PATH):
            os.remove(tesla_solar_manager.CACHE_PATH)

        # Set up env mocks and test config override
        self.config_patcher = patch('tesla_solar_manager.load_config')
        self.mock_load_config = self.config_patcher.start()
        
        self.test_config = {
            "FRONIUS_IP": f"127.0.0.1:{self.port}",
            "FRONIUS_EXPORT_IS_POSITIVE": False,
            "TESLA_VIN": "5YJ3TESTINGVIN123",
            "TESLA_API_TOKEN": "mock_token",
            "MOCK_TESLA": True,
            "MOCK_API_FAILURE_RATE": 0.0,
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
            "THROTTLE_INTERVAL_MINUTES": 10
        }
        self.mock_load_config.return_value = self.test_config

        # Set default gating mock variables
        os.environ["MOCK_VEHICLE_HOME"] = "True"
        os.environ["MOCK_VEHICLE_PLUGGED"] = "True"
        os.environ["MOCK_VEHICLE_SOC"] = "75"
        os.environ["MOCK_VEHICLE_CHARGE_LIMIT"] = "90"

    def tearDown(self):
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
        MockFroniusAPIHandler.grid_power = -3000.0
        
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
        tesla_solar_manager.write_cache({"charging": True, "amps": 10, "last_command_time": None, "solar_history": []})

        tesla_solar_manager.run_solar_loop(override_time=midday_time)

        updated_cache = tesla_solar_manager.read_cache()
        self.assertFalse(updated_cache["charging"])

    def test_e2e_solar_loop_throttling_behavior(self):
        tz = ZoneInfo(self.test_config["TIMEZONE"])
        midday_time_1 = dt(2026, 6, 21, 12, 0, 0, tzinfo=tz)
        midday_time_2 = dt(2026, 6, 21, 12, 4, 0, tzinfo=tz) # 4 minutes later (under the 10 min throttle)

        # 1. Trigger first change: starts charging at 11A
        MockFroniusAPIHandler.grid_power = -3000.0
        tesla_solar_manager.run_solar_loop(override_time=midday_time_1)
        
        cache_1 = tesla_solar_manager.read_cache()
        self.assertTrue(cache_1["charging"])
        self.assertEqual(cache_1["amps"], 11)
        last_time_1 = cache_1["last_command_time"]

        # 2. Trigger second change: export spikes to 8000W (calculated 32A) but running only 4 mins later
        MockFroniusAPIHandler.grid_power = -8000.0
        tesla_solar_manager.run_solar_loop(override_time=midday_time_2)

        # Cache should STILL show 11A due to throttle blocking command
        cache_2 = tesla_solar_manager.read_cache()
        self.assertTrue(cache_2["charging"])
        self.assertEqual(cache_2["amps"], 11) # Unchanged!
        self.assertEqual(cache_2["last_command_time"], last_time_1)


if __name__ == '__main__':
    unittest.main()
