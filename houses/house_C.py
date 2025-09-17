# เหมือนบ้าน A แต่ delta_con เพิ่มทุกรอบ
import time, os, sys, sqlite3
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

ADDRESS = os.getenv("C_ADDRESS")
PRIVATE_KEY = os.getenv("C_PK")
ROLE = "PROSUMER"
DB_PATH = "energy_C.db"
SCALE = 1000

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
    return 0.0, 0.0

def save_energy(total_gen, total_con, delta_gen, delta_con):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO energy_log (total_generated, total_consumed, delta_generated, delta_consumed)
        VALUES (?, ?, ?, ?)
    """, (total_gen, total_con, delta_gen, delta_con))
    conn.commit()
    conn.close()

def init_baseline():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM energy_log")
    row_count = cur.fetchone()[0]
    conn.close()
    if row_count == 0:
        baseline_gen = 0.0
        baseline_con = 0.0
        save_energy(baseline_gen, baseline_con, 0.0, 0.0)
        print(f"📊 Baseline ถูกสร้าง → total_gen={baseline_gen}, total_con={baseline_con}")
        return True
    return False

# -------------------------------
init_db()
is_first_run = init_baseline()

try:
    while True:
        last_gen, last_con = get_last_total()

        # ตัวอย่างจำลองการผลิต/ใช้
        new_gen = round(last_gen + 0.002, 3)
        new_con = round(last_con + 0.001, 3)

        delta_gen = round(new_gen - last_gen, 3)
        delta_con = round(new_con - last_con, 3)

        save_energy(new_gen, new_con, delta_gen, delta_con)

        net = delta_gen - delta_con
        print(f"\n🏠 House C → ผลิต {delta_gen:.3f}, ใช้ {delta_con:.3f} = Net {net:.3f} kWh")

        if is_first_run:
            print("⏩ ข้ามรอบแรก (baseline) → ไม่ส่งค่าเข้า contract")
            is_first_run = False
        else:
            gen_int = int(delta_gen * SCALE)
            con_int = int(delta_con * SCALE)
            report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)

            if net < 0:
                pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net) * SCALE))

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
