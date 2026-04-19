"""
Полный пример работы с Mobiteam API:
1. Подключение через connect
2. Получение списка объектов
3. Получение списка датчиков
"""

import requests
import json


# ========================================
# ПОСТОЯННЫЕ НАСТРОЙКИ (уже заполнено)
# ========================================

BASE_URL = "https://gps.mobiteam.com.ua"
LOGIN = "abvprom"
PASSWORD = "29328"

# ========================================


def connect(login, password):
    """
    Шаг 1: Подключение через connect
    Возвращает SessionId
    """
    url = f"{BASE_URL}/api/integration/v1/connect"
    
    params = {
        'login': login,
        'password': password,
        'lang': 'ru-ru',
        'timezone': '3'
    }
    
    print("=" * 60)
    print("ШАГ 1: Подключение (connect)")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Логин: {login}")
    
    response = requests.get(url, params=params)
    
    print(f"\nОтвет: {response.text}")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200 and response.text.strip('"') == 'Ok':
        session_id = response.headers.get('sessionid') or response.headers.get('SessionId')
        print(f"\n✅ Подключение успешно!")
        print(f"SessionId: {session_id}")
        return session_id
    else:
        print("\n❌ Ошибка подключения")
        return None


def get_objects_list(session_id):
    """
    Шаг 2: Получение списка объектов (транспортных средств)
    """
    url = f"{BASE_URL}/api/integration/v1/objectslist"
    
    # ВАЖНО: Добавляем SessionId в заголовки
    headers = {
        'SessionId': session_id
    }
    
    print("\n" + "=" * 60)
    print("ШАГ 2: Получение списка объектов (objectslist)")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Header SessionId: {session_id[:20]}...")
    
    response = requests.get(url, headers=headers)
    
    print(f"\nStatus: {response.status_code}")
    
    try:
        data = response.json()
        print(f"\nОтвет (JSON):")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        if data.get('result') == 'Ok':
            objects = data.get('objects', [])
            print(f"\n✅ Найдено объектов: {len(objects)}")
            
            if objects:
                print("\nСписок объектов:")
                for obj in objects:
                    obj_id = obj.get('id')
                    obj_name = obj.get('name', 'Без названия')
                    print(f"  - ID: {obj_id}, Название: {obj_name}")
            
            return objects
        else:
            print(f"\n❌ Ошибка: {data.get('result')}")
            return []
            
    except Exception as e:
        print(f"\n❌ Ошибка парсинга JSON: {e}")
        print(f"Raw response: {response.text}")
        return []


def get_object_sensors(session_id, object_id):
    """
    Шаг 3: Получение списка датчиков конкретного объекта
    """
    url = f"{BASE_URL}/api/integration/v1/objsensorslist"
    
    headers = {
        'SessionId': session_id
    }
    
    params = {
        'oid': object_id
    }
    
    print("\n" + "=" * 60)
    print(f"ШАГ 3: Получение датчиков объекта ID={object_id}")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Параметр oid: {object_id}")
    
    response = requests.get(url, headers=headers, params=params)
    
    print(f"\nStatus: {response.status_code}")
    
    try:
        data = response.json()
        print(f"\nОтвет (JSON):")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        if data.get('result') == 'Ok':
            sensors = data.get('obj_sensors', [])
            print(f"\n✅ Найдено датчиков: {len(sensors)}")
            
            if sensors:
                print("\nСписок датчиков:")
                for sensor in sensors:
                    sensor_id = sensor.get('sid')
                    sensor_name = sensor.get('name', 'Без названия')
                    print(f"  - ID: {sensor_id}, Название: {sensor_name}")
            
            return sensors
        else:
            print(f"\n❌ Ошибка: {data.get('result')}")
            return []
            
    except Exception as e:
        print(f"\n❌ Ошибка парсинга JSON: {e}")
        print(f"Raw response: {response.text}")
        return []


def disconnect(session_id):
    """
    Шаг 4 (опционально): Закрытие сессии
    """
    url = f"{BASE_URL}/api/integration/v1/disconnect"
    
    headers = {
        'SessionId': session_id
    }
    
    print("\n" + "=" * 60)
    print("Закрытие сессии (disconnect)")
    print("=" * 60)
    
    try:
        response = requests.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        print("✅ Сессия закрыта")
    except:
        print("⚠ Ошибка при закрытии сессии")


def main():
    """
    Основная функция - демонстрация полного цикла работы с API
    """
    
    print("\n" + "█" * 60)
    print("ПОЛНЫЙ ПРИМЕР РАБОТЫ С MOBITEAM API")
    print("█" * 60)
    
    # Шаг 1: Подключение
    session_id = connect(LOGIN, PASSWORD)
    
    if not session_id:
        print("\n❌ Не удалось подключиться. Завершение.")
        return
    
    # Шаг 2: Получение списка объектов
    objects = get_objects_list(session_id)
    
    if not objects:
        print("\n⚠ Объекты не найдены или нет доступа")
    else:
        # Шаг 3: Для первого объекта получаем датчики
        first_object_id = objects[0].get('id')
        get_object_sensors(session_id, first_object_id)
    
    # Шаг 4: Закрываем сессию
    disconnect(session_id)
    
    print("\n" + "█" * 60)
    print("ЗАВЕРШЕНО")
    print("█" * 60)


if __name__ == "__main__":
    main()
