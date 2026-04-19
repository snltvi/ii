import requests

# Данные со скриншотов
BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "ваш_пароль"

def get_vehicle_ids():
    # Используем Session для автоматического сохранения cookie (как требует скриншот №2)
    session = requests.Session()
    
    # Параметры из скриншота №2
    auth_params = {
        "login": LOGIN,
        "password": PASSWORD,
        "lang": "ru-ru",      # Обязательный параметр
        "timezone": "2"       # Смещение UTC для Украины (зимой +2)
    }

    try:
        print(f"Подключение к {BASE_URL}/connect...")
        # Метод GET, как на скриншоте
        response = session.get(f"{BASE_URL}/connect", params=auth_params)
        
        # На скриншоте сказано: ответ "Ok" при успехе
        if response.text == "Ok" or response.status_code == 200:
            print("✅ Авторизация успешна (Cookie сохранены)")
            
            # Запрашиваем список машин (GetTree обычно доступен в этом же API)
            tree_url = f"{BASE_URL}/gettree"
            tree_res = session.get(tree_url)
            
            if tree_res.status_code == 200:
                data = tree_res.json()
                print(f"\n{'ID':<15} | {'Название ТС'}")
                print("-" * 40)
                for item in data:
                    print(f"{item.get('id'):<15} | {item.get('name')}")
            else:
                print(f"Ошибка GetTree: {tree_res.status_code}")
        else:
            print(f"Ошибка авторизации: {response.status_code}")
            print(f"Ответ сервера: {response.text}")

    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    get_vehicle_ids()