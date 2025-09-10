import time
import os
import sys
import sqlite3
from dotenv import load_dotenv
import minimalmodbus

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

ADDRESS = os.getenv("F_ADDRESS")
PRIVATE_KEY = os.getenv("F_PK")
ROLE = "BUY_ONLY"

DB_PATH = "energy_F.db"
SCALE = 1000

# -------------------------------
# Modbus SDM120 setup
# -------------------------------
dev_addr = 26
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
    if row:
        return row[0], row[1]
    return 0.000, 0.000

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
# Loop
# -------------------------------
init_db()

try:
    while True:
        last_gen, last_con = get_last_total()

        # บ้านซื้อ: ผลิต = 0
        total_gen = 0.0
        # ใช้ไฟจาก Modbus
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)

        delta_gen = round(total_gen - last_gen, 5)
        delta_con = round(total_con - last_con, 5)

        save_energy(total_gen, total_con, delta_gen, delta_con)

        net = total_gen - total_con
        print(f"\n🏠 House F → ผลิตรวม {total_gen:.5f}, ใช้รวม {total_con:.5f} = Net {net:.5f} kWh")

        # ส่งค่า delta เข้า contract
        gen_int = int(delta_gen * SCALE)
        con_int = int(delta_con * SCALE)
        report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)

        if net < 0:
            pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net) * SCALE))

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial:
        rs485.serial.close()
