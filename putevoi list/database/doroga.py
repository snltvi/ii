import requests

LOGIN = "abvprom"
PASSWORD = "ваш_пароль"
# Проверьте этот адрес в браузере!
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1/connect"

def test_connect():
    print(f"⏳ Пробую подключиться к {API_URL}...")
    
    # Прямая склейка строки (иногда API не понимает параметры в объекте)
    full_url = f"{API_URL}?login={LOGIN}&password={PASSWORD}"
    
    try:
        res = requests.get(full_url)
        print(f"Статус ответа: {res.status_code}")
        print(f"Ответ сервера: {res.text}")
        
        if res.status_code == 200:
            data = res.json()
            print(f"Результат: {data.get('result')}")
            
    except Exception as e:
        print(f"Ошибка: {e}")

test_connect()