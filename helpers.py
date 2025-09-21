from config import web3, CHAIN_ID, MARKET_ADDRESS, token_contract, market_contract
from web3.exceptions import ContractLogicError

def approve_token_if_needed(addr, pk, amount):
    current_allowance = token_contract.functions.allowance(addr, MARKET_ADDRESS).call()
    if current_allowance < amount:
        print(f"🔑 {addr} approve {amount} PALM ให้ EnergyMarket")
        nonce = web3.eth.get_transaction_count(addr, "pending")
        tx = token_contract.functions.approve(MARKET_ADDRESS, 10**27).build_transaction({
            "chainId": CHAIN_ID,
            "gas": 100000,
            "gasPrice": int(web3.eth.gas_price * 1.2),
            "nonce": nonce
        })
        signed_tx = web3.eth.account.sign_transaction(tx, pk)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        web3.eth.wait_for_transaction_receipt(tx_hash)

def report_energy(addr, pk, gen, con):
    nonce = web3.eth.get_transaction_count(addr, "pending")
    tx = market_contract.functions.reportEnergy(gen, con).build_transaction({
        "chainId": CHAIN_ID,
        "gas": 150000,
        "gasPrice": int(web3.eth.gas_price * 1.2),
        "nonce": nonce
    })
    signed_tx = web3.eth.account.sign_transaction(tx, pk)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"📡 {addr} รายงาน Energy → ผลิต {gen}, ใช้ {con}, tx={web3.to_hex(tx_hash)}")
    web3.eth.wait_for_transaction_receipt(tx_hash)


def pay_energy(addr, pk, kwh):
    """
    ✅ เวอร์ชันใหม่ ไม่ต้องส่ง pricePerKwh ให้สัญญา
    ✅ ราคาไปถูกกำหนดใน smart contract แล้ว
    """

    # ✅ อนุมัติ token เผื่อไว้ (ใช้จำนวนมากพอ ไม่ต้อง approve บ่อย)
    # สัญญาจะเป็นคนดึง token เท่าที่ต้องจ่ายเอง
    approve_token_if_needed(addr, pk, 10**24)  # Approve สูง ๆ ไว้ก่อน

    # ✅ สร้าง transaction
    nonce = web3.eth.get_transaction_count(addr, "pending")
    tx = market_contract.functions.payEnergy(
        addr,
        kwh
    ).build_transaction({
        "chainId": CHAIN_ID,
        "gas": 250000,
        "gasPrice": int(web3.eth.gas_price * 1.2),
        "nonce": nonce
    })

    signed_tx = web3.eth.account.sign_transaction(tx, pk)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

    try:
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash)

        if receipt["status"] == 0:
            print(f"❌ การจ่ายเงินล้มเหลว, tx={web3.to_hex(tx_hash)}")
            return None

        print(f"✅ {addr} ซื้อ {kwh} kWh, tx={web3.to_hex(tx_hash)}")
        return receipt

    except ContractLogicError as e:
        print(f"❌ ContractLogicError: {str(e)}")
        return None

    except ValueError as e:
        print(f"❌ ValueError: {str(e)}")
        return None

    except Exception as e:
        print(f"❌ Unknown error: {str(e)}")
        return None


def reset_energy(addr, pk):
    nonce = web3.eth.get_transaction_count(addr, "pending")
    tx = market_contract.functions.resetEnergy().build_transaction({
        "chainId": CHAIN_ID,
        "gas": 100000,
        "gasPrice": int(web3.eth.gas_price * 1.2),
        "nonce": nonce
    })
    signed_tx = web3.eth.account.sign_transaction(tx, pk)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"🧹 {addr} resetEnergy(), tx={web3.to_hex(tx_hash)}")
    web3.eth.wait_for_transaction_receipt(tx_hash)
