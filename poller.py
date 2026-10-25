import os
import sqlite3
import time
import queue
import threading
import sys
import yaml
from pysnmp.hlapi import (
    getCmd, nextCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
)

# --- CONFIGURATION & CONSTANTS ---
CONFIG_FILE = "config.yaml"
DB_FILE = "snmp_metrics.db"
NUM_THREADS = 8
INTERVAL = 10  

# MIB OIDs
OID_IF_NAME = "1.3.6.1.2.1.2.2.1.2"
OID_IN_OCTETS_HC = "1.3.6.1.2.1.31.1.1.1.6"   
OID_OUT_OCTETS_HC = "1.3.6.1.2.1.31.1.1.1.10" 


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS port_metrics (
                timestamp INTEGER,
                switch_ip TEXT,
                interface_id INTEGER,
                interface_name TEXT,
                in_octets INTEGER,
                out_octets INTEGER,
                PRIMARY KEY (timestamp, switch_ip, interface_id)
            )
        """)
        conn.commit()


def discover_interface_indexes(ip, community, target_names):
    """Walks the ifName table to build a dynamic mapping of Name -> ifIndex."""
    mapping = {}
    target_set = set(target_names)
    
    # Walk the ifName column
    for error_indication, error_status, error_index, var_binds in nextCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        UdpTransportTarget((ip, 161), timeout=2.0, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(OID_IF_NAME)),
        lexicographicMode=False
    ):
        if error_indication or error_status:
            print(f"[DISCOVERY WARN] SNMP error during walk on {ip}: {error_indication}", file=sys.stderr)
            break
            
        for var_bind in var_binds:
            oid, val = var_bind
            # Extract the index from the end of the OID (e.g., 1.3.6.1.2.1.2.2.1.2.45 -> 45)
            if_index = oid.asTuple()[-1]
            if_name = str(val)
            
            if if_name in target_set:
                mapping[if_name] = if_index
                
    return mapping


def snmp_get_hc_counters(ip, community, if_id):
    try:
        error_indication, error_status, error_index, var_binds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                UdpTransportTarget((ip, 161), timeout=1.0, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity(f"{OID_IN_OCTETS_HC}.{if_id}")),
                ObjectType(ObjectIdentity(f"{OID_OUT_OCTETS_HC}.{if_id}"))
            )
        )
        if error_indication or error_status:
            return None, None
        return int(var_binds[0][1]), int(var_binds[1][1])
    except Exception:
        return None, None


def db_writer_worker(write_queue):
    """Optimized batch-writing SQLite consumer to handle scaling data volume."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Performance tuning for fast concurrent writes
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-64000") # Allocate ~64MB cache memory
    
    batch_size = 50
    batch = []
    
    while True:
        data = write_queue.get()
        if data is None:
            # Commit any remaining items before exiting
            if batch:
                try:
                    cursor.executemany("INSERT OR REPLACE INTO port_metrics VALUES (?, ?, ?, ?, ?, ?)", batch)
                    conn.commit()
                except sqlite3.Error as e:
                    print(f"[DB ERROR] Final batch failed: {e}", file=sys.stderr)
            break
            
        batch.append(data)
        
        # Write to disk in controlled blocks
        if len(batch) >= batch_size:
            try:
                cursor.executemany("INSERT OR REPLACE INTO port_metrics VALUES (?, ?, ?, ?, ?, ?)", batch)
                conn.commit()
            except sqlite3.Error as e:
                print(f"[DB ERROR] Batch commit failed: {e}", file=sys.stderr)
            finally:
                batch = []
                
        write_queue.task_done()
        
    conn.close()
    write_queue.task_done()

def poller_worker(job_queue, write_queue, timestamp):
    while True:
        try:
            job = job_queue.get_nowait()
        except queue.Empty:
            break
            
        in_octets, out_octets = snmp_get_hc_counters(job['switch_ip'], job['community'], job['if_id'])
        if in_octets is not None and out_octets is not None:
            write_queue.put((timestamp, job['switch_ip'], job['if_id'], job['if_name'], in_octets, out_octets))
        job_queue.task_done()


def run_polling_cycle(switch_maps):
    current_timestamp = int(time.time())
    job_queue = queue.Queue()
    write_queue = queue.Queue()
    
    # Populate the runtime execution tracking queues using resolved metadata maps
    for switch_ip, switch_info in switch_maps.items():
        community = switch_info['community']
        for if_name, if_id in switch_info['resolved_indexes'].items():
            job_queue.put({
                'switch_ip': switch_ip,
                'community': community,
                'if_id': if_id,
                'if_name': if_name
            })
            
    if job_queue.empty():
        return
        
    db_thread = threading.Thread(target=db_writer_worker, args=(write_queue,), daemon=True)
    db_thread.start()
    
    threads = []
    for _ in range(min(NUM_THREADS, job_queue.qsize())):
        t = threading.Thread(target=poller_worker, args=(job_queue, write_queue, current_timestamp))
        t.start()
        threads.append(t)
        
    job_queue.join()
    write_queue.join()
    write_queue.put(None)
    write_queue.join()


def load_and_resolve_config():
    """Loads configuration and dynamically resolves interface IDs from names via SNMP walk."""
    if not os.path.exists(CONFIG_FILE):
        print(f"Config file {CONFIG_FILE} missing.", file=sys.stderr)
        return None

    with open(CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f)

    switch_maps = {}
    for switch in config.get('switches', []):
        ip = switch['ip']
        community = switch['community']
        target_interfaces = switch.get('interfaces', [])
        
        print(f"[DISCOVERY] Mapping interface indexes for switch {ip}...")
        resolved = discover_interface_indexes(ip, community, target_interfaces)
        
        # Log any requested interfaces that failed the lookup validation
        for target in target_interfaces:
            if target not in resolved:
                print(f"[WARN] Interface '{target}' not found or unreachable on {ip}", file=sys.stderr)
                
        switch_maps[ip] = {
            'community': community,
            'resolved_indexes': resolved
        }
    return switch_maps


def main():
    init_db()
    print("SNMP daemon poller initialized.", flush=True)
    
    # Map infrastructure constraints once during the initial script wake phase
    switch_maps = load_and_resolve_config()
    if not switch_maps:
        print("Initial configuration processing failed. Exiting.", file=sys.stderr)
        return

    next_wake = time.monotonic()
    
    while True:
        next_wake += INTERVAL
        run_polling_cycle(switch_maps)
        
        sleep_time = next_wake - time.monotonic()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            next_wake = time.monotonic()


if __name__ == "__main__":
    main()
