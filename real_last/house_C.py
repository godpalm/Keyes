import time
import os
import sys
import sqlite3
from dotenv import load_dotenv
import minimalmodbus

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

ADDRESS = os.getenv("C_ADDRESS")
PRIVATE_KEY = os.getenv("C_PK")
ROLE = "PROSUMER"

DB_PATH = "palm_C.db"
SCALE = 1000  # แปลง float → int (milli-kWh)

dev_addr_gen = 13
dev_addr_con = 23
serial_port = 'COM1'
baudrate = 2400

rs485 = minimalmodbus.Instrument(serial_port, dev_addr_gen)
rs485.serial.baudrate = baudrate
rs485.serial.bytesize = 8
rs485.serial.parity   = minimalmodbus.serial.PARITY_NONE
rs485.serial.stopbits = 1
rs485.serial.timeout  = 0.5
rs485.debug = False
rs485.mode = minimalmodbus.MODE_RTU

# -------------------------------
# DB
# -------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS energy_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_generated REAL,
            total_consumed REAL,
            delta_generated REAL,
            delta_consumed REAL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_last_total():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_generated, total_consumed FROM energy_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return (row[0], row[1]) if row else (0.0, 0.0)

def save_energy(total_gen, total_con, delta_gen, delta_con):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO energy_log (total_generated, total_consumed, delta_generated, delta_consumed)
        VALUES (?, ?, ?, ?)
    """, (total_gen, total_con, delta_gen, delta_con))
    conn.commit()
    conn.close()

# -------------------------------
# Baseline
# -------------------------------
def init_baseline():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM energy_log")
    row_count = cur.fetchone()[0]
    conn.close()
    
    if row_count == 0:
        try:
            rs485.address = dev_addr_gen
            total_gen = round(rs485.read_float(0x0156, functioncode=4, number_of_registers=2),3)
        except minimalmodbus.NoResponseError:
            total_gen = 0.0
        try:
            rs485.address = dev_addr_con
            total_con = round(rs485.read_float(0x0156, functioncode=4, number_of_registers=2),3)
        except minimalmodbus.NoResponseError:
            total_con = 0.0
        save_energy(total_gen, total_con, 0.0, 0.0)
        print(f"📊 Baseline created → total_gen={total_gen:.3f}, total_con={total_con:.3f}")
        return True
    return False

# -------------------------------
# Main Loop
# -------------------------------
init_db()
is_first_run = init_baseline()

try:
    while True:
        last_gen, last_con = get_last_total()

        try:
            rs485.address = dev_addr_gen
            new_gen = round(rs485.read_float(0x0156, functioncode=4, number_of_registers=2),3)
        except minimalmodbus.NoResponseError:
            new_gen = last_gen

        time.sleep(0.3)

        try:
            rs485.address = dev_addr_con
            new_con = round(rs485.read_float(0x0156, functioncode=4, number_of_registers=2),3)
        except minimalmodbus.NoResponseError:
            new_con = last_con

        delta_gen = round(new_gen - last_gen,3)
        delta_con = round(new_con - last_con,3)

        if delta_gen < 0: delta_gen = 0.0
        if delta_con < 0: delta_con = 0.0

        save_energy(new_gen, new_con, delta_gen, delta_con)

        net = delta_gen - delta_con
        print(f"\n🏠 PROSUMER → ผลิต {delta_gen:.3f}, ใช้ {delta_con:.3f}, Net {net:.3f} kWh")

        gen_int = int(delta_gen * SCALE)
        con_int = int(delta_con * SCALE)

        if is_first_run:
            print("⏩ ข้ามรอบแรก (baseline)")
            is_first_run = False
        else:
            report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)
            if net < 0:
                pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net)*SCALE))
            elif net==0:
                print("ℹ️ บ้านไม่ได้ผลิต → supply บ้านนี้ = 0")

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial: rs485.serial.close()
