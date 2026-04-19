"""
ДЕТАЛЬНАЯ ДИАГНОСТИКА: Что именно возвращает API
"""

import requests
import json
from datetime import datetime, timedelta

# ===== НАСТРОЙКИ =====
LOGIN = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"
TEST_OBJECT_ID = 8666  # Первый ID из вашей базы
# =====================

print("=" * 90)
print("ДЕТАЛЬНАЯ ДИАГНОСТИКА API")
print("=" * 90)

# Подключение
print("\n[1] Подключение к API...")
url = f"{BASE_URL}/api/integration/v1/connect"
params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}
response = requests.get(url, params=params)

if response.status_code != 200 or response.text.strip('"') != 'Ok':
    print("❌ Ошибка подключения!")
    exit()

session_id = response.headers.get('sessionid')
headers = {'SessionId': session_id}
print("✅ Подключено!")


# ===== ТЕСТ 1: Информация об объекте =====
print("\n" + "=" * 90)
print("[2] ИНФОРМАЦИЯ ОБ ОБЪЕКТЕ")
print("=" * 90)

print(f"\nОбъект ID: {TEST_OBJECT_ID}")

# Пробуем метод objectinfo
url = f"{BASE_URL}/api/integration/v1/objectinfo"
params = {'oid': TEST_OBJECT_ID}

try:
    response = requests.get(url, headers=headers, params=params, timeout=10)
    print(f"\nЗапрос: {url}")
    print(f"Статус: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\nПолный ответ API:")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])  # Первые 1000 символов
        
        if data.get('result') == 'Ok':
            print(f"\n✅ Информация получена!")
            print(f"\nКлючи в ответе: {list(data.keys())}")
except Exception as e:
    print(f"❌ Ошибка: {e}")


# ===== ТЕСТ 2: Трек за СЕГОДНЯ =====
print("\n" + "=" * 90)
print("[3] ТРЕК ЗА СЕГОДНЯ")
print("=" * 90)

today = datetime.now()
date_from = today.replace(hour=0, minute=0, second=0)
date_to = today.replace(hour=23, minute=59, second=59)

print(f"\nДата: {today.strftime('%d.%m.%Y')}")
print(f"Период: {date_from} - {date_to}")

url = f"{BASE_URL}/api/integration/v1/track"
params = {
    'oid': TEST_OBJECT_ID,
    'from': date_from.strftime('%Y-%m-%d %H:%M:%S'),
    'to': date_to.strftime('%Y-%m-%d %H:%M:%S')
}

try:
    response = requests.get(url, headers=headers, params=params, timeout=10)
    print(f"\nЗапрос: {url}")
    print(f"Параметры: {params}")
    print(f"Статус: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        
        print(f"\nРезультат API: {data.get('result')}")
        
        if 'track' in data:
            track = data['track']
            print(f"Количество точек: {len(track)}")
            
            if track:
                print(f"\n✅ ЕСТЬ ДАННЫЕ!")
                
                # Расшифровка полей
                field_names = {
                    'dt': 'Время',
                    'time': 'Время',
                    'timestamp': 'Время',
                    'm': 'Одометр (км)',
                    'mileage': 'Одометр (км)',
                    'odometer': 'Одометр (км)',
                    'lat': 'Широта',
                    'lon': 'Долгота',
                    'latitude': 'Широта',
                    'longitude': 'Долгота',
                    'speed': 'Скорость (км/ч)',
                    'v': 'Скорость (км/ч)',
                    'course': 'Направление (градусы)',
                    'dir': 'Направление (градусы)',
                    'sat': 'Спутников',
                    'satellites': 'Спутников',
                    'engine': 'Двигатель (1=вкл, 0=выкл)',
                    'ignition': 'Зажигание (1=вкл, 0=выкл)',
                    'fuel': 'Топливо (литры)',
                    'temp': 'Температура (°C)',
                    'alt': 'Высота (метры)',
                    'altitude': 'Высота (метры)',
                }
                
                print(f"\n📍 Первая точка трека (с расшифровкой):")
                for key, value in track[0].items():
                    rus_name = field_names.get(key, f"{key} (неизвестное поле)")
                    print(f"   {rus_name}: {value}")
            else:
                print(f"\n⚠ Трек пустой (нет движения сегодня)")
        else:
            print(f"\nКлючи в ответе: {list(data.keys())}")
            print(f"\nПолный ответ:")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
            
except Exception as e:
    print(f"❌ Ошибка: {e}")


# ===== ТЕСТ 3: Трек за ПОСЛЕДНИЕ 7 ДНЕЙ =====
print("\n" + "=" * 90)
print("[4] ПОИСК ДАННЫХ ЗА ПОСЛЕДНИЕ 7 ДНЕЙ")
print("=" * 90)

for days_ago in range(7):
    check_date = today - timedelta(days=days_ago)
    date_from = check_date.replace(hour=0, minute=0, second=0)
    date_to = check_date.replace(hour=23, minute=59, second=59)
    
    url = f"{BASE_URL}/api/integration/v1/track"
    params = {
        'oid': TEST_OBJECT_ID,
        'from': date_from.strftime('%Y-%m-%d %H:%M:%S'),
        'to': date_to.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('result') == 'Ok':
                track = data.get('track', [])
                
                status = "✅" if len(track) > 0 else "⚠"
                print(f"{status} {check_date.strftime('%d.%m.%Y')}: {len(track)} точек")
                
                if len(track) > 0:
                    # Показываем детали
                    first = track[0]
                    last = track[-1]
                    
                    # Расшифровка полей
                    field_names = {
                        'dt': 'Время',
                        'time': 'Время',
                        'timestamp': 'Время',
                        'm': 'Одометр (км)',
                        'mileage': 'Одометр (км)',
                        'odometer': 'Одометр (км)',
                        'lat': 'Широта',
                        'lon': 'Долгота',
                        'latitude': 'Широта',
                        'longitude': 'Долгота',
                        'speed': 'Скорость (км/ч)',
                        'v': 'Скорость (км/ч)',
                        'course': 'Направление (градусы)',
                        'dir': 'Направление (градусы)',
                        'sat': 'Спутников',
                        'satellites': 'Спутников',
                        'engine': 'Двигатель (вкл/выкл)',
                        'ignition': 'Зажигание (вкл/выкл)',
                        'fuel': 'Топливо (л)',
                        'temp': 'Температура (°C)',
                    }
                    
                    time_start = first.get('dt', first.get('time', first.get('timestamp', 'N/A')))
                    time_end = last.get('dt', last.get('time', last.get('timestamp', 'N/A')))
                    
                    print(f"   📅 Период: {time_start} - {time_end}")
                    
                    # Проверяем наличие одометра
                    mileage_start = first.get('m', first.get('mileage', first.get('odometer')))
                    mileage_end = last.get('m', last.get('mileage', last.get('odometer')))
                    
                    if mileage_start is not None and mileage_end is not None:
                        print(f"   🚗 Одометр: {mileage_start} км → {mileage_end} км")
                        print(f"   📊 Пробег: {mileage_end - mileage_start:.1f} км")
                    else:
                        print(f"   ⚠ Одометр отсутствует в данных!")
                    
                    print(f"\n   💾 Доступные данные в точке трека:")
                    for key, value in first.items():
                        rus_name = field_names.get(key, key)
                        print(f"      {rus_name}: {value}")
                    
                    if len(list(first.keys())) > 10:
                        print(f"      ... всего {len(first.keys())} полей")
            else:
                print(f"⚠ {check_date.strftime('%d.%m.%Y')}: {data.get('result')}")
        else:
            print(f"❌ {check_date.strftime('%d.%m.%Y')}: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"❌ {check_date.strftime('%d.%m.%Y')}: {e}")


# ===== ИТОГИ =====
print("\n" + "=" * 90)
print("ИТОГИ")
print("=" * 90)

print("\n💡 Что проверили:")
print("   1. Подключение к API - работает ли")
print("   2. Информация об объекте - что возвращает")
print("   3. Трек за сегодня - есть ли движение")
print("   4. Поиск данных за 7 дней - когда была активность")

print("\n💡 Возможные причины 'Нет данных':")
print("   • GPS терминал выключен или неисправен")
print("   • Машина действительно не ездила")
print("   • Данные не передаются на сервер")
print("   • Тариф API не включает историю треков")
print("   • Данные удалены или не сохранены")

print("\n💡 Что делать:")
print("   1. Проверьте в веб-интерфейсе Mobiteam - видны ли треки там")
print("   2. Свяжитесь с техподдержкой Mobiteam")
print("   3. Проверьте что GPS терминалы включены и работают")

input("\nНажмите Enter для выхода...")
