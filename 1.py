import requests

# Настройки из вашего Swagger
BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "ВАШ_ПАРОЛЬ"

session = requests.Session()

def start_fort_monitor():
    print("📡 Подключение к Fort Monitor 3 API...")
    
    # 1. Открываем сессию через /connect
    connect_url = f"{BASE_URL}/connect"
    params = {
        'login': LOGIN,
        'password': PASSWORD
    }
    
    try:
        response = session.get(connect_url, params=params, timeout=15)
        data = response.json()
        
        if data.get("result") == "Ok":
            print("✅ Сессия открыта успешно!")
            
            # 2. Теперь запрашиваем данные для вашего DAF (OID 8783)
            get_mileage(8783)
            
        else:
            print(f"❌ Ошибка входа: {data.get('result')}")
            
    except Exception as e:
        print(f"⚠️ Ошибка связи: {e}")

def get_mileage(oid):
    # Используем метод objdata для получения текущих значений
    url = f"{BASE_URL}/objdata"
    params = {"oid": oid}
    
    res = session.get(url, params=params)
    data = res.json()
    
    if data.get("result") == "Ok":
        print(f"\n--- Данные по объекту {oid} ---")
        # Ищем в списке датчиков наш пробег (sid 130160)
        found = False
        for sensor in data.get('states', []):
            if sensor.get('sid') == 130160:
                print(f"📏 Пробег (накопленный): {sensor.get('val')} км")
                found = True
        
        if not found:
            print("ℹ️ Датчик 130160 пока не прислал данные. Попробуйте обновить отчет на сайте.")
    else:
        print(f"❌ Не удалось получить данные: {data.get('result')}")

if __name__ == "__main__":
    start_fort_monitor()