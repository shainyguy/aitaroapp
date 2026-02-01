from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import hashlib
import hmac
import json
import os
import aiosqlite

app = FastAPI()

# CORS для Mini App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_PATH = "astro_bot.db"


# ==================== МОДЕЛИ ====================

class ActionRequest(BaseModel):
    user_id: int
    action: str
    data: Dict[str, Any] = {}


# ==================== ПРОВЕРКА TELEGRAM ====================

def verify_telegram_data(init_data: str) -> Optional[dict]:
    """Проверка данных от Telegram"""
    if not init_data or not BOT_TOKEN:
        return None
    
    try:
        parsed = dict(x.split('=') for x in init_data.split('&'))
        check_hash = parsed.pop('hash', None)
        
        if not check_hash:
            return None
        
        # Создаём строку для проверки
        data_check = '\n'.join(f'{k}={v}' for k, v in sorted(parsed.items()))
        
        # Создаём секретный ключ
        secret_key = hmac.new(
            b'WebAppData', 
            BOT_TOKEN.encode(), 
            hashlib.sha256
        ).digest()
        
        # Проверяем хеш
        calculated_hash = hmac.new(
            secret_key,
            data_check.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if calculated_hash == check_hash:
            if 'user' in parsed:
                return json.loads(parsed['user'])
        
        return None
    except Exception as e:
        print(f"Verification error: {e}")
        return None


# ==================== БАЗА ДАННЫХ ====================

async def get_user_data(user_id: int) -> dict:
    """Получить данные пользователя"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                user = await cursor.fetchone()
                
            if not user:
                return {}
            
            user = dict(user)
            
            # Статистика рефералов
            async with db.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)
            ) as cursor:
                referrals = (await cursor.fetchone())[0]
            
            # Знак зодиака
            zodiac_map = {
                'aries': ('Овен', '♈'), 'taurus': ('Телец', '♉'),
                'gemini': ('Близнецы', '♊'), 'cancer': ('Рак', '♋'),
                'leo': ('Лев', '♌'), 'virgo': ('Дева', '♍'),
                'libra': ('Весы', '♎'), 'scorpio': ('Скорпион', '♏'),
                'sagittarius': ('Стрелец', '♐'), 'capricorn': ('Козерог', '♑'),
                'aquarius': ('Водолей', '♒'), 'pisces': ('Рыбы', '♓')
            }
            
            zodiac_key = user.get('zodiac_sign', '')
            zodiac_info = zodiac_map.get(zodiac_key, (None, None))
            
            return {
                'id': user_id,
                'name': user.get('first_name', 'Путник'),
                'zodiac': zodiac_info[0],
                'zodiacEmoji': zodiac_info[1],
                'subscription': user.get('subscription_until') is not None,
                'readings': user.get('free_readings_used', 0),
                'referrals': referrals,
                'bonusDays': user.get('referral_bonus_days', 0)
            }
    except Exception as e:
        print(f"Database error: {e}")
        return {}


async def log_action(user_id: int, action: str, data: dict):
    """Логирование действий"""
    print(f"User {user_id}: {action} - {data}")


# ==================== ЭНДПОИНТЫ ====================

@app.get("/")
async def root():
    """Главная страница — Mini App"""
    return FileResponse("index.html")


@app.get("/api/user/{user_id}")
async def get_user(user_id: int, request: Request):
    """Получить данные пользователя"""
    # Проверяем Telegram данные
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    # tg_user = verify_telegram_data(init_data)  # Опционально
    
    user_data = await get_user_data(user_id)
    return JSONResponse(user_data)


@app.post("/api/action")
async def handle_action(action_req: ActionRequest, request: Request):
    """Обработка действий из Mini App"""
    
    user_id = action_req.user_id
    action = action_req.action
    data = action_req.data
    
    await log_action(user_id, action, data)
    
    # Обрабатываем разные действия
    if action == "tarot_reading":
        return {"status": "ok", "message": "Расклад сохранён"}
    
    elif action == "horoscope":
        return {
            "status": "ok",
            "text": "Звёзды благоволят вашим начинаниям. Сегодня хороший день для новых проектов."
        }
    
    elif action == "compatibility":
        return {"status": "ok", "score": data.get("score", 75)}
    
    elif action == "money_forecast":
        return {
            "status": "ok",
            "text": "Финансовая удача на вашей стороне. Благоприятные дни: вторник и четверг."
        }
    
    elif action == "karma_analysis":
        return {
            "status": "ok",
            "text": "Ваша душа несёт опыт многих жизней. Главный урок — научиться доверять."
        }
    
    elif action == "buy_premium":
        # Здесь можно отправить сообщение в бот
        return {"status": "ok", "redirect": "bot"}
    
    elif action == "share_referral":
        return {"status": "ok"}
    
    return {"status": "ok"}


@app.get("/health")
async def health():
    """Проверка здоровья"""
    return {"status": "healthy"}


# Запуск
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)