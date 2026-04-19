import requests
import re

# 1. Вставьте ваш ключ сюда. 
# ВНИМАНИЕ: Здесь должны быть только цифры и латинские буквы!
# ===== НАСТРОЙКИ =====
LOGIN = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"

def clean_token(token):
    # Эта функция удалит любые русские/украинские буквы, если они случайно попали в ключ
    return re.sub(r'[^a-zA-Z0-9\.\-\_]', '', token)

def check_my_fleet():
    # Очищаем токен перед использованием
    safe_key = clean_token(API_KEY)
    
    # Проверка: если после очистки ключ изменился, значит там была кириллица
    if safe_key != API_KEY:
        print("!!! Внимание: В вашем ключе были найдены и удалены недопустимые символы (кириллица или пробелы).")

    # Базовый URL для Mobiteam (проверьте этот адрес в документации!)
    url = "https://gps.mobiteam.com.ua/api/get_units" 

    headers = {
        "Authorization": f"Bearer {safe_key}",
        "Accept": "application/json"
    }

    print("Подключение к серверу Mobiteam...")
    
    try:
        # Увеличим время ожидания до 10 секунд (timeout)
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            units = response.json()
            print(f"{'Имя авто':<25} | {'Статус данных'}")
            print("-" * 50)
            for unit in units:
                name = unit.get('name', 'N/A')
                # Проверяем, есть ли ключи параметров или сенсоров
                has_sensors = "Есть датчики" if unit.get('sensors') else "Датчиков НЕТ"
                print(f"{name:<25} | {has_sensors}")
        elif response.status_code == 401:
            print("Ошибка 401: Неверный ключ API. Проверьте ваш токен.")
        else:
            print(f"Сервер ответил ошибкой {response.status_code}")
            print("Текст ответа:", response.text)

    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == "__main__":
    check_my_fleet()