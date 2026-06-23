#!/bin/bash
cd /volume1/homes/admin/tesla_tracker
source env/bin/activate
python3 tesla_solar_manager.py >> execution.log 2>&1
