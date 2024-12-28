import asyncio
import aiohttp
from prettytable import PrettyTable
from datetime import datetime
import os
from telegram_bot import buy_coin, create_client, SessionManager, get_bot_username
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
WHALE_USD_AMOUNT = int(os.getenv("WHALE_USD_AMOUNT", "700"))
MAX_WHALE_COIN_MARKETCAP = int(os.getenv("MAX_WHALE_COIN_MARKETCAP", "200000"))
SAVE_BOUGHT_COINS = os.getenv("SAVE_BOUGHT_COINS", "False").strip().lower() == "true"
WHALE_NAMES_BLACKLIST = set(
    name.strip().upper() for name in os.getenv("WHALE_NAMES_BLACKLIST", "").split(",") if name.strip()
)


if not ACCESS_TOKEN:
    raise ValueError("ACCESS_TOKEN is missing in your env file.")

URL = "https://swap-api.assetdash.com/api/api_v5/whalewatch/transactions/list"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "authorization": f"Bearer {ACCESS_TOKEN}",
    "cache-control": "no-cache, no-store, must-revalidate",
    "origin": "https://swap.assetdash.com",
    "referer": "https://swap.assetdash.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}
PARAMS = {"page": 1, "limit": 1, "transaction_types": "buy"}


# Table setup
transaction_table = PrettyTable()
transaction_table.field_names = [
    "Which Whale?", "Bought Coin", "Amount (USD)", "Market Cap (USD)", "Contract Address", "Time Ago"
]

bought_table = PrettyTable()
bought_table.field_names = ["Which Whale?", "Bought Coin", "Market Cap (USD)", "Contract Address", "Dextools Link"]

bought_coins_details = []
recent_transactions = []
last_transaction_id = None
bought_coins = set()


if SAVE_BOUGHT_COINS:
    try:
        with open("blacklist.txt", "r") as file:
            bought_coins.update(line.strip() for line in file if line.strip())
    except FileNotFoundError:
        print("blacklist.txt file not found. Creating a new one...")
        open("blacklist.txt", "w").close()
    except Exception as e:
        print(f"An error occurred while loading the blacklist: {e}")


def save_blacklist(bought_coins, filename="blacklist.txt"):
    try:
        with open(filename, "w") as file:
            for contract_address in bought_coins:
                file.write(contract_address + "\n")
        print(f"Updated blacklist saved to {filename}.")
    except Exception as e:
        print(f"Error saving blacklist: {e}")


async def fetch_transaction(session):
    try:
        async with session.get(URL, headers=HEADERS, params=PARAMS, timeout=2) as response:
            response.raise_for_status()
            data = await response.json()
            if "transactions" in data and data["transactions"]:
                return data["transactions"][0]
    except asyncio.TimeoutError:
        print("Request timed out while fetching whale buys info. Retrying...")
    except aiohttp.ClientError as e:
        print(f"Error while fetching whale buys info: {e}")
    return None


def format_transaction(transaction):
    try:
        whale_name = transaction["swap_whalewatch_list"]["name"]
        bought_coin = transaction["swap_token"]["symbol"]
        amount = transaction.get("trade_amount_rounded")
        amount = round(amount, 2) if amount is not None else 0.0
        market_cap = transaction.get("token_market_cap", "Unknown")
        if market_cap != "Unknown" and market_cap is not None:
            market_cap = round(market_cap, 2)
        else:
            market_cap = "Unknown"    
        contract_address = transaction["swap_token"]["token_address"]

        return (
            whale_name,
            bought_coin,
            f"${amount:,.2f}",
            f"${market_cap:,.2f}" if market_cap != "Unknown" else market_cap,
            contract_address,
            transaction["timestamp"],
        )
    except KeyError as e:
        print(f"Missing key in transaction data: {e}")
    return None


def update_table(transaction):
    global recent_transactions
    formatted_transaction = format_transaction(transaction)
    if formatted_transaction and formatted_transaction not in recent_transactions:
        recent_transactions.insert(0, formatted_transaction)
        if len(recent_transactions) > 10:
            recent_transactions.pop()


def add_bought_coin_details(transaction):
    try:
        bought_coin = transaction["swap_token"]["symbol"]
        whale_name = transaction["swap_whalewatch_list"]["name"]
        market_cap = transaction.get("token_market_cap", "Unknown")
        if market_cap != "Unknown" and market_cap is not None:
            market_cap = round(market_cap, 2)
        else:
            market_cap = "Unknown"    
        contract_address = transaction["swap_token"]["token_address"]
        dextools_link = f"https://dextools.io/app/en/solana/pair-explorer/{contract_address}"

        bought_coins_details.insert(0, [
            whale_name,
            bought_coin,
            f"${market_cap:,.2f}" if market_cap != "Unknown" else market_cap,
            contract_address,
            dextools_link,
        ])

        if len(bought_coins_details) > 5:
            bought_coins_details.pop()
    except KeyError as e:
        print(f"Error adding bought coin details: Missing key {e}")


async def check_and_buy_coin(transaction, bought_coins, client):
    try:
        bot_username = get_bot_username()

        amount = transaction.get("trade_amount_rounded")
        if amount is None:
            print("Error: trade_amount_rounded is missing or None.")
            return

        market_cap = transaction.get("token_market_cap")
        if market_cap is None:
            print("Error: token_market_cap is missing or None.")
            return

        contract_address = transaction["swap_token"]["token_address"]

        if amount >= WHALE_USD_AMOUNT and market_cap <= MAX_WHALE_COIN_MARKETCAP:
            if contract_address not in bought_coins:
                print(f"Criteria met! Buying coin with contract address: {contract_address}")
                await buy_coin(client, contract_address, bot_username)
                bought_coins.add(contract_address)
                add_bought_coin_details(transaction)
            else:
                print(f"Coin with contract address {contract_address} already bought. Skipping.")
    except KeyError as e:
        print(f"Missing key in transaction data: {e}")
    except Exception as e:
        print(f"Unexpected error in check_and_buy_coin function: {e}")

async def main():
    global last_transaction_id

    start_time = datetime.utcnow()

    session_name = SessionManager().get_first_session()
    async with create_client(session_name) as telegram_client:
        print("Telegram client initialized successfully.")

        async with aiohttp.ClientSession() as session:
            try:
                while True:
                    latest_transaction = await fetch_transaction(session)
                    if latest_transaction:
                        transaction_id = latest_transaction.get("id")
                        transaction_timestamp = latest_transaction.get("timestamp")

                        try:
                            transaction_time = datetime.strptime(transaction_timestamp, "%Y-%m-%dT%H:%M:%S")
                        except Exception as e:
                            print(f"Error parsing transaction timestamp: {e}")
                            continue
                        
                        update_table(latest_transaction)

                        if transaction_id and transaction_id != last_transaction_id:
                            last_transaction_id = transaction_id

                            if transaction_time < start_time:
                                print(f"Transaction skipped: Timestamp {transaction_time} is earlier than script start time {start_time}.")
                                continue

                            whale_name = latest_transaction["swap_whalewatch_list"]["name"].upper().strip()
                            if whale_name in WHALE_NAMES_BLACKLIST:
                                print(f"Transaction skipped: Whale '{whale_name}' is in the blacklist.")
                                continue

                            await check_and_buy_coin(latest_transaction, bought_coins, telegram_client)

                    transaction_table.clear_rows()
                    for tx in recent_transactions:
                        whale_name, bought_coin, amount, market_cap, contract_address, timestamp = tx
                        try:
                            transaction_time = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S")
                            time_ago_seconds = (datetime.utcnow() - transaction_time).total_seconds()
                            time_ago = f"{int(time_ago_seconds // 60)}m ago" if time_ago_seconds >= 60 else f"{int(time_ago_seconds)}s ago"

                            transaction_table.add_row([
                                whale_name, bought_coin, amount, market_cap, contract_address, time_ago
                            ])
                        except Exception as e:
                            print(f"Error processing timestamp: {e}")

                    bought_table.clear_rows()
                    for detail in bought_coins_details:
                        bought_table.add_row(detail)

                    os.system("cls" if os.name == "nt" else "clear")
                    print("Recent Whale Transactions:")
                    print(transaction_table)
                    print("\nBought Coins Details: You better Monitor it on BonkBot")
                    print(bought_table)

                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                print("Program interrupted.")
            except Exception as e:
                print(f"Unexpected error: {e}")



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by User")
    finally:
        if SAVE_BOUGHT_COINS:
            save_blacklist(bought_coins)
        else:
            print("SAVE_BOUGHT_COINS is not Enabled in your env. Changes to bought coins were not saved to the blacklist.")    