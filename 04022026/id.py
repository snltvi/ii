import requests
import json

BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328" # <--- Впишите актуальный пароль

def get_vehicle_ids():
    session = requests.Session()
    # Параметры из вашей документации Mobiteam
    auth_params = {
        "login": LOGIN, 
        "password": PASSWORD, 
        "lang": "ru-ru", 
        "timezone": "2"
    }

    try:
        print(f"Попытка входа для {LOGIN}...")
        res = session.get(f"{BASE_URL}/connect", params=auth_params)
        
        # Очищаем ответ от кавычек и пробелов
        server_response = res.text.strip().replace('"', '')
        
        if server_response == "Ok":
            print("✅ Авторизация успешна! Запрашиваю список машин...")
            
            # Используем метод, который ранее выдал статус 200
            response = session.get(f"{BASE_URL}/getobjectslist")
            
            if response.status_code == 200:
                data = response.json()
                
                # Сохраняем "сырые" данные в файл для подстраховки
                with open("debug_data.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                
                print(f"\n{'ID МАШИНЫ':<40} | {'НАЗВАНИЕ'}")
                print("-" * 70)
                
                # В системе Fort Monitor 3 объекты обычно приходят списком
                items = data if isinstance(data, list) else data.get('objects', [])
                
                if not items:
                    print("⚠️ Список пуст. Возможно, данные в другом поле. Проверьте debug_data.json")
                else:
                    for item in items:
                        obj_id = item.get('id')
                        name = item.get('name', 'Без имени')
                        print(f"{obj_id:<40} | {name}")
            else:
                print(f"❌ Ошибка списка: {response.status_code}")
        else:
            print(f"❌ Сервер ответил: {res.text}. Доступ отклонен.")

    except Exception as e:
        print(f"❗ Произошла ошибка: {e}")

if __name__ == "__main__":
    get_vehicle_ids()