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

DB_PATH = "energy_C.db"
SCALE = 1000  # เก็บ 3 ตำแหน่งทศนิยม → int

# -------------------------------
# Modbus SDM120 setup
# -------------------------------
dev_addr_gen = 13  # Address ของมิเตอร์ฝั่งผลิต
dev_addr_con = 23  # Address ของมิเตอร์ฝั่งใช้
serial_port = 'COM1'
baudrate = 2400

rs485_gen = minimalmodbus.Instrument(serial_port, dev_addr_gen)
rs485_gen.serial.baudrate = baudrate
rs485_gen.serial.bytesize = 8
rs485_gen.serial.parity   = minimalmodbus.serial.PARITY_NONE
rs485_gen.serial.stopbits = 1
rs485_gen.serial.timeout  = 0.5
rs485_gen.debug = False
rs485_gen.mode = minimalmodbus.MODE_RTU

rs485_con = minimalmodbus.Instrument(serial_port, dev_addr_con)
rs485_con.serial.baudrate = baudrate
rs485_con.serial.bytesize = 8
rs485_con.serial.parity   = minimalmodbus.serial.PARITY_NONE
rs485_con.serial.stopbits = 1
rs485_con.serial.timeout  = 0.5
rs485_con.debug = False
rs485_con.mode = minimalmodbus.MODE_RTU

# -------------------------------
# DB functions
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
# Main Loop
# -------------------------------
init_db()

try:
    while True:
        last_gen, last_con = get_last_total()

        # ✅ อ่านค่ารวมจากมิเตอร์
        new_gen = round(rs485_gen.read_float(0x0156, functioncode=4, number_of_registers=2), 3)
        new_con = round(rs485_con.read_float(0x0156, functioncode=4, number_of_registers=2), 3)

        delta_gen = round(new_gen - last_gen, 3)
        delta_con = round(new_con - last_con, 3)

        # ✅ บันทึกลง DB
        save_energy(new_gen, new_con, delta_gen, delta_con)

        net = delta_gen - delta_con
        print(f"\n🏠 House C (PROSUMER) → ผลิต {delta_gen:.3f}, ใช้ {delta_con:.3f} = Net {net:.3f} kWh")

        # ✅ ส่งค่า delta เข้า contract
        gen_int = int(delta_gen * SCALE)
        con_int = int(delta_con * SCALE)
        report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)

        if net < 0:
            pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net) * SCALE))

        time.sleep(300)  # 5 นาที

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485_gen.serial:
        rs485_gen.serial.close()
    if rs485_con.serial:
        rs485_con.serial.close()
