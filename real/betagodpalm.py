import time, os, sys, sqlite3
from dotenv import load_dotenv
import minimalmodbus

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy

load_dotenv()

# -------------------------------
# Config per house
# -------------------------------
ADDRESS = os.getenv("A_ADDRESS")
PRIVATE_KEY = os.getenv("A_PK")
ROLE = "SELL_ONLY"

DB_PATH = "energy_A.db"
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
# SQLite functions
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
        total_gen = rs485.read_float(0x0158, functioncode=4, number_of_registers=2) if ROLE != "BUY_ONLY" else 0.0
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2) if ROLE != "SELL_ONLY" else 0.0
        save_energy(total_gen, total_con, 0.0, 0.0)
        print(f"📊 Baseline created → total_gen={total_gen}, total_con={total_con}")
        return True
    return False

# -------------------------------
# Market functions (simplified)
# -------------------------------
market_supply = {}  # key=SELL_ONLY_ADDRESS, value=delta_gen

def update_market_supply(seller_address, delta_gen):
    """SELL_ONLY ส่ง delta_gen → update market_supply"""
    global market_supply
    market_supply[seller_address] = delta_gen

def get_available_energy():
    """รวม supply ทั้งหมด"""
    return sum(market_supply.values())

def match_delta(delta_con):
    """จับคู่ผู้ซื้อกับ market supply"""
    available = get_available_energy()
    actual = min(delta_con, available)
    # ลบ supply ตามสัดส่วน (ง่าย)
    remaining = actual
    for seller in market_supply:
        if market_supply[seller] >= remaining:
            market_supply[seller] -= remaining
            break
        else:
            remaining -= market_supply[seller]
            market_supply[seller] = 0
    return actual

# -------------------------------
# Main loop
# -------------------------------
init_db()
is_first_run = init_baseline()

try:
    while True:
        last_gen, last_con = get_last_total()

        # อ่านไฟจาก Modbus
        total_gen = rs485.read_float(0x0156, functioncode=4, number_of_registers=2) if ROLE != "BUY_ONLY" else 0.0
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2) if ROLE != "SELL_ONLY" else 0.0

        delta_gen = round(total_gen - last_gen, 5)
        delta_con = round(total_con - last_con, 5)

        matched_gen = delta_gen
        matched_con = delta_con

        # -------------------
        # SELL_ONLY → update market
        # -------------------
        if ROLE == "SELL_ONLY":
            update_market_supply(ADDRESS, delta_gen)
        # -------------------
        # BUY_ONLY / PROSUMER → match market
        # -------------------
        elif ROLE in ["BUY_ONLY", "PROSUMER"] and delta_con > 0:
          matched_con = match_delta(delta_con)
          if matched_con == 0:
            print("⚠️ ไม่มี supply ในตลาด → ไม่คิดเงินรอบนี้")


        # บันทึกลง DB
        save_energy(total_gen, total_con, matched_gen, matched_con)

        net = matched_gen - matched_con
        print(f"\n🏠 {ROLE} → total_gen={total_gen:.5f}, total_con={total_con:.5f}, delta_gen={matched_gen:.5f}, delta_con={matched_con:.5f}, net={net:.5f} kWh")

        if is_first_run:
            print("⏩ ข้ามรอบแรก (baseline)")
            is_first_run = False
        else:
            gen_int = int(matched_gen * SCALE)
            con_int = int(matched_con * SCALE)
            report_energy(ADDRESS, PRIVATE_KEY, gen_int, con_int)

            if net < 0:
                pay_energy(ADDRESS, PRIVATE_KEY, int(abs(net) * SCALE))

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 Exiting → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial:
        rs485.serial.close()
