import time
import os
import sys
import sqlite3
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

ADDRESS = os.getenv("G_ADDRESS")       # บ้าน C เป็น BUY_ONLY
PRIVATE_KEY = os.getenv("G_PK")
ROLE = "BUY_ONLY"

DB_PATH = "energy_G.db"
SCALE = 1000  # แปลง float → int สำหรับ smart contract (milli-kWh)

# -------------------------------
# สร้างตาราง SQLite
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

# -------------------------------
# อ่านค่าล่าสุดจาก DB
# -------------------------------
def get_last_total():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_generated, total_consumed FROM energy_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return 0.000, 0.000  # เริ่มจาก 0 ถ้า DB ว่าง

# -------------------------------
# บันทึกค่าลง DB
# -------------------------------
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
# เริ่มทำงาน
# -------------------------------
init_db()

try:
    while True:
        last_gen, last_con = get_last_total()

        # บ้านซื้อ: ผลิต = 0, ใช้เพิ่ม 0.002 kWh ทุก 5 นาที
        new_gen = last_gen
        new_con = round(last_con + 0.002, 3)

        delta_gen = 0.000
        delta_con = round(new_con - last_con, 3)

        # บันทึกลง DB
        save_energy(new_gen, new_con, delta_gen, delta_con)

        net = new_gen - new_con  # สำหรับ log
        print(f"\n🏠 House G → ผลิตรวม {new_gen:.3f}, ใช้รวม {new_con:.3f} = Net {net:.3f} kWh")

        # ส่งค่า delta เข้า contract (gen=0, con>0)
        gen_int = int(delta_gen * SCALE)
        con_int = int(delta_con * SCALE)

        report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)

        # ถ้าใช้เกินที่มี ต้องจ่าย token
        if net < 0:
            pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net) * SCALE))

        time.sleep(300)  # 5 นาที

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรมแล้ว → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
