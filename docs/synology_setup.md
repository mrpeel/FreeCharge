# Synology NAS Deployment Guide

This guide explains how to deploy the FreeCharge solar tracker script to a Synology NAS running DSM (DiskStation Manager) using the official Python 3.9 package.

---

## 1. Prerequisites
1. Install **Python 3.9** from the Synology Package Center.
2. Enable SSH on your NAS:
   * Go to **Control Panel** > **Terminal & SNMP** > **Terminal**.
   * Check **Enable SSH service**.
   * Note the port number (default is 22).

---

## 2. Deploy Project Files
Copy the following files from your local workspace to a directory on your Synology NAS (e.g. `/volume1/homes/admin/tesla_tracker` or `/volume1/docker/tesla_tracker`):

* `tesla_solar_manager.py`
* `config.json`
* `requirements.txt`
* `.env.example` (rename to `.env` on your Synology NAS)

You can copy files via File Station, an SMB/AFP shared drive, or SFTP/SCP.

---

## 3. Configure the Virtual Environment via SSH

1. Connect to your Synology NAS via SSH (replace `admin` and `192.168.1.x` with your NAS username and IP):
   ```bash
   ssh admin@192.168.1.x
   ```
2. Navigate to your project folder:
   ```bash
   cd /volume1/homes/admin/tesla_tracker
   ```
3. Create the virtual environment using the Synology Python 3.9 binary:
   ```bash
   python3.9 -m venv env
   ```
4. Activate the environment:
   ```bash
   source env/bin/activate
   ```
5. Install dependencies inside the virtual environment:
   ```bash
   pip install -r requirements.txt
   ```

---

## 4. Environment Variables Configuration
Open the `.env` file on your NAS (using Synology Text Editor or `vi .env` via SSH) and update the values:

```ini
FRONIUS_IP=192.168.1.150  # Your local inverter IP
LATITUDE=-33.8688         # Home latitude
LONGITUDE=151.2093        # Home longitude
TESLA_VIN=5YJ3X...        # Tesla VIN
TESLA_API_TOKEN=...       # Tesla Fleet API access token
MOCK_TESLA=True           # Set to False only when ready for real vehicle updates
```

---

## 5. Create the Scheduler Wrapper Script (`run.sh`)
Create a file named `run.sh` inside `/volume1/homes/admin/tesla_tracker/`:

```bash
#!/bin/bash
cd /volume1/homes/admin/tesla_tracker
source env/bin/activate
python3 tesla_solar_manager.py >> execution.log 2>&1
```

Set executable permissions on the script:
```bash
chmod +x run.sh
```

---

Configure the script to run every 2 minutes automatically to support the rolling average/median calculation:

1. Open **Control Panel** in DSM and click on **Task Scheduler**.
2. Select **Create** > **Scheduled Task** > **User-defined script**.
3. **General**:
   * **Task**: `Tesla Solar Tracker`
   * **User**: `admin` (or the user owning the directory)
4. **Schedule**:
   * **Run on the following days**: *Daily*
   * **Frequency**: *Every 2 minutes* (configure this in the scheduler dropdown to ensure the history logic maintains a high-resolution rolling window)
   * **Active Time**: *06:00 AM to 06:00 PM* (limits processing to daylight hours)
5. **Task Settings**:
   * Under **Run command**, enter:
     ```bash
     /bin/bash /volume1/homes/admin/tesla_tracker/run.sh
     ```
6. Click **OK** to save.

---

## 7. Verification & Logs
* To test the setup immediately, select the task in Task Scheduler and click **Action** > **Run**.
* Open **File Station** and navigate to your folder.
* Inspect `execution.log` to view tracker evaluations, solar calculations, and telemetry gating outcomes.
