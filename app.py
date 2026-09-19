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
    "BEAUTY": {
        "niche_name": "Парикмахерская / Барбершоп",
        "niche_genitive": "салонов красоты",
        "client_word": "клиент",
        "quality_phrase": "мастерства стилистов и уровня сервиса",
        "benchmark_leads": 150,
        "base_check": 1800,
        "ltv_months": 6,
        "benchmark_source": "РБК («Российский рынок бьюти-услуг»)",
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
    },
    "OTHER": {
        "niche_name": "Локальный бизнес",
        "niche_genitive": "конкурентов",
        "client_word": "клиент",
        "quality_phrase": "качества услуг и клиентского сервиса",
        "benchmark_leads": 50,
        "base_check": 2000,
        "ltv_months": 3,
        "benchmark_source": "Усредненные данные локального поиска",
    }
}

FALLBACK_CRITERIA_REGISTRY = {
    "CONV-48.1": {"title": "Онлайн-запись на приём", "group": "Конверсия", "complexity": 2, "weight": 6.0, "descs": {"Обоснование_ОШИБКИ": "Отсутствие прямой онлайн-записи отсекает до 60% вечернего спроса."}},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "descs": {"Обоснование_ОШИБКИ": "В описании клиники нет четкой структуры процедур."}},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "descs": {"Обоснование_ОШИБКИ": "Рейтинг ниже 4.5 приводит к отсечению фильтрами Яндекса."}},
    "PROF-11.3": {"title": "Цены у товаров и услуг", "group": "Базовое заполнение", "complexity": 1, "weight": 3.5, "descs": {"Обоснование_ОШИБКИ": "Слепой прайс отпугивает страхом скрытых накруток."}}
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
        except ValueError as e:
            return FALLBACK_CRITERIA_REGISTRY, f"В таблице не найден столбец: {e}"

        desc_cols = {h: i for i, h in enumerate(headers) if h.startswith("Обоснование_ОШИБКИ")}

        registry = {}
        for row in rows[1:]:
            if len(row) > max(idx_code, idx_weight):
                code = str(row[idx_code]).strip()
                if not code: continue

                try: weight = float(str(row[idx_weight]).replace(',', '.'))
                except ValueError: weight = 0.0

                descs = {}
                for col_name, col_idx in desc_cols.items():
                    if len(row) > col_idx and str(row[col_idx]).strip():
                        descs[col_name] = str(row[col_idx]).strip()

                registry[code] = {
                    "title": str(row[idx_title]).strip() if len(row) > idx_title else code,
                    "group": str(row[idx_group]).strip() if len(row) > idx_group else "Анализ",
                    "complexity": 2, "weight": weight,
                    "descs": descs
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
# 4. АНАЛИЗАТОР ПЕРСПЕКТИВНОСТИ КЛИЕНТА (НОВЫЙ БЛОК)
# ==========================================================

def calculate_client_potential(rating: float, score: float, lost_leads: int) -> Tuple[int, str, str]:
    """Анализирует карточку и выдает оценку перспективности для B2B продаж от 1 до 5 звезд."""
    stars = 0
    reasons = []

    # 1. Репутация (Фундамент продукта)
    if rating >= 4.7:
        stars += 2
        reasons.append(f"отличная репутация ({rating})")
    elif rating >= 4.3:
        stars += 1
        reasons.append(f"хороший рейтинг ({rating})")
    else:
        reasons.append(f"слабая репутация ({rating}) – бизнесу тяжело помочь")

    # 2. Техническая боль (Наш продукт)
    if score <= 65:
        stars += 2
        reasons.append(f"провальная карточка ({score:.1f}/100) – легко показать ошибки")
    elif score <= 85:
        stars += 1
        reasons.append(f"средняя оптимизация ({score:.1f}/100) – есть куда расти")
    else:
        reasons.append(f"карточка уже оптимизирована ({score:.1f}/100) – сложно продать аудит")

    # 3. Экономическая боль (Триггер потерь)
    if lost_leads >= 20:
        stars += 1
        reasons.append(f"очевидные фин. потери (-{lost_leads} обращений)")

    # Финализация звезд
    stars = min(5, max(1, stars)) 
    star_str = "⭐" * stars
    
    if stars >= 4:
        justification = "Горячий лид: " + ", ".join(reasons) + "."
    elif stars == 3:
        justification = "Средний потенциал: " + ", ".join(reasons) + "."
    else:
        justification = "Сомнительный клиент: " + ", ".join(reasons) + "."
        
    return stars, star_str, justification

# ==========================================================
# 5. ХАРДКОРНЫЙ ПАРСИНГ (ВСЕЯДНЫЙ)
# ==========================================================

def perform_deep_scoring(data: Dict[str, Any], logger: TerminalLogger, criteria_registry: Dict, niche: str) -> Tuple[float, List[Dict[str, Any]], Dict[str, float]]:
    logger.log(f"Запуск оценки по {len(criteria_registry)} правилам из Google Таблицы...", "STEP")
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

    # 1. КОНВЕРСИЯ
    if "CONV-48.1" in raw_scores and not any(w in struct_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "dikidi", "записаться", "онлайн-запис", "bookingurl", "actionbuttons"]):
        raw_scores["CONV-48.1"] = 0.0
    if "CONV-48.2" in raw_scores and not any(w in struct_str for w in ["specialist", "doctor", "staff", "стаж", "опыт работы", "врач ", "специалист "]):
        raw_scores["CONV-48.2"] = 0.0
    if "CONV-46.1" in raw_scores and photos_count < 5: raw_scores["CONV-46.1"] = 0.0 
    if "CONV-49.1" in raw_scores and (not any(char.isdigit() for char in full_description) or "мы лучшие" in full_description or "индивидуальный подход" in full_description):
        raw_scores["CONV-49.1"] = 0.0
    if "CONV-52.1" in raw_scores and not any(w in struct_str for w in ["faq", "вопрос", "ответы"]): raw_scores["CONV-52.1"] = 0.0
    if "CONV-53.1" in raw_scores and ("акция" not in struct_str and "скидк" not in struct_str and "старая цена" not in struct_str and "promo" not in struct_str): 
        raw_scores["CONV-53.1"] = 0.0
    if "CONV-54.1" in raw_scores and not promo_data: 
        raw_scores["CONV-54.1"] = 0.0

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
    if "PROF-10.3" in raw_scores and not any(kw in full_description for kw in ["лечение", "прием", "услуг", "диагностик", "терапи", "консультац"]):
        raw_scores["PROF-10.3"] = 0.0

    legal_info = data.get("legalInfo")
    tax_id = legal_info.get("taxId") if isinstance(legal_info, dict) else None
    has_legal = "инн" in struct_str or "огрн" in struct_str or "taxid" in struct_str or "реквизит" in struct_str or bool(tax_id)
    
    if "PROF-15.1" in raw_scores and not has_legal:
        raw_scores["PROF-15.1"] = 0.0

    # ПРАВИЛА 80% ДЛЯ УСЛУГ
    if isinstance(items, list) and len(items) > 0:
        if "PROF-11.1" in raw_scores and len(items) < 10: raw_scores["PROF-11.1"] = 2.0 if len(items) >= 3 else 0.0
        has_photo = sum(1 for i in items if isinstance(i, dict) and (i.get("image") or i.get("imageUrl") or i.get("image_url") or i.get("photoUrl") or i.get("picture")))
        has_price = sum(1 for i in items if isinstance(i, dict) and (i.get("price") or i.get("cost") or i.get("priceValue")))
        has_desc = sum(1 for i in items if isinstance(i, dict) and i.get("description") and len(str(i.get("description"))) > 50)
        has_cta = sum(1 for i in items if isinstance(i, dict) and (i.get("url") or i.get("action") or i.get("bookingUrl")))
        total_items = len(items)
        
        if "PROF-11.2" in raw_scores and (has_photo / total_items) < 0.8: raw_scores["PROF-11.2"] = 0.0
        if "PROF-11.3" in raw_scores and (has_price / total_items) < 0.8: raw_scores["PROF-11.3"] = 0.0
        if "PROF-11.4" in raw_scores and (has_desc / total_items) < 0.8:  raw_scores["PROF-11.4"] = 0.0
        if "PROF-11.5" in raw_scores and (has_cta / total_items) < 0.1:  raw_scores["PROF-11.5"] = 0.0
    else:
        for k in ["PROF-11.1", "PROF-11.2", "PROF-11.3", "PROF-11.4", "PROF-11.5"]:
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
        
    has_news = bool(data.get("posts") or data.get("news") or data.get("updates") or "story" in struct_str or "новост" in struct_str)
    if "CONT-43.1" in raw_scores and not has_news: raw_scores["CONT-43.1"] = 0.0

    # 4. РЕПУТАЦИЯ И ОТЗЫВЫ
    if "REP-27.2" in raw_scores and rating < 4.8: raw_scores["REP-27.2"] = 0.0
    if "REP-27.1" in raw_scores and rating < 4.5: raw_scores["REP-27.1"] = 0.0
    if "REP-28.1" in raw_scores and rev_count < 50: raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

    if reviews and isinstance(reviews, list):
        replied_count = 0
        seo_in_reviews = False
        most_recent_date = None

        for r in reviews:
            if isinstance(r, dict):
                reply = r.get("reply") or r.get("comments") or r.get("businessComment")
                if reply:
                    replied_count += 1
                    
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
        if "SEO-19.2" in raw_scores and not seo_in_reviews: raw_scores["SEO-19.2"] = 0.0

        if "REP-29.1" in raw_scores:
            if most_recent_date:
                days_diff = (datetime.datetime.now() - most_recent_date).days
                if days_diff > 14: raw_scores["REP-29.1"] = 0.0
            else: raw_scores["REP-29.1"] = 0.0

        last_20 = reviews[:20]
        znatoki_count = sum(1 for r in last_20 if isinstance(r, dict) and ("знаток" in str(r.get("authorLevel") or r.get("author", "")).lower() or "уровень" in str(r.get("authorLevel") or r.get("author", "")).lower()))
        photo_rev_count = sum(1 for r in last_20 if isinstance(r, dict) and (r.get("photos") or r.get("photoCount", 0) > 0))

        if "REP-34.1" in raw_scores and (znatoki_count / len(last_20)) < 0.25: raw_scores["REP-34.1"] = 0.0
        if "REP-35.1" in raw_scores and (photo_rev_count / len(last_20)) < 0.10: raw_scores["REP-35.1"] = 0.0

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
            logger.log(f"[{code}] {meta['title']} -> Снят балл: -{lost:.1f}", "WARN")

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]
    while len(top_3) < 3:
        top_3.append({"title": "Техническая оптимизация", "desc": "Поддерживайте актуальность данных.", "impact": 0})

    return round(total_score, 1), top_3, raw_scores


def fetch_apify_data(target_url: str, logger: TerminalLogger) -> Dict[str, Any]:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    actor = os.getenv("APIFY_ACTOR_ID", "").strip()
    
    if "APIFY_API_TOKEN" in st.secrets: token = st.secrets["APIFY_API_TOKEN"]
    if "APIFY_ACTOR_ID" in st.secrets: actor = st.secrets["APIFY_ACTOR_ID"]

    if not token or not actor: raise ValueError("Не настроены ключи APIFY_API_TOKEN и APIFY_ACTOR_ID (добавьте их в Secrets).")

    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=300"
    logger.log(f"Отправка URL в Apify Actor...", "STEP")
    
    payload = {
        "startUrls": [{"url": target_url.strip()}], 
        "maxItems": 1, 
        "includeReviews": True
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
        model = genai.GenerativeModel('gemini-3.5-flash')
        
        safe_data = {
            "title": data.get("title", ""),
            "rating": data.get("rating", ""),
            "reviews_count": data.get("reviewsCount", ""),
            "features": data.get("features") or [],
            "recent_reviews": [r.get("text", "") for r in (data.get("reviews") or [])[:5] if isinstance(r, dict)]
        }
        
        prompt = f"""
        Ты маркетолог-эксперт по Яндекс Картам. Анализируем стоматологию/клинику/салон красоты:
        {json.dumps(safe_data, ensure_ascii=False)}
        
        Наш продукт: аудит карточки и услуги по ее ведению.
        
        🛑 АНТИ-СПАМ ПРАВИЛА ЯНДЕКСА (СТРОГО СОБЛЮДАТЬ ПРИ АНАЛИЗЕ):
        1. Название компании: Запрещены ключевые слова (например, "стоматология", "недорого"), если их нет на реальной вывеске. НИКОГДА не рекомендуй добавлять ключевые слова в название карточки.
        2. Описание: Запрещен SEO-спам (бессмысленное перечисление станций метро, районов или списки услуг через запятую).
        3. Отзывы: Запрещена прямая покупка отзывов за скидки.
        
        🛑 ПРАВИЛО ЯЗЫКА:
        Не используй маркетинговые термины (конверсия, лиды, целевое действие, путь клиента). Пиши простым, понятным языком владельца бизнеса (например: "клиентам неудобно записываться вечером, и они уходят к тем, у кого есть онлайн-запись").
        
        Выдай ответ СТРОГО в формате JSON с ключами:
        1. "score" (число 0-100): Оценка вероятности продажи.
        2. "pain_point" (текст): Одно предложение с самой грубой ошибкой профиля. Фокусируйся ТОЛЬКО на легальных механиках: незаполненный прайс-лист, нет фото врачей, нет онлайн-записи, неотвеченные негативные отзывы, шаблонное описание "мы лучшие" вместо конкретики.
        """
        
        resp = model.generate_content(prompt)
        result_text = resp.text.replace('```json', '').replace('
