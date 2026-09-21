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

# Ссылка для авторизации (строго без скобок и markdown-форматирования)
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CRITERIA_SHEET_ID = "1NUuGhHn3H-GrgfLnnJoY1Paz8vvl_5E9AUu0QyxweVY"
CRITERIA_RANGE = "Rules!A:Z"

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "company_word": "клиники",
        "client_word": "пациент",
        "client_word_plural": "пациенты",
        "client_word_genitive_plural": "пациентов",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Анализ рынка стоматологии РФ») и РБК",
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "company_word": "клиники",
        "client_word": "клиент",
        "client_word_plural": "клиенты",
        "client_word_genitive_plural": "клиентов",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4800,
        "ltv_months": 10,
        "benchmark_source": "РБК («Российский рынок эстетической медицины»)",
    },
    "BEAUTY": {
        "niche_name": "Парикмахерская / Барбершоп",
        "niche_genitive": "салонов красоты",
        "company_word": "салона",
        "client_word": "клиент",
        "client_word_plural": "клиенты",
        "client_word_genitive_plural": "клиентов",
        "quality_phrase": "мастерства стилистов и уровня сервиса",
        "benchmark_leads": 150,
        "base_check": 1800,
        "ltv_months": 6,
        "benchmark_source": "РБК («Российский рынок бьюти-услуг»)",
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "company_word": "медцентра",
        "client_word": "пациент",
        "client_word_plural": "пациенты",
        "client_word_genitive_plural": "пациентов",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3900,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat и НАФИ",
    },
    "OTHER": {
        "niche_name": "Локальный бизнес",
        "niche_genitive": "конкурентов",
        "company_word": "организации",
        "client_word": "клиент",
        "client_word_plural": "клиенты",
        "client_word_genitive_plural": "клиентов",
        "quality_phrase": "качества услуг и клиентского сервиса",
        "benchmark_leads": 50,
        "base_check": 2000,
        "ltv_months": 3,
        "benchmark_source": "Усредненные данные локального поиска",
    }
}

FALLBACK_CRITERIA_REGISTRY = {
    "CONV-48.1": {"title": "Онлайн-запись на приём", "group": "Конверсия", "complexity": 2, "weight": 6.0, "descs": {"Обоснование_ОШИБКИ": "Отсутствие прямой онлайн-записи отсекает до 60% вечернего спроса."}},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "descs": {"Обоснование_ОШИБКИ": "В описании нет четкой структуры процедур."}},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "descs": {"Обоснование_ОШИБКИ": "Рейтинг ниже 4.5 приводит к отсечению фильтрами."}},
    "PROF-11.3": {"title": "Цены у товаров и услуг", "group": "Базовое заполнение", "complexity": 1, "weight": 3.5, "descs": {"Обоснование_ОШИБКИ": "Слепой прайс отпугивает страхом скрытых накруток."}}
}

# ==========================================================
# 2. УНИВЕРСАЛЬНАЯ АВТОРИЗАЦИЯ GOOGLE
# ==========================================================

def get_google_credentials() -> Tuple[Any, str]:
    if not GOOGLE_LIBS_AVAILABLE:
        return None, "Библиотеки Google API не установлены."
    
    creds_data = st.secrets.get("GCP_CREDENTIALS") or st.secrets.get("GOOGLE_CREDENTIALS")
    if creds_data:
        try:
            creds_dict = json.loads(creds_data) if isinstance(creds_data, str) else dict(creds_data)
            creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка парсинга секретов Google: {e}"
            
    creds_file = Path("credentials.json")
    if creds_file.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(str(creds_file), scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка чтения локального файла ключей: {e}"
            
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
        except ValueError as e:
            return FALLBACK_CRITERIA_REGISTRY, f"В таблице не найден обязательный столбец: {e}"

        desc_cols = {h: i for i, h in enumerate(headers) if h.startswith("Обоснование_ОШИБКИ")}
        registry = {}

        for row in rows[1:]:
            if len(row) > max(idx_code, idx_weight):
                code = str(row[idx_code]).strip()
                if not code:
                    continue

                try:
                    weight = float(str(row[idx_weight]).replace(',', '.'))
                except ValueError:
                    weight = 0.0

                descs = {}
                for col_name, col_idx in desc_cols.items():
                    if len(row) > col_idx and str(row[col_idx]).strip():
                        descs[col_name] = str(row[col_idx]).strip()

                registry[code] = {
                    "title": str(row[idx_title]).strip() if len(row) > idx_title else code,
                    "group": str(row[idx_group]).strip() if len(row) > idx_group else "Анализ",
                    "complexity": 2,
                    "weight": weight,
                    "descs": descs
                }
        return registry, "OK"
    except Exception as e:
        return FALLBACK_CRITERIA_REGISTRY, f"Ошибка Google Sheets API: {str(e)}"

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
    bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"🚨 <b>PIN100 Ошибка</b>\n<b>Контекст:</b> {context}\n<code>{error_message}</code>"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
        return True
    except Exception:
        return False

def get_declension(number: int, word_type: str = "пациент") -> str:
    n = abs(int(number)) % 100
    n1 = n % 10
    if word_type in ["пациент", "клиент"]:
        if 11 <= n <= 19:
            return f"{word_type}ов"
        if n1 == 1:
            return word_type
        if 2 <= n1 <= 4:
            return f"{word_type}а"
        return f"{word_type}ов"
    return "обращений"

def get_points_declension(number: int) -> str:
    n = abs(int(number)) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        return "ключевых точек"
    if n1 == 1:
        return "ключевая точка"
    if 2 <= n1 <= 4:
        return "ключевые точки"
    return "ключевых точек"

# ==========================================================
# 4. АНАЛИЗАТОР ПЕРСПЕКТИВНОСТИ И ИНТЕГРАЦИИ
# ==========================================================

def calculate_client_potential(rating: float, score: float, lost_leads: int) -> Tuple[int, str, str]:
    stars = 0
    reasons = []

    if rating >= 4.7:
        stars += 2
        reasons.append(f"отличная репутация ({rating})")
    elif rating >= 4.3:
        stars += 1
        reasons.append(f"хороший рейтинг ({rating})")
    else:
        reasons.append(f"слабая репутация ({rating})")

    if score <= 65:
        stars += 2
        reasons.append(f"критический балл ({score:.1f}/100)")
    elif score <= 85:
        stars += 1
        reasons.append(f"средняя оптимизация ({score:.1f}/100)")
    else:
        reasons.append(f"карточка оптимизирована ({score:.1f}/100)")

    if lost_leads >= 20:
        stars += 1
        reasons.append(f"потери -{lost_leads} лид/мес")

    stars = min(5, max(1, stars))
    star_str = "⭐" * stars
    
    if stars >= 4:
        justification = "Горячий лид: " + ", ".join(reasons) + "."
    elif stars == 3:
        justification = "Средний потенциал: " + ", ".join(reasons) + "."
    else:
        justification = "Сомнительный клиент: " + ", ".join(reasons) + "."
        
    return stars, star_str, justification

def fetch_dadata_ceo(inn: str, logger: TerminalLogger) -> str:
    api_key = st.secrets.get("DADATA_API_KEY") or os.getenv("DADATA_API_KEY", "").strip()
    if not api_key:
        logger.log("Ключ DADATA_API_KEY не настроен. Поиск ЛПР пропущен.", "WARN")
        return ""
        
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Token {api_key}"
    }
    
    try:
        logger.log(f"🔎 Поиск ЛПР в DaData по ИНН: {inn}...", "STEP")
        resp = requests.post(url, json={"query": inn}, headers=headers, timeout=5)
        if resp.status_code == 200:
            results = resp.json().get("suggestions", [])
            if results:
                data = results[0].get("data", {})
                management = data.get("management")
                if management and management.get("name"):
                    name = management.get("name")
                    post = management.get("post", "Руководитель")
                    logger.log(f"Найден ЛПР: {name} ({post})", "SUCCESS")
                    return f"{name} ({post})"
                else:
                    name = data.get("name", {}).get("full")
                    type_party = data.get("type")
                    if type_party == "INDIVIDUAL" and name:
                        logger.log(f"Найден ЛПР (ИП): {name}", "SUCCESS")
                        return f"{name} (ИП)"
        logger.log("DaData: ЛПР не найден в реестре.", "WARN")
        return ""
    except Exception as e:
        logger.log(f"Ошибка API DaData: {e}", "ERROR")
        return ""

# ==========================================================
# 5. ХАРДКОРНЫЙ ПАРСИНГ И СКОРИНГ
# ==========================================================

def perform_deep_scoring(data: Dict[str, Any], logger: TerminalLogger, criteria_registry: Dict, niche: str) -> Tuple[float, List[Dict[str, Any]], Dict[str, float]]:
    logger.log(f"Запуск оценки по {len(criteria_registry)} правилам из таблицы...", "STEP")
    raw_scores = {}
    
    reviews = data.get("reviews") or []
    working_hours = data.get("workingHours") or data.get("schedule") or []
    photos_count = int(data.get("photoCount") or data.get("photosCount") or len(data.get("photos") or []) or 0)
    
    rating = float(data.get("rating") or data.get("reviewsRating") or 5.0)
    rev_count = int(data.get("reviewsCount") or data.get("ratingCount") or len(reviews))
    categories = data.get("categories") or []
    title = str(data.get("title") or data.get("name") or "").lower()
    website = str(data.get("website") or data.get("url") or "").lower()
    features = data.get("features") or data.get("attributes") or []

    base_desc = str(data.get("description") or data.get("about") or "")
    promo_data = data.get("promo")
    promo_desc = str(promo_data.get("description", "")) if isinstance(promo_data, dict) else ""
    full_description = (base_desc + " " + promo_desc).lower()

    items = []
    menu_data = data.get("menu")
    if isinstance(menu_data, dict) and isinstance(menu_data.get("items"), list) and menu_data["items"]:
        items = menu_data["items"]
    elif isinstance(data.get("priceList"), list) and data["priceList"]:
        items = data["priceList"]
    else:
        for key in ["items", "services", "goods", "productCatalog"]:
            val = data.get(key)
            if isinstance(val, list) and val:
                items.extend(val)

    data_no_reviews = {k: v for k, v in data.items() if k not in ["reviews", "reviewsCount", "ratingCount"]}
    struct_str = json.dumps(data_no_reviews, ensure_ascii=False).lower()

    for c_code, c_meta in criteria_registry.items():
        raw_scores[c_code] = float(c_meta["weight"])

    if "CONV-48.1" in raw_scores and not any(w in struct_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "dikidi", "записаться", "онлайн-запис", "bookingurl", "actionbuttons"]):
        raw_scores["CONV-48.1"] = 0.0
    if "CONV-48.2" in raw_scores and not any(w in struct_str for w in ["specialist", "doctor", "staff", "стаж", "опыт работы", "врач ", "специалист "]):
        raw_scores["CONV-48.2"] = 0.0
    if "CONV-46.1" in raw_scores and photos_count < 5:
        raw_scores["CONV-46.1"] = 0.0 
    if "CONV-49.1" in raw_scores and (not any(char.isdigit() for char in full_description) or "мы лучшие" in full_description or "индивидуальный подход" in full_description):
        raw_scores["CONV-49.1"] = 0.0
    if "CONV-52.1" in raw_scores and not any(w in struct_str for w in ["faq", "вопрос", "ответы"]):
        raw_scores["CONV-52.1"] = 0.0
    if "CONV-53.1" in raw_scores and ("акция" not in struct_str and "скидк" not in struct_str and "старая цена" not in struct_str and "promo" not in struct_str): 
        raw_scores["CONV-53.1"] = 0.0
    if "CONV-54.1" in raw_scores and not promo_data: 
        raw_scores["CONV-54.1"] = 0.0

    is_verified = bool(data.get("isVerified") or data.get("verified") or data.get("hasBlueBadge") or data.get("isVerifiedOwner"))
    if "PROF-01.1" in raw_scores and not (is_verified or len(title) > 2):
        raw_scores["PROF-01.1"] = 0.0
    if "PROF-12.1" in raw_scores and not is_verified:
        raw_scores["PROF-12.1"] = 0.0
    if "PROF-03.1" in raw_scores and not categories:
        raw_scores["PROF-03.1"] = 0.0
    if "PROF-03.2" in raw_scores and len(categories) < 3:
        raw_scores["PROF-03.2"] = 0.75 if len(categories) == 2 else 0.0

    if not website: 
        if "PROF-04.1" in raw_scores: raw_scores["PROF-04.1"] = 0.0
        if "PROF-04.2" in raw_scores: raw_scores["PROF-04.2"] = 0.0
    elif "PROF-04.2" in raw_scores and "utm_" not in website:
        raw_scores["PROF-04.2"] = 0.0

    if "PROF-05.1" in raw_scores and not data.get("phones"):
        raw_scores["PROF-05.1"] = 0.0
    if "PROF-07.1" in raw_scores and len(working_hours) < 7:
        raw_scores["PROF-07.1"] = 1.0 if len(working_hours) > 0 else 0.0
    if "PROF-13.1" in raw_scores and not any(w in struct_str for w in ["wa.me", "t.me", "whatsapp"]):
        raw_scores["PROF-13.1"] = 0.0
    if "PROF-10.3" in raw_scores and not any(kw in full_description for kw in ["лечение", "прием", "услуг", "диагностик", "терапи", "консультац"]):
        raw_scores["PROF-10.3"] = 0.0

    legal_info = data.get("legalInfo")
    tax_id = legal_info.get("taxId") if isinstance(legal_info, dict) else None
    has_legal = "инн" in struct_str or "огрн" in struct_str or "taxid" in struct_str or "реквизит" in struct_str or bool(tax_id)
    if "PROF-15.1" in raw_scores and not has_legal:
        raw_scores["PROF-15.1"] = 0.0

    if isinstance(items, list) and len(items) > 0:
        total_items = len(items)
        if "PROF-11.1" in raw_scores and total_items < 10:
            raw_scores["PROF-11.1"] = 2.0 if total_items >= 3 else 0.0
        
        has_photo = sum(1 for i in items if isinstance(i, dict) and (i.get("image") or i.get("imageUrl") or i.get("image_url") or i.get("photoUrl") or i.get("picture")))
        has_price = sum(1 for i in items if isinstance(i, dict) and (i.get("price") or i.get("cost") or i.get("priceValue")))
        has_desc = sum(1 for i in items if isinstance(i, dict) and i.get("description") and len(str(i.get("description"))) > 50)
        has_cta = sum(1 for i in items if isinstance(i, dict) and (i.get("url") or i.get("action") or i.get("bookingUrl")))
        
        if "PROF-11.2" in raw_scores and (has_photo / total_items) < 0.8: raw_scores["PROF-11.2"] = 0.0
        if "PROF-11.3" in raw_scores and (has_price / total_items) < 0.8: raw_scores["PROF-11.3"] = 0.0
        if "PROF-11.4" in raw_scores and (has_desc / total_items) < 0.8:  raw_scores["PROF-11.4"] = 0.0
        if "PROF-11.5" in raw_scores and (has_cta / total_items) < 0.1:  raw_scores["PROF-11.5"] = 0.0
    else:
        for k in ["PROF-11.1", "PROF-11.2", "PROF-11.3", "PROF-11.4", "PROF-11.5"]:
            if k in raw_scores: raw_scores[k] = 0.0

    if "SEO-18.3" in raw_scores and not any(kw in full_description for kw in ["метро", "район", "улиц", "шоссе", "проспект"]):
        raw_scores["SEO-18.3"] = 0.0
    if "PROF-01.2" in raw_scores and (len(title) > 60 or "недорого" in title or "скидк" in title):
        raw_scores["PROF-01.2"] = 0.0 
    if "PROF-08.1" in raw_scores and not features:
        raw_scores["PROF-08.1"] = 0.0

    features_str = str(features).lower()
    if "PROF-08.2" in raw_scores and "дмс" not in features_str and "рассрочка" not in features_str:
        raw_scores["PROF-08.2"] = 0.0
    if "CONT-38.1" in raw_scores and photos_count < 10:
        raw_scores["CONT-38.1"] = 0.5 if photos_count >= 5 else 0.0
    if "CONT-42.1" in raw_scores and not any(kw in struct_str for kw in ["видео", "video", "youtube", "тур", "панорам", "videos"]):
        raw_scores["CONT-42.1"] = 0.0
        
    has_news = bool(data.get("posts") or data.get("news") or data.get("updates") or "story" in struct_str or "новост" in struct_str)
    if "CONT-43.1" in raw_scores and not has_news:
        raw_scores["CONT-43.1"] = 0.0

    if "REP-27.2" in raw_scores and rating < 4.8: raw_scores["REP-27.2"] = 0.0
    if "REP-27.1" in raw_scores and rating < 4.5: raw_scores["REP-27.1"] = 0.0
    if "REP-28.1" in raw_scores and rev_count < 50: raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

    if reviews and isinstance(reviews, list) and len(reviews) > 0:
        replied_count = 0
        seo_in_reviews = False
        most_recent_date = None
        total_revs = len(reviews)

        for r in reviews:
            if isinstance(r, dict):
                if r.get("reply") or r.get("comments") or r.get("businessComment"):
                    replied_count += 1
                rev_text = str(r.get("text", "")).lower()
                if any(kw in rev_text for kw in ["врач", "процедур", "пломб", "кариес", "анализ", "зуб", "мастер", "стрижк"]):
                    seo_in_reviews = True

                date_str = r.get("publishedAtDate") or r.get("updatedAt") or r.get("date")
                if date_str:
                    try:
                        clean_date = str(date_str).split('.')[0].replace('Z', '')
                        r_date = datetime.datetime.fromisoformat(clean_date)
                        if not most_recent_date or r_date > most_recent_date:
                            most_recent_date = r_date
                    except Exception:
                        pass

        if "REP-30.1" in raw_scores and (replied_count / total_revs) < 0.9:
            raw_scores["REP-30.1"] = 1.5 if (replied_count / total_revs) >= 0.5 else 0.0
        if "SEO-19.2" in raw_scores and not seo_in_reviews:
            raw_scores["SEO-19.2"] = 0.0

        if "REP-29.1" in raw_scores:
            if most_recent_date:
                days_diff = (datetime.datetime.now() - most_recent_date).days
                if days_diff > 14:
                    raw_scores["REP-29.1"] = 0.0
            else:
                raw_scores["REP-29.1"] = 0.0

        last_20 = reviews[:20]
        l20_len = len(last_20)
        if l20_len > 0:
            znatoki_count = sum(1 for r in last_20 if isinstance(r, dict) and ("знаток" in str(r.get("authorLevel") or r.get("author", "")).lower() or "уровень" in str(r.get("authorLevel") or r.get("author", "")).lower()))
            photo_rev_count = sum(1 for r in last_20 if isinstance(r, dict) and (r.get("photos") or r.get("photoCount", 0) > 0))

            if "REP-34.1" in raw_scores and (znatoki_count / l20_len) < 0.25:
                raw_scores["REP-34.1"] = 0.0
            if "REP-35.1" in raw_scores and (photo_rev_count / l20_len) < 0.10:
                raw_scores["REP-35.1"] = 0.0
    else:
        for k in ["REP-30.1", "REP-35.1", "REP-34.1", "SEO-19.2", "REP-29.1", "REP-32.2"]:
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
            niche_desc_key = f"Обоснование_ОШИБКИ_{niche}"
            final_desc = meta.get("descs", {}).get(niche_desc_key) or meta.get("descs", {}).get("Обоснование_ОШИБКИ") or "Требуется оптимизация карточки."
            
            gap_list.append({"code": code, "title": meta["title"], "desc": final_desc, "impact": impact})

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_n = gap_list[:5]
    while len(top_n) < 3:
        top_n.append({"title": "Техническая оптимизация", "desc": "Поддерживайте актуальность данных.", "impact": 0})

    return round(total_score, 1), top_n, raw_scores


def fetch_apify_data(target_url: str, logger: TerminalLogger) -> Dict[str, Any]:
    token = st.secrets.get("APIFY_API_TOKEN") or os.getenv("APIFY_API_TOKEN", "").strip()
    actor = st.secrets.get("APIFY_ACTOR_ID") or os.getenv("APIFY_ACTOR_ID", "").strip()
    
    if not token or not actor:
        raise ValueError("Не настроены ключи APIFY_API_TOKEN и APIFY_ACTOR_ID в Secrets или .env.")

    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=300"
    logger.log("Отправка URL в Apify Actor...", "STEP")
    
    payload = {
        "startUrls": [{"url": target_url.strip()}], 
        "maxItems": 1, 
        "includeReviews": True
    }
    
    resp = requests.post(run_url, json=payload, timeout=310)
    if resp.status_code not in [200, 201]:
        raise RuntimeError(f"Сбой Apify: {resp.text[:200]}")
    
    items = resp.json()
    if not items:
        raise ValueError("Apify вернул пустой массив данных.")
    logger.log("Сырые данные успешно загружены.", "SUCCESS")
    return items[0]


def get_gemini_insights(data: Dict[str, Any], logger: TerminalLogger) -> Dict[str, Any]:
    api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not GEMINI_AVAILABLE:
        return {"score": 0, "pain_point": ""}
        
    logger.log("🧠 Запрос к Gemini для поиска главной боли...", "STEP")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash') if hasattr(genai, 'GenerativeModel') else None
        if not model:
            model = genai.GenerativeModel('gemini-1.5-flash')
        
        safe_data = {
            "title": data.get("title", ""),
            "rating": data.get("rating", ""),
            "reviews_count": data.get("reviewsCount", ""),
            "features": data.get("features") or [],
            "recent_reviews": [r.get("text", "") for r in (data.get("reviews") or [])[:5] if isinstance(r, dict)]
        }
        
        prompt = f"""
        Ты маркетолог-эксперт по Яндекс Картам. Анализируем локальный бизнес:
        {json.dumps(safe_data, ensure_ascii=False)}
        
        ПРАВИЛО ЯЗЫКА:
        Не используй маркетинговые термины (конверсия, лиды, целевое действие, путь клиента). Пиши простым языком владельца бизнеса.
        
        Выдай ответ СТРОГО в формате JSON с ключами:
        1. "score" (число 0-100): Оценка вероятности продажи.
        2. "pain_point" (текст): Одно предложение с самой грубой ошибкой профиля (прайс, запись, отзывы, описание).
        """
        
        resp = model.generate_content(prompt)
        
        # Безопасная очистка Markdown-разметки от ИИ
        result_text = resp.text
        result_text = result_text.replace("```json", "")
        result_text = result_text.replace("```", "")
        result_text = result_text.strip()
        
        ai_data = json.loads(result_text)
        return ai_data
    except Exception as e:
        logger.log(f"Ошибка Gemini: {e}", "WARN")
        return {"score": 0, "pain_point": ""}


def process_company_data(raw_input: Any, logger: TerminalLogger, criteria_registry: Dict) -> Dict[str, Any]:
    data = raw_input[0] if isinstance(raw_input, list) and raw_input else raw_input
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        data = data["items"][0]

    title = data.get("title") or data.get("name") or "Организация"
    org_id = str(data.get("org_id") or data.get("id") or "0000000000")
    rating = round(float(data.get("rating") or data.get("reviewsRating") or 5.0), 1)

    logger.log(f"Найдена карточка: «{title}» (Рейтинг: {rating})", "INFO")

    niche = "OTHER"
    low_txt = (str(title) + " " + str(data.get("categories", ""))).lower()
    
    if any(k in low_txt for k in ["стоматолог", "dent"]): niche = "DENTISTRY"
    elif any(k in low_txt for k in ["космет", "эпиляц", "beauty"]): niche = "COSMETOLOGY"
    elif any(k in low_txt for k in ["медцентр", "клиника"]): niche = "GENERAL_MEDICINE"
    elif any(k in low_txt for k in ["стрижк", "барбер", "парикмахер", "волос", "салон красоты"]): niche = "BEAUTY"
    elif any(k in low_txt for k in ["авто", "шиномонтаж", "сервис"]): niche = "AUTOSERVICES"

    score, top_fails, raw_scores = perform_deep_scoring(data, logger, criteria_registry, niche)
    logger.log(f"Итоговый балл готовности: {score:.1f} / 100", "INFO")

    comps = data.get("competitors") or []
    if not isinstance(comps, list) or len(comps) < 2:
        comps = ["соседние бизнесы локации", "конкуренты района"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["OTHER"])
    c_word = n_def["client_word"]
    n_gen = n_def["niche_genitive"]
    
    for f in top_fails:
        desc = f["desc"]
        desc = desc.replace("{CLIENT_WORD}", c_word.capitalize())
        desc = desc.replace("{client_word}", c_word)
        desc = desc.replace("{NICHE_GENITIVE}", n_gen.capitalize())
        desc = desc.replace("{niche_genitive}", n_gen)
        f["desc"] = desc

    legal_info = data.get("legalInfo")
    tax_id = legal_info.get("taxId") if isinstance(legal_info, dict) else None
    
    inn = str(tax_id).strip() if tax_id else ""
    if not inn:
        struct_str = json.dumps(data, ensure_ascii=False).lower()
        match = re.search(r'(?:инн|inn)\s*:?\s*(\d{10,12})\b', struct_str)
        if match:
            inn = match.group(1)

    lpr_info = fetch_dadata_ceo(inn, logger) if inn else ""

    return {
        "title": title, "org_id": org_id, "rating": rating, "score": score, "niche": niche,
        "competitors": comps, "canonical_url": data.get("url", ""),
        "benchmark_leads": n_def["benchmark_leads"], "base_check": n_def["base_check"], 
        "ltv_months": n_def["ltv_months"], "benchmark_source": n_def["benchmark_source"],
        "top_failures": top_fails, "date": datetime.date.today().strftime("%d.%m.%Y"),
        "criteria_scores": raw_scores,
        "raw_data_ref": data,
        "lpr_info": lpr_info
    }

def build_metrics(audit: Dict[str, Any], criteria_registry: Dict) -> Dict[str, str]:
    n_info = NICHE_CONFIG[audit["niche"]]
    score = audit["score"]
    dev = max(0.0, round(100.0 - score, 1))
    
    competitor_score = min(98.5, round(score + max(12.0, (100.0 - score) * 0.6), 1))
    lost_leads = int(round(audit["benchmark_leads"] * (dev / 100.0)))
    current_leads = max(0, audit["benchmark_leads"] - lost_leads)
    
    rev_loss = lost_leads * audit["base_check"]
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * audit["ltv_months"]

    table_declension = get_declension(lost_leads, n_info["client_word"])
    failures = audit.get("top_failures", [])

    colors = []
    for f in failures:
        impact = f.get("impact", 0)
        if impact > 3.0: colors.append("dc2626")       
        elif impact > 1.5: colors.append("ea580c")     
        else: colors.append("eab308")                  
    while len(colors) < 3: colors.append("eab308")

    group_losses = {}
    for code, meta in criteria_registry.items():
        max_w = meta["weight"]
        cur_w = audit.get("criteria_scores", {}).get(code, max_w)
        lost = max_w - cur_w
        if lost > 0: group_losses[meta["group"]] = group_losses.get(meta["group"], 0.0) + lost

    worst_group = max(group_losses, key=group_losses.get) if group_losses else ""
    reason_phrases = {
        "Конверсия": "из-за отсутствия прямого конверсионного инструментария (онлайн-записи или промоакций)",
        "Базовое заполнение": "из-за критических пробелов в заполнении карточки (отсутствие цен или структуры услуг)",
        "Репутация": "из-за просадки в репутационных факторах (паузы в отзывах)",
        "SEO и Трафик": "из-за слабой гео-оптимизации профиля",
        "Контент": "из-за недостатка визуального доверия"
    }
    
    reason_text = reason_phrases.get(worst_group, "из-за технических недочетов в оформлении")
    executive_summary = (f"Профиль «{audit['title']}» обладает высокой репутацией ({audit['rating']:.1f}), "
                         f"однако {reason_text} алгоритм перенаправляет до {lost_leads} готовых обращений в месяц "
                         f"прямым конкурентам локации.")
    
    return {
        "[[TITLE]]": audit["title"], "[[NICHE]]": n_info["niche_name"], "[[DATE]]": audit["date"],
        "[[SCORE]]": f"{score:.1f}", "[[SCORE_COLOR]]": "16a34a" if score >= 80 else ("d97706" if score >= 60 else "dc2626"),
        "[[COMPETITOR_SCORE]]": f"{competitor_score:.1f}",
        "[[REV_LOSS_FMT]]": f"{int(rev_loss):,}".replace(",", " "), 
        "[[CLIENT_LEADS]]": str(audit["benchmark_leads"]),
        "[[CURRENT_LEADS]]": str(current_leads),
        "[[POTENTIAL_LEADS]]": str(audit["benchmark_leads"]),
        "[[DEV]]": f"{dev:.1f}", "[[LOST_LEADS]]": str(lost_leads), "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": f"{int(audit['base_check']):,}".replace(",", " "), "[[CLIENT_LTV]]": str(audit["ltv_months"]),
        "[[LTV_LOSS_FMT]]": f"{int(ltv_loss):,}".replace(",", " "), "[[BENCHMARK_SOURCE]]": audit["benchmark_source"],
        "[[QUALITY_PHRASE]]": n_info["quality_phrase"], "[[EXECUTIVE_SUMMARY]]": executive_summary,
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери", "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию в первичное обращение:",
        "[[FAIL_1_TITLE]]": failures[0]["title"] if len(failures) > 0 else "Барьер конверсии",
        "[[FAIL_1_DESC]]": failures[0]["desc"] if len(failures) > 0 else "Требуется оптимизация.",
        "[[FAIL_1_COLOR]]": colors[0],
        "[[FAIL_2_TITLE]]": failures[1]["title"] if len(failures) > 1 else "Барьер доверия",
        "[[FAIL_2_DESC]]": failures[1]["desc"] if len(failures) > 1 else "Требуется заполнение команды.",
        "[[FAIL_2_COLOR]]": colors[1],
        "[[FAIL_3_TITLE]]": failures[2]["title"] if len(failures) > 2 else "Барьер прейскуранта",
        "[[FAIL_3_DESC]]": failures[2]["desc"] if len(failures) > 2 else "Требуется открытие цен.",
        "[[FAIL_3_COLOR]]": colors[2],
        "[[WEEKLY_LOSS_FMT]]": f"{int(weekly_loss):,}".replace(",", " "),
        "[[RISK_REVERSAL]]": "Отчет ни к чему вас не обязывает. Вы можете передать его своему маркетологу как готовое ТЗ."
    }

def compile_pdf(typ_content: str, out_path: Path, work_dir: Path, logger: TerminalLogger) -> bool:
    temp_typ = work_dir / f"temp_{out_path.stem}.typ"
    try:
        with open(temp_typ, "w", encoding="utf-8") as f:
            f.write(typ_content)
        if PY_TYPST_AVAILABLE:
            typst.compile(str(temp_typ), output=str(out_path))
            return True
        subprocess.run(["typst", "compile", str(temp_typ), str(out_path)], check=True)
        return True
    except Exception as e:
        logger.log(f"Ошибка компиляции Typst: {e}", "ERROR")
        return False
    finally:
        if temp_typ.exists():
            temp_typ.unlink()

def sync_to_google(audit: Dict, mapping: Dict, p_txt: Path, p_json: Path, logger: TerminalLogger) -> bool:
    creds, status = get_google_credentials()
    if not creds:
        return False
        
    try:
        sheets = build("sheets", "v4", credentials=creds)
        sheet_id = st.secrets.get("GOOGLE_SHEET_ID") or os.getenv("GOOGLE_SHEET_ID", "").strip()
        if not sheet_id:
            return False

        audit_id = f"{audit['org_id']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        formatted_org_id = f"{audit['org_id']} | {audit.get('client_stars_str', '')} | {audit.get('client_justification', '')}"

        row_main = [
            audit_id, 
            mapping["[[DATE]]"], 
            datetime.datetime.now().strftime("%H:%M:%S"), 
            audit["title"], 
            formatted_org_id, 
            audit["canonical_url"], 
            audit["niche"], 
            audit["rating"], 
            mapping["[[SCORE]]"], 
            mapping["[[LOST_LEADS]]"], 
            mapping["[[REV_LOSS_FMT]]"], 
            "", # L: Статус воронки
            audit.get("lpr_info", ""), # M: ЛПР и Контакт
            "", # N: Дата фоллоу-апа
            "", # O: Следующий шаг
            audit.get("ai_score", ""), 
            audit.get("ai_pain_point", "")
        ]

        scores_dict = audit.get("criteria_scores", {})
        sorted_codes = sorted(scores_dict.keys())
        row_scores = [audit_id, audit["title"]] + [str(scores_dict[code]) for code in sorted_codes]

        with open(p_txt, "r", encoding="utf-8") as f: letter_text = f.read()
        with open(p_json, "r", encoding="utf-8") as f: json_text = f.read()
        
        if len(json_text) > 49000:
            json_text = json_text[:49000] + "\n\n... [JSON ОБРЕЗАН]"

        row_raw = [audit_id, audit["title"], letter_text, json_text]

        sheets.spreadsheets().values().append(spreadsheetId=sheet_id, range="Main!A:Q", valueInputOption="USER_ENTERED", body={"values": [row_main]}).execute()
        sheets.spreadsheets().values().append(spreadsheetId=sheet_id, range="Scores!A:AQ", valueInputOption="USER_ENTERED", body={"values": [row_scores]}).execute()
        sheets.spreadsheets().values().append(spreadsheetId=sheet_id, range="RawData!A:D", valueInputOption="USER_ENTERED", body={"values": [row_raw]}).execute()
        
        logger.log("Данные синхронизированы с Google Таблицей.", "SUCCESS")
        return True
    except Exception as e:
        logger.log(f"Ошибка записи в Google Sheets: {e}", "ERROR")
        return False

def run_pipeline(raw_data: Any, logger: TerminalLogger, criteria_registry: Dict):
    try:
        audit = process_company_data(raw_data, logger, criteria_registry)
        
        ll = int(round(audit["benchmark_leads"] * ((100.0 - audit["score"]) / 100.0)))
        stars, star_str, justification = calculate_client_potential(audit["rating"], audit["score"], ll)
        
        audit["client_stars"] = stars
        audit["client_stars_str"] = star_str
        audit["client_justification"] = justification
        
        st.session_state.current_audit = audit
        mapping = build_metrics(audit, criteria_registry)
        st.session_state.current_mapping = mapping
        
        ai_insights = get_gemini_insights(audit["raw_data_ref"], logger)
        audit["ai_score"] = ai_insights.get("score", "")
        audit["ai_pain_point"] = ai_insights.get("pain_point", "")

        logger.log("Генерация письма Teardown...", "STEP")
        
        n_info = NICHE_CONFIG.get(audit["niche"], NICHE_CONFIG["OTHER"])
        client_word = n_info["client_word"]
        client_plural = n_info.get("client_word_plural", "клиенты")
        client_gen_pl = n_info.get("client_word_genitive_plural", "клиентов")
        company_word = n_info.get("company_word", "компании")
        
        if "сосед" not in audit['competitors'][0].lower():
            competitors_phrase = f"соседним конкурентам с настроенными профилями (например, «{audit['competitors'][0]}» и «{audit['competitors'][1]}»)"
        else:
            competitors_phrase = "ближайшим конкурентам в вашем районе с настроенными профилями"
            
        failures_text = ""
        num_failures = len(audit["top_failures"])
        for f in audit["top_failures"]:
            failures_text += f"• **{f['title']}**\n{f['desc']}\n\n"
            
        points_declension = get_points_declension(num_failures)
        invisible_pct = round(100.0 - audit['score'], 1)

        ib_txt = (
            f"Тема: Почему {client_plural} на Яндекс Картах не доходят до «{audit['title']}»?\n\n"
            f"Причины, по которым потенциальные {client_plural} на Яндекс Картах не доходят до {company_word} «{audit['title']}», "
            f"определяются сочетанием алгоритмических и психологических барьеров:\n\n"
            f"📊 **Главный вывод: Низкая готовность карточки**\n"
            f"Индекс алгоритмической готовности профиля «{audit['title']}» составляет всего {audit['score']:.1f} из 100. "
            f"Из-за технических и смысловых сбоев витрина бизнеса невидима для {invisible_pct}% целевых локальных поисков. "
            f"Горячий первичный трафик района перетекает к {competitors_phrase}.\n\n"
            f"🚨 **{num_failures} {points_declension} слива {client_gen_pl}:**\n\n"
            f"{failures_text.strip()}\n\n"
            f"💸 **Финансовый масштаб потерь**\n"
            f"Из-за комбинации этих факторов «{audit['title']}» ежемесячно недополучает около {ll} первичных {client_gen_pl}, "
            f"что формирует невидимый кассовый разрыв порядка {mapping['[[REV_LOSS_FMT]]']} ₽ упущенной выручки каждый месяц.\n\n"
            f"Хотите, чтобы я сгенерировал обновленный коммерческий PDF-отчет по «{audit['title']}» или подготовил сценарий короткого видеоразбора этих {num_failures} ошибок для руководителя?"
        )
        
        st.session_state.current_icebreaker = ib_txt

        logger.log("Компиляция PDF-отчета...", "STEP")
        out_dir = Path("output")
        out_dir.mkdir(exist_ok=True)
        prefix = f"{re.sub(r'[^a-zA-Z0-9а-яА-Я]', '_', audit['title'])}_{audit['org_id']}"
        p_pdf, p_txt, p_json = out_dir / f"{prefix}.pdf", out_dir / f"{prefix}.txt", out_dir / f"{prefix}.json"
        
        with open(p_txt, "w", encoding="utf-8") as f: f.write(ib_txt)
        safe_audit_for_json = {k: v for k, v in audit.items() if k != "raw_data_ref"}
        with open(p_json, "w", encoding="utf-8") as f: json.dump(safe_audit_for_json, f, ensure_ascii=False)
        
        tpl = Path("report_template.typ")
        if tpl.exists():
            with open(tpl, "r", encoding="utf-8") as f: content = f.read()
            for k, v in mapping.items(): content = content.replace(k, str(v))
            if compile_pdf(content, p_pdf, out_dir, logger):
                st.session_state.pdf_path = str(p_pdf)
                logger.log("PDF скомпилирован успешно.", "SUCCESS")
        else:
            logger.log("Шаблон report_template.typ не найден!", "ERROR")

        sync_to_google(audit, mapping, p_txt, p_json, logger)
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
        if data:
            run_pipeline(data, logger, criteria_registry)
        else:
            logger.log("Нет данных для анализа.", "ERROR")
    
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
            st.subheader("✉️ Письмо для Аутрича (Teardown)")
            
            if aud.get("lpr_info"):
                st.success(f"👤 **Найден ЛПР:** {aud['lpr_info']}")
            else:
                st.info("👤 ЛПР не найден (ИНН отсутствует или не зарегистрирован в базе)")
                
            st.text_area("Текст для рассылки:", value=st.session_state.current_icebreaker, height=500)

        with c2:
            st.subheader("🎯 Квалификация лида (PIN100)")
            st.markdown(f"**Оценка:** {aud.get('client_stars_str', '')}\n\n**Обоснование:** {aud.get('client_justification', '')}")
            st.divider()
            
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
                st.success("✅ Данные успешно сохранены в Google Таблицу!")

if __name__ == "__main__":
    app()
