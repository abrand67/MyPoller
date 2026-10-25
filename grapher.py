import os
import sqlite3
import sys
import rrdtool

# --- CONFIGURATION ---
DB_FILE = "snmp_metrics.db"
RRD_DIR = "rrd_storage"
OUTPUT_DIR = "graphs"


def init_db_indices():
    """Ensures composite indices exist on SQLite to guarantee fast lookup performance."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # This composite index speeds up query execution for distinct port groups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_switch_port_ts 
            ON port_metrics (switch_ip, interface_id, timestamp)
        """)
        conn.commit()


def fetch_unique_interfaces():
    """Retrieves all unique switch/interface targets discovered in the database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT switch_ip, interface_id, interface_name FROM port_metrics")
        return cursor.fetchall()


def ensure_rrd_exists(rrd_path, start_timestamp):
    """Creates a permanent, fixed-size round-robin archive if it doesn't exist yet."""
    if not os.path.exists(rrd_path):
        try:
            # Pre-allocates fixed space on disk exactly once
            rrdtool.create(
                rrd_path,
                "--start", str(start_timestamp - 1),
                "--step", "10",                # Configured for 10-second metric steps
                "DS:in:COUNTER:30:U:U",       # Heartbeat gives a 30s grace window
                "DS:out:COUNTER:30:U:U",
                "RRA:AVERAGE:0.5:1:17280"     # Stores up to 48 hours of high-resolution tracking
            )
            print(f"[RRD INITIALIZED] Created file: {rrd_path}")
        except rrdtool.error as e:
            print(f"[RRD CREATE ERROR] Failed initialization: {e}", file=sys.stderr)


def process_interface_metrics(switch_ip, if_id, if_name):
    """Processes incremental database updates and builds the traffic graph."""
    os.makedirs(RRD_DIR, exist_ok=True)
    rrd_path = os.path.join(RRD_DIR, f"{switch_ip}_if{if_id}.rrd")
    
    # 1. Determine the latest record timestamp inside the RRD archive
    try:
        last_update = rrdtool.last(rrd_path)
    except rrdtool.error:
        last_update = 0

    # 2. Extract only incremental data rows newer than the archive's marker
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, in_octets, out_octets 
            FROM port_metrics 
            WHERE switch_ip = ? AND interface_id = ? AND timestamp > ?
            ORDER BY timestamp ASC
        """, (switch_ip, if_id, last_update))
        rows = cursor.fetchall()
        
    if not rows:
        # No new data points available yet for this polling window
        return

    # 3. Bootstrap the file if this is the first execution path
    if last_update == 0:
        ensure_rrd_exists(rrd_path, rows[0][0])

    # 4. Stream new metrics to the permanent archive
    for row in rows:
        ts, in_oct, out_oct = row
        try:
            rrdtool.update(rrd_path, f"{ts}:{in_oct}:{out_oct}")
        except rrdtool.error:
            # Safeguard against out-of-order timestamps or duplicate points
            continue
            
    # 5. Render the graph file using the optimized RRD backend
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    graph_path = os.path.join(OUTPUT_DIR, f"{switch_ip}_if{if_id}.png")
    
    # Define a rolling window looking back over the last 1 hour of history
    end_time = rows[-1][0]
    start_view = end_time - 3600 

    try:
        rrdtool.graph(
            graph_path,
            "--start", str(start_view),
            "--end", str(end_time),
            f"--title=Traffic Profile: {switch_ip} - {if_name}",
            "--vertical-label=Bits per Second",
            "--width=650",
            "--height=200",
            "--anti-aliasing", "all",
            
            # Classic Mikrotik WinBox Visual Style Palette
            "--color", "BACK#D4D0C8",       # Frame Background
            "--color", "CANVAS#FFFFFF",     # Plot Grid Area Background
            "--color", "GRID#B0B0B0",       # Grid Lines
            "--color", "MGRID#808080",      # Major Grid Markings
            "--color", "FONT#000000",       # Typography
            
            f"DEF:in_bytes={rrd_path}:in:AVERAGE",
            f"DEF:out_bytes={rrd_path}:out:AVERAGE",
            "CDEF:in_bits=in_bytes,8,*",
            "CDEF:out_bits=out_bytes,8,*",
            
            # RX / Inbound Layout (Red Background Fill with Distinct Border Line)
            "AREA:in_bits#FFC0C0:rx (bit/s)",
            "LINE1:in_bits#CC0000",
            
            # TX / Outbound Layout (Semi-Transparent Purple Overlay Layer)
            "AREA:out_bits#C0A0E080:tx (bit/s)",
            "LINE1:out_bits#660099",
            
            # Value Outputs matching legend typography rules
            "GPRINT:in_bits:LAST:Current Rx\\: %6.2lf %sBps",
            "GPRINT:in_bits:MAX:Max Rx\\: %6.2lf %sBps\\j",
            "GPRINT:out_bits:LAST:Current Tx\\: %6.2lf %sBps",
            "GPRINT:out_bits:MAX:Max Tx\\: %6.2lf %sBps\\j"
        )
    except rrdtool.error as e:
        print(f"[GRAPH ERROR] Failed rendering {graph_path}: {e}", file=sys.stderr)


def main():
    if not os.path.exists(DB_FILE):
        print(f"Database target '{DB_FILE}' not found. Run your poller script first.", file=sys.stderr)
        return
        
    init_db_indices()
    targets = fetch_unique_interfaces()
    
    for switch_ip, if_id, if_name in targets:
        process_interface_metrics(switch_ip, if_id, if_name)


if __name__ == "__main__":
    main()
