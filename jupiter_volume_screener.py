import requests
import time
from datetime import datetime
import os
import logging

# Configure logging
logging.basicConfig(
    filename='jupiter_volume_screener.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

# Инициализация
previous_data = {}  # {token_address: {'volume': float, 'symbol': str}}
current_data = {}
percentage_changes = {}  # {token_address: volume_change_percentage}
last_update_time = time.time()

def clear_screen():
    """Clear terminal screen"""
    os.system('clear' if os.name != 'nt' else 'cls')

def get_jupiter_tokens():
    """
    Получить топ токены Solana через Birdeye API
    Birdeye предоставляет данные о объемах для токенов на Solana
    """
    try:
        # Используем DexScreener API как более доступную альтернативу
        # Получаем топ токены по объему за последние 24 часа на Solana
        url = "https://api.dexscreener.com/latest/dex/tokens/solana"
        
        # Альтернативный подход: получаем все пары на Raydium и Orca
        pairs_url = "https://api.dexscreener.com/latest/dex/pairs/solana"
        
        # Для более полного охвата используем поиск топ токенов
        response = requests.get(
            "https://api.dexscreener.com/latest/dex/search/?q=SOL",
            timeout=10
        )
        
        if response.status_code != 200:
            logging.warning(f"DexScreener API returned status {response.status_code}")
            return {}
        
        data = response.json()
        tokens_data = {}
        
        if 'pairs' in data:
            for pair in data['pairs']:
                # Фильтруем только Solana пары
                if pair.get('chainId') != 'solana':
                    continue
                    
                # Получаем базовый токен (не SOL)
                base_token = pair.get('baseToken', {})
                quote_token = pair.get('quoteToken', {})
                
                # Пропускаем если это не пара с SOL или USDC
                if quote_token.get('symbol') not in ['SOL', 'USDC', 'USDT']:
                    continue
                
                token_address = base_token.get('address')
                symbol = base_token.get('symbol')
                volume_24h = pair.get('volume', {}).get('h24', 0)
                
                if token_address and symbol and volume_24h:
                    try:
                        volume_float = float(volume_24h)
                        if volume_float > 1000:  # Фильтр >$1000
                            if token_address not in tokens_data or tokens_data[token_address]['volume'] < volume_float:
                                tokens_data[token_address] = {
                                    'volume': volume_float,
                                    'symbol': symbol,
                                    'price': float(pair.get('priceUsd', 0)),
                                    'pair': pair.get('pairAddress', ''),
                                    'dex': pair.get('dexId', 'unknown')
                                }
                    except (ValueError, TypeError):
                        continue
        
        return tokens_data
        
    except Exception as e:
        logging.error(f"Error fetching Jupiter tokens: {e}")
        return {}

def get_top_solana_pairs():
    """
    Получить топ пары напрямую с нескольких DEX на Solana
    """
    tokens_data = {}
    
    try:
        # Получаем пары с большим объемом на Solana
        response = requests.get(
            "https://api.dexscreener.com/latest/dex/pairs/solana",
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if 'pairs' in data:
                for pair in data['pairs']:
                    base_token = pair.get('baseToken', {})
                    quote_token = pair.get('quoteToken', {})
                    
                    token_address = base_token.get('address')
                    symbol = base_token.get('symbol')
                    volume_24h = pair.get('volume', {}).get('h24', 0)
                    
                    if token_address and symbol and volume_24h:
                        try:
                            volume_float = float(volume_24h)
                            if volume_float > 1000:  # Фильтр >$1000
                                if token_address not in tokens_data or tokens_data[token_address]['volume'] < volume_float:
                                    tokens_data[token_address] = {
                                        'volume': volume_float,
                                        'symbol': symbol,
                                        'price': float(pair.get('priceUsd', 0)),
                                        'pair_address': pair.get('pairAddress', ''),
                                        'dex': pair.get('dexId', 'unknown'),
                                        'liquidity': float(pair.get('liquidity', {}).get('usd', 0))
                                    }
                        except (ValueError, TypeError):
                            continue
    except Exception as e:
        logging.error(f"Error fetching Solana pairs: {e}")
    
    return tokens_data

def get_top_movers(data, num_top=10):
    """
    Identifies the top gainers and losers by volume change.
    """
    if not data:
        return [], []
    
    sorted_data = sorted(data.items(), key=lambda x: x[1], reverse=True)
    top_gainers = sorted_data[:num_top]
    top_losers = sorted_data[-num_top:] if len(sorted_data) >= num_top else sorted_data[::-1]
    return top_gainers, top_losers

def initialize_previous_data():
    """Initialize previous_data with the first data fetch"""
    global previous_data
    
    print("🔄 Инициализация... Получение начальных данных Solana токенов...")
    logging.info("Initializing previous_data")
    
    tokens_data = get_top_solana_pairs()
    
    if tokens_data:
        previous_data = tokens_data.copy()
        print(f"✅ Инициализировано {len(previous_data)} токенов")
        logging.info(f"Initialized {len(previous_data)} tokens")
    else:
        print("⚠️  Не удалось получить данные, повторная попытка...")
        logging.warning("Failed to initialize data")

def fetch_and_process_data():
    """Fetch data and process volume changes"""
    global current_data, previous_data, percentage_changes, last_update_time
    
    current_data.clear()
    percentage_changes.clear()
    
    try:
        # Получаем текущие данные
        current_data = get_top_solana_pairs()
        
        if not current_data:
            print("⚠️  Нет данных от API")
            logging.warning("No data received from API")
            return
        
        # Вычисляем изменения объёма
        for token_address, token_info in current_data.items():
            if token_address in previous_data:
                current_volume = token_info['volume']
                prev_volume = previous_data[token_address]['volume']
                
                if prev_volume > 0:
                    volume_change = ((current_volume - prev_volume) / prev_volume) * 100
                    percentage_changes[token_address] = volume_change
        
        # Очистка экрана и вывод результатов
        clear_screen()
        
        valid_changes = {k: v for k, v in percentage_changes.items() if isinstance(v, (int, float))}
        
        if not valid_changes:
            print("⏳ Накопление данных для расчета изменений...")
            print(f"   Отслеживается токенов: {len(current_data)}")
            return
        
        top_gainers, top_losers = get_top_movers(valid_changes)
        
        current_time = datetime.now().strftime('%H:%M:%S')
        time_since_reset = int(time.time() - last_update_time)
        
        print("=" * 80)
        print(f"🚀 JUPITER/SOLANA VOLUME SCREENER | Обновлено: {current_time}")
        print(f"⏱️  Интервал отсчета: {time_since_reset}s / 300s (5 мин)")
        print(f"📊 Всего токенов отслеживается: {len(current_data)}")
        print("=" * 80)
        
        print(f"\n✅ ТОП-10 ТОКЕНОВ С РОСТОМ ОБЪЁМА:")
        print(f"{'Символ':<15} {'Изменение':<15} {'Объём 24ч':<20} {'DEX':<12}")
        print("-" * 80)
        
        for token_address, change in top_gainers:
            token_info = current_data.get(token_address, {})
            symbol = token_info.get('symbol', 'UNKNOWN')
            volume = token_info.get('volume', 0)
            dex = token_info.get('dex', 'unknown')
            
            volume_str = f"${volume:,.0f}" if volume > 0 else "N/A"
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            
            print(f"\033[92m{symbol:<15} {change_str:<15} {volume_str:<20} {dex:<12}\033[0m")
            logging.info(f"UP: {symbol} {change:.2f}% | Vol: ${volume:,.0f} | DEX: {dex}")
        
        print(f"\n❌ ТОП-10 ТОКЕНОВ С ПАДЕНИЕМ ОБЪЁМА:")
        print(f"{'Символ':<15} {'Изменение':<15} {'Объём 24ч':<20} {'DEX':<12}")
        print("-" * 80)
        
        for token_address, change in reversed(top_losers):
            token_info = current_data.get(token_address, {})
            symbol = token_info.get('symbol', 'UNKNOWN')
            volume = token_info.get('volume', 0)
            dex = token_info.get('dex', 'unknown')
            
            volume_str = f"${volume:,.0f}" if volume > 0 else "N/A"
            change_str = f"{change:.2f}%"
            
            print(f"\033[91m{symbol:<15} {change_str:<15} {volume_str:<20} {dex:<12}\033[0m")
            logging.info(f"DOWN: {symbol} {change:.2f}% | Vol: ${volume:,.0f} | DEX: {dex}")
        
        print("\n" + "=" * 80)
        print("🔄 Следующее обновление через 5 секунд...")
        print("💡 Базовые данные обновляются каждые 5 минут")
        print("=" * 80)
        
        # Обновляем previous_data каждые 5 минут
        if time_since_reset >= 300:
            previous_data = current_data.copy()
            last_update_time = time.time()
            logging.info("Updated previous_data (5 min interval)")
            print("\n🔄 Базовые данные обновлены! Новый 5-минутный интервал начат.")
            time.sleep(2)
    
    except Exception as e:
        logging.error(f"Error during fetch: {e}")
        print(f"❌ Ошибка: {e}")

def main():
    """Main execution loop"""
    print("=" * 80)
    print("🚀 JUPITER/SOLANA VOLUME SCREENER")
    print("=" * 80)
    print("📊 Мониторинг изменений объёма торговли на Solana DEX")
    print("⏱️  Интервал расчета: 5 минут")
    print("🔄 Обновление данных: каждые 5 секунд")
    print("=" * 80)
    print()
    
    initialize_previous_data()
    
    print("\n⏳ Ожидание 5 секунд перед началом мониторинга...")
    time.sleep(5)
    
    while True:
        try:
            fetch_and_process_data()
            time.sleep(5)  # Fetch every 5 seconds
        except KeyboardInterrupt:
            print("\n\n👋 Скринер остановлен пользователем")
            logging.info("Screener stopped by user")
            break
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            print(f"\n❌ Непредвиденная ошибка: {e}")
            print("⏳ Повторная попытка через 10 секунд...")
            time.sleep(10)

if __name__ == "__main__":
    main()
