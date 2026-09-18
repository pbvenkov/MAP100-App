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

# РАСШИРЕННЫЙ СЛОВАРЬ НИШ (С ПРИВЯЗКОЙ К СТОЛБЦАМ ТАБЛИЦЫ)
NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Анализ рынка стоматологии РФ»)",
        "sheet_column": "DENTISTRY"
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4800,
        "ltv_months": 10,
        "benchmark_source": "РБК («Рынок эстетической медицины»)",
        "sheet_column": "BEAUTY_MEDICAL"
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3900,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat и НАФИ",
        "sheet_column": "DENTISTRY"
    },
    "BEAUTY_SALON": {
        "niche_name": "Салон красоты / Барбершоп",
        "niche_genitive": "салонов красоты",
        "client_word": "клиент",
        "quality_phrase": "мастерства стилистов и сервиса",
        "benchmark_leads": 150,
        "base_check": 2500,
        "ltv_months": 6,
        "benchmark_source": "РБК («Российский рынок салонов красоты»)",
        "sheet_column": "BEAUTY_MEDICAL"
    },
    "AUTOSERVICES": {
        "niche_name": "Автосервис / СТО",
        "niche_genitive": "автосервисов",
        "client_word": "клиент",
        "quality_phrase": "качества ремонта и квалификации механиков",
        "benchmark_leads": 100,
        "base_check": 8000,
        "ltv_months": 12,
        "benchmark_source": "Автостат",
        "sheet_column": "AUTOSERVICES"
    },
    "OTHER": {
        "niche_name": "Локальная компания",
        "niche_genitive": "локального бизнеса",
        "client_word": "клиент",
        "quality_phrase": "качества услуг и клиентского сервиса",
        "benchmark_leads": 60,
        "base_check": 3000,
        "ltv_months": 6,
        "benchmark_source": "Усредненные бенчмарки локального поиска",
        "sheet_column": "OTHER"
    }
}

FALLBACK_CRITERIA_REGISTRY = {
    "CONV-48.1": {"title": "Онлайн-запись на приём", "group": "Конверсия", "complexity": 2, "weight": 6.0, "desc": "Отсутствие прямой онлайн-записи отсекает вечерний спрос.", "active_for": {"OTHER": 1}},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "desc": "Нет четкой структуры.", "active_for": {"OTHER": 1}}
}

# ==========================================================
# 2. УНИВЕРСАЛЬНАЯ АВТОРИЗАЦИЯ GOOGLE
# ==========================================================

def get_google_credentials() -> Tuple[Any, str]:
    if not GOOGLE_LIBS_AVAILABLE: return None, "Библиотеки Google API не установлены."
    creds_data = st.secrets.get("GCP_CREDENTIALS") or st.secrets.get("GOOGLE_CREDENTIALS")
    if creds_data:
        try:
            creds_dict = json.loads(creds_data) if isinstance(creds_data, str) else dict(creds_data)
            return service_account.Credentials.from_service_account_info(creds_dict, scopes=GDRIVE_SCOPES), "OK"
        except Exception as e: return None, f"Ошибка парсинга Secrets: {e}"
    creds_file = Path("credentials.json")
    if creds_file.exists():
        try: return service_account.Credentials.from_service_account_file(str(creds_file), scopes=GDRIVE_SCOPES), "OK"
        except Exception as e: return None, f"Ошибка файла: {e}"
    return None, "Ключи доступа не найдены."

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_criteria_from_google() -> Tuple[Dict[str, Dict[str, Any]], str]:
    creds, status = get_google_credentials()
    if not creds: return FALLBACK_CRITERIA_REGISTRY, status
    try:
        sheets = build("sheets", "v4", credentials=creds)
        result = sheets.spreadsheets().values().get(spreadsheetId=CRITERIA_SHEET_ID, range=CRITERIA_RANGE).execute()
        rows = result.get('values', [])
        if len(rows) < 2: return FALLBACK_CRITERIA_REGISTRY, "Таблица пуста."

        headers = [str(h).strip() for h in rows[0]]
        idx_code, idx_title, idx_group, idx_weight, idx_desc = headers.index("Код"), headers.index("Критерий"), headers.index("Группа метрик"), headers.index("Балл"), headers.index("Обоснование_ОШИБКИ")
        
        # Индексы столбцов с флагами применимости
        cols_to_check = ["DENTISTRY", "BEAUTY_MEDICAL", "AUTOSERVICES", "OTHER"]
        idx_map = {col: (headers.index(col) if col in headers else -1) for col in cols_to_check}

        registry = {}
        for row in rows[1:]:
            if len(row) > max(idx_code, idx_weight):
                code = str(row[idx_code]).strip()
                if not code: continue

                try: weight = float(str(row[idx_weight]).replace(',', '.'))
                except ValueError: weight = 0.0
                
                # Парсим единички и нули для разных ниш
                active_for = {}
                for col, idx in idx_map.items():
                    if idx != -1 and len(row) > idx:
                        val = str(row[idx]).strip()
                        if val.replace(',', '.', 1).replace('.', '', 1).isdigit(): active_for[col] = float(val.replace(',', '.'))
                        else: active_for[col] = 1.0
                    else: active_for[col] = 1.0

                registry[code] = {
                    "title": str(row[idx_title]).strip() if len(row) > idx_title else code,
                    "group": str(row[idx_group]).strip() if len(row) > idx_group else "Анализ",
                    "complexity": 2, "weight": weight,
                    "desc": str(row[idx_desc]).strip() if len(row) > idx_desc else "",
                    "active_for": active_for
                }
        return registry, "OK"
    except Exception as e: return FALLBACK_CRITERIA_REGISTRY, f"Ошибка API: {str(e)}"

# ==========================================================
# 3. ТЕРМИНАЛ И УВЕДОМЛЕНИЯ
# ==========================================================

class TerminalLogger:
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.logs: List[str] = []
    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {"INFO": "🔵 [INFO]", "SUCCESS": "🟢 [SUCCESS]", "WARN": "🟠 [WARN]", "ERROR": "🔴 [ERROR]", "STEP": "⚙️ [STEP]"}.get(level, "🔵 [INFO]")
        self.logs.append(f"{ts} {prefix} {msg}")
        self.placeholder.code("\n".join(self.logs), language="bash")

def send_telegram_error(error_message: str, context: str = "") -> bool:
    bot_token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id: return False
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": f"🚨 <b>Ошибка</b>\n<code>{error_message}</code>", "parse_mode": "HTML"}, timeout=3)
    return True

def get_declension(number: int, word_type: str = "клиент") -> str:
    n, n1 = abs(int(number)) % 100, abs(int(number)) % 10
    if word_type in ["пациент", "клиент"]:
        if 11 <= n <= 19: return f"{word_type}ов"
        if n1 == 1: return word_type
        if 2 <= n1 <= 4: return f"{word_type}а"
        return f"{word_type}ов"
    return "обращений"

# ==========================================================
# 5. ХАРДКОРНЫЙ ПАРСИНГ (ДИНАМИЧЕСКИЙ)
# ==========================================================

def perform_deep_scoring(data: Dict[str, Any], logger: TerminalLogger, criteria_registry: Dict, current_niche: str) -> Tuple[float, List[Dict[str, Any]], Dict[str, float]]:
    logger.log(f"Запуск оценки для ниши {current_niche}...", "STEP")
    
    niche_col = NICHE_CONFIG.get(current_niche, NICHE_CONFIG["OTHER"]).get("sheet_column", "OTHER")
    active_registry = {}
    raw_scores = {}
    
    # ФИЛЬТРУЕМ ПРАВИЛА, АКТИВНЫЕ ТОЛЬКО ДЛЯ ЭТОЙ НИШИ
    for code, meta in criteria_registry.items():
        if meta.get("active_for", {}).get(niche_col, 1.0) > 0:
            active_registry[code] = meta
            raw_scores[code] = float(meta["weight"])
            
    logger.log(f"Отобрано {len(active_registry)} релевантных правил из базы.", "INFO")

    reviews = data.get("reviews") or []
    working_hours = data.get("workingHours") or data.get("schedule") or []
    photos_count = int(data.get("photoCount") or data.get("photosCount") or len(data.get("photos") or []) or 0)
    rating = float(data.get("rating") or data.get("reviewsRating") or 5.0)
    rev_count = int(data.get("reviewsCount") or data.get("ratingCount") or len(reviews))
    categories, title, website = data.get("categories") or [], str(data.get("title") or "").lower(), str(data.get("website") or "").lower()
    features = data.get("features") or data.get("attributes") or []
    base_desc = str(data.get("description") or data.get("about") or "")
    promo_data = data.get("promo")
    promo_desc = str(promo_data.get("description", "")) if isinstance(promo_data, dict) else ""
    full_description = (base_desc + " " + promo_desc).lower()

    items = []
    if isinstance(data.get("menu"), dict) and data["menu"].get("items"): items = data["menu"]["items"]
    elif isinstance(data.get("priceList"), list): items = data["priceList"]
    else:
        for k in ["items", "services", "goods", "productCatalog"]:
            if isinstance(data.get(k), list): items.extend(data[k])

    struct_str = json.dumps({k: v for k, v in data.items() if k not in ["reviews"]}, ensure_ascii=False).lower()

    # 1. КОНВЕРСИЯ
    if "CONV-48.1" in raw_scores and not any(w in struct_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "dikidi", "записаться", "онлайн-запис", "bookingurl"]): raw_scores["CONV-48.1"] = 0.0
    if "CONV-48.2" in raw_scores and not any(w in struct_str for w in ["specialist", "doctor", "staff", "стаж", "опыт работы", "врач ", "специалист ", "мастер", "стилист"]): raw_scores["CONV-48.2"] = 0.0
    if "CONV-46.1" in raw_scores and photos_count < 5: raw_scores["CONV-46.1"] = 0.0 
    if "CONV-49.1" in raw_scores and (not any(char.isdigit() for char in full_description) or "мы лучшие" in full_description): raw_scores["CONV-49.1"] = 0.0
    if "CONV-52.1" in raw_scores and not any(w in struct_str for w in ["faq", "вопрос", "ответы"]): raw_scores["CONV-52.1"] = 0.0
    if "CONV-53.1" in raw_scores and ("акция" not in struct_str and "скидк" not in struct_str and "старая цена" not in struct_str and "promo" not in struct_str): raw_scores["CONV-53.1"] = 0.0
    if "CONV-54.1" in raw_scores and not promo_data: raw_scores["CONV-54.1"] = 0.0

    # 2. БАЗОВОЕ ЗАПОЛНЕНИЕ
    is_verified = bool(data.get("isVerified") or data.get("verified") or data.get("hasBlueBadge"))
    if "PROF-01.1" in raw_scores and not (is_verified or len(title) > 2): raw_scores["PROF-01.1"] = 0.0
    if "PROF-12.1" in raw_scores and not is_verified: raw_scores["PROF-12.1"] = 0.0
    if "PROF-03.1" in raw_scores and not categories: raw_scores["PROF-03.1"] = 0.0
    if "PROF-03.2" in raw_scores and len(categories) < 3: raw_scores["PROF-03.2"] = 0.75 if len(categories) == 2 else 0.0
    if "PROF-04.1" in raw_scores and not website: raw_scores["PROF-04.1"] = 0.0
    if "PROF-04.2" in raw_scores and ("utm_" not in website if website else True): raw_scores["PROF-04.2"] = 0.0
    if "PROF-05.1" in raw_scores and not data.get("phones"): raw_scores["PROF-05.1"] = 0.0
    if "PROF-07.1" in raw_scores and len(working_hours) < 7: raw_scores["PROF-07.1"] = 1.0 if len(working_hours) > 0 else 0.0
    if "PROF-13.1" in raw_scores and not any(w in struct_str for w in ["wa.me", "t.me", "whatsapp"]): raw_scores["PROF-13.1"] = 0.0
    if "PROF-10.3" in raw_scores and not any(kw in full_description for kw in ["лечение", "услуг", "ремонт", "стрижк", "маникюр", "консультац"]): raw_scores["PROF-10.3"] = 0.0
    has_legal = any(w in struct_str for w in ["инн", "огрн", "taxid", "реквизит"]) or (isinstance(data.get("legalInfo"), dict) and data["legalInfo"].get("taxId"))
    if "PROF-15.1" in raw_scores and not has_legal: raw_scores["PROF-15.1"] = 0.0

    if items:
        if "PROF-11.1" in raw_scores and len(items) < 10: raw_scores["PROF-11.1"] = 2.0 if len(items) >= 3 else 0.0
        has_photo = sum(1 for i in items if isinstance(i, dict) and any(k in i for k in ["image", "imageUrl", "photoUrl", "picture"]))
        has_price = sum(1 for i in items if isinstance(i, dict) and any(k in i for k in ["price", "cost", "priceValue"]))
        has_desc = sum(1 for i in items if isinstance(i, dict) and len(str(i.get("description", ""))) > 50)
        has_cta = sum(1 for i in items if isinstance(i, dict) and any(k in i for k in ["url", "action", "bookingUrl"]))
        t_it = len(items)
        if "PROF-11.2" in raw_scores and (has_photo / t_it) < 0.8: raw_scores["PROF-11.2"] = 0.0
        if "PROF-11.3" in raw_scores and (has_price / t_it) < 0.8: raw_scores["PROF-11.3"] = 0.0
        if "PROF-11.4" in raw_scores and (has_desc / t_it) < 0.8:  raw_scores["PROF-11.4"] = 0.0
        if "PROF-11.5" in raw_scores and (has_cta / t_it) < 0.1:  raw_scores["PROF-11.5"] = 0.0
    else:
        for k in ["PROF-11.1", "PROF-11.2", "PROF-11.3", "PROF-11.4", "PROF-11.5"]:
            if k in raw_scores: raw_scores[k] = 0.0

    # 3. SEO И ТРАФИК
    if "SEO-18.3" in raw_scores and not any(kw in full_description for kw in ["метро", "район", "улиц", "шоссе", "проспект"]): raw_scores["SEO-18.3"] = 0.0
    if "PROF-01.2" in raw_scores and (len(title) > 60 or "недорого" in title or "скидк" in title): raw_scores["PROF-01.2"] = 0.0 
    if "PROF-08.1" in raw_scores and not features: raw_scores["PROF-08.1"] = 0.0
    if "CONT-38.1" in raw_scores and photos_count < 10: raw_scores["CONT-38.1"] = 0.5 if photos_count >= 5 else 0.0
    if "CONT-42.1" in raw_scores and not any(kw in struct_str for kw in ["видео", "video", "youtube", "тур", "панорам", "videos"]): raw_scores["CONT-42.1"] = 0.0
    has_news = bool(data.get("posts") or data.get("news") or data.get("updates") or "story" in struct_str or "новост" in struct_str)
    if "CONT-43.1" in raw_scores and not has_news: raw_scores["CONT-43.1"] = 0.0

    # 4. РЕПУТАЦИЯ И ОТЗЫВЫ
    if "REP-27.2" in raw_scores and rating < 4.8: raw_scores["REP-27.2"] = 0.0
    if "REP-27.1" in raw_scores and rating < 4.5: raw_scores["REP-27.1"] = 0.0
    if "REP-28.1" in raw_scores and rev_count < 50: raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

    if reviews:
        replied_count = sum(1 for r in reviews if isinstance(r, dict) and any(k in r for k in ["reply", "comments", "businessComment"]))
        if "REP-30.1" in raw_scores and (replied_count / len(reviews)) < 0.9: raw_scores["REP-30.1"] = 1.5 if (replied_count / len(reviews)) >= 0.5 else 0.0
        
        most_recent_date = None
        for r in reviews:
            d = r.get("publishedAtDate") or r.get("updatedAt") or r.get("date")
            if d:
                try: 
                    rd = datetime.datetime.fromisoformat(str(d).split('.')[0].replace('Z', ''))
                    if not most_recent_date or rd > most_recent_date: most_recent_date = rd
                except: pass
        if "REP-29.1" in raw_scores:
            if most_recent_date and (datetime.datetime.now() - most_recent_date).days > 14: raw_scores["REP-29.1"] = 0.0
            elif not most_recent_date: raw_scores["REP-29.1"] = 0.0
            
        last_20 = reviews[:20]
        if "REP-34.1" in raw_scores and sum(1 for r in last_20 if "знаток" in str(r).lower() or "уровень" in str(r).lower()) / len(last_20) < 0.25: raw_scores["REP-34.1"] = 0.0
        if "REP-35.1" in raw_scores and sum(1 for r in last_20 if isinstance(r, dict) and r.get("photoCount", 0) > 0) / len(last_20) < 0.10: raw_scores["REP-35.1"] = 0.0
    else:
        for k in ["REP-30.1", "REP-35.1", "REP-34.1", "SEO-19.2", "REP-29.1", "REP-32.2"]:
            if k in raw_scores: raw_scores[k] = 0.0 

    # ПЕРЕСЧЕТ В ИДЕАЛЬНУЮ ШКАЛУ 100 БАЛЛОВ (ДИНАМИЧЕСКИ)
    max_possible = sum(meta["weight"] for meta in active_registry.values())
    total_score = 0.0
    gap_list = []
    
    for code, meta in active_registry.items():
        max_w = meta["weight"]
        cur_w = raw_scores.get(code, max_w)
        total_score += cur_w
        lost = max_w - cur_w
        
        if lost > 0.1:
            impact = (lost / max_possible * 100) * (6.0 - meta["complexity"]) if max_possible > 0 else 0
            gap_list.append({"code": code, "title": meta["title"], "desc": meta["desc"], "impact": impact})
            logger.log(f"[{code}] {meta['title']} -> Снят балл: -{lost:.1f}", "WARN")

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]
    while len(top_3) < 3: top_3.append({"title": "Техническая оптимизация", "desc": "Поддерживайте актуальность данных."})

    normalized_score = round((total_score / max_possible) * 100, 1) if max_possible > 0 else 0.0
    return normalized_score, top_3, raw_scores


def fetch_apify_data(target_url: str, logger: TerminalLogger) -> Dict[str, Any]:
    token = os.getenv("APIFY_API_TOKEN", "") or st.secrets.get("APIFY_API_TOKEN", "")
    actor = os.getenv("APIFY_ACTOR_ID", "") or st.secrets.get("APIFY_ACTOR_ID", "")
    if not token or not actor: raise ValueError("Ключи Apify не найдены.")

    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=300"
    logger.log("Отправка URL в Apify Actor...", "STEP")
    resp = requests.post(run_url, json={"startUrls": [{"url": target_url.strip()}], "maxItems": 1, "includeReviews": True}, timeout=310)
    if resp.status_code not in [200, 201]: raise RuntimeError(f"Сбой Apify: {resp.text[:200]}")
    
    items = resp.json()
    if not items: raise ValueError("Apify вернул пустой массив.")
    logger.log("Данные загружены из Apify.", "SUCCESS")
    return items[0]

def get_gemini_insights(data: Dict[str, Any], logger: TerminalLogger, niche_name: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "") or st.secrets.get("GEMINI_API_KEY", "")
    if not api_key or not GEMINI_AVAILABLE:
        logger.log("Gemini API отключен.", "WARN")
        return {"score": 0, "pain_point": ""}
        
    logger.log("🧠 Запрос к ИИ Gemini...", "STEP")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3.5-flash')
        safe_data = {"title": data.get("title", ""), "rating": data.get("rating", ""), "recent_reviews": [r.get("text", "") for r in (data.get("reviews") or [])[:5] if isinstance(r, dict)]}
        
        prompt = f"""
        Ты эксперт по Яндекс Картам. Анализируем {niche_name.lower()}:
        {json.dumps(safe_data, ensure_ascii=False)}
        
        🛑 АНТИ-СПАМ ПРАВИЛА ЯНДЕКСА: Запрещены SEO-ключи в названии, спам районами в описании и подкуп за отзывы.
        Выдай ответ JSON:
        1. "score" (0-100): Вероятность продажи.
        2. "pain_point": Одно предложение с главной грубой ошибкой (пустой прайс, нет фото, шаблоны, нет онлайн-записи).
        """
        resp = model.generate_content(prompt)
        ai_data = json.loads(resp.text.replace('```json', '').replace('
