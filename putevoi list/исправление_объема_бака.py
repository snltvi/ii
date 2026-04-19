import os
import pandas as pd
import sqlite3

# --- НАСТРОЙКИ ---
DB_NAME = "abv_fuel_in_out_comsum.db"

def main():
    # 1. Определяем папку, где лежит сам скрипт
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Ищем именно EXCEL файл (.xlsx), в названии которого есть "цепка"
    target_file_path = None
    for file in os.listdir(base_path):
        if file.lower().endswith(".xlsx") and "цепка" in file.lower():
            target_file_path = os.path.join(base_path, file)
            break

    if not target_file_path:
        print(f"❌ Ошибка: В папке {base_path} не найден Excel-файл (.xlsx) со словом 'Сцепка'")
        return

    print(f"📂 Нашел Excel-файл: {os.path.basename(target_file_path)}")

    try:
        # 3. Читаем Excel файл напрямую
        # engine='openpyxl' позволяет читать современные форматы .xlsx
        df = pd.read_excel(target_file_path, engine='openpyxl')
        
        # Чистим названия колонок
        df.columns = [str(c).strip() for c in df.columns]
        
        if 'ID объекта' not in df.columns or 'Бак' not in df.columns:
            print(f"❌ Ошибка: В Excel не найдены колонки 'ID объекта' или 'Бак'.")
            print(f"Найденные колонки: {list(df.columns)}")
            return

        # Убираем пустые строки
        df_clean = df[['ID объекта', 'Бак']].dropna()
        df_clean['ID объекта'] = df_clean['ID объекта'].astype(int)

        # 4. Обновляем базу данных
        db_path = os.path.join(base_path, DB_NAME)
        if not os.path.exists(db_path):
            print(f"❌ База данных {DB_NAME} не найдена в папке {base_path}!")
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("🔄 Синхронизирую баки из Excel в базу данных...")
        total_fixed = 0
        
        for _, row in df_clean.iterrows():
            oid = int(row['ID объекта'])
            tank = int(row['Бак'])
            
            # Обновляем все записи для этого автомобиля
            cursor.execute("UPDATE abv_fuel_in_out_comsum SET tank_volume = ? WHERE obj_id = ?", (tank, oid))
            total_fixed += cursor.rowcount

        conn.commit()
        conn.close()

        print(f"✅ Успешно! Исправлено записей в базе: {total_fixed}")

    except Exception as e:
        print(f"💥 Ошибка при чтении Excel-файла: {e}")

if __name__ == "__main__":
    main()