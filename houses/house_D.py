import time
import os
import sys
import sqlite3
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

ADDRESS = os.getenv("D_ADDRESS")
PRIVATE_KEY = os.getenv("D_PK")
ROLE = "PROSUMER"

DB_PATH = "energy_D.db"

# ✅ scale factor เก็บ 3 ตำแหน่งทศนิยม
SCALE = 1000

# ✅ สร้างตารางถ้ายังไม่มี
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

# ✅ อ่านค่าล่าสุดจาก DB
def get_last_total():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_generated, total_consumed FROM energy_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return 0.000, 0.000  # เริ่มจาก 0 ถ้า DB ว่าง

# ✅ บันทึกค่าลง DB
def save_energy(total_gen, total_con, delta_gen, delta_con):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO energy_log (total_generated, total_consumed, delta_generated, delta_consumed)
        VALUES (?, ?, ?, ?)
    """, (total_gen, total_con, delta_gen, delta_con))
    conn.commit()
    conn.close()

# 🚀 เริ่มทำงาน
init_db()

try:
    while True:
        last_gen, last_con = get_last_total()

        # ✅ เพิ่มไฟทีละ 0.002, ใช้ไฟทีละ 0.001
        new_gen = round(last_gen + 0.002, 3)
        new_con = round(last_con + 0.001, 3)

        delta_gen = round(new_gen - last_gen, 3)
        delta_con = round(new_con - last_con, 3)

        # บันทึกลง DB (เก็บ float)
        save_energy(new_gen, new_con, delta_gen, delta_con)

        net = delta_gen - delta_con
        print(f"\n🏠 House D → ผลิต {delta_gen:.3f}, ใช้ {delta_con:.3f} = Net {net:.3f} kWh")

        # ✅ ส่งค่าเป็น int (milli-kWh) เข้า contract
        gen_int = int(delta_gen * SCALE)
        con_int = int(delta_con * SCALE)

        report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)

        if net < 0:
            pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net) * SCALE))

        time.sleep(300)  # 5 นาที

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรมแล้ว → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
