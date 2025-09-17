import time
import os
import sys
import sqlite3
from dotenv import load_dotenv
import minimalmodbus

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, reset_energy  # SELL_ONLY ไม่ต้องจ่าย pay_energy

load_dotenv()

ADDRESS = os.getenv("A_ADDRESS")
PRIVATE_KEY = os.getenv("A_PK")
ROLE = "SELL_ONLY"

DB_PATH = "palm_A.db"
SCALE = 1000  # แปลง float → int (milli-kWh)

# -------------------------------
# Modbus SDM120 setup
# -------------------------------
dev_addr = 11
serial_port = 'COM1'
baudrate = 2400

rs485 = minimalmodbus.Instrument(serial_port, dev_addr)
rs485.serial.baudrate = baudrate
rs485.serial.bytesize = 8
rs485.serial.parity   = minimalmodbus.serial.PARITY_NONE
rs485.serial.stopbits = 1
rs485.serial.timeout  = 0.5
rs485.debug = False
rs485.mode = minimalmodbus.MODE_RTU

# -------------------------------
# SQLite
# -------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS energy_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_generated REAL,
            delta_generated REAL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_last_total():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_generated FROM energy_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0.0

def save_energy(total_gen, delta_gen):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO energy_log (total_generated, delta_generated)
        VALUES (?, ?)
    """, (total_gen, delta_gen))
    conn.commit()
    conn.close()

def init_baseline():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM energy_log")
    row_count = cur.fetchone()[0]
    conn.close()
    if row_count == 0:
        total_gen = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)
        save_energy(total_gen, 0.0)
        print(f"📊 Baseline created → total_gen={total_gen:.5f}")
        return True
    return False

# -------------------------------
# Main loop
# -------------------------------
init_db()
is_first_run = init_baseline()

try:
    while True:
        last_gen = get_last_total()
        total_gen = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)

        delta_gen = round(total_gen - last_gen, 5)

        if delta_gen < 0:
            print("⚠️ Generation meter reset → ใช้ค่าใหม่เป็น baseline")
            delta_gen = 0.0

        save_energy(total_gen, delta_gen)

        print(f"\n🏠 SELL_ONLY → total_gen={total_gen:.5f}, delta_gen={delta_gen:.5f}")

        if is_first_run:
            print("⏩ ข้ามรอบแรก (baseline)")
            is_first_run = False
        else:
            # ✅ ส่งทุกครั้ง แม้ delta_gen = 0
            gen_int = int(delta_gen * SCALE)
            report_energy(ADDRESS, PRIVATE_KEY, gen_int, 0)

            if delta_gen == 0:
                print("ℹ️ บ้านไม่ได้ผลิต → supply บ้านนี้ = 0")
            else:
                print(f"📡 ส่ง delta_gen = {gen_int}")

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial:
        rs485.serial.close()
