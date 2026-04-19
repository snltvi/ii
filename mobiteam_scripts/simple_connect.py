"""
Простой скрипт для подключения к Mobiteam API через метод connect
"""

import requests


def connect_to_mobiteam(login, password):
    """
    Подключение к Mobiteam API через метод connect
    
    Args:
        login: Ваш логин
        password: Ваш пароль
        
    Returns:
        SessionId если успешно, None если ошибка
    """
    
    # URL для подключения
    url = "https://gps.mobiteam.com.ua/api/integration/v1/connect"
    
    # Параметры запроса
    params = {
        'login': login,
        'password': password,
        'lang': 'ru-ru',      # Язык (ru-ru, en-us, ro-ro, ka-ge)
        'timezone': '3'        # Часовой пояс UTC+3 (для Украины)
    }
    
    print("🔗 Подключение к Mobiteam API...")
    print(f"   URL: {url}")
    print(f"   Логин: {login}")
    
    try:
        # Выполняем GET запрос
        response = requests.get(url, params=params)
        
        print(f"\n📡 Ответ сервера:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text}")
        
        # Проверяем успешность
        if response.status_code == 200:
            result = response.text.strip('"')  # Убираем кавычки из "Ok"
            
            if result == 'Ok':
                # Получаем SessionId из заголовков
                session_id = response.headers.get('sessionid') or response.headers.get('SessionId')
                
                if session_id:
                    print(f"\n✅ УСПЕШНОЕ ПОДКЛЮЧЕНИЕ!")
                    print(f"   SessionId: {session_id}")
                    print(f"\n💡 Используйте этот SessionId для всех последующих запросов")
                    return session_id
                else:
                    print("\n❌ Ошибка: SessionId не получен")
                    return None
            else:
                print(f"\n❌ Ошибка авторизации: {result}")
                return None
        else:
            print(f"\n❌ Ошибка HTTP: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"\n❌ Ошибка подключения: {e}")
        return None


def main():
    """Основная функция"""
    
    print("=" * 60)
    print("Подключение к Mobiteam API через метод connect")
    print("=" * 60)
    
    # ========================================
    # ПОСТОЯННЫЕ НАСТРОЙКИ (уже заполнено)
    # ========================================
    
    LOGIN = "abvprom"
    PASSWORD = "29328"
    
    # ========================================
    
    # Выполняем подключение
    session_id = connect_to_mobiteam(LOGIN, PASSWORD)
    
    if session_id:
        print("\n" + "=" * 60)
        print("✅ Подключение успешно!")
        print("=" * 60)
        print(f"\nВаш SessionId:\n{session_id}")
        print("\nТеперь добавляйте этот SessionId в заголовок всех запросов:")
        print(f"Header: SessionId: {session_id}")
    else:
        print("\n" + "=" * 60)
        print("❌ Подключение не удалось")
        print("=" * 60)
        print("\nПроверьте:")
        print("1. Правильность логина и пароля")
        print("2. Доступность сервера gps.mobiteam.com.ua")
        print("3. Подключение к интернету")


if __name__ == "__main__":
    main()
