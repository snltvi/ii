import requests

LOGIN = "abvprom"
PASSWORD = "29328"
BASE_DOMAIN = "https://gps.mobiteam.com.ua"

# Список всех возможных вариантов путей
VARIANTS = [
    "/api/integration/v1/connect",
    "/api/v1/connect",
    "/api/connect",
    "/integration/v1/connect",
    "/GpsServer/api/integration/v1/connect",
    "/GpsServer/api/v1/connect"
]

def scan_api():
    print(f"🔎 Начинаю поиск рабочего адреса API для {LOGIN}...")
    
    for path in VARIANTS:
        url = f"{BASE_DOMAIN}{path}"
        print(f"📡 Проверка: {url}", end=" -> ")
        try:
            # Пробуем передать параметры и в строке, и в заголовках
            params = {'login': LOGIN, 'password': PASSWORD}
            res = requests.get(url, params=params, timeout=5)
            
            if res.status_code == 200:
                print("✅ НАЙДЕНО!")
                print(f"Ответ сервера: {res.text}")
                return url
            elif res.status_code == 401:
                print("❌ Ошибка авторизации (Пароль не подошел)")
            else:
                print(f"Ошибка {res.status_code}")
        except Exception as e:
            print(f"Сбой связи")
            
    print("\n‼️ Все стандартные пути вернули 404.")
    print("Пожалуйста, сделайте следующее:")
    print(f"1. Зайдите в браузер на https://gps.mobiteam.com.ua")
    print(f"2. После входа скопируйте адрес из строки (например, https://gps.mobiteam.com.ua/Web/...)")
    print(f"3. Пришлите этот адрес мне.")

if __name__ == "__main__":
    scan_api()