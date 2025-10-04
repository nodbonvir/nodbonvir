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

def get_raydium_pairs():
    """
    Получить пары с Raydium DEX
    """
    tokens_data = {}
    
    try:
        url = "https://api.raydium.io/v2/main/pairs"
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
        
        print("🔄 Запрос к Raydium API...")
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            pairs = response.json()
            print(f"✅ Получено {len(pairs)} пар от Raydium")
            
            for pair in pairs:
                if isinstance(pair, dict):
                    # Получаем базовый токен
                    base_mint = pair.get('baseMint')
                    base_symbol = pair.get('baseSymbol', pair.get('name', 'UNKNOWN'))
                    volume_24h = pair.get('volume24h', 0)
                    quote_symbol = pair.get('quoteSymbol', '')
                    
                    # Фильтруем только пары с SOL или USDC
                    if quote_symbol not in ['SOL', 'USDC', 'USDT']:
                        continue
                    
                    if base_mint and volume_24h:
                        try:
                            volume_float = float(volume_24h)
                            if volume_float > 100:  # Фильтр >$100
                                if base_mint not in tokens_data or tokens_data[base_mint]['volume'] < volume_float:
                                    tokens_data[base_mint] = {
                                        'volume': volume_float,
                                        'symbol': base_symbol,
                                        'price': float(pair.get('price', 0)),
                                        'pair_address': pair.get('ammId', ''),
                                        'dex': 'raydium',
                                        'liquidity': float(pair.get('liquidity', 0)),
                                        'quote': quote_symbol
                                    }
                        except (ValueError, TypeError):
                            continue
            
            logging.info(f"Raydium API: fetched {len(tokens_data)} tokens")
            print(f"📊 Отфильтровано {len(tokens_data)} токенов с объёмом >$100")
        else:
            print(f"❌ Raydium API вернул статус {response.status_code}")
            logging.error(f"Raydium API returned status {response.status_code}")
    
    except Exception as e:
        print(f"❌ Ошибка Raydium API: {e}")
        logging.error(f"Raydium API error: {e}")
    
    return tokens_data

def get_orca_pairs():
    """
    Получить пары с Orca DEX через публичный API
    """
    tokens_data = {}
    
    try:
        # Используем Orca's whirlpools API
        url = "https://api.mainnet.orca.so/v1/whirlpool/list"
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
        
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            whirlpools = data.get('whirlpools', [])
            
            for pool in whirlpools:
                token_a = pool.get('tokenA', {})
                token_b = pool.get('tokenB', {})
                
                token_address = token_a.get('mint')
                symbol = token_a.get('symbol', 'UNKNOWN')
                
                # Примерно считаем volume через TVL (реальный volume API может не быть доступен)
                tvl = pool.get('tvl', 0)
                volume_estimate = tvl * 0.1  # Примерная оценка
                
                if token_address and volume_estimate > 100:
                    try:
                        if token_address not in tokens_data:
                            tokens_data[token_address] = {
                                'volume': float(volume_estimate),
                                'symbol': symbol,
                                'price': float(token_a.get('price', 0)),
                                'pair_address': pool.get('address', ''),
                                'dex': 'orca',
                                'liquidity': float(tvl),
                                'quote': token_b.get('symbol', '')
                            }
                    except (ValueError, TypeError):
                        continue
            
            logging.info(f"Orca API: fetched {len(tokens_data)} tokens")
    
    except Exception as e:
        logging.error(f"Orca API error: {e}")
    
    return tokens_data

def get_jupiter_tokens():
    """
    Получить токены через Jupiter Token List
    """
    tokens_data = {}
    
    try:
        # Jupiter's token list endpoint
        url = "https://token.jup.ag/all"
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
        
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            tokens = response.json()
            
            # Jupiter token list не имеет объемов, но можем использовать для проверки символов
            logging.info(f"Jupiter token list: {len(tokens)} tokens available")
    
    except Exception as e:
        logging.error(f"Jupiter API error: {e}")
    
    return tokens_data

def get_top_solana_pairs():
    """
    Получить топ пары с нескольких источников
    """
    tokens_data = {}
    
    # Основной источник - Raydium (работает стабильно)
    raydium_data = get_raydium_pairs()
    tokens_data.update(raydium_data)
    
    # Если нужно больше данных, добавляем Orca
    if len(tokens_data) < 50:
        orca_data = get_orca_pairs()
        for addr, data in orca_data.items():
            if addr not in tokens_data:
                tokens_data[addr] = data
    
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
    
    print("=" * 80)
    print("🔄 ИНИЦИАЛИЗАЦИЯ...")
    print("=" * 80)
    print("📡 Получение начальных данных о токенах Solana...")
    print()
    
    logging.info("Initializing previous_data")
    
    tokens_data = get_top_solana_pairs()
    
    if tokens_data:
        previous_data = tokens_data.copy()
        print()
        print("=" * 80)
        print(f"✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА")
        print(f"📊 Отслеживается {len(previous_data)} токенов")
        print("=" * 80)
        logging.info(f"Initialized {len(previous_data)} tokens")
    else:
        print()
        print("=" * 80)
        print("⚠️  НЕ УДАЛОСЬ ПОЛУЧИТЬ ДАННЫЕ")
        print("🔄 Повторная попытка через 10 секунд...")
        print("=" * 80)
        logging.warning("Failed to initialize data")
        time.sleep(10)
        initialize_previous_data()  # Retry

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
            print("=" * 80)
            print("⏳ НАКОПЛЕНИЕ ДАННЫХ...")
            print("=" * 80)
            print(f"📊 Отслеживается токенов: {len(current_data)}")
            print(f"⏱️  Время работы: {int(time.time() - last_update_time)}s")
            print()
            print("💡 Изменения объёма будут видны после следующего 5-минутного цикла")
            print("=" * 80)
            return
        
        top_gainers, top_losers = get_top_movers(valid_changes)
        
        current_time = datetime.now().strftime('%H:%M:%S')
        time_since_reset = int(time.time() - last_update_time)
        
        print("=" * 90)
        print(f"🚀 JUPITER/SOLANA VOLUME SCREENER | ⏰ {current_time} | 🔄 {time_since_reset}s / 300s")
        print("=" * 90)
        print(f"📊 Токенов отслеживается: {len(current_data)} | 📈 С изменениями: {len(valid_changes)}")
        print("=" * 90)
        
        print(f"\n✅ ТОП-10 ТОКЕНОВ С РОСТОМ ОБЪЁМА:")
        print(f"{'#':<4} {'Символ':<12} {'Изменение':<14} {'Объём 24ч':<18} {'Ликвидность':<18} {'DEX':<10}")
        print("-" * 90)
        
        for idx, (token_address, change) in enumerate(top_gainers, 1):
            token_info = current_data.get(token_address, {})
            symbol = token_info.get('symbol', 'UNKNOWN')
            volume = token_info.get('volume', 0)
            liquidity = token_info.get('liquidity', 0)
            dex = token_info.get('dex', 'unknown')
            
            volume_str = f"${volume:,.0f}" if volume > 0 else "N/A"
            liquidity_str = f"${liquidity:,.0f}" if liquidity > 0 else "N/A"
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            
            print(f"\033[92m{idx:<4} {symbol:<12} {change_str:<14} {volume_str:<18} {liquidity_str:<18} {dex:<10}\033[0m")
            logging.info(f"UP #{idx}: {symbol} {change:.2f}% | Vol: ${volume:,.0f} | Liq: ${liquidity:,.0f}")
        
        print(f"\n❌ ТОП-10 ТОКЕНОВ С ПАДЕНИЕМ ОБЪЁМА:")
        print(f"{'#':<4} {'Символ':<12} {'Изменение':<14} {'Объём 24ч':<18} {'Ликвидность':<18} {'DEX':<10}")
        print("-" * 90)
        
        for idx, (token_address, change) in enumerate(reversed(top_losers), 1):
            token_info = current_data.get(token_address, {})
            symbol = token_info.get('symbol', 'UNKNOWN')
            volume = token_info.get('volume', 0)
            liquidity = token_info.get('liquidity', 0)
            dex = token_info.get('dex', 'unknown')
            
            volume_str = f"${volume:,.0f}" if volume > 0 else "N/A"
            liquidity_str = f"${liquidity:,.0f}" if liquidity > 0 else "N/A"
            change_str = f"{change:.2f}%"
            
            print(f"\033[91m{idx:<4} {symbol:<12} {change_str:<14} {volume_str:<18} {liquidity_str:<18} {dex:<10}\033[0m")
            logging.info(f"DOWN #{idx}: {symbol} {change:.2f}% | Vol: ${volume:,.0f} | Liq: ${liquidity:,.0f}")
        
        print("\n" + "=" * 90)
        print("🔄 Обновление через 5 секунд | 💾 Базовые данные обновляются каждые 5 минут")
        print("=" * 90)
        
        # Обновляем previous_data каждые 5 минут
        if time_since_reset >= 300:
            previous_data = current_data.copy()
            last_update_time = time.time()
            logging.info("Updated previous_data (5 min interval)")
            print("\n" + "=" * 90)
            print("🔄 БАЗОВЫЕ ДАННЫЕ ОБНОВЛЕНЫ! Новый 5-минутный интервал начат.")
            print("=" * 90)
            time.sleep(3)
    
    except Exception as e:
        logging.error(f"Error during fetch: {e}")
        print(f"\n❌ Ошибка: {e}")

def main():
    """Main execution loop"""
    print("\n")
    print("=" * 90)
    print(" " * 25 + "🚀 JUPITER/SOLANA VOLUME SCREENER")
    print("=" * 90)
    print(" " * 20 + "📊 Мониторинг изменений объёма торговли")
    print(" " * 25 + "⏱️  Интервал: 5 минут | 🔄 Обновление: 5 сек")
    print("=" * 90)
    print("\n")
    
    initialize_previous_data()
    
    print("\n⏳ Запуск мониторинга через 3 секунды...\n")
    time.sleep(3)
    
    while True:
        try:
            fetch_and_process_data()
            time.sleep(5)  # Fetch every 5 seconds
        except KeyboardInterrupt:
            print("\n\n" + "=" * 90)
            print(" " * 30 + "👋 СКРИНЕР ОСТАНОВЛЕН")
            print("=" * 90)
            logging.info("Screener stopped by user")
            break
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            print(f"\n❌ Непредвиденная ошибка: {e}")
            print("⏳ Повторная попытка через 10 секунд...")
            time.sleep(10)

if __name__ == "__main__":
    main()
