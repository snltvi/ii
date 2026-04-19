"""
Скрипт для получения показаний одометра при выезде/въезде из геозоны гаража
через Fort Monitor 3 API (версия с конфигурационным файлом)
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import os


class FortMonitorAPI:
    """Класс для работы с Fort Monitor 3 API"""
    
    def __init__(self, base_url: str, username: str, password: str):
        """
        Инициализация подключения к API
        
        Args:
            base_url: Базовый URL сервера Fort Monitor
            username: abvprom
            password: 29328
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session_id = None
        
    def connect(self) -> bool:
        """Подключение к API и получение SessionId"""
        try:
            url = f"{self.base_url}/api/integration/v1/connect"
            
            payload = {
                "userName": self.username,
                "password": self.password
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 200:
                self.session_id = response.headers.get('SessionId')
                
                if self.session_id:
                    self.session.headers.update({'SessionId': self.session_id})
                    print("✓ Успешное подключение к Fort Monitor API")
                    return True
                else:
                    print("✗ Ошибка: SessionId не получен")
                    return False
            else:
                print(f"✗ Ошибка подключения: {response.status_code}")
                print(f"  Ответ: {response.text}")
                return False
                
        except Exception as e:
            print(f"✗ Ошибка при подключении: {e}")
            return False
    
    def disconnect(self):
        """Отключение от API"""
        try:
            url = f"{self.base_url}/api/integration/v1/disconnect"
            self.session.post(url)
            print("✓ Отключение от API")
        except Exception as e:
            print(f"⚠ Предупреждение при отключении: {e}")
    
    def get_objects_list(self) -> List[Dict]:
        """Получение списка доступных объектов"""
        try:
            url = f"{self.base_url}/api/integration/v1/objectslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('objects', [])
            else:
                print(f"✗ Ошибка получения списка объектов: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении списка объектов: {e}")
            return []
    
    def get_geozones(self) -> List[Dict]:
        """Получение списка геозон"""
        try:
            url = f"{self.base_url}/api/integration/v1/geozoneslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('geozones', [])
            else:
                print(f"✗ Ошибка получения списка геозон: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении списка геозон: {e}")
            return []
    
    def get_track(self, object_id: int, date_from: datetime, 
                  date_to: datetime) -> List[Dict]:
        """Получение трека движения объекта"""
        try:
            url = f"{self.base_url}/api/integration/v1/track"
            
            params = {
                'objectId': object_id,
                'from': date_from.strftime('%Y-%m-%dT%H:%M:%S'),
                'to': date_to.strftime('%Y-%m-%dT%H:%M:%S')
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('track', [])
            else:
                print(f"✗ Ошибка получения трека: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении трека: {e}")
            return []


def is_point_in_geozone(lat: float, lon: float, geozone: Dict) -> bool:
    """
    Проверка, находится ли точка внутри геозоны
    (Упрощенная проверка для круговых геозон)
    """
    if geozone.get('geo_type') == 0:  # Круг
        points = geozone.get('points', [])
        if points:
            center = points[0]
            center_lat = center.get('lat', 0)
            center_lon = center.get('lon', 0)
            radius = geozone.get('geo_radius', 0)
            
            lat_diff = abs(lat - center_lat)
            lon_diff = abs(lon - center_lon)
            distance = ((lat_diff * 111000) ** 2 + (lon_diff * 111000) ** 2) ** 0.5
            
            return distance <= radius
    
    return False


def find_garage_enter_exit_events(api: FortMonitorAPI, object_id: int, 
                                   garage_geozone_id: int, date: datetime) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Поиск событий выезда и въезда за день"""
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n📅 Анализ данных за {date.strftime('%d.%m.%Y')}...")
    
    track = api.get_track(object_id, date_from, date_to)
    
    if not track:
        print("⚠ Трек движения не найден")
        return None, None
    
    print(f"✓ Получено {len(track)} точек трека")
    
    geozones = api.get_geozones()
    garage_geozone = None
    
    for gz in geozones:
        if gz.get('id') == garage_geozone_id:
            garage_geozone = gz
            break
    
    if not garage_geozone:
        print(f"✗ Геозона с ID {garage_geozone_id} не найдена")
        return None, None
    
    first_exit = None
    last_enter = None
    prev_in_garage = None
    
    for point in track:
        lat = point.get('lat', 0)
        lon = point.get('lon', 0)
        mileage = point.get('mileage', 0)
        dt = point.get('dt', '')
        
        in_garage = is_point_in_geozone(lat, lon, garage_geozone)
        
        if prev_in_garage is not None:
            if prev_in_garage and not in_garage and first_exit is None:
                first_exit = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🚗 Выезд: {dt}, одометр: {mileage:.2f} км")
            
            elif not prev_in_garage and in_garage:
                last_enter = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🏠 Въезд: {dt}, одометр: {mileage:.2f} км")
        
        prev_in_garage = in_garage
    
    return first_exit, last_enter


def load_config():
    """Загрузка конфигурации из файла config.py"""
    try:
        import config
        return {
            'url': config.FORT_MONITOR_URL,
            'username': config.FORT_MONITOR_USERNAME,
            'password': config.FORT_MONITOR_PASSWORD,
            'vehicle_id': getattr(config, 'VEHICLE_ID', None),
            'garage_geozone_id': getattr(config, 'GARAGE_GEOZONE_ID', None)
        }
    except ImportError:
        return None


def save_config(vehicle_id: int = None, garage_geozone_id: int = None):
    """Сохранение выбранных ID в config.py"""
    config_file = 'config.py'
    
    if not os.path.exists(config_file):
        # Создаем новый файл конфигурации
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write('# Конфигурация Fort Monitor\n\n')
            f.write(f'FORT_MONITOR_URL = "https://web.fort-monitor.ru"\n')
            f.write(f'FORT_MONITOR_USERNAME = "ваш_логин"\n')
            f.write(f'FORT_MONITOR_PASSWORD = "ваш_пароль"\n\n')
            
            if vehicle_id:
                f.write(f'VEHICLE_ID = {vehicle_id}\n')
            if garage_geozone_id:
                f.write(f'GARAGE_GEOZONE_ID = {garage_geozone_id}\n')
        
        print(f"\n✓ Создан файл конфигурации: {config_file}")
    else:
        # Обновляем существующий файл
        with open(config_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        with open(config_file, 'w', encoding='utf-8') as f:
            vehicle_updated = False
            garage_updated = False
            
            for line in lines:
                if line.startswith('VEHICLE_ID') and vehicle_id:
                    f.write(f'VEHICLE_ID = {vehicle_id}\n')
                    vehicle_updated = True
                elif line.startswith('GARAGE_GEOZONE_ID') and garage_geozone_id:
                    f.write(f'GARAGE_GEOZONE_ID = {garage_geozone_id}\n')
                    garage_updated = True
                else:
                    f.write(line)
            
            if vehicle_id and not vehicle_updated:
                f.write(f'\nVEHICLE_ID = {vehicle_id}\n')
            if garage_geozone_id and not garage_updated:
                f.write(f'GARAGE_GEOZONE_ID = {garage_geozone_id}\n')
        
        print(f"\n✓ Обновлен файл конфигурации: {config_file}")


def main():
    """Главная функция"""
    
    print("=" * 60)
    print("Fort Monitor 3 - Получение показаний одометра")
    print("=" * 60)
    
    # Загрузка конфигурации
    config = load_config()
    
    if config:
        print("\n✓ Загружена конфигурация из config.py")
        BASE_URL = config['url']
        USERNAME = config['username']
        PASSWORD = config['password']
        saved_vehicle_id = config['vehicle_id']
        saved_garage_id = config['garage_geozone_id']
    else:
        print("\n⚠ Файл config.py не найден, используются настройки по умолчанию")
        BASE_URL = "https://web.fort-monitor.ru"
        USERNAME = "ваш_логин"
        PASSWORD = "ваш_пароль"
        saved_vehicle_id = None
        saved_garage_id = None
    
    # Инициализация API
    api = FortMonitorAPI(BASE_URL, USERNAME, PASSWORD)
    
    if not api.connect():
        print("\n❌ Не удалось подключиться к API")
        print("Проверьте настройки в файле config.py")
        return
    
    try:
        # Получение списка объектов
        print("\n📋 Загрузка списка транспортных средств...")
        objects = api.get_objects_list()
        
        if not objects:
            print("⚠ Объекты не найдены")
            return
        
        print(f"✓ Найдено объектов: {len(objects)}")
        
        # Выбор объекта
        if saved_vehicle_id:
            object_id = saved_vehicle_id
            selected_object = next((obj for obj in objects if obj.get('id') == object_id), None)
            if selected_object:
                print(f"\n✓ Используется сохраненный объект: {selected_object.get('name')}")
            else:
                print(f"\n⚠ Сохраненный объект ID {object_id} не найден")
                saved_vehicle_id = None
        
        if not saved_vehicle_id:
            print("\nДоступные транспортные средства:")
            for i, obj in enumerate(objects, 1):
                print(f"  {i}. ID: {obj.get('id')} - {obj.get('name')} ({obj.get('gos_num', 'без номера')})")
            
            object_choice = int(input("\nВыберите номер транспортного средства: ")) - 1
            selected_object = objects[object_choice]
            object_id = selected_object.get('id')
            
            # Предложение сохранить выбор
            save_choice = input("\nСохранить выбор в config.py? (y/n): ").lower()
            if save_choice == 'y':
                save_config(vehicle_id=object_id)
        
        # Получение списка геозон
        print("\n📍 Загрузка списка геозон...")
        geozones = api.get_geozones()
        
        if not geozones:
            print("⚠ Геозоны не найдены")
            return
        
        print(f"✓ Найдено геозон: {len(geozones)}")
        
        # Выбор геозоны
        if saved_garage_id:
            garage_geozone_id = saved_garage_id
            selected_geozone = next((gz for gz in geozones if gz.get('id') == garage_geozone_id), None)
            if selected_geozone:
                print(f"\n✓ Используется сохраненная геозона: {selected_geozone.get('name')}")
            else:
                print(f"\n⚠ Сохраненная геозона ID {garage_geozone_id} не найдена")
                saved_garage_id = None
        
        if not saved_garage_id:
            print("\nДоступные геозоны:")
            for i, gz in enumerate(geozones, 1):
                print(f"  {i}. ID: {gz.get('id')} - {gz.get('name')}")
            
            geozone_choice = int(input("\nВыберите номер геозоны гаража: ")) - 1
            selected_geozone = geozones[geozone_choice]
            garage_geozone_id = selected_geozone.get('id')
            
            # Предложение сохранить выбор
            save_choice = input("\nСохранить выбор в config.py? (y/n): ").lower()
            if save_choice == 'y':
                save_config(vehicle_id=object_id if not saved_vehicle_id else None, 
                           garage_geozone_id=garage_geozone_id)
        
        # Выбор даты
        date_input = input("\nВведите дату (ДД.ММ.ГГГГ) или нажмите Enter для сегодняшнего дня: ").strip()
        
        if date_input:
            target_date = datetime.strptime(date_input, "%d.%m.%Y")
        else:
            target_date = datetime.now()
        
        # Поиск событий
        first_exit, last_enter = find_garage_enter_exit_events(
            api, object_id, garage_geozone_id, target_date
        )
        
        # Вывод результатов
        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТ")
        print("=" * 60)
        
        if first_exit:
            print(f"\n🚗 ВЫЕЗД ИЗ ГАРАЖА:")
            print(f"   Время: {first_exit['time']}")
            print(f"   Показание одометра: {first_exit['mileage']:.2f} км")
        else:
            print("\n⚠ Выезд из гаража не обнаружен")
        
        if last_enter:
            print(f"\n🏠 ВЪЕЗД В ГАРАЖ:")
            print(f"   Время: {last_enter['time']}")
            print(f"   Показание одометра: {last_enter['mileage']:.2f} км")
        else:
            print("\n⚠ Въезд в гараж не обнаружен")
        
        if first_exit and last_enter:
            daily_mileage = last_enter['mileage'] - first_exit['mileage']
            print(f"\n📊 ПРОБЕГ ЗА ДЕНЬ: {daily_mileage:.2f} км")
        
    finally:
        api.disconnect()
    
    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()