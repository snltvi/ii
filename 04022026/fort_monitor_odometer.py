"""
Скрипт для получения показаний одометра при выезде/въезде из геозоны гаража
через Fort Monitor 3 API
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple


class FortMonitorAPI:
    """Класс для работы с Fort Monitor 3 API"""
    
    def __init__(self, base_url: str, username: str, password: str):
        """
        Инициализация подключения к API
        
        Args:
            base_url: Базовый URL сервера Fort Monitor (например: https://web.fort-monitor.ru)
            username: Имя пользователя
            password: Пароль
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session_id = None
        
    def connect(self) -> bool:
        """
        Подключение к API и получение SessionId
        
        Returns:
            True если подключение успешно, False в противном случае
        """
        try:
            url = f"{self.base_url}/api/integration/v1/connect"
            
            payload = {
                "userName": self.username,
                "password": self.password
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 200:
                # Получаем SessionId из заголовков
                self.session_id = response.headers.get('SessionId')
                
                if self.session_id:
                    # Устанавливаем SessionId для последующих запросов
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
        """
        Получение списка доступных объектов (транспортных средств)
        
        Returns:
            Список объектов
        """
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
        """
        Получение списка геозон
        
        Returns:
            Список геозон
        """
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
    
    def get_object_data(self, object_id: int, date_from: datetime, 
                        date_to: datetime) -> Optional[Dict]:
        """
        Получение данных объекта за период (включая пробег, события, треки)
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Данные объекта или None
        """
        try:
            url = f"{self.base_url}/api/integration/v1/fullobjinfo"
            
            params = {
                'objectId': object_id,
                'from': date_from.strftime('%Y-%m-%dT%H:%M:%S'),
                'to': date_to.strftime('%Y-%m-%dT%H:%M:%S'),
                'param': 'actions;events;mileage'  # Запрашиваем действия, события и пробег
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"✗ Ошибка получения данных объекта: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"✗ Ошибка при получении данных объекта: {e}")
            return None
    
    def get_track(self, object_id: int, date_from: datetime, 
                  date_to: datetime) -> List[Dict]:
        """
        Получение трека движения объекта с показаниями одометра
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Список точек трека
        """
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
    Упрощенная проверка для круговых геозон
    
    Args:
        lat: Широта точки
        lon: Долгота точки
        geozone: Данные геозоны
        
    Returns:
        True если точка внутри геозоны
    """
    # Для простоты реализуем проверку только для круговых геозон
    # Для полигонов нужна более сложная логика
    if geozone.get('geo_type') == 0:  # Круг
        points = geozone.get('points', [])
        if points:
            center = points[0]
            center_lat = center.get('lat', 0)
            center_lon = center.get('lon', 0)
            radius = geozone.get('geo_radius', 0)  # в метрах
            
            # Упрощенное вычисление расстояния
            # Для более точного расчета нужна формула Haversine
            lat_diff = abs(lat - center_lat)
            lon_diff = abs(lon - center_lon)
            
            # Примерное расстояние (1 градус ≈ 111 км)
            distance = ((lat_diff * 111000) ** 2 + (lon_diff * 111000) ** 2) ** 0.5
            
            return distance <= radius
    
    return False


def find_garage_enter_exit_events(api: FortMonitorAPI, object_id: int, 
                                   garage_geozone_id: int, date: datetime) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Поиск событий выезда из гаража и въезда в гараж за день
    
    Args:
        api: Экземпляр API
        object_id: ID объекта
        garage_geozone_id: ID геозоны гаража
        date: Дата для поиска
        
    Returns:
        Кортеж (первый_выезд, последний_въезд) с данными о пробеге
    """
    # Получаем данные за весь день
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n📅 Анализ данных за {date.strftime('%d.%m.%Y')}...")
    
    # Получаем трек движения
    track = api.get_track(object_id, date_from, date_to)
    
    if not track:
        print("⚠ Трек движения не найден")
        return None, None
    
    print(f"✓ Получено {len(track)} точек трека")
    
    # Получаем информацию о геозоне
    geozones = api.get_geozones()
    garage_geozone = None
    
    for gz in geozones:
        if gz.get('id') == garage_geozone_id:
            garage_geozone = gz
            break
    
    if not garage_geozone:
        print(f"✗ Геозона с ID {garage_geozone_id} не найдена")
        return None, None
    
    # Ищем первый выезд и последний въезд
    first_exit = None
    last_enter = None
    prev_in_garage = None
    
    for i, point in enumerate(track):
        lat = point.get('lat', 0)
        lon = point.get('lon', 0)
        mileage = point.get('mileage', 0)  # Показание одометра
        dt = point.get('dt', '')  # Время точки
        
        in_garage = is_point_in_geozone(lat, lon, garage_geozone)
        
        # Определяем момент выезда (был в гараже, стал вне гаража)
        if prev_in_garage is not None:
            if prev_in_garage and not in_garage and first_exit is None:
                # Первый выезд
                first_exit = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🚗 Выезд: {dt}, одометр: {mileage:.2f} км")
            
            elif not prev_in_garage and in_garage:
                # Въезд (обновляем последний)
                last_enter = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🏠 Въезд: {dt}, одометр: {mileage:.2f} км")
        
        prev_in_garage = in_garage
    
    return first_exit, last_enter


def main():
    """Главная функция"""
    
    print("=" * 60)
    print("Fort Monitor 3 - Получение показаний одометра")
    print("=" * 60)
    
    # Настройки подключения (ЗАПОЛНИТЕ СВОИ ДАННЫЕ)
    BASE_URL = "https://web.fort-monitor.ru"  # Или адрес вашего сервера
    USERNAME = "ваш_логин"
    PASSWORD = "ваш_пароль"
    
    # Инициализация API
    api = FortMonitorAPI(BASE_URL, USERNAME, PASSWORD)
    
    # Подключение
    if not api.connect():
        print("\n❌ Не удалось подключиться к API")
        return
    
    try:
        # Получение списка объектов
        print("\n📋 Загрузка списка транспортных средств...")
        objects = api.get_objects_list()
        
        if not objects:
            print("⚠ Объекты не найдены")
            return
        
        print(f"✓ Найдено объектов: {len(objects)}")
        print("\nДоступные транспортные средства:")
        for i, obj in enumerate(objects, 1):
            print(f"  {i}. ID: {obj.get('id')} - {obj.get('name')} ({obj.get('gos_num', 'без номера')})")
        
        # Выбор объекта
        object_choice = int(input("\nВыберите номер транспортного средства: ")) - 1
        selected_object = objects[object_choice]
        object_id = selected_object.get('id')
        
        print(f"\n✓ Выбран объект: {selected_object.get('name')}")
        
        # Получение списка геозон
        print("\n📍 Загрузка списка геозон...")
        geozones = api.get_geozones()
        
        if not geozones:
            print("⚠ Геозоны не найдены")
            return
        
        print(f"✓ Найдено геозон: {len(geozones)}")
        print("\nДоступные геозоны:")
        for i, gz in enumerate(geozones, 1):
            print(f"  {i}. ID: {gz.get('id')} - {gz.get('name')}")
        
        # Выбор геозоны гаража
        geozone_choice = int(input("\nВыберите номер геозоны гаража: ")) - 1
        selected_geozone = geozones[geozone_choice]
        garage_geozone_id = selected_geozone.get('id')
        
        print(f"\n✓ Выбрана геозона: {selected_geozone.get('name')}")
        
        # Выбор даты
        date_input = input("\nВведите дату (ДД.ММ.ГГГГ) или нажмите Enter для сегодняшнего дня: ").strip()
        
        if date_input:
            target_date = datetime.strptime(date_input, "%d.%m.%Y")
        else:
            target_date = datetime.now()
        
        # Поиск событий выезда/въезда
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
        # Отключение
        api.disconnect()
    
    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()
