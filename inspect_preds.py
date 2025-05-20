# inspect_preds.py
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# ваш модуль API
from betai.api import get_fixtures, get_predictions

# загружаем .env
load_dotenv()

def main():
    # 1) Укажите дату, за которую хотим глянуть первый матч
    #    Формат YYYY, M, D — сегодня:
    today = datetime.now(timezone.utc).date()
    
    # 2) Получаем список матчей на сегодня
    fixtures = get_fixtures(today)["response"]
    if not fixtures:
        print("❌ Нет матчей на сегодня в топ-лигах.")
        return
    
    # 3) Изберём первый попавшийся матч из топ-лиг (ID из TOP_LEAGUES)
    #    Здесь трудно знать заранее, какие лиги придут, поэтому просто берём первый:
    fx = fixtures[0]
    fixture_id = fx["fixture"]["id"]
    print(f"У inspect_preds.py первый матч fixture_id = {fixture_id}")
    
    # 4) Забираем predictions
    preds = get_predictions(fixture_id)
    
    # 5) Сохраняем в файл / печатаем в консоль отформатированно
    print(json.dumps(preds, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
