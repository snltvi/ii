"""
Скрипт для просмотра всех датчиков на всех объектах
Mobiteam GPS API
"""

import requests
import json
from typing import List, Dict


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
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                result = response.text.strip('"')
                
                if result == 'Ok':
                    self.session_id = response.headers.get('sessionid', response.headers.get('SessionId'))
                    
                    if self.session_id:
                        self.session.headers.update({'SessionId': self.session_id})
                        print("✓ Успешная авторизация")
                        return True
            
            print(f"✗ Ошибка авторизации")
            return False
                
        except Exception as e:
            print(f"✗ Ошибка: {e}")
            return False
    
    def get_objects_list(self) -> List[Dict]:
        """Получение списка объектов"""
        try:
            url = f"{self.base_url}/api/integration/v1/objectslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('result') == 'Ok':
                    return data.get('objects', [])
            return []
        except:
            return []
    
    def get_object_sensors(self, object_id: int) -> List[Dict]:
        """Получение списка датчиков объекта"""
        try:
            url = f"{self.base_url}/api/integration/v1/objsensorslist"
            
            params = {'oid': object_id}
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('result') == 'Ok':
                    return data.get('obj_sensors', [])
            return []
        except:
            return []
    
    def disconnect(self):
        """Закрытие сессии"""
        try:
            if self.session_id:
                url = f"{self.base_url}/api/integration/v1/disconnect"
                self.session.get(url)
        except:
            pass


def main():
    print("=" * 70)
    print("Mobiteam GPS - Просмотр датчиков на транспортных средствах")
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
        print("❌ Не удалось авторизоваться")
        return
    
    try:
        print("\n📋 Загрузка списка транспортных средств...")
        objects = api.get_objects_list()
        
        if not objects:
            print("⚠ Объекты не найдены")
            return
        
        print(f"✓ Найдено объектов: {len(objects)}\n")
        
        # Проходим по всем объектам
        for obj in objects:
            obj_id = obj.get('id', obj.get('oid'))
            obj_name = obj.get('name', 'Без названия')
            obj_plate = obj.get('plate_num', obj.get('plate', ''))
            
            print("─" * 70)
            print(f"🚗 {obj_name} ({obj_plate})")
            print(f"   ID объекта: {obj_id}")
            
            # Получаем датчики для этого объекта
            sensors = api.get_object_sensors(obj_id)
            
            if sensors:
                print(f"   ✓ Датчиков: {len(sensors)}")
                print("\n   Список датчиков:")
                
                for sensor in sensors:
                    sensor_id = sensor.get('sid', 'N/A')
                    sensor_pid = sensor.get('pid', 'N/A')
                    sensor_name = sensor.get('name', 'Без названия')
                    sensor_icon = sensor.get('icon', '')
                    
                    print(f"     • {sensor_name}")
                    print(f"       - ID датчика (sid): {sensor_id}")
                    print(f"       - ID протокольного датчика (pid): {sensor_pid}")
                    if sensor_icon:
                        print(f"       - Иконка: {sensor_icon}")
            else:
                print("   ⚠ Датчики не найдены")
            
            print()
        
        print("─" * 70)
        
        # Подсказка о типах датчиков
        print("\n💡 Типичные датчики:")
        print("   • Одометр - общий пробег транспорта")
        print("   • ДУТ (датчик уровня топлива) - уровень топлива в баке")
        print("   • Зажигание - включен/выключен двигатель")
        print("   • Скорость - текущая скорость движения")
        print("   • Температура - для рефрижераторов")
        print("   • Моточасы - общее время работы двигателя")
        
        print("\n💡 Для получения показаний датчиков используйте:")
        print("   - API метод: /api/integration/v1/track")
        print("   - В каждой точке трека есть показания датчиков")
        
    except KeyboardInterrupt:
        print("\n⚠ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
    finally:
        api.disconnect()
    
    print("\n" + "=" * 70)
    print("Готово!")
    print("=" * 70)


if __name__ == "__main__":
    main()
