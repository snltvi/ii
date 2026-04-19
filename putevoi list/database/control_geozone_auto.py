import requests

# --- ВАШИ ДАННЫЕ ---
LOGIN = "abvprom"
PASSWORD = "29328"

# Пробуем основной и альтернативный адреса
ENDPOINTS = [
    "https://gps.mobiteam.com.ua/api/integration/v1",
    "https://gps.mobiteam.com.ua/api/v1"
]

def run_control():
    sid = None
    working_base = None

    # 1. ПОИСК РАБОЧЕГО АДРЕСА И АВТОРИЗАЦИЯ
    for base in ENDPOINTS:
        print(f"📡 Проверка связи с {base}...")
        auth_url = f"{base}/connect?login={LOGIN}&password={PASSWORD}"
        try:
            res = requests.get(auth_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('result') and data['result'] != 'Error':
                    sid = data['result']
                    working_base = base
                    print(f"✅ Успешное подключение!")
                    break
            elif res.status_code == 404:
                print(f"❌ Путь {base} не найден (404)")
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")

    if not sid:
        print("\n🆘 Не удалось авторизоваться. Проверьте адрес API или пароль.")
        return

    # 2. ПОЛУЧЕНИЕ СПИСОКА ГЕОЗОН
    print("\n🔍 Загрузка списка геозон...")
    try:
        zones_res = requests.get(f"{working_base}/getzones", headers={'SessionId': sid})
        zones = zones_res.json().get('zones', [])
        
        if not zones:
            print("ℹ️ В вашем аккаунте пока не создано ни одной геозоны.")
        else:
            print("📍 НАЙДЕНЫ ГЕОЗОНЫ:")
            print("-" * 40)
            for z in zones:
                print(f"ID: {z['id']} | Название: {z['name']}")
            print("-" * 40)
            print("☝️ Найдите в списке выше 'Гараж' и запомните его ID.")

        # 3. ПРИМЕР ЗАПРОСА ПОСЕЩЕНИЙ (для авто Демченко 8783)
        # Если в списке есть зоны, проверим посещение первой из них за сегодня
        if zones:
            target_zone_id = zones[0]['id'] # Замените на ID Гаража после запуска
            print(f"\n⏳ Проверка заездов в зону ID {target_zone_id} за сегодня...")
            
            from_dt = "2026-02-14 00:00:00"
            to_dt = "2026-02-14 23:59:59"
            
            v_params = {
                'objects_ids': '8783',
                'zones_ids': target_zone_id,
                'from': from_dt,
                'to': to_dt,
                'minDuration': 0
            }
            v_res = requests.get(f"{working_base}/zonesvisits", params=v_params, headers={'SessionId': sid})
            print(f"📊 Результат посещений: {v_res.text}")

    except Exception as e:
        print(f"💥 Ошибка при получении данных: {e}")

if __name__ == "__main__":
    run_control()