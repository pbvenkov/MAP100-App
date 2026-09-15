import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

# ==========================================================
# 0. АВТОЗАГРУЗКА .ENV И БЕЗОПАСНЫЙ ИМПОРТ
# ==========================================================

env_file = Path(".env")
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

try:
    import typst
    PY_TYPST_AVAILABLE = True
except ImportError:
    PY_TYPST_AVAILABLE = False

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

st.set_page_config(page_title="PIN100 Analytics", page_icon="📍", layout="wide")

# ==========================================================
# 1. КОНФИГУРАЦИЯ СИСТЕМЫ И БЕНЧМАРКИ
# ==========================================================

GDRIVE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CRITERIA_SHEET_ID = "1NUuGhHn3H-GrgfLnnJoY1Paz8vvl_5E9AUu0QyxweVY"
CRITERIA_RANGE = "Rules!A:Z"

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Анализ рынка стоматологии РФ») и РБК",
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4800,
        "ltv_months": 10,
        "benchmark_source": "РБК («Российский рынок эстетической медицины»)",
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3900,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat и НАФИ",
    }
}

FALLBACK_CRITERIA_REGISTRY = {
    "CONV-48.1": {"title": "Онлайн-запись на приём", "group": "Конверсия", "complexity": 2, "weight": 6.0, "desc": "Отсутствие прямой онлайн-записи отсекает до 60% вечернего спроса."},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "desc": "В описании клиники нет четкой структуры процедур."},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "desc": "Рейтинг ниже 4.5 приводит к отсечению фильтрами Яндекса."},
    "PROF-11.3": {"title": "Цены у товаров и услуг", "group": "Базовое заполнение", "complexity": 1, "weight": 3.5, "desc": "Слепой прайс отпугивает пациентов страхом скрытых накруток."}
}

# ==========================================================
# 2. УНИВЕРСАЛЬНАЯ АВТОРИЗАЦИЯ GOOGLE
# ==========================================================

def get_google_credentials() -> Tuple[Any, str]:
    if not GOOGLE_LIBS_AVAILABLE:
        return None, "Библиотеки Google API не установлены."
    
    creds_data = None
    if "GCP_CREDENTIALS" in st.secrets:
        creds_data = st.secrets["GCP_CREDENTIALS"]
    elif "GOOGLE_CREDENTIALS" in st.secrets:
        creds_data = st.secrets["GOOGLE_CREDENTIALS"]

    if creds_data:
        try:
            if isinstance(creds_data, str):
                creds_dict = json.loads(creds_data)
            else:
                creds_dict = dict(creds_data)
            creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка парсинга Streamlit Secrets: {e}"
            
    creds_file = Path("credentials.json")
    if creds_file.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(str(creds_file), scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка чтения локального файла: {e}"
            
    return None, "Ключи доступа не найдены ни в Secrets, ни в файле."

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_criteria_from_google() -> Tuple[Dict[str, Dict[str, Any]], str]:
    creds, status = get_google_credentials()
    if not creds:
        return FALLBACK_CRITERIA_REGISTRY, status

    try:
        sheets = build("sheets", "v4", credentials=creds)
        result = sheets.spreadsheets().values().get(spreadsheetId=CRITERIA_SHEET_ID, range=CRITERIA_RANGE).execute()
        rows = result.get('values', [])

        if not rows or len(rows) < 2:
            return FALLBACK_CRITERIA_REGISTRY, "Таблица пуста или не найден лист Rules."

        headers = [str(h).strip() for h in rows[0]]

        try:
            idx_code = headers.index("Код")
            idx_title = headers.index("Критерий")
            idx_group = headers.index("Группа метрик")
            idx_weight = headers.index("Балл")
            idx_desc = headers.index("Обоснование_ОШИБКИ")
        except ValueError as e:
            return FALLBACK_CRITERIA_REGISTRY, f"В таблице не найден столбец: {e}"

        registry = {}
        for row in rows[1:]:
            if len(row) > max(idx_code, idx_weight):
                code = str(row[idx_code]).strip()
                if not code: continue

                try: weight = float(str(row[idx_weight]).replace(',', '.'))
                except ValueError: weight = 0.0

                registry[code] = {
                    "title": str(row[idx_title]).strip() if len(row) > idx_title else code,
                    "group": str(row[idx_group]).strip() if len(row) > idx_group else "Анализ",
                    "complexity": 2, "weight": weight,
                    "desc": str(row[idx_desc]).strip() if len(row) > idx_desc else ""
                }
        return registry, "OK"
    except Exception as e:
        return FALLBACK_CRITERIA_REGISTRY, f"Ошибка API: {str(e)}"

# ==========================================================
# 3. ТЕРМИНАЛ И УВЕДОМЛЕНИЯ
# ==========================================================

class TerminalLogger:
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.logs: List[str] = []

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "🔵 [INFO]", "SUCCESS": "🟢 [SUCCESS]", 
            "WARN": "🟠 [WARN]", "ERROR": "🔴 [ERROR]", "STEP": "⚙️ [STEP]"
        }.get(level, "🔵 [INFO]")
        
        self.logs.append(f"{ts} {prefix} {msg}")
        self.placeholder.code("\n".join(self.logs), language="bash")

def send_telegram_error(error_message: str, context: str = "") -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id: return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"🚨 <b>PIN100 Ошибка</b>\n<b>Контекст:</b> {context}\n<code>{error_message}</code>"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
        return True
    except: return False

def get_declension(number: int, word_type: str = "пациент") -> str:
    n = abs(int(number)) % 100
    n1 = n % 10
    if word_type in ["пациент", "клиент"]:
        if 11 <= n <= 19: return f"{word_type}ов"
        if n1 == 1: return word_type
        if 2 <= n1 <= 4: return f"{word_type}а"
        return f"{word_type}ов"
    return "обращений"

# ==========================================================
# 5. ХАРДКОРНЫЙ ПАРСИНГ (ВСЕЯДНЫЙ)
# ==========================================================

def perform_deep_scoring(data: Dict[str, Any], logger: TerminalLogger, criteria_registry: Dict) -> Tuple[float, List[Dict[str, Any]], Dict[str, float]]:
    logger.log(f"Запуск оценки по {len(criteria_registry)} правилам из Google Таблицы...", "STEP")
    raw_scores = {}
    
    reviews = data.get("reviews", [])
    working_hours = data.get("workingHours") or data.get("schedule") or []
    
    photos_count = int(data.get("photoCount") or data.get("photosCount") or len(data.get("photos", [])) or 0)
    
    rating = float(data.get("rating") or data.get("reviewsRating") or 5.0)
    rev_count = int(data.get("reviewsCount") or data.get("ratingCount") or len(reviews))
    categories = data.get("categories", [])
    title = str(data.get("title") or data.get("name") or "").lower()
    website = str(data.get("website") or data.get("url") or "").lower()
    features = data.get("features") or data.get("attributes") or []

    base_desc = str(data.get("description") or data.get("about") or "")
    promo_desc = str(data.get("promo", {}).get("description", "")) if isinstance(data.get("promo"), dict) else ""
    full_description = (base_desc + " " + promo_desc).lower()

    items = []
    if isinstance(data.get("menu"), dict) and isinstance(data.get("menu").get("items"), list) and data["menu"]["items"]:
        items = data["menu"]["items"]
    elif data.get("priceList") and isinstance(data.get("priceList"), list) and data["priceList"]:
        items = data["priceList"]
    else:
        for key in ["items", "services", "goods", "productCatalog"]:
            if isinstance(data.get(key), list) and data.get(key):
                items.extend(data[key])

    data_no_reviews = {k: v for k, v in data.items() if k not in ["reviews", "reviewsCount", "ratingCount"]}
    struct_str = json.dumps(data_no_reviews, ensure_ascii=False).lower()

    for c_code, c_meta in criteria_registry.items():
        raw_scores[c_code] = float(c_meta["weight"])

    # 1. КОНВЕРСИЯ
    if "CONV-48.1" in raw_scores and not any(w in struct_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "dikidi", "записаться", "онлайн-запис", "bookingurl", "actionbuttons"]):
        raw_scores["CONV-48.1"] = 0.0
    if "CONV-48.2" in raw_scores and not any(w in struct_str for w in ["specialist", "doctor", "staff", "стаж", "опыт работы", "врач ", "специалист "]):
        raw_scores["CONV-48.2"] = 0.0
    if "CONV-46.1" in raw_scores and photos_count < 5: raw_scores["CONV-46.1"] = 0.0 
    if "CONV-49.1" in raw_scores and (not any(char.isdigit() for char in full_description) or "мы лучшие" in full_description or "индивидуальный подход" in full_description):
        raw_scores["CONV-49.1"] = 0.0
    if "CONV-50.1" in raw_scores and not any(w in struct_str for w in ["чат", "chat", "ischatenabled"]): raw_scores["CONV-50.1"] = 0.0
    if "CONV-52.1" in raw_scores and not any(w in struct_str for w in ["faq", "вопрос", "ответы"]): raw_scores["CONV-52.1"] = 0.0
    if "CONV-53.1" in raw_scores and ("акция" not in struct_str and "скидк" not in struct_str and "старая цена" not in struct_str and "promo" not in struct_str): 
        raw_scores["CONV-53.1"] = 0.0

    # 2. БАЗОВОЕ ЗАПОЛНЕНИЕ
    is_verified = bool(data.get("isVerified") or data.get("verified") or data.get("hasBlueBadge") or data.get("isVerifiedOwner"))
    if "PROF-01.1" in raw_scores and not (is_verified or len(title) > 2): raw_scores["PROF-01.1"] = 0.0
    if "PROF-12.1" in raw_scores and not is_verified: raw_scores["PROF-12.1"] = 0.0
    if "PROF-03.1" in raw_scores and not categories: raw_scores["PROF-03.1"] = 0.0
    if "PROF-03.2" in raw_scores and len(categories) < 3: raw_scores["PROF-03.2"] = 0.75 if len(categories) == 2 else 0.0

    if not website: 
        if "PROF-04.1" in raw_scores: raw_scores["PROF-04.1"] = 0.0
        if "PROF-04.2" in raw_scores: raw_scores["PROF-04.2"] = 0.0
    elif "PROF-04.2" in raw_scores and "utm_" not in website:
        raw_scores["PROF-04.2"] = 0.0

    if "PROF-05.1" in raw_scores and not data.get("phones"): raw_scores["PROF-05.1"] = 0.0
    if "PROF-07.1" in raw_scores and len(working_hours) < 7: raw_scores["PROF-07.1"] = 1.0 if len(working_hours) > 0 else 0.0
    if "PROF-13.1" in raw_scores and not any(w in struct_str for w in ["wa.me", "t.me", "whatsapp"]): raw_scores["PROF-13.1"] = 0.0
    if "PROF-09.1" in raw_scores and len(full_description) < 1200: raw_scores["PROF-09.1"] = 0.0
    if "PROF-10.3" in raw_scores and not any(kw in full_description for kw in ["лечение", "прием", "услуг", "диагностик", "терапи", "консультац"]):
        raw_scores["PROF-10.3"] = 0.0

    has_legal = "инн" in struct_str or "огрн" in struct_str or "taxid" in struct_str or "реквизит" in struct_str or bool(data.get("legalInfo", {}).get("taxId"))
    if "PROF-15.1" in raw_scores and not has_legal:
        raw_scores["PROF-15.1"] = 0.0

    # ПРАВИЛА 80% ДЛЯ УСЛУГ
    if isinstance(items, list) and len(items) > 0:
        if "PROF-11.1" in raw_scores and len(items) < 10: raw_scores["PROF-11.1"] = 2.0 if len(items) >= 3 else 0.0
        has_photo = sum(1 for i in items if i.get("image") or i.get("imageUrl") or i.get("image_url") or i.get("photoUrl") or i.get("picture"))
        has_price = sum(1 for i in items if i.get("price") or i.get("cost") or i.get("priceValue"))
        has_desc = sum(1 for i in items if i.get("description") and len(str(i.get("description"))) > 50)
        total_items = len(items)
        if "PROF-11.2" in raw_scores and (has_photo / total_items) < 0.8: raw_scores["PROF-11.2"] = 0.0
        if "PROF-11.3" in raw_scores and (has_price / total_items) < 0.8: raw_scores["PROF-11.3"] = 0.0
        if "PROF-11.4" in raw_scores and (has_desc / total_items) < 0.8:  raw_scores["PROF-11.4"] = 0.0
    else:
        for k in ["PROF-11.1", "PROF-11.2", "PROF-11.3", "PROF-11.4"]:
            if k in raw_scores: raw_scores[k] = 0.0

    # 3. SEO И ТРАФИК 
    if "SEO-18.3" in raw_scores and not any(kw in full_description for kw in ["метро", "район", "улиц", "шоссе", "проспект"]):
        raw_scores["SEO-18.3"] = 0.0
    if "PROF-01.2" in raw_scores and (len(title) > 60 or "недорого" in title or "скидк" in title):
        raw_scores["PROF-01.2"] = 0.0 
    if "PROF-08.1" in raw_scores and not features: raw_scores["PROF-08.1"] = 0.0

    features_str = str(features).lower()
    if "PROF-08.2" in raw_scores and "дмс" not in features_str and "рассрочка" not in features_str: raw_scores["PROF-08.2"] = 0.0
    if "CONT-38.1" in raw_scores and photos_count < 10: raw_scores["CONT-38.1"] = 0.5 if photos_count >= 5 else 0.0
    if "CONT-42.1" in raw_scores and not any(kw in struct_str for kw in ["видео", "video", "youtube", "тур", "панорам", "videos"]):
        raw_scores["CONT-42.1"] = 0.0

    # 4. РЕПУТАЦИЯ И ОТЗЫВЫ
    if "REP-27.2" in raw_scores and rating < 4.8: raw_scores["REP-27.2"] = 0.0
    if "REP-27.1" in raw_scores and rating < 4.5: raw_scores["REP-27.1"] = 0.0
    if "REP-28.1" in raw_scores and rev_count < 50: raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

    if reviews and isinstance(reviews, list):
        replied_count = 0
        reply_lengths = []
        seo_in_reviews = False
        most_recent_date = None

        for r in reviews:
            if isinstance(r, dict):
                reply = r.get("reply") or r.get("comments") or r.get("businessComment")
                if reply:
                    replied_count += 1
                    reply_lengths.append(len(str(reply)))
                    
                rev_text = str(r.get("text", "")).lower()
                if any(kw in rev_text for kw in ["врач", "процедур", "пломб", "кариес", "анализ", "зуб"]):
                    seo_in_reviews = True

                date_str = r.get("publishedAtDate") or r.get("updatedAt") or r.get("date")
                if date_str:
                    try:
                        clean_date = str(date_str).split('.')[0].replace('Z', '')
                        r_date = datetime.datetime.fromisoformat(clean_date)
                        if not most_recent_date or r_date > most_recent_date: most_recent_date = r_date
                    except Exception: pass

        if "REP-30.1" in raw_scores and (replied_count / len(reviews)) < 0.9: raw_scores["REP-30.1"] = 1.5 if (replied_count / len(reviews)) >= 0.5 else 0.0
        avg_reply = sum(reply_lengths) / len(reply_lengths) if reply_lengths else 0
        if "REP-30.4" in raw_scores and avg_reply < 80: raw_scores["REP-30.4"] = 0.0
        if "SEO-19.2" in raw_scores and not seo_in_reviews: raw_scores["SEO-19.2"] = 0.0

        if "REP-29.1" in raw_scores:
            if most_recent_date:
                days_diff = (datetime.datetime.now() - most_recent_date).days
                if days_diff > 14: raw_scores["REP-29.1"] = 0.0
            else: raw_scores["REP-29.1"] = 0.0

        last_20 = reviews[:20]
        znatoki_count = sum(1 for r in last_20 if "знаток" in str(r.get("authorLevel") or r.get("author", "")).lower() or "уровень" in str(r.get("authorLevel") or r.get("author", "")).lower())
        photo_rev_count = sum(1 for r in last_20 if r.get("photos") or r.get("photoCount", 0) > 0)

        if "REP-34.1" in raw_scores and (znatoki_count / len(last_20)) < 0.25: raw_scores["REP-34.1"] = 0.0
        if "REP-35.1" in raw_scores and (photo_rev_count / len(last_20)) < 0.10: raw_scores["REP-35.1"] = 0.0

    else:
        for k in ["REP-30.1", "REP-30.4", "REP-35.1", "REP-34.1", "SEO-19.2", "REP-29.1", "REP-32.2"]:
            if k in raw_scores: raw_scores[k] = 0.0 

    total_score = 0.0
    gap_list = []
    
    for code, meta in criteria_registry.items():
        max_w = meta["weight"]
        cur_w = raw_scores.get(code, max_w)
        total_score += cur_w
        lost = max_w - cur_w
        
        if lost > 0.1:
            impact = lost * (6.0 - meta["complexity"])
            gap_list.append({"code": code, "title": meta["title"], "desc": meta["desc"], "impact": impact})
            logger.log(f"[{code}] {meta['title']} -> Снят балл: -{lost:.1f}", "WARN")

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]
    while len(top_3) < 3:
        top_3.append({"title": "Техническая оптимизация", "desc": "Поддерживайте актуальность данных."})

    return round(total_score, 1), top_3, raw_scores


def fetch_apify_data(target_url: str, logger: TerminalLogger) -> Dict[str, Any]:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    actor = os.getenv("APIFY_ACTOR_ID", "").strip()
    
    if "APIFY_API_TOKEN" in st.secrets: token = st.secrets["APIFY_API_TOKEN"]
    if "APIFY_ACTOR_ID" in st.secrets: actor = st.secrets["APIFY_ACTOR_ID"]

    if not token or not actor: raise ValueError("Не настроены ключи APIFY_API_TOKEN и APIFY_ACTOR_ID (добавьте их в Secrets).")

    # УВЕЛИЧЕН ТАЙМ-АУТ ДО 300 секунд
    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=300"
    logger.log(f"Отправка URL в Apify Actor...", "STEP")
    
    # ДОБАВЛЕНЫ ЛИМИТЫ (maxReviews и maxImages), чтобы избежать тайм-аута
    payload = {
        "startUrls": [{"url": target_url.strip()}], 
        "maxItems": 1, 
        "includeReviews": True,
        "maxReviews": 20,
        "maxImages": 10
    }
    
    resp = requests.post(run_url, json=payload, timeout=310)
    if resp.status_code not in [200, 201]: raise RuntimeError(f"Сбой Apify: {resp.text[:200]}")
    
    items = resp.json()
    if not items: raise ValueError("Apify вернул пустой массив данных.")
    logger.log("Сырые данные успешно загружены из Apify.", "SUCCESS")
    return items[0]


def get_gemini_insights(data: Dict[str, Any], logger: TerminalLogger) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        
    if not api_key or not GEMINI_AVAILABLE:
        logger.log("Gemini API отключен (нет ключа или библиотеки).", "WARN")
        return {"score": 0, "pain_point": ""}
        
    logger.log("🧠 Запрос к ИИ Gemini для поиска главной боли...", "STEP")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        safe_data = {
            "title": data.get("title", ""),
            "rating": data.get("rating", ""),
            "reviews_count": data.get("reviewsCount", ""),
            "features": data.get("features", []),
            "recent_reviews": [r.get("text", "") for r in data.get("reviews", [])[:5] if isinstance(r, dict)]
        }
        
        prompt = f"""
        Ты маркетолог-эксперт по Яндекс Картам. Анализируем стоматологию/клинику:
        {json.dumps(safe_data, ensure_ascii=False)}
        
        Наш продукт: аудит карточки и услуги по ее ведению.
        Выдай ответ СТРОГО в формате JSON с ключами:
        1. "score" (число 0-100): Оценка вероятности продажи.
        2. "pain_point" (текст): Одно предложение с самой грубой ошибкой профиля.
        """
        
        resp = model.generate_content(prompt)
        result_text = resp.text.replace('```json', '').replace('```', '').strip()
        ai_data = json.loads(result_text)
        logger.log(f"Gemini: Скоринг {ai_data.get('score')}%, Боль: {ai_data.get('pain_point')}", "SUCCESS")
        return ai_data
    except Exception as e:
        logger.log(f"Ошибка Gemini: {e}", "ERROR")
        return {"score": 0, "pain_point": ""}


def process_company_data(raw_input: Any, logger: TerminalLogger, criteria_registry: Dict) -> Dict[str, Any]:
    data = raw_input[0] if isinstance(raw_input, list) and raw_input else raw_input
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list): data = data["items"][0]

    title = data.get("title") or data.get("name") or "Организация"
    org_id = str(data.get("org_id") or data.get("id") or "0000000000")
    rating = round(float(data.get("rating") or data.get("reviewsRating") or 5.0), 1)

    logger.log(f"Найдена карточка: «{title}» (Рейтинг: {rating})", "INFO")

    niche = "DENTISTRY"
    low_txt = (str(title) + " " + str(data.get("categories", ""))).lower()
    if any(k in low_txt for k in ["космет", "beauty"]): niche = "COSMETOLOGY"
    elif any(k in low_txt for k in ["авто", "сервис"]): niche = "AUTOSERVICES"
    elif any(k in low_txt for k in ["медцентр"]): niche = "GENERAL_MEDICINE"

    score, top_fails, raw_scores = perform_deep_scoring(data, logger, criteria_registry)
    logger.log(f"Итоговый честный балл готовности: {score:.1f} / 100", "INFO")

    comps = data.get("competitors") or []
    if not isinstance(comps, list) or len(comps) < 2:
        comps = ["соседние клиники локации", "сетевые клиники района"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["DENTISTRY"])

    return {
        "title": title, "org_id": org_id, "rating": rating, "score": score, "niche": niche,
        "competitors": comps, "canonical_url": data.get("url", ""),
        "benchmark_leads": n_def["benchmark_leads"], "base_check": n_def["base_check"], 
        "ltv_months": n_def["ltv_months"], "benchmark_source": n_def["benchmark_source"],
        "top_failures": top_fails, "date": datetime.date.today().strftime("%d.%m.%Y"),
        "criteria_scores": raw_scores,
        "raw_data_ref": data # Сохраняем ссылку на сырые данные для ИИ
    }

def build_metrics(audit: Dict[str, Any], criteria_registry: Dict) -> Dict[str, str]:
    n_info = NICHE_CONFIG[audit["niche"]]
    score = audit["score"]
    dev = max(0.0, round(100.0 - score, 1))
    
    lost_leads = int(round(audit["benchmark_leads"] * (dev / 100.0)))
    rev_loss = lost_leads * audit["base_check"]
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * audit["ltv_months"]

    table_declension = get_declension(lost_leads, n_info["client_word"])
    failures = audit.get("top_failures", [])

    group_losses = {}
    for code, meta in criteria_registry.items():
        max_w = meta["weight"]
        cur_w = audit.get("criteria_scores", {}).get(code, max_w)
        lost = max_w - cur_w
        if lost > 0: group_losses[meta["group"]] = group_losses.get(meta["group"], 0.0) + lost

    worst_group = max(group_losses, key=group_losses.get) if group_losses else ""

    reason_phrases = {
        "Конверсия": "из-за отсутствия прямого конверсионного инструментария (онлайн-записи, витрины врачей или чата)",
        "Базовое заполнение": "из-за критических пробелов в заполнении карточки (отсутствие цен, структуры услуг или реквизитов)",
        "Репутация": "из-за просадки в репутационных факторах (паузы в отзывах, рейтинг или игнорирование обратной связи)",
        "SEO и Трафик": "из-за слабой гео-оптимизации профиля (нехватка нишевых атрибутов, топонимов или смежных рубрик)",
        "Контент": "из-за недостатка визуального доверия (мало качественных фотографий интерьера или отсутствие видео)"
    }
    
    reason_text = reason_phrases.get(worst_group, "из-за технических недочетов в оформлении и настройках профиля")
    executive_summary = (f"Профиль «{audit['title']}» обладает высокой клинической репутацией ({audit['rating']:.1f}), "
                         f"однако {reason_text} алгоритм перенаправляет до {lost_leads} готовых обращений в месяц "
                         f"прямым конкурентам локации.")
    
    return {
        "[[TITLE]]": audit["title"], "[[NICHE]]": n_info["niche_name"], "[[DATE]]": audit["date"],
        "[[SCORE]]": f"{score:.1f}", "[[SCORE_COLOR]]": "16a34a" if score >= 80 else ("d97706" if score >= 60 else "dc2626"),
        "[[REV_LOSS_FMT]]": f"{int(rev_loss):,}".replace(",", " "), "[[CLIENT_LEADS]]": str(audit["benchmark_leads"]),
        "[[DEV]]": f"{dev:.1f}", "[[LOST_LEADS]]": str(lost_leads), "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": f"{int(audit['base_check']):,}".replace(",", " "), "[[CLIENT_LTV]]": str(audit["ltv_months"]),
        "[[LTV_LOSS_FMT]]": f"{int(ltv_loss):,}".replace(",", " "), "[[BENCHMARK_SOURCE]]": audit["benchmark_source"],
        "[[QUALITY_PHRASE]]": n_info["quality_phrase"], "[[EXECUTIVE_SUMMARY]]": executive_summary,
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери пациентов", "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию в первичное обращение:",
        "[[FAIL_1_TITLE]]": failures[0]["title"] if len(failures) > 0 else "Барьер конверсии",
        "[[FAIL_1_DESC]]": failures[0]["desc"] if len(failures) > 0 else "Требуется оптимизация карточки.",
        "[[FAIL_2_TITLE]]": failures[1]["title"] if len(failures) > 1 else "Барьер доверия",
        "[[FAIL_2_DESC]]": failures[1]["desc"] if len(failures) > 1 else "Требуется заполнение команды.",
        "[[FAIL_3_TITLE]]": failures[2]["title"] if len(failures) > 2 else "Барьер прейскуранта",
        "[[FAIL_3_DESC]]": failures[2]["desc"] if len(failures) > 2 else "Требуется открытие цен.",
        "[[WEEKLY_LOSS_FMT]]": f"{int(weekly_loss):,}".replace(",", " ")
    }

def compile_pdf(typ_content: str, out_path: Path, work_dir: Path, logger: TerminalLogger) -> bool:
    temp_typ = work_dir / f"temp_{out_path.stem}.typ"
    try:
        with open(temp_typ, "w", encoding="utf-8") as f: f.write(typ_content)
        if PY_TYPST_AVAILABLE:
            typst.compile(str(temp_typ), output=str(out_path))
            return True
        subprocess.run(["typst", "compile", str(temp_typ), str(out_path)], check=True)
        return True
    except Exception as e:
        logger.log(f"Ошибка компиляции Typst: {e}", "ERROR")
        return False
    finally:
        if temp_typ.exists(): temp_typ.unlink()

# ==========================================================
# 6. ВЫГРУЗКА В GOOGLE ТАБЛИЦУ (НА 3 ЛИСТА)
# ==========================================================
def sync_to_google(audit: Dict, mapping: Dict, p_txt: Path, p_json: Path, logger: TerminalLogger) -> bool:
    creds, status = get_google_credentials()
    if not creds:
        logger.log(f"Пропуск выгрузки в Google Таблицу: {status}", "WARN")
        return False
        
    try:
        sheets = build("sheets", "v4", credentials=creds)
        sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
        if "GOOGLE_SHEET_ID" in st.secrets: sheet_id = st.secrets["GOOGLE_SHEET_ID"]
        
        if not sheet_id:
            logger.log("ID Google Таблицы (GOOGLE_SHEET_ID) не найден в секретах.", "WARN")
            return False

        # 1. Генерируем уникальный ID аудита для связи листов
        audit_id = f"{audit['org_id']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 2. Подготовка данных для листа "Main" (Добавлены столбцы ИИ-Анализа L и M)
        row_main = [
            audit_id, mapping["[[DATE]]"], datetime.datetime.now().strftime("%H:%M:%S"), 
            audit["title"], audit["org_id"], audit["canonical_url"], audit["niche"], 
            audit["rating"], mapping["[[SCORE]]"], mapping["[[LOST_LEADS]]"], mapping["[[REV_LOSS_FMT]]"],
            audit.get("ai_score", ""), audit.get("ai_pain_point", "")
        ]

        # 3. Подготовка данных для листа "Scores"
        scores_dict = audit.get("criteria_scores", {})
        sorted_codes = sorted(scores_dict.keys())
        row_scores = [audit_id, audit["title"]] + [str(scores_dict[code]) for code in sorted_codes]

        # 4. Подготовка данных для листа "RawData"
        with open(p_txt, "r", encoding="utf-8") as f: letter_text = f.read()
        with open(p_json, "r", encoding="utf-8") as f: json_text = f.read()
        
        if len(json_text) > 49000:
            json_text = json_text[:49000] + "\n\n... [JSON ОБРЕЗАН ИЗ-ЗА ЛИМИТА GOOGLE СИМВОЛОВ]"

        row_raw = [audit_id, audit["title"], letter_text, json_text]

        # 5. Отправка данных на 3 разных листа (Заменено Main!A:K на Main!A:M)
        sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id, range="Main!A:M", valueInputOption="USER_ENTERED", body={"values": [row_main]}
        ).execute()
        
        sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id, range="Scores!A:AQ", valueInputOption="USER_ENTERED", body={"values": [row_scores]}
        ).execute()
        
        sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id, range="RawData!A:D", valueInputOption="USER_ENTERED", body={"values": [row_raw]}
        ).execute()
        
        logger.log("Данные успешно распределены по 3 листам Google Таблицы (Main, Scores, RawData)!", "SUCCESS")
        return True
    except Exception as e:
        logger.log(f"Ошибка записи в таблицу: {e}", "ERROR")
        return False

def run_pipeline(raw_data: Any, logger: TerminalLogger, criteria_registry: Dict):
    try:
        audit = process_company_data(raw_data, logger, criteria_registry)
        st.session_state.current_audit = audit
        mapping = build_metrics(audit, criteria_registry)
        st.session_state.current_mapping = mapping
        
        # ЗАПРОС К GEMINI
        ai_insights = get_gemini_insights(audit["raw_data_ref"], logger)
        audit["ai_score"] = ai_insights.get("score", "")
        audit["ai_pain_point"] = ai_insights.get("pain_point", "")

        logger.log("Генерация письма Icebreaker...", "STEP")
        c_str = f"«{audit['competitors'][0]}» и «{audit['competitors'][1]}»" if "сосед" not in audit['competitors'][0].lower() else "соседние клиники локации"
        ll = int(mapping["[[LOST_LEADS]]"])
        
        # Формирование боли: ИИ-приоритет или жесткая логика из кода
        if audit["ai_pain_point"]:
            ib_fail_text = f"На поверхности лежат недочеты: {audit['ai_pain_point'].lower().strip(' .')}"
        else:
            top_fail_title = audit["top_failures"][0]["title"].lower()
            if "запись" in top_fail_title or "мис" in top_fail_title:
                ib_fail_text = "На поверхности лежит отсутствие быстрой онлайн-записи (пациенты вечером не хотят звонить и уходят к соседям)"
            elif "врач" in top_fail_title or "специалист" in top_fail_title:
                ib_fail_text = "На поверхности лежит отсутствие витрины врачей (пациенты выбирают клиники с открытой командой)"
            elif "услуг" in top_fail_title or "прайс" in top_fail_title or "цены" in top_fail_title:
                ib_fail_text = "На поверхности лежит отсутствие понятного каталога услуг (пациенты боятся скрытых накруток и уходят к соседям)"
            elif "отзыв" in top_fail_title or "рейтинг" in top_fail_title:
                ib_fail_text = "На поверхности лежат репутационные недочеты (алгоритмы Яндекса пессимизируют профиль за просадку в отзывах)"
            else:
                ib_fail_text = f"На поверхности лежат пара недочетов (например, алгоритмы Яндекса пессимизируют профиль за пункт «{audit['top_failures'][0]['title']}»)"

        ib_txt = (f"Добрый день!\n\nАнализировали выдачу в вашем районе и обратили внимание на карточку «{audit['title']}». При сильной репутации ({audit['rating']:.1f}) первичный поток перехватывают {c_str}.\n\n"
                  f"{ib_fail_text}. По емкости района это отток около {max(1, ll-2)}–{ll+3} пациентов в месяц.\n\n"
                  f"Собрали наглядный разбор карточки и расчет потерь в PDF на 4 страницы. Скинуть файл для ознакомления?")
        st.session_state.current_icebreaker = ib_txt

        logger.log("Компиляция PDF-отчета...", "STEP")
        out_dir = Path("output"); out_dir.mkdir(exist_ok=True)
        prefix = f"{re.sub(r'[^a-zA-Z0-9а-яА-Я]', '_', audit['title'])}_{audit['org_id']}"
        p_pdf, p_txt, p_json = out_dir / f"{prefix}.pdf", out_dir / f"{prefix}.txt", out_dir / f"{prefix}.json"
        
        with open(p_txt, "w", encoding="utf-8") as f: f.write(ib_txt)
        
        # Удаляем тяжелый raw_data_ref перед сохранением JSON
        safe_audit_for_json = {k: v for k, v in audit.items() if k != "raw_data_ref"}
        with open(p_json, "w", encoding="utf-8") as f: json.dump(safe_audit_for_json, f, ensure_ascii=False)
        
        tpl = Path("report_template.typ")
        if tpl.exists():
            with open(tpl, "r", encoding="utf-8") as f: content = f.read()
            for k, v in mapping.items(): content = content.replace(k, str(v))
            if compile_pdf(content, p_pdf, out_dir, logger):
                st.session_state.pdf_path = str(p_pdf)
                logger.log("PDF успешно скомпилирован (доступен для скачивания).", "SUCCESS")
        else: logger.log("Шаблон report_template.typ не найден!", "ERROR")

        logger.log("Сохранение аналитики в базу Google Таблиц...", "STEP")
        db_saved = sync_to_google(audit, mapping, p_txt, p_json, logger)
        if db_saved: st.session_state.db_saved = True
            
        logger.log("КОНВЕЙЕР УСПЕШНО ЗАВЕРШЕН!", "SUCCESS")

    except Exception as ex:
        logger.log(f"Критическая ошибка: {ex}", "ERROR")
        send_telegram_error(str(ex), "Pipeline Run")

def app():
    criteria_registry, sync_status = fetch_criteria_from_google()
    
    with st.sidebar:
        st.header("⚙️ Настройки системы")
        if st.button("🔄 Синхронизировать критерии", use_container_width=True):
            fetch_criteria_from_google.clear()
            st.rerun()
            
        st.caption(f"Загружено правил: {len(criteria_registry)}")
        if sync_status != "OK":
            st.error(f"⚠️ Сбой таблицы:\n{sync_status}")
            
    st.title("📍 PIN100 Analytics: Генератор аудитов гео-выдачи")
    tab_json, tab_url = st.tabs(["📋 Загрузить JSON", "🔗 Ссылка (Apify API)"])

    with tab_json:
        col1, col2 = st.columns([1, 2])
        file = col1.file_uploader("Файл .json из Apify:", type=["json"])
        txt = col2.text_area("Или код JSON:", height=100)
        btn_json = st.button("🚀 Запустить конвейер по JSON", type="primary", use_container_width=True)

    with tab_url:
        url = st.text_input("Ссылка на Яндекс Карты:")
        btn_url = st.button("🚀 Запустить краулинг и конвейер", type="primary", use_container_width=True)

    st.subheader("🖥️ Терминал выполнения конвейера (Live Diagnostics)")
    logger = TerminalLogger(st.empty())

    if btn_json:
        data = json.load(file) if file else (json.loads(txt) if txt.strip() else None)
        if data: run_pipeline(data, logger, criteria_registry)
        else: logger.log("Нет данных для анализа.", "ERROR")
    
    if btn_url and url.strip():
        try:
            data = fetch_apify_data(url, logger)
            run_pipeline(data, logger, criteria_registry)
        except Exception as e:
            logger.log(str(e), "ERROR")

    if st.session_state.get("current_audit") and st.session_state.get("current_mapping"):
        st.divider()
        c1, c2 = st.columns([1.1, 0.9])
        map_d = st.session_state.current_mapping
        aud = st.session_state.current_audit

        with c1:
            st.subheader("✉️ Первое сообщение (Icebreaker)")
            st.text_area("Текст:", value=st.session_state.current_icebreaker, height=200)
            
            if aud.get("ai_pain_point"):
                st.info(f"🧠 ИИ-вывод (пошло в письмо): {aud['ai_pain_point']}")
            
            st.markdown("**Топ-3 уязвимости:**")
            for i, f in enumerate(aud["top_failures"], 1):
                st.markdown(f"**{i}. {f['title']}**\n<small>{f['desc']}</small>", unsafe_allow_html=True)

        with c2:
            st.subheader(f"📊 Экономика потерь «{aud['title']}»")
            m1, m2 = st.columns(2)
            m1.metric("Балл", f"{map_d['[[SCORE]]']} / 100")
            m2.metric("Потери", f"~{map_d['[[LOST_LEADS]]']} чел/мес")
            m3, m4 = st.columns(2)
            m3.metric("Упущенная выручка", f"{map_d['[[REV_LOSS_FMT]]']} ₽/мес")
            
            if aud.get("ai_score"):
                 m4.metric("🧠 ИИ-Скоринг (Вероятность)", f"{aud['ai_score']}%")
            else:
                 m4.metric("Потери за неделю", f"~{map_d['[[WEEKLY_LOSS_FMT]]']} ₽/нед")
            
            st.divider()
            st.subheader("📄 PDF-отчет")
            if st.session_state.get("pdf_path"):
                with open(st.session_state.pdf_path, "rb") as f:
                    st.download_button("📥 Скачать PDF", f, Path(st.session_state.pdf_path).name, "application/pdf", type="primary", use_container_width=True)
            
            if st.session_state.get("db_saved"):
                st.success("✅ Все данные успешно сохранены в вашу базу (Google Таблицы)!")

if __name__ == "__main__":
    app()
