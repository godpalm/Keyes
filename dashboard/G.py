import time
import os
import sys
import sqlite3
from dotenv import load_dotenv
import minimalmodbus
import threading
from flask import Flask, jsonify, render_template_string

try:
    from flask_cors import CORS

    CORS_AVAILABLE = True
except ImportError:
    CORS_AVAILABLE = False

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import report_energy, pay_energy, reset_energy
from config import web3, token_contract, market_contract

load_dotenv()

ADDRESS = os.getenv("G_ADDRESS")
PRIVATE_KEY = os.getenv("G_PK")
ROLE = "BUY_ONLY"

DB_PATH = "new_G.db"
SCALE = 1000

dev_addr = 27
serial_port = "COM1"
baudrate = 2400

rs485 = minimalmodbus.Instrument(serial_port, dev_addr)
rs485.serial.baudrate = baudrate
rs485.serial.bytesize = 8
rs485.serial.parity = minimalmodbus.serial.PARITY_NONE
rs485.serial.stopbits = 1
rs485.serial.timeout = 0.5
rs485.debug = False
rs485.mode = minimalmodbus.MODE_RTU


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS energy_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_consumed REAL,
            delta_consumed REAL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
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
    cur.execute(
        "INSERT INTO energy_log (total_consumed, delta_consumed) VALUES (?, ?)",
        (total_con, delta_con),
    )
    conn.commit()
    conn.close()


def init_baseline():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM energy_log")
    row_count = cur.fetchone()[0]
    conn.close()
    if row_count == 0:
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)
        save_energy(total_con, 0.0)
        print(f"📊 Baseline created → total_con={total_con:.5f}")
        return True
    return False


# -------------------------------
# Flask Web Dashboard
# -------------------------------
app = Flask(__name__)
if CORS_AVAILABLE:
    CORS(app)

# Global variables to share data between threads
current_data = {
    "total_consumed": 0.0,
    "delta_consumed": 0.0,
    "wallet_balance": 0.0,
    "last_update": None,
}


def get_wallet_balance():
    """ดึงยอด PALM token balance จาก wallet โดยใช้ Private Key แบบบ้าน A"""
    try:
        # ใช้ Private Key เพื่อสร้าง account object และดึง address
        account = web3.eth.account.from_key(PRIVATE_KEY)

        # สร้าง ABI สำหรับ balanceOf function (แบบบ้าน A)
        balance_abi = [
            {
                "constant": True,
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function",
            }
        ]

        # สร้าง contract object ด้วย ABI ที่มี balanceOf
        token_address = os.getenv("TOKEN_ADDRESS")
        balance_contract = web3.eth.contract(address=token_address, abi=balance_abi)

        # ดึง balance จาก address ที่ได้จาก private key
        balance_wei = balance_contract.functions.balanceOf(account.address).call()
        balance_palm = balance_wei / (10**18)

        # แสดง log สำหรับการ debug
        print(f"💰 Wallet Address: {account.address}")
        print(f"💰 Balance: {balance_palm:.6f} PALM")

        return balance_palm
    except Exception as e:
        print(f"❌ ไม่สามารถดึง wallet balance: {e}")
        return 0.0


def get_transaction_history():
    """ดึงประวัติการทำธุรกรรมจาก database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT total_consumed, delta_consumed, ts 
            FROM energy_log 
            ORDER BY id DESC 
            LIMIT 10
        """
        )
        rows = cur.fetchall()
        conn.close()

        history = []
        for row in rows:
            history.append(
                {
                    "total_consumed": row[0],
                    "delta_consumed": row[1],
                    "timestamp": row[2],
                    "type": "Energy Purchase" if row[1] > 0 else "No Purchase",
                }
            )
        return history
    except Exception as e:
        print(f"❌ ไม่สามารถดึงประวัติ: {e}")
        return []


def get_monthly_summary():
    """ดึงสรุปการใช้ไฟรายเดือน"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # ดึงข้อมูลเดือนปัจจุบัน
        cur.execute(
            """
            SELECT 
                SUM(delta_consumed) as total_delta,
                MIN(DATE(ts)) as start_date,
                MAX(DATE(ts)) as end_date,
                COUNT(*) as record_count
            FROM energy_log 
            WHERE strftime('%Y-%m', ts) = strftime('%Y-%m', 'now')
        """
        )
        row = cur.fetchone()
        conn.close()

        if row and row[0] is not None:
            return {
                "total_delta": row[0],
                "start_date": row[1],
                "end_date": row[2],
                "record_count": row[3],
            }
        else:
            return {
                "total_delta": 0.0,
                "start_date": None,
                "end_date": None,
                "record_count": 0,
            }

    except Exception as e:
        print(f"❌ ไม่สามารถดึงสรุปรายเดือน: {e}")
        return {
            "total_delta": 0.0,
            "start_date": None,
            "end_date": None,
            "record_count": 0,
        }


@app.route("/")
def dashboard():
    """หน้า Dashboard หลัก"""
    html_template = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🏠 House G - Energy Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(90deg, #9C27B0, #673AB7);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .role-badge {
            background: rgba(255,255,255,0.2);
            padding: 8px 16px;
            border-radius: 20px;
            display: inline-block;
            font-weight: bold;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            padding: 30px;
        }
        
        .stat-card {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
        }
        
        .stat-icon {
            font-size: 3em;
            margin-bottom: 15px;
        }
        
        .stat-title {
            font-size: 1.1em;
            color: #666;
            margin-bottom: 10px;
            font-weight: 600;
        }
        
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #333;
        }
        
        .stat-unit {
            font-size: 0.8em;
            color: #666;
            margin-left: 5px;
        }
        
        .history-section {
            padding: 30px;
            border-top: 1px solid #eee;
        }
        
        .history-title {
            font-size: 1.8em;
            margin-bottom: 20px;
            color: #333;
            text-align: center;
        }
        
        .history-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .history-table th {
            background: #9C27B0;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }
        
        .history-table td {
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
        }
        
        .history-table tr:hover {
            background: #f5f5f5;
        }
        
        .energy-purchase {
            color: #9C27B0;
            font-weight: bold;
        }
        
        .no-purchase {
            color: #666;
        }
        
        .loading {
            opacity: 0.6;
            transition: opacity 0.3s ease;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏠 House G Energy Dashboard</h1>
            <div class="role-badge">BUY ONLY - Energy Consumer</div>
        </div>
        
        <div class="stats-grid" id="statsGrid">
            <div class="stat-card">
                <div class="stat-icon">⚡</div>
                <div class="stat-title">ไฟที่ซื้อ (Delta)</div>
                <div class="stat-value" id="deltaConsumed">0<span class="stat-unit">หน่วย</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🔌</div>
                <div class="stat-title">ไฟรวมที่ใช้ (Total)</div>
                <div class="stat-value" id="totalConsumed">0.00000<span class="stat-unit">kWh</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">💰</div>
                <div class="stat-title">ยอดเงินในกระเป๋า</div>
                <div class="stat-value" id="walletBalance">0.000<span class="stat-unit">PALM</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🕐</div>
                <div class="stat-title">อัปเดตครั้งถัดไป</div>
                <div class="stat-value" id="nextUpdate" style="font-size: 1.2em;">-</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">📅</div>
                <div class="stat-title">เวลาปัจจุบัน</div>
                <div class="stat-value" id="currentTime" style="font-size: 1.2em;">-</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">📊</div>
                <div class="stat-title">Delta รวมเดือนนี้</div>
                <div class="stat-value" id="monthlyDelta">0<span class="stat-unit">หน่วย</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">📆</div>
                <div class="stat-title">ช่วงวันที่เดือนนี้</div>
                <div class="stat-value" id="monthlyPeriod" style="font-size: 1em;">-</div>
            </div>
        </div>
        
        <div class="history-section">
            <h2 class="history-title">📊 ประวัติการซื้อพลังงาน</h2>
            <table class="history-table">
                <thead>
                    <tr>
                        <th>เวลา</th>
                        <th>ไฟที่ซื้อ (หน่วย)</th>
                        <th>ไฟรวม (kWh)</th>
                        <th>ประเภท</th>
                    </tr>
                </thead>
                <tbody id="historyTableBody">
                    <tr>
                        <td colspan="4" style="text-align: center; padding: 20px;">กำลังโหลดข้อมูล...</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let nextUpdateTime = null;
        let countdownStartTime = null;
        
        // โหลดเวลาจาก localStorage หรือสร้างใหม่
        function initializeCountdown() {
            const savedCountdownStart = localStorage.getItem('houseG_countdownStart');
            const now = Date.now();
            
            if (savedCountdownStart) {
                countdownStartTime = parseInt(savedCountdownStart);
                // คำนวณเวลาถัดไปจากเวลาที่เซฟไว้
                const elapsedTime = now - countdownStartTime;
                const cycleTime = 300000; // 5 นาที
                const timeInCurrentCycle = elapsedTime % cycleTime;
                nextUpdateTime = new Date(now + (cycleTime - timeInCurrentCycle));
            } else {
                // สร้างเวลาใหม่และเซฟ
                countdownStartTime = now;
                nextUpdateTime = new Date(now + 300000);
                localStorage.setItem('houseG_countdownStart', countdownStartTime.toString());
            }
        }
        
        function updateCurrentTime() {
            const now = new Date();
            const options = { 
                year: 'numeric', 
                month: '2-digit', 
                day: '2-digit', 
                hour: '2-digit', 
                minute: '2-digit', 
                second: '2-digit',
                hour12: false
            };
            document.getElementById('currentTime').textContent = 
                now.toLocaleDateString('th-TH', options);
        }
        
        function updateNextUpdateTime() {
            if (nextUpdateTime) {
                const now = new Date();
                const timeLeft = Math.max(0, Math.floor((nextUpdateTime - now) / 1000));
                const minutes = Math.floor(timeLeft / 60);
                const seconds = timeLeft % 60;
                document.getElementById('nextUpdate').textContent = 
                    `${minutes}:${seconds.toString().padStart(2, '0')}`;
                
                // ถ้าหมดเวลาแล้ว ให้ตั้งเวลาใหม่ (รีเซ็ต countdown ทุก 5 นาที)
                if (timeLeft <= 0) {
                    const now = Date.now();
                    countdownStartTime = now;
                    nextUpdateTime = new Date(now + 300000);
                    localStorage.setItem('houseG_countdownStart', countdownStartTime.toString());
                }
            }
        }
        
        async function fetchData() {
            try {
                const statsGrid = document.getElementById('statsGrid');
                statsGrid.classList.add('loading');
                
                const response = await fetch('/api/data');
                const data = await response.json();
                
                // Update stats - คูณ delta_consumed ด้วย 1000 สำหรับการแสดงผล
                document.getElementById('deltaConsumed').innerHTML = 
                    `${Math.round(data.delta_consumed * 1000)}<span class="stat-unit">หน่วย</span>`;
                document.getElementById('totalConsumed').innerHTML = 
                    `${data.total_consumed.toFixed(5)}<span class="stat-unit">kWh</span>`;
                document.getElementById('walletBalance').innerHTML = 
                    `${data.wallet_balance.toFixed(3)}<span class="stat-unit">PALM</span>`;
                
                statsGrid.classList.remove('loading');
                
                // Update history
                const historyResponse = await fetch('/api/history');
                const historyData = await historyResponse.json();
                updateHistoryTable(historyData.history);
                
                // Update monthly summary
                const monthlyResponse = await fetch('/api/monthly');
                const monthlyData = await monthlyResponse.json();
                updateMonthlySummary(monthlyData);
                
            } catch (error) {
                console.error('Error fetching data:', error);
            }
        }
        
        function updateMonthlySummary(data) {
            // อัปเดต Delta รวมเดือนนี้
            document.getElementById('monthlyDelta').innerHTML = 
                `${Math.round(data.total_delta * 1000)}<span class="stat-unit">หน่วย</span>`;
            
            // อัปเดตช่วงวันที่
            if (data.start_date && data.end_date) {
                const startDate = new Date(data.start_date + 'T00:00:00');
                const endDate = new Date(data.end_date + 'T00:00:00');
                const startStr = startDate.toLocaleDateString('th-TH', {day: '2-digit', month: '2-digit'});
                const endStr = endDate.toLocaleDateString('th-TH', {day: '2-digit', month: '2-digit'});
                document.getElementById('monthlyPeriod').textContent = `${startStr} - ${endStr}`;
            } else {
                document.getElementById('monthlyPeriod').textContent = 'ยังไม่มีข้อมูล';
            }
        }
        
        function updateHistoryTable(history) {
            const tbody = document.getElementById('historyTableBody');
            if (history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 20px;">ยังไม่มีข้อมูล</td></tr>';
                return;
            }
            
            tbody.innerHTML = history.map(record => `
                <tr>
                    <td>${record.timestamp}</td>
                    <td>${Math.round(record.delta_consumed * 1000)}</td>
                    <td>${record.total_consumed.toFixed(5)}</td>
                    <td class="${record.delta_consumed > 0 ? 'energy-purchase' : 'no-purchase'}">
                        ${record.type}
                    </td>
                </tr>
            `).join('');
        }
        
        // Initialize countdown timer
        initializeCountdown();
        
        // Initial load and auto refresh every 30 seconds
        fetchData();
        setInterval(fetchData, 30000);
        
        // Update countdown timer every second
        setInterval(updateNextUpdateTime, 1000);
        
        // Update current time every second
        updateCurrentTime();
        setInterval(updateCurrentTime, 1000);
    </script>
</body>
</html>
    """
    return render_template_string(html_template)


@app.route("/api/data")
def get_current_data():
    """API endpoint สำหรับดึงข้อมูลปัจจุบัน"""
    # อัปเดต wallet balance
    current_data["wallet_balance"] = get_wallet_balance()
    return jsonify(current_data)


@app.route("/api/history")
def get_history():
    """API endpoint สำหรับดึงประวัติการทำธุรกรรม"""
    history = get_transaction_history()
    return jsonify({"history": history})


@app.route("/api/monthly")
def get_monthly():
    """API endpoint สำหรับดึงสรุปการใช้ไฟรายเดือน"""
    monthly_data = get_monthly_summary()
    return jsonify(monthly_data)


def run_flask_app():
    """รัน Flask app ใน thread แยก"""
    app.run(host="0.0.0.0", port=5002, debug=False, use_reloader=False)


def update_current_data(total_con, delta_con):
    """อัปเดตข้อมูลปัจจุบันสำหรับ Dashboard"""
    global current_data
    current_data.update(
        {
            "total_consumed": total_con,
            "delta_consumed": delta_con,
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


# -------------------------------
# Main loop
# -------------------------------
init_db()
is_first_run = init_baseline()

# เริ่ม Flask server ใน thread แยก
flask_thread = threading.Thread(target=run_flask_app, daemon=True)
flask_thread.start()
print("🌐 Dashboard เริ่มทำงานที่ http://localhost:5002")

try:
    while True:
        last_con = get_last_total()
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)
        delta_con = round(total_con - last_con, 5)
        if delta_con < 0:
            delta_con = 0.0
        save_energy(total_con, delta_con)

        # อัปเดตข้อมูลสำหรับ Dashboard
        update_current_data(total_con, delta_con)

        print(f"\n🏠 BUY_ONLY → total_con={total_con:.5f}, delta_con={delta_con:.5f}")

        con_int = int(delta_con * SCALE)
        if is_first_run:
            print("⏩ ข้ามรอบแรก (baseline)")
            is_first_run = False
        else:
            report_energy(ADDRESS, PRIVATE_KEY, 0, con_int)
            if delta_con > 0:
                pay_energy(ADDRESS, PRIVATE_KEY, con_int)
            elif delta_con == 0:
                print("ℹ️ ไม่มีการใช้ไฟเพิ่ม → ไม่ซื้อ/จ่าย")

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial:
        rs485.serial.close()
is_first_run = init_baseline()

try:
    while True:
        last_con = get_last_total()
        total_con = rs485.read_float(0x0156, functioncode=4, number_of_registers=2)
        delta_con = round(total_con - last_con, 5)
        if delta_con < 0:
            delta_con = 0.0
        save_energy(total_con, delta_con)

        print(f"\n🏠 BUY_ONLY → total_con={total_con:.5f}, delta_con={delta_con:.5f}")

        con_int = int(delta_con * SCALE)
        if is_first_run:
            print("⏩ ข้ามรอบแรก (baseline)")
            is_first_run = False
        else:
            report_energy(ADDRESS, PRIVATE_KEY, 0, con_int)
            if delta_con > 0:
                pay_energy(ADDRESS, PRIVATE_KEY, con_int)
            elif delta_con == 0:
                print("ℹ️ ไม่มีการใช้ไฟเพิ่ม → ไม่ซื้อ/จ่าย")

        time.sleep(300)

except KeyboardInterrupt:
    print("🚪 ออกจากโปรแกรม → resetEnergy()")
    reset_energy(ADDRESS, PRIVATE_KEY)
finally:
    if rs485.serial:
        rs485.serial.close()

