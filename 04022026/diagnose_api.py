"""
Диагностический скрипт для проверки ответов Mobiteam API
Показывает что именно возвращает каждый метод
"""

import requests
import json


class MobiteamAPI:
    """Класс для работы с Mobiteam GPS API"""
    
    def __init__(self, base_url: str, login: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.login = login
        self.password = password
        self.session = requests.Session()
        self.session_id = None
        
    def connect(self) -> bool:
        """Авторизация и получение SessionId"""
        try:
            url = f"{self.base_url}/api/integration/v1/connect"
            
            params = {
                'login': self.login,
                'password': self.password,
                'lang': 'ru-ru',
                'timezone': '3'
            }
            
            print(f"🔗 Подключение к: {url}")
            print(f"   Параметры: {params}")
            
            response = self.session.get(url, params=params)
            
            print(f"\n📡 Ответ сервера:")
            print(f"   Status Code: {response.status_code}")
            print(f"   Response Text: {response.text}")
            print(f"   Headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.text.strip('"')
                
                if result == 'Ok':
                    self.session_id = response.headers.get('sessionid', response.headers.get('SessionId'))
                    
                    if self.session_id:
                        self.session.headers.update({'SessionId': self.session_id})
                        print(f"\n✓ Авторизация успешна")
                        print(f"   SessionId: {self.session_id}")
                        return True
            
            print(f"\n✗ Ошибка авторизации")
            return False
                
        except Exception as e:
            print(f"\n✗ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_objectslist(self):
        """Тестирование метода objectslist"""
        print("\n" + "=" * 70)
        print("ТЕСТ: objectslist")
        print("=" * 70)
        
        url = f"{self.base_url}/api/integration/v1/objectslist"
        
        print(f"🔗 URL: {url}")
        print(f"   Headers: {dict(self.session.headers)}")
        
        response = self.session.get(url)
        
        print(f"\n📡 Ответ сервера:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Content-Type: {response.headers.get('Content-Type')}")
        print(f"\n   Raw Response Text:")
        print(f"   {response.text}")
        
        try:
            data = response.json()
            print(f"\n   Parsed JSON:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"\n   ⚠ Не удалось распарсить JSON: {e}")
    
    def test_geozoneslist(self):
        """Тестирование метода geozoneslist"""
        print("\n" + "=" * 70)
        print("ТЕСТ: geozoneslist")
        print("=" * 70)
        
        url = f"{self.base_url}/api/integration/v1/geozoneslist"
        
        print(f"🔗 URL: {url}")
        
        response = self.session.get(url)
        
        print(f"\n📡 Ответ сервера:")
        print(f"   Status Code: {response.status_code}")
        print(f"\n   Raw Response Text:")
        print(f"   {response.text[:500]}...")  # Первые 500 символов
        
        try:
            data = response.json()
            print(f"\n   Parsed JSON (первые поля):")
            if isinstance(data, dict):
                for key, value in list(data.items())[:5]:
                    print(f"     {key}: {type(value).__name__}")
                    if key == 'result':
                        print(f"       value = {value}")
        except Exception as e:
            print(f"\n   ⚠ Не удалось распарсить JSON: {e}")
    
    def disconnect(self):
        """Закрытие сессии"""
        try:
            if self.session_id:
                url = f"{self.base_url}/api/integration/v1/disconnect"
                self.session.get(url)
                print("\n✓ Сессия закрыта")
        except:
            pass


def main():
    print("=" * 70)
    print("ДИАГНОСТИКА Mobiteam API")
    print("=" * 70)
    
    # ========================================
    # ПОСТОЯННЫЕ НАСТРОЙКИ (уже заполнено)
    # ========================================
    
    BASE_URL = "https://gps.mobiteam.com.ua"
    LOGIN = "abvprom"
    PASSWORD = "29328"
    
    # ========================================
    
    api = MobiteamAPI(BASE_URL, LOGIN, PASSWORD)
    
    if not api.connect():
        print("\n❌ Не удалось авторизоваться")
        return
    
    try:
        # Тестируем получение списка объектов
        api.test_objectslist()
        
        # Тестируем получение списка геозон
        api.test_geozoneslist()
        
    except KeyboardInterrupt:
        print("\n\n⚠ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        api.disconnect()
    
    print("\n" + "=" * 70)
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 70)
    print("\n💡 Скопируйте весь вывод и отправьте для анализа")


if __name__ == "__main__":
    main()
