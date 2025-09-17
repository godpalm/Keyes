import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

RPC_URL = "https://ethereum-holesky-rpc.publicnode.com"
CHAIN_ID = 17000

web3 = Web3(Web3.HTTPProvider(RPC_URL))
if not web3.is_connected():
    raise Exception("❌ เชื่อมต่อ Holesky ไม่ได้")

TOKEN_ADDRESS = os.getenv("TOKEN_ADDRESS")
MARKET_ADDRESS = os.getenv("MARKET_ADDRESS")

TOKEN_ABI = [
    {"constant": False,"inputs":[{"name":"spender","type":"address"},{"name":"value","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant": True,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},
]

MARKET_ABI = [
    {
        "inputs":[
            {"internalType":"uint256","name":"generated","type":"uint256"},
            {"internalType":"uint256","name":"consumed","type":"uint256"}
        ],
        "name":"reportEnergy",
        "outputs":[],
        "stateMutability":"nonpayable",
        "type":"function"
    },
    {
        "inputs":[
            {"internalType":"address","name":"buyer","type":"address"},
            {"internalType":"uint256","name":"kwh","type":"uint256"},
            {"internalType":"uint256","name":"pricePerKwh","type":"uint256"}
        ],
        "name":"payEnergy",
        "outputs":[],
        "stateMutability":"nonpayable",
        "type":"function"
    },
    {
        "inputs":[],
        "name":"resetEnergy",
        "outputs":[],
        "stateMutability":"nonpayable",
        "type":"function"
    }
]


token_contract = web3.eth.contract(address=TOKEN_ADDRESS, abi=TOKEN_ABI)
market_contract = web3.eth.contract(address=MARKET_ADDRESS, abi=MARKET_ABI)
