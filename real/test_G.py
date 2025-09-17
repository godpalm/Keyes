import time
import os
import sys
import sqlite3
from dotenv import load_dotenv
import minimalmodbus

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

ADDRESS = os.getenv("G_ADDRESS")
PRIVATE_KEY = os.getenv("G_PK")
ROLE = "BUY_ONLY"

DB_PATH = "energy_G.db"
SCALE = 1000  # แปลง float → int (milli-kWh)

# -------------------------------
# Modbus SDM120 setup
# -------------------------------
dev_addr = 27
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
            total_consumed REAL,
            delta_consumed REAL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_last_total():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_consumed FROM energy_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0.0

def save_energy(total_con, delta_con):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO energy_log (total_consumed, delta_consumed)
        VALUES (?, ?)
    """, (total_con, delta_con))
    conn.commit()
    conn.close()

# -------------------------------
# Main loop
# -------------------------------
init_db()

try:
    while True:
        last_con = get_last_total()
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)

        delta_con = round(total_con - last_con, 5)

        # ป้องกันกรณี meter reset
        if delta_con < 0:
            print("⚠️ Consumption meter reset → ใช้ค่าใหม่เป็น baseline")
            delta_con = 0.0

        save_energy(total_con, delta_con)

        print(f"\n🏠 BUY_ONLY → total_con={total_con:.5f}, delta_con={delta_con:.5f}")

        if delta_con > 0:
            con_int = int(delta_con * SCALE)
            report_energy(ADDRESS, PRIVATE_KEY, 0, con_int)
            pay_energy(ADDRESS, PRIVATE_KEY, con_int)
        else:
            print("ℹ️ ไม่มีการใช้ไฟเพิ่ม → ไม่ส่ง transaction")

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial:
        rs485.serial.close()
