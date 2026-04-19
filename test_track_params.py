"""
ТЕСТ: Правильные параметры для /api/integration/v1/track
"""

import requests
from datetime import datetime

# ===== НАСТРОЙКИ =====
LOGIN = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"
TEST_OBJECT_ID = 8666  # ID из вашей базы
# =====================

print("=" * 80)
print("ТЕСТ: /api/integration/v1/track")
print("=" * 80)

# Подключение
print("\nПодключение...")
url = f"{BASE_URL}/api/integration/v1/connect"
params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}
response = requests.get(url, params=params)

if response.status_code != 200 or response.text.strip('"') != 'Ok':
    print("❌ Ошибка подключения!")
    exit()

session_id = response.headers.get('sessionid')
headers = {'SessionId': session_id}
print("✅ Подключено!")

# Тестовые даты
date_from = datetime(2026, 2, 1, 0, 0, 0)
date_to = datetime(2026, 2, 1, 23, 59, 59)

print(f"\nТестируем объект ID: {TEST_OBJECT_ID}")
print(f"Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}")

# Разные варианты параметров
param_variants = [
    {
        'name': 'Вариант 1: oid, sdt, edt',
        'params': {
            'oid': TEST_OBJECT_ID,
            'sdt': date_from.strftime('%Y-%m-%d %H:%M:%S'),
            'edt': date_to.strftime('%Y-%m-%d %H:%M:%S')
        }
    },
    {
        'name': 'Вариант 2: objectId, startDate, endDate',
        'params': {
            'objectId': TEST_OBJECT_ID,
            'startDate': date_from.strftime('%Y-%m-%d %H:%M:%S'),
            'endDate': date_to.strftime('%Y-%m-%d %H:%M:%S')
        }
    },
    {
        'name': 'Вариант 3: oid, from, to',
        'params': {
            'oid': TEST_OBJECT_ID,
            'from': date_from.strftime('%Y-%m-%d %H:%M:%S'),
            'to': date_to.strftime('%Y-%m-%d %H:%M:%S')
        }
    },
    {
        'name': 'Вариант 4: oid, sdt, edt (ISO формат)',
        'params': {
            'oid': TEST_OBJECT_ID,
            'sdt': date_from.isoformat(),
            'edt': date_to.isoformat()
        }
    },
    {
        'name': 'Вариант 5: objectId, sdt, edt',
        'params': {
            'objectId': TEST_OBJECT_ID,
            'sdt': date_from.strftime('%Y-%m-%d %H:%M:%S'),
            'edt': date_to.strftime('%Y-%m-%d %H:%M:%S')
        }
    },
]

print("\n" + "=" * 80)

for variant in param_variants:
    print(f"\n🔍 {variant['name']}")
    print(f"   Параметры: {variant['params']}")
    
    url = f"{BASE_URL}/api/integration/v1/track"
    
    try:
        response = requests.get(url, headers=headers, params=variant['params'], timeout=10)
        
        print(f"   Статус: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                result = data.get('result', 'N/A')
                print(f"   Результат API: {result}")
                
                if result == 'Ok':
                    track = data.get('track', [])
                    print(f"   ✅ РАБОТАЕТ! Точек: {len(track)}")
                    
                    if track:
                        print(f"\n   📍 Пример первой точки:")
                        first = track[0]
                        print(f"      Время: {first.get('dt', first.get('time', 'N/A'))}")
                        print(f"      Одометр: {first.get('m', first.get('mileage', 'N/A'))}")
                        print(f"      Координаты: {first.get('lat')}, {first.get('lon')}")
                    
                    print(f"\n   ✅ ЭТО ПРАВИЛЬНЫЕ ПАРАМЕТРЫ!")
                    break
                else:
                    print(f"   ⚠ Результат: {result}")
            except Exception as e:
                print(f"   ⚠ Ошибка парсинга: {e}")
                print(f"   Ответ: {response.text[:200]}")
        else:
            print(f"   ❌ HTTP {response.status_code}")
            if response.status_code == 404:
                print(f"   Ответ: {response.text[:200]}")
            
    except Exception as e:
        print(f"   ❌ Ошибка запроса: {e}")

print("\n" + "=" * 80)
print("ИТОГ")
print("=" * 80)
print("\n💡 Проверьте также документацию Swagger:")
print("   https://gps.mobiteam.com.ua/api/help/index")
print("   Найдите раздел 'track' и посмотрите примеры параметров")

input("\nНажмите Enter для выхода...")
