# High-Frequency Distributed SNMP Poller & Grapher

A performant, distributed network infrastructure monitoring system optimized for high-frequency polling. The stack uses a multi-threaded Python daemon to poll 64-bit High-Capacity (HC) interface counters every 10 seconds, buffers metrics locally using an optimized SQLite Write-Ahead Log (WAL) layout, and renders classic WinBox-style traffic graphs every 2 minutes using permanent RRDtool data stores to minimize disk I/O.

## Architecture Highlights
* **Dynamic Index Discovery:** Interfaces are declared by their human-readable system names (e.g., `GigabitEthernet0/1`). Numerical SNMP indices are resolved automatically at startup via an initial MIB table walk.
* **Shared-Nothing Edge Sharding:** Optimized to run independently at local edge sites or data centers, protecting your metrics backend against WAN network splits and tracking latency bottlenecks.
* **Pre-allocated RRD Stores:** Eliminates write amplification by utilizing fixed-size round-robin databases on disk, preserving storage endurance.

---

## Prerequisites & Dependencies

The system requires Python 3 and native RRDtool development libraries installed on your host system. 

### Ubuntu / Debian Linux
```bash
sudo apt update
sudo apt install -y rrdtool librrd-dev python3-pip python3-venv
```

### RHEL / Rocky Linux
```bash
sudo dnf install -y epel-release
sudo dnf install -y rrdtool rrdtool-devel python3-pip
```

---

## Installation & Deployment

### 1. File Structure Setup
Create a dedicated application home directory and organize your script resources:

```bash
sudo mkdir -p /opt/snmp
# Copy your poller.py, grapher.py, and config.yaml files into this directory
# Ensure files are owned by the user running the service (e.g., root or a system user)
cd /opt/snmp
```

### 2. Configure Virtual Environment & Python Packages
Isolate dependencies using a localized Python virtual environment:

```bash
sudo python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install pyyaml pysnmp python-rrdtool
```

### 3. Setup Target Configuration (`config.yaml`)
Populate your network infrastructure map. You can completely omit numerical OID indices—use exact string interfaces matching your switch configuration profiles:

```yaml
switches:
  - ip: "192.168.1.10"
    community: "public"
    interfaces:
      - "GigabitEthernet0/1"
      - "GigabitEthernet0/2"
  - ip: "192.168.1.11"
    community: "public"
    interfaces:
      - "TenGigabitEthernet0/1"
```

---

## System Integration Services

### 1. Install Poller Daemon (Systemd)
To handle the 10-second polling cadence smoothly without cron process-spawning overhead, run the poller as a persistent engine service.

Create the service unit layout profile:
```bash
sudo nano /etc/systemd/system/snmp-poller.service
```

Paste the following configurations:
```ini
[Unit]
Description=High-Frequency SNMP Interface Counter Poller Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/snmp
ExecStart=/opt/snmp/venv/bin/python /opt/snmp/poller.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Reload the systemd manager framework, enable the daemon engine to kick off at system startup, and launch the core instance:
```bash
sudo systemctl daemon-reload
sudo systemctl enable snmp-poller.service
sudo systemctl start snmp-poller.service
```

Verify the real-time runtime log stream to ensure initial discovery maps successfully:
```bash
sudo journalctl -u snmp-poller.service -f
```

### 2. Schedule Graph Generator Engine (Cron)
Since rendering visualizations occurs at a standard 2-minute cadence, it remains best handled by a cron configuration script.

Open the system crontab scheduler console:
```bash
sudo crontab -e
```

Append the following configuration target profile line at the bottom of the script:
```text
# Rebuild WinBox style traffic charts every 2 minutes from the incremental RRD engine
*/2 * * * * /opt/snmp/venv/bin/python /opt/snmp/grapher.py > /dev/null 2>&1
```

---

## File System Manifest Targets

Once operational, the working layout path will automatically construct and maintain these structural endpoints:
* `/opt/snmp/snmp_metrics.db` - Active raw high-frequency buffer metric store.
* `/opt/snmp/rrd_storage/` - Directory holding fixed-size permanent network archives (`.rrd`).
* `/opt/snmp/graphs/` - Target outputs containing rendered visualization layout charts (`.png`).



## Other 64-Bit Counters

ifHCInOctets (.1.3.6.1.2.1.31.1.1.1.6)<br>
ifHCOutOctets (1.3.6.1.2.1.31.1.1.1.10)<br>
ifHCInUcastPkts (.1.3.6.1.2.1.31.1.1.1.7)<br>
ifHCOutUcastPkts (.1.3.6.1.2.1.31.1.1.1.11)<br>
ifHCInMulticastPkts (.1.3.6.1.2.1.31.1.1.1.8)<br>	
ifHCOutMulticastPkts (.1.3.6.1.2.1.31.1.1.1.12)<br>
ifHCInBroadcastPkts (.1.3.6.1.2.1.31.1.1.1.9)<br>	
ifHCOutBroadcastPkts (.1.3.6.1.2.1.31.1.1.1.13)<br>
