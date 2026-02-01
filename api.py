from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import aiohttp
import os
import json
import aiosqlite
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "astro_bot.db")
STARS_PRICE = 250


class ActionRequest(BaseModel):
    user_id: int
    action: str
    data: Dict[str, Any] = {}


class InvoiceRequest(BaseModel):
    user_id: int
    product: str
    method: str


# ==================== БАЗА ДАННЫХ ====================

async def get_user_data(user_id: int) -> dict:
    """Получить данные пользователя из БД бота"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                user = await cursor.fetchone()
            
            if not user:
                return {
                    'userId': user_id,
                    'isPremium': False,
                    'freeUsed': 0,
                    'readings': 0,
                    'bonusDays': 0
                }
            
            user = dict(user)
            
            # Проверяем подписку
            is_premium = False
            if user.get('subscription_until'):
                sub_until = datetime.fromisoformat(user['subscription_until'])
                is_premium = sub_until > datetime.now()
            
            # Зодиак
            zodiac_map = {
                'aries': ('Овен', '♈'), 'taurus': ('Телец', '♉'),
                'gemini': ('Близнецы', '♊'), 'cancer': ('Рак', '♋'),
                'leo': ('Лев', '♌'), 'virgo': ('Дева', '♍'),
                'libra': ('Весы', '♎'), 'scorpio': ('Скорпион', '♏'),
                'sagittarius': ('Стрелец', '♐'), 'capricorn': ('Козерог', '♑'),
                'aquarius': ('Водолей', '♒'), 'pisces': ('Рыбы', '♓')
            }
            
            zodiac_key = user.get('zodiac_sign', '')
            zodiac_info = zodiac_map.get(zodiac_key, ('Овен', '♈'))
            
            # Статистика рефералов
            async with db.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)
            ) as cursor:
                referrals = (await cursor.fetchone())[0]
            
            return {
                'userId': user_id,
                'userName': user.get('first_name', 'Путник'),
                'zodiac': zodiac_info[0],
                'zodiacEmoji': zodiac_info[1],
                'isPremium': is_premium,
                'freeUsed': user.get('free_readings_used', 0),
                'readings': user.get('free_readings_used', 0),
                'referrals': referrals,
                'bonusDays': user.get('referral_bonus_days', 0)
            }
    except Exception as e:
        print(f"Database error: {e}")
        return {
            'userId': user_id,
            'isPremium': False,
            'freeUsed': 0,
            'readings': 0
        }


async def increment_readings(user_id: int):
    """Увеличить счётчик использований"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE users SET free_readings_used = free_readings_used + 1
                WHERE user_id = ?
            """, (user_id,))
            await db.commit()
    except Exception as e:
        print(f"Database error: {e}")


# ==================== TELEGRAM BOT API ====================

async def create_stars_invoice(user_id: int) -> Optional[str]:
    """Создать инвойс для Telegram Stars"""
    if not BOT_TOKEN:
        return None
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    
    payload = {
        "title": "⭐ Премиум подписка",
        "description": "Безлимитный доступ на 30 дней",
        "payload": f"subscription_{user_id}",
        "currency": "XTR",  # Telegram Stars
        "prices": [{"label": "Подписка", "amount": STARS_PRICE}]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok"):
                        return data["result"]
    except Exception as e:
        print(f"Invoice error: {e}")
    
    return None


async def send_message_to_user(user_id: int, text: str):
    """Отправить сообщение пользователю"""
    if not BOT_TOKEN:
        return
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={
                "chat_id": user_id,
                "text": text,
                "parse_mode": "Markdown"
            })
    except Exception as e:
        print(f"Send message error: {e}")


# ==================== ЭНДПОИНТЫ ====================

@app.get("/")
async def root():
    return FileResponse("index.html")


@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    """Получить данные пользователя"""
    data = await get_user_data(user_id)
    return JSONResponse(data)


@app.post("/api/action")
async def handle_action(req: ActionRequest):
    """Обработка действий"""
    
    if req.action == "use_reading":
        await increment_readings(req.user_id)
        return {"status": "ok"}
    
    elif req.action == "buy_subscription":
        # Отправляем сообщение в бот
        await send_message_to_user(
            req.user_id,
            "💳 Для оформления подписки нажми /start и выбери «⭐ Подписка»"
        )
        return {"status": "ok", "redirect": "bot"}
    
    return {"status": "ok"}


@app.post("/api/create-invoice")
async def create_invoice(req: InvoiceRequest):
    """Создать инвойс для оплаты"""
    
    if req.method == "stars":
        invoice_link = await create_stars_invoice(req.user_id)
        
        if invoice_link:
            return {"status": "ok", "invoice_link": invoice_link}
        else:
            return {"status": "error", "message": "Failed to create invoice"}
    
    elif req.method == "yookassa":
        # Для ЮKassa отправляем в бот
        await send_message_to_user(
            req.user_id,
            "💳 Переходи к оплате в боте: /start → Подписка"
        )
        return {"status": "ok", "redirect": "bot"}
    
    return {"status": "error"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
