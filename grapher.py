import os
import sqlite3
import rrdtool

DB_FILE = "snmp_metrics.db"
OUTPUT_DIR = "graphs"


def fetch_unique_interfaces():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT switch_ip, interface_id, interface_name FROM port_metrics")
        return cursor.fetchall()


def generate_graph(switch_ip, interface_id, interface_name):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, in_octets, out_octets 
            FROM port_metrics 
            WHERE switch_ip = ? AND interface_id = ? 
            ORDER BY timestamp ASC
        """, (switch_ip, interface_id))
        rows = cursor.fetchall()
        
    if len(rows) < 2:
        return

    rrd_filename = f"temp_{switch_ip}_{interface_id}.rrd"
    start_time = rows[0][0] - 1
    
    try:
        rrdtool.create(
            rrd_filename,
            "--start", str(start_time),
            "--step", "10",
            "DS:in:COUNTER:30:U:U",
            "DS:out:COUNTER:30:U:U",
            "RRA:AVERAGE:0.5:1:17280"
        )
        
        for row in rows:
            ts, in_oct, out_oct = row
            try:
                rrdtool.update(rrd_filename, f"{ts}:{in_oct}:{out_oct}")
            except rrdtool.error:
                continue
                
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        graph_path = os.path.join(OUTPUT_DIR, f"{switch_ip}_if{interface_id}.png")
        
        rrdtool.graph(
            graph_path,
            "--start", str(rows[0][0]),
            "--end", str(rows[-1][0]),
            f"--title=Traffic Profile: {switch_ip} - {interface_name}",
            "--vertical-label=Bits per Second",
            "--width=650",
            "--height=200",
            "--anti-aliasing", "all",
            
            # Canvas Color Styling (Classic WinBox Palette)
            "--color", "BACK#D4D0C8",       # Frame Background
            "--color", "CANVAS#FFFFFF",     # Plot Grid Area Background
            "--color", "GRID#B0B0B0",       # Grid Lines
            "--color", "MGRID#808080",      # Major Grid Markings
            "--color", "FONT#000000",       # Legend Typography
            
            f"DEF:in_bytes={rrd_filename}:in:AVERAGE",
            f"DEF:out_bytes={rrd_filename}:out:AVERAGE",
            "CDEF:in_bits=in_bytes,8,*",
            "CDEF:out_bits=out_bytes,8,*",
            
            # --- RX / Inbound Traffic (Light Red Fill with Red Line Border) ---
            "AREA:in_bits#FFC0C0:rx (bit/s)",
            "LINE1:in_bits#CC0000",
            
            # --- TX / Outbound Traffic (Transparent Purple Layer over RX) ---
            "AREA:out_bits#C0A0E080:tx (bit/s):STACK", # Added Alpha Channel hex '80' for opacity blending
            "LINE1:out_bits#660099",
            
            # Text Metrics Output Layout
            "GPRINT:in_bits:LAST:Current Rx\\: %6.2lf %sBps",
            "GPRINT:in_bits:MAX:Max Rx\\: %6.2lf %sBps\\j",
            "GPRINT:out_bits:LAST:Current Tx\\: %6.2lf %sBps",
            "GPRINT:out_bits:MAX:Max Tx\\: %6.2lf %sBps\\j"
        )
    finally:
        if os.path.exists(rrd_filename):
            os.remove(rrd_filename)


def main():
    if not os.path.exists(DB_FILE):
        return
    targets = fetch_unique_interfaces()
    for switch_ip, if_id, if_name in targets:
        generate_graph(switch_ip, if_id, if_name)


if __name__ == "__main__":
    main()
