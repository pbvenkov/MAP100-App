import datetime
import json
import math
import os
import re
import subprocess
import urllib.parse
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

st.set_page_config(page_title="PIN100 Analytics | Envy Matrix", page_icon="📍", layout="wide")

# ==========================================================
# 1. КОНФИГУРАЦИЯ СИСТЕМЫ И БЕНЧМАРКИ
# ==========================================================

GDRIVE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CRITERIA_SHEET_ID = "1NUuGhHn3H-GrgfLnnJoY1Paz8vvl_5E9AUu0QyxweVY"
CRITERIA_RANGE = "Rules!A:Z"
CRM_SHEET_RANGE = "Lead!A:N" # 🎯 Вкладка Lead в таблице Клиенты PiN 100

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
        "search_volume": "более 10 000 поисков стоматологических услуг",
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
        "search_volume": "более 15 000 поисков косметологических услуг",
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
        "search_volume": "более 25 000 поисков бьюти-услуг",
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
        "search_volume": "более 20 000 поисков медицинских услуг",
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
        "search_volume": "тысячи локальных поисков",
    }
}

FALLBACK_CRITERIA_REGISTRY = {
    "CONV-48.1": {"title": "Онлайн-запись на приём", "group": "Конверсия", "complexity": 2, "weight": 6.0, "descs": {"Обоснование_ОШИБКИ": "Отсутствие прямой онлайн-записи отсекает до 60% вечернего спроса."}},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "descs": {"Обоснование_ОШИБКИ": "В описании нет четкой структуры процедур."}},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "descs": {"Обоснование_ОШИБКИ": "Рейтинг ниже 4.5 приводит к отсечению фильтрами."}},
    "PROF-11.3": {"title": "Цены у товаров и услуг", "group": "Базовое заполнение", "complexity": 1, "weight": 3.5, "descs": {"Обоснование_ОШИБКИ": "Слепой прайс отпугивает страхом скрытых накруток."}}
}

# 🛡️ АБСОЛЮТНО БЕЗОПАСНЫЙ RAW-ШАБЛОН TYPST
DEFAULT_TYPST_TEMPLATE = r"""#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2.5cm),
  header: align(right)[
    #text(8pt, fill: luma(120))[PIN 100 Analytics | Независимый аудит гео-выдачи]
  ],
  footer: align(center)[
    #text(8pt, fill: luma(150))[Сгенерировано аналитической платформой. Документ исключительно для внутреннего использования.]
  ]
)

#set text(font: ("Arial", "Liberation Sans", "DejaVu Sans", "Roboto"), size: 11pt, lang: "ru")

#align(center)[
  #text(size: 24pt, weight: "bold", fill: rgb("#1e3a8a"))[PIN 100 ANALYTICS]
  #v(1em)
  #text(size: 18pt, weight: "bold")[Аналитическое заключение:]
  #text(size: 14pt)[Где профиль теряет первичных клиентов]
  #text(size: 12pt, fill: luma(100))[Расчет упущенной выручки локации и перетока спроса к конкурентам]
]

#v(3em)

#rect(width: 100%, fill: luma(245), stroke: luma(200), radius: 4pt, inset: 15pt)[
  #grid(
    columns: (1fr, 2fr),
    row-gutter: 1em,
    [*Организация:*], [*[[TITLE]]*],
    [*Направление:*], [*[[NICHE]]*],
    [*Дата фиксации данных:*], [*[[DATE]]*]
  )
]

#v(3em)

#text(size: 14pt, weight: "bold")[Практическая ценность отчета:]
#v(0.5em)
Отчет показывает скрытые программные фильтры Яндекс Карт, из-за которых готовые к обращению клиенты района уходят к ближайшим конкурентам. Здесь нет общих советов по рекламе: зафиксированы конкретные барьеры конверсии в профиле и рассчитана упущенная выручка бизнеса без затрат на платный трафик.

#pagebreak()

#text(size: 18pt, weight: "bold", fill: rgb("#1e3a8a"))[Резюме для руководителя]
#v(1em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 2em,
  rect(width: 100%, fill: rgb("#[[SCORE_BG_COLOR]]"), stroke: rgb("#[[SCORE_COLOR]]"), radius: 4pt, inset: 15pt)[
    #text(size: 10pt)[ГОТОВНОСТЬ К ПРИЕМУ ТРАФИКА]
    
    #text(size: 24pt, weight: "bold", fill: rgb("#[[SCORE_COLOR]]"))[ [[SCORE]] / 100 ]
    
    #text(size: 9pt)[Балл конкурента-лидера: [[COMPETITOR_SCORE]] / 100]
  ],
  rect(width: 100%, fill: rgb("#fef2f2"), stroke: rgb("#ef4444"), radius: 4pt, inset: 15pt)[
    #text(size: 10pt)[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ]
    
    #text(size: 24pt, weight: "bold", fill: rgb("#ef4444"))[ [[REV_LOSS_FMT]] ₽/мес ]
    
    #text(size: 9pt)[Консервативная оценка первого визита]
  ]
)

#v(2em)

#text(size: 14pt, weight: "bold")[Критический вывод анализа:]
#v(0.5em)
[[EXECUTIVE_SUMMARY]]

#v(2em)

#text(size: 14pt, weight: "bold")[Воронка потерь: где именно карточка теряет клиентов]
#v(1em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1em,
  rect(width: 100%, stroke: luma(200), inset: 10pt)[
    *1. ТРАФИК ЛИДЕРОВ*
    
    *[[POTENTIAL_LEADS]] обр.*
    
    #text(size: 9pt)[Медиана прямых контактов в ТОП-3 локации.]
  ],
  rect(width: 100%, stroke: luma(200), inset: 10pt)[
    *2. ЭКРАННЫЙ ФИЛЬТР*
    
    *Отказ от контакта*
    
    #text(size: 9pt)[Часть людей уходит из-за технических недочетов карточки.]
  ],
  rect(width: 100%, stroke: rgb("#ef4444"), fill: rgb("#fef2f2"), inset: 10pt)[
    *3. УХОД К СОСЕДЯМ*
    
    *[[LOST_LEADS]] [[TABLE_DECLENSION]]*
    
    #text(size: 9pt)[Ежемесячно перетекают к конкурентам.]
  ]
)

#v(2em)
#text(size: 8pt, fill: luma(100))[
  - Консервативный расчет первого визита (базовый чек [[CLIENT_CHECK_FMT]] ₽). С учетом лояльности клиентов (LTV: [[CLIENT_LTV]] мес.) годовой отток районного бюджета составляет до [[LTV_LOSS_FMT]] ₽. Источник бенчмарков: [[BENCHMARK_SOURCE]].
  
  Важное примечание: Оценка [[SCORE]] / 100 фиксирует исключительно техническую готовность профиля в гео-выдаче Яндекса, а не реальное качество [[QUALITY_PHRASE]]. Это программные особенности поисковой системы, которые не зависят от работы администраторов и специалистов.
]

#pagebreak()

#text(size: 18pt, weight: "bold", fill: rgb("#1e3a8a"))[ [[PAGE_3_HEADING]] ]
#v(0.5em)
#text(size: 12pt)[ [[PAGE_3_SUBTITLE]] ]
#v(2em)

#rect(width: 100%, fill: rgb("#[[FAIL_1_BG]]"), stroke: rgb("#[[FAIL_1_COLOR]]"), radius: 4pt, inset: 15pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("#[[FAIL_1_COLOR]]"))[1. [[FAIL_1_TITLE]]]
  #v(0.5em)
  [[FAIL_1_DESC]]
]
#v(1em)

#rect(width: 100%, fill: rgb("#[[FAIL_2_BG]]"), stroke: rgb("#[[FAIL_2_COLOR]]"), radius: 4pt, inset: 15pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("#[[FAIL_2_COLOR]]"))[2. [[FAIL_2_TITLE]]]
  #v(0.5em)
  [[FAIL_2_DESC]]
]
#v(1em)

#rect(width: 100%, fill: rgb("#[[FAIL_3_BG]]"), stroke: rgb("#[[FAIL_3_COLOR]]"), radius: 4pt, inset: 15pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("#[[FAIL_3_COLOR]]"))[3. [[FAIL_3_TITLE]]]
  #v(0.5em)
  [[FAIL_3_DESC]]
]

#pagebreak()

#text(size: 18pt, weight: "bold", fill: rgb("#1e3a8a"))[Дорожная карта перехвата локального спроса]
#v(0.5em)
Пошаговый план возврата первичных клиентов в кассу организации:
#v(1.5em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.5em,
  [
    *ЭТАП 1: СТАРТ*
    
    *3-5 дней*
    
    #text(size: 10pt)[Привязка услуг к запросам, исправление меток входа, парковки и дублирующих адресов.]
  ],
  [
    *ЭТАП 2: ОЦИФРОВКА*
    
    *14 дней*
    
    #text(size: 10pt)[Подключение инструментов конверсии, оформление карточек команды, наглядный прейскурант.]
  ],
  [
    *ЭТАП 3: ЗАКРЕПЛЕНИЕ*
    
    *Постоянно*
    
    #text(size: 10pt)[Регламент ответов на отзывы, защита от недостоверных правок, удержание в ТОП-3 района.]
  ]
)

#v(2em)
#rect(width: 100%, fill: rgb("#fef2f2"), stroke: rgb("#ef4444"), radius: 4pt, inset: 15pt)[
  *ЦЕНА НЕДЕЛИ ПРОМЕДЛЕНИЯ: [[WEEKLY_LOSS_FMT]] ₽ / нед*
  
  #text(size: 10pt)[Сумма, которая безвозвратно переходит к прямым конкурентам локации.]
  #v(0.5em)
  *БЫСТРАЯ ОКУПАЕМОСТЬ:*
  
  #text(size: 10pt)[Всего 2-3 первичных визита полностью перекрывают любые затраты на профессиональную оптимизацию профиля.]
]

#v(2em)
#line(length: 100%, stroke: 0.5pt + luma(200))
#v(1em)

#text(size: 16pt, weight: "bold")[Регламент внедрения изменений]
#v(0.5em)
[[RISK_REVERSAL]]

#v(2em)
С уважением, 

*Павел Венков*

Руководитель агентства PIN 100 

#v(1em)
*Контакты для связи:*

🌐 Сайт: pin100.ru 

💬 Telegram: t.me/paulvenkov 

📞 Телефон: +7 (921) 966-26-89
"""

# ==========================================
# УТИЛИТА ЭКРАНИРОВАНИЯ ТЕКСТА
# ==========================================
def escape_typst(text: Any) -> str:
    """Обезвреживает текст из Яндекса и ИИ для защиты компилятора Typst"""
    if text is None: return ""
    s = str(text)
    s = s.replace("\\", "\\\\") 
    s = s.replace("[", "\\[")        s = s.replace("]", "\\]")   
    s = s.replace("#", "\\#")   
    s = s.replace('"', '«')     
    s = s.replace('$', '\\$')   
    return s

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Вычисляет расстояние между двумя GPS-координатами в метрах"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return int(2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

# ==========================================
# 2. УНИВЕРСАЛЬНАЯ АВТОРИЗАЦИЯ GOOGLE
# ==========================================

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
            return None, f"Ошибка парсинга секретов: {e}"
            
    creds_file = Path("credentials.json")
    if creds_file.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(str(creds_file), scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка чтения локального файла: {e}"
            
    return None, "Ключи доступа не найдены ни в Secrets, ни в файле."

@st.cache_data(ttl=86400, show_spinner=False)
def _load_google_rules() -> List[List[Any]]:
    creds, status = get_google_credentials()
    if not creds:
        raise ValueError(f"Нет доступа к ключам: {status}")
        
    sheets = build("sheets", "v4", credentials=creds)
    result = sheets.spreadsheets().values().get(spreadsheetId=CRITERIA_SHEET_ID, range=CRITERIA_RANGE).execute()
    rows = result.get('values', [])
    
    if not rows or len(rows) < 2:
        raise ValueError("Таблица пуста или не найден лист Rules.")
    return rows

def fetch_criteria_from_google() -> Tuple[Dict[str, Dict[str, Any]], str]:
    try:
        rows = _load_google_rules()
        headers = [str(h).strip() for h in rows[0]]
        
        idx_code = headers.index("Код")
        idx_title = headers.index("Критерий")
        idx_group = headers.index("Группа метрик")
        idx_weight = headers.index("Балл")
        
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
    if not bot_token or not chat_id: return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"🚨 <b>PIN100 Ошибка</b>\n<b>Контекст:</b> {context}\n<code>{error_message}</code>"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
        return True
    except Exception: return False

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
    
    if stars >= 4: justification = "Горячий лид: " + ", ".join(reasons) + "."
    elif stars == 3: justification = "Средний потенциал: " + ", ".join(reasons) + "."
    else: justification = "Сомнительный клиент: " + ", ".join(reasons) + "."
        
    return stars, star_str, justification

def fetch_dadata_ceo(inn: str, logger: TerminalLogger) -> str:
    api_key = st.secrets.get("DADATA_API_KEY") or os.getenv("DADATA_API_KEY", "").strip()
    if not api_key: return ""
        
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Token {api_key}"}
    
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
        return ""
    except Exception as e:
        logger.log(f"Ошибка API DaData: {e}", "ERROR")
        return ""

# ==========================================================
# 5. ХАРДКОРНЫЙ ПАРСИНГ И СКОРИНГ
# ==========================================================

def perform_deep_scoring(data: Dict[str, Any], logger: TerminalLogger, criteria_registry: Dict, niche: str) -> Tuple[float, List[Dict[str, Any]], Dict[str, float]]:
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
    if "PROF-15.1" in raw_scores and not has_legal: raw_scores["PROF-15.1"] = 0.0

    if isinstance(items, list) and len(items) > 0:
        total_items = len(items)
        if "PROF-11.1" in raw_scores and total_items < 10: raw_scores["PROF-11.1"] = 2.0 if total_items >= 3 else 0.0
        
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

    if "SEO-18.3" in raw_scores and not any(kw in full_description for kw in ["метро", "район", "улиц", "шоссе", "проспект"]): raw_scores["SEO-18.3"] = 0.0
    if "PROF-01.2" in raw_scores and (len(title) > 60 or "недорого" in title or "скидк" in title): raw_scores["PROF-01.2"] = 0.0 
    if "PROF-08.1" in raw_scores and not features: raw_scores["PROF-08.1"] = 0.0

    features_str = str(features).lower()
    if "PROF-08.2" in raw_scores and "дмс" not in features_str and "рассрочка" not in features_str: raw_scores["PROF-08.2"] = 0.0
    if "CONT-38.1" in raw_scores and photos_count < 10: raw_scores["CONT-38.1"] = 0.5 if photos_count >= 5 else 0.0
    if "CONT-42.1" in raw_scores and not any(kw in struct_str for kw in ["видео", "video", "youtube", "тур", "панорам", "videos"]): raw_scores["CONT-42.1"] = 0.0
        
    has_news = bool(data.get("posts") or data.get("news") or data.get("updates") or "story" in struct_str or "новост" in struct_str)
    if "CONT-43.1" in raw_scores and not has_news: raw_scores["CONT-43.1"] = 0.0

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
                if r.get("reply") or r.get("comments") or r.get("businessComment"): replied_count += 1
                rev_text = str(r.get("text", "")).lower()
                if any(kw in rev_text for kw in ["врач", "процедур", "пломб", "кариес", "анализ", "зуб", "мастер", "стрижк"]): seo_in_reviews = True

                date_str = r.get("publishedAtDate") or r.get("updatedAt") or r.get("date")
                if date_str:
                    try:
                        clean_date = str(date_str).split('.')[0].replace('Z', '')
                        r_date = datetime.datetime.fromisoformat(clean_date)
                        if not most_recent_date or r_date > most_recent_date: most_recent_date = r_date
                    except Exception: pass

        if "REP-30.1" in raw_scores and (replied_count / total_revs) < 0.9: raw_scores["REP-30.1"] = 1.5 if (replied_count / total_revs) >= 0.5 else 0.0
        if "SEO-19.2" in raw_scores and not seo_in_reviews: raw_scores["SEO-19.2"] = 0.0

        if "REP-29.1" in raw_scores:
            if most_recent_date:
                days_diff = (datetime.datetime.now() - most_recent_date).days
                if days_diff > 14: raw_scores["REP-29.1"] = 0.0
            else: raw_scores["REP-29.1"] = 0.0

        last_20 = reviews[:20]
        l20_len = len(last_20)
        if l20_len > 0:
            znatoki_count = sum(1 for r in last_20 if isinstance(r, dict) and ("знаток" in str(r.get("authorLevel") or r.get("author", "")).lower() or "уровень" in str(r.get("authorLevel") or r.get("author", "")).lower()))
            photo_rev_count = sum(1 for r in last_20 if isinstance(r, dict) and (r.get("photos") or r.get("photoCount", 0) > 0))

            if "REP-34.1" in raw_scores and (znatoki_count / l20_len) < 0.25: raw_scores["REP-34.1"] = 0.0
            if "REP-35.1" in raw_scores and (photo_rev_count / l20_len) < 0.10: raw_scores["REP-35.1"] = 0.0
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
    
    if not token or not actor: raise ValueError("Не настроены ключи APIFY_API_TOKEN и APIFY_ACTOR_ID.")

    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=300"
    logger.log("Отправка URL в Apify Actor...", "STEP")
    
    payload = {"startUrls": [{"url": target_url.strip()}], "maxItems": 1, "includeReviews": True}
    resp = requests.post(run_url, json=payload, timeout=310)
    if resp.status_code not in [200, 201]: raise RuntimeError(f"Сбой Apify: {resp.text[:200]}")
    
    items = resp.json()
    if not items: raise ValueError("Apify вернул пустой массив данных.")
    logger.log("Сырые данные успешно загружены.", "SUCCESS")
    return items[0]

# ==========================================================
# 🚀 НОВЫЙ АЛГОРИТМ: ПАКЕТНЫЙ ПОИСК РАЙОНА В YANDEX ЧЕРЕЗ APIFY
# ==========================================================
def fetch_apify_batch_search(query: str, max_items: int, logger: TerminalLogger) -> List[Dict[str, Any]]:
    token = st.secrets.get("APIFY_API_TOKEN") or os.getenv("APIFY_API_TOKEN", "").strip()
    actor = st.secrets.get("APIFY_ACTOR_ID") or os.getenv("APIFY_ACTOR_ID", "").strip()
    
    if not token or not actor: raise ValueError("Не настроены ключи APIFY_API_TOKEN и APIFY_ACTOR_ID.")

    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=300"
    logger.log(f"Отправка запроса в Apify: «{query}» (Лимит: {max_items} клиник)...", "STEP")
    logger.log("⏳ Это может занять 1-3 минуты. Пожалуйста, подождите...", "INFO")
    
    search_url = f"https://yandex.ru/maps/search/{urllib.parse.quote(query)}"
    payload = {"startUrls": [{"url": search_url}], "maxItems": max_items, "includeReviews": True}
    
    resp = requests.post(run_url, json=payload, timeout=310)
    if resp.status_code not in [200, 201]: raise RuntimeError(f"Сбой Apify: {resp.text[:200]}")
    
    items = resp.json()
    if not items: raise ValueError("Apify вернул пустой массив. Возможно, по вашему запросу ничего не найдено.")
    logger.log(f"Сырые данные ({len(items)} карточек) успешно загружены.", "SUCCESS")
    return items

def get_gemini_insights(data: Dict[str, Any], logger: TerminalLogger) -> Dict[str, Any]:
    api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not GEMINI_AVAILABLE: return {"score": 0, "pain_point": ""}
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3.8-flash')
        
        safe_data = {
            "title": data.get("title", ""),
            "rating": data.get("rating", ""),
            "reviews_count": data.get("reviewsCount", ""),
            "features": data.get("features") or [],
            "recent_reviews": [r.get("text", "") for r in (data.get("reviews") or [])[:5] if isinstance(r, dict)]
        }
        
        prompt = f"""
        Ты маркетолог-эксперт по B2B продажам. Анализируем профиль бизнеса:
        {json.dumps(safe_data, ensure_ascii=False)}
        
        ПРАВИЛО ЯЗЫКА (СТРОГО):
        - Не используй слова: "мастера", "лид-магнит", "кликабельность", "промо-блок", "целевое действие".
        - Используй B2B термины: "врачи и специалисты", "точка первого контакта", "ценообразование", "видимость".
        - Не указывай клиенту, что делать (никакой дидактики и советов "опишите", "добавьте"). Просто констатируй алгоритмическую проблему.
        - Не оскорбляй бизнес (не пиши "вызывает ощущение некомпетентности").
        
        Выдай ответ СТРОГО в формате JSON с ключами:
        1. "score" (число 0-100).
        2. "pain_point" (текст): Одно предложение с самой грубой алгоритмической ошибкой.
        """
        
        resp = model.generate_content(prompt)
        result_text = resp.text.strip()
        if result_text.startswith("```"):
            result_text = re.sub(r"^```(?:json)?\n?", "", result_text)
            result_text = re.sub(r"\n?```$", "", result_text).strip()
            
        try:
            return json.loads(result_text)
        except Exception:
            match = re.search(r'\{.*\}', result_text, re.DOTALL)
            return json.loads(match.group(0)) if match else {"score": 0, "pain_point": ""}
            
    except Exception as e:
        return {"score": 0, "pain_point": ""}

def process_company_data(raw_input: Any, logger: TerminalLogger, criteria_registry: Dict) -> Dict[str, Any]:
    data = raw_input[0] if isinstance(raw_input, list) and raw_input else raw_input
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list): data = data["items"][0]

    title = data.get("title") or data.get("name") or "Организация"
    org_id = str(data.get("org_id") or data.get("id") or "0000000000")
    rating = round(float(data.get("rating") or data.get("reviewsRating") or 5.0), 1)
    
    loc = data.get("location", {})
    lat = loc.get("lat") or data.get("latitude") or 0.0
    lon = loc.get("lng") or loc.get("lon") or data.get("longitude") or 0.0

    niche = "OTHER"
    low_txt = (str(title) + " " + str(data.get("categories", ""))).lower()
    
    if any(k in low_txt for k in ["стоматолог", "dent"]): niche = "DENTISTRY"
    elif any(k in low_txt for k in ["космет", "эпиляц", "beauty"]): niche = "COSMETOLOGY"
    elif any(k in low_txt for k in ["медцентр", "клиника"]): niche = "GENERAL_MEDICINE"
    elif any(k in low_txt for k in ["стрижк", "барбер", "парикмахер", "волос", "салон красоты"]): niche = "BEAUTY"
    elif any(k in low_txt for k in ["авто", "шиномонтаж", "сервис"]): niche = "AUTOSERVICES"

    score, top_fails, raw_scores = perform_deep_scoring(data, logger, criteria_registry, niche)
    
    comps = data.get("competitors") or []
    if not isinstance(comps, list) or len(comps) < 2: comps = ["соседние бизнесы локации", "конкуренты района"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["OTHER"])
    c_word = n_def["client_word"]
    n_gen = n_def["niche_genitive"]
    
    for f in top_fails:
        desc = f["desc"]
        desc = desc.replace("{CLIENT_WORD}", c_word.capitalize()).replace("{client_word}", c_word)
        desc = desc.replace("{NICHE_GENITIVE}", n_gen.capitalize()).replace("{niche_genitive}", n_gen)
        f["desc"] = desc

    legal_info = data.get("legalInfo")
    tax_id = legal_info.get("taxId") if isinstance(legal_info, dict) else None
    
    inn = str(tax_id).strip() if tax_id else ""
    if not inn:
        struct_str = json.dumps(data, ensure_ascii=False).lower()
        match = re.search(r'(?:инн|inn)\s*:?\s*(\d{10,12})\b', struct_str)
        if match: inn = match.group(1)

    lpr_info = fetch_dadata_ceo(inn, logger) if inn else ""

    dev = max(0.0, 100.0 - score)
    ll = int(round(n_def["benchmark_leads"] * (dev / 100.0)))
    rev_loss = ll * n_def["base_check"]

    return {
        "title": title, "org_id": org_id, "rating": rating, "score": score, "niche": niche,
        "lat": lat, "lon": lon,
        "competitors": comps, "canonical_url": data.get("url", ""),
        "benchmark_leads": n_def["benchmark_leads"], "base_check": n_def["base_check"], 
        "ltv_months": n_def["ltv_months"], "benchmark_source": n_def["benchmark_source"],
        "top_failures": top_fails, "date": datetime.date.today().strftime("%d.%m.%Y"),
        "criteria_scores": raw_scores, "raw_data_ref": data, "lpr_info": lpr_info,
        "rev_loss": rev_loss
    }

def build_metrics(audit: Dict[str, Any], criteria_registry: Dict) -> Dict[str, str]:
    n_info = NICHE_CONFIG[audit["niche"]]
    score = audit["score"]
    
    total_params = 41
    filled_params = int(round(total_params * (score / 100.0)))
    
    dev = max(0.0, 100.0 - score)
    lost_leads = int(round(audit["benchmark_leads"] * (dev / 100.0)))
    current_leads = max(0, audit["benchmark_leads"] - lost_leads)
    
    rev_loss = lost_leads * audit["base_check"]
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * audit["ltv_months"]

    table_declension = get_declension(lost_leads, n_info["client_word"])
    failures = audit.get("top_failures", [])

    fail_colors = []
    fail_bgs = []
    for f in failures:
        impact = f.get("impact", 0)
        if impact > 3.0: 
            fail_colors.append("dc2626")
            fail_bgs.append("fef2f2")
        elif impact > 1.5: 
            fail_colors.append("ea580c")
            fail_bgs.append("fff7ed")
        else: 
            fail_colors.append("eab308")
            fail_bgs.append("fefce8")
            
    while len(fail_colors) < 3: 
        fail_colors.append("eab308")
        fail_bgs.append("fefce8")
        
    if score >= 80:
        score_col, score_bg = "16a34a", "f0fdf4"
    elif score >= 60:
        score_col, score_bg = "d97706", "fff7ed"
    else:
        score_col, score_bg = "dc2626", "fef2f2"

    reason_text = "из-за технических недочетов в оформлении"
    executive_summary = (f"Профиль «{audit['title']}» обладает высокой репутацией ({audit['rating']:.1f}), "
                         f"однако {reason_text} алгоритм перенаправляет до {lost_leads} готовых обращений в месяц "
                         f"прямым конкурентам локации.")
                         
    competitor_score = min(98.5, round(score + max(12.0, (100.0 - score) * 0.6), 1))
    
    return {
        "[[TITLE]]": audit["title"], "[[NICHE]]": n_info["niche_name"], "[[DATE]]": audit["date"],
        "[[SCORE]]": f"{score:.1f}", "[[SCORE_COLOR]]": score_col, "[[SCORE_BG_COLOR]]": score_bg,
        "[[COMPETITOR_SCORE]]": f"{competitor_score:.1f}", "[[REV_LOSS_FMT]]": f"{int(rev_loss):,}".replace(",", " "), 
        "[[CLIENT_LEADS]]": str(audit["benchmark_leads"]), "[[CURRENT_LEADS]]": str(current_leads),
        "[[POTENTIAL_LEADS]]": str(audit["benchmark_leads"]), "[[DEV]]": f"{dev:.1f}", 
        "[[LOST_LEADS]]": str(lost_leads), "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": f"{int(audit['base_check']):,}".replace(",", " "), "[[CLIENT_LTV]]": str(audit["ltv_months"]),
        "[[LTV_LOSS_FMT]]": f"{int(ltv_loss):,}".replace(",", " "), "[[BENCHMARK_SOURCE]]": audit["benchmark_source"],
        "[[QUALITY_PHRASE]]": n_info["quality_phrase"], "[[EXECUTIVE_SUMMARY]]": executive_summary,
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери", "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию:",
        "[[FAIL_1_TITLE]]": failures[0]["title"] if len(failures) > 0 else "Барьер конверсии",
        "[[FAIL_1_DESC]]": failures[0]["desc"] if len(failures) > 0 else "Требуется оптимизация.", 
        "[[FAIL_1_COLOR]]": fail_colors[0], "[[FAIL_1_BG]]": fail_bgs[0],
        "[[FAIL_2_TITLE]]": failures[1]["title"] if len(failures) > 1 else "Барьер доверия",
        "[[FAIL_2_DESC]]": failures[1]["desc"] if len(failures) > 1 else "Требуется заполнение команды.", 
        "[[FAIL_2_COLOR]]": fail_colors[1], "[[FAIL_2_BG]]": fail_bgs[1],
        "[[FAIL_3_TITLE]]": failures[2]["title"] if len(failures) > 2 else "Барьер прейскуранта",
        "[[FAIL_3_DESC]]": failures[2]["desc"] if len(failures) > 2 else "Требуется открытие цен.", 
        "[[FAIL_3_COLOR]]": fail_colors[2], "[[FAIL_3_BG]]": fail_bgs[2],
        "[[WEEKLY_LOSS_FMT]]": f"{int(weekly_loss):,}".replace(",", " "),
        "[[RISK_REVERSAL]]": "Я готов бесплатно записать для вас 3-минутный видеоразбор. В нем я открою Яндекс Карты и прямо на экране покажу, как именно конкуренты перехватывают ваши поисковые запросы."
    }

def compile_pdf(typ_content: str, out_path: Path, work_dir: Path, logger: TerminalLogger) -> bool:
    temp_typ = work_dir / f"temp_{out_path.stem}.typ"
    st.session_state.broken_typst = typ_content  
    try:
        with open(temp_typ, "w", encoding="utf-8") as f: f.write(typ_content)
        if PY_TYPST_AVAILABLE:
            typst.compile(str(temp_typ), output=str(out_path))
            st.session_state.broken_typst = None 
            return True
        result = subprocess.run(["typst", "compile", str(temp_typ), str(out_path)], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            logger.log(f"Сбой компиляции Typst: {result.stderr.strip()}", "ERROR")
            return False
        st.session_state.broken_typst = None 
        return True
    except FileNotFoundError:
        logger.log("Критическая ошибка: Компилятор Typst не установлен на сервере!", "ERROR")
        return False
    except Exception as e:
        logger.log(f"Ошибка компиляции Typst: {e}", "ERROR")
        return False
    finally:
        if temp_typ.exists(): temp_typ.unlink()

def sync_batch_to_google(rows: List[List[Any]], logger: TerminalLogger) -> bool:
    creds, status = get_google_credentials()
    if not creds: return False
    try:
        sheets = build("sheets", "v4", credentials=creds)
        sheet_id = st.secrets.get("GOOGLE_SHEET_ID") or os.getenv("GOOGLE_SHEET_ID", "").strip()
        if not sheet_id: return False

        sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id, 
            range=CRM_SHEET_RANGE, 
            valueInputOption="USER_ENTERED", 
            body={"values": rows}
        ).execute()
        
        logger.log(f"Успешно выгружено {len(rows)} строк во вкладку Lead.", "SUCCESS")
        return True
    except Exception as e:
        logger.log(f"Ошибка выгрузки матрицы в Google Sheets: {e}", "WARN")
        return False

# ==========================================================
# 🎯 PREDICTIVE MATCHMAKING ALGORITHM
# ==========================================================
def process_batch(items: List[Dict], logger: TerminalLogger, criteria_registry: Dict):
    logger.log(f"Начата пакетная обработка {len(items)} локаций...", "STEP")
    audits = []
    for idx, raw_item in enumerate(items):
        try:
            audit = process_company_data([raw_item], logger, criteria_registry)
            audits.append(audit)
        except Exception as e:
            logger.log(f"Сбой парсинга локации #{idx+1}: {e}", "WARN")
            
    logger.log(f"Аудит завершен. Ищем идеальных раздражителей...", "STEP")
    
    rows_to_export = []
    
    for lead in audits:
        if lead['score'] >= 85: continue # Пропускаем лидеров, они нам не клиенты
        
        best_comp = None
        best_comp_dist = float('inf')
        max_contrast = -1
        
        for comp in audits:
            if lead['org_id'] == comp['org_id']: continue
            
            dist = haversine(lead['lat'], lead['lon'], comp['lat'], comp['lon'])
            
            if dist <= 2000 and comp['score'] > lead['score'] + 15:
                contrast = comp['score'] - lead['score']
                if comp['rating'] < lead['rating']:
                    contrast += 20 
                    
                if contrast > max_contrast:
                    max_contrast = contrast
                    best_comp = comp
                    best_comp_dist = dist
                    
        vuln = lead['top_failures'][0]['title'] if lead['top_failures'] else "Слабое заполнение"
        
        if best_comp:
            comp_name = best_comp['title']
            dist_str = f"{best_comp_dist} метров"
            comp_adv = f"Балл алгоритма {best_comp['score']} из 100"
            scenario = f"Сравниваем с «{comp_name}» ({dist_str}). Покажи экран: Яндекс дает им {best_comp['score']} баллов, а нашему клиенту {lead['score']}. Главная боль: {vuln}."
        else:
            comp_name = "Нет сильного соседа рядом"
            dist_str = "-"
            comp_adv = "-"
            scenario = f"Соседей-лидеров в радиусе 2 км нет. Дави на то, что локация свободна и можно легко забрать весь трафик, исправив '{vuln}'."

        row = [
            lead['title'], 
            lead['canonical_url'], 
            f"{lead['lat']}, {lead['lon']}",
            lead['lpr_info'],
            f"{lead['score']:.1f}",
            lead['rev_loss'],
            vuln,
            comp_name,
            dist_str,
            comp_adv,
            scenario,
            "Новый",
            "Записать видеоразбор",
            datetime.date.today().strftime("%d.%m.%Y")
        ]
        rows_to_export.append(row)
        
    sync_batch_to_google(rows_to_export, logger)
    logger.log("Пакетный конвейер завершен! Матрица зависти сформирована.", "SUCCESS")
    st.session_state.batch_done = True
    st.balloons()

def run_pipeline(raw_data: Any, logger: TerminalLogger, criteria_registry: Dict):
    try:
        audit = process_company_data(raw_data, logger, criteria_registry)
        
        dev = max(0.0, 100.0 - audit["score"])
        ll = int(round(audit["benchmark_leads"] * (dev / 100.0)))
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

        logger.log("Генерация B2B-письма Teardown...", "STEP")
        
        n_info = NICHE_CONFIG.get(audit["niche"], NICHE_CONFIG["OTHER"])
        client_plural = n_info.get("client_word_plural", "клиенты")
        company_word = n_info.get("company_word", "организации")
        search_volume = n_info.get("search_volume", "тысячи локальных поисков")
        
        if "сосед" not in audit['competitors'][0].lower():
            competitors_phrase = f"«{audit['competitors'][0]}» и «{audit['competitors'][1]}»"
        else:
            competitors_phrase = "ближайших конкурентов района"
            
        failures_text = ""
        top_3 = audit["top_failures"][:3]
        for f in top_3:
            failures_text += f"• **{f['title']}**. {f['desc']}\n\n"

        total_params = 41
        filled_params = int(round(total_params * (audit["score"] / 100.0)))
        missing_params = total_params - filled_params
        
        lpr_name = audit.get("lpr_info", "").split(" (")[0] if audit.get("lpr_info") else "Коллеги"
        if not lpr_name.strip() or len(lpr_name) < 3: lpr_name = "Коллеги"

        ib_txt = (
            f"Тема: Почему {client_plural} на Яндекс Картах не доходят до {company_word} «{audit['title']}»?\n\n"
            f"{lpr_name}, добрый день.\n\n"
            f"В вашей локации ежемесячно фиксируется {search_volume}, однако часть этого первичного потока "
            f"проходит мимо «{audit['title']}» и уходит к ближайшим конкурентам (в частности, в {competitors_phrase}).\n\n"
            f"Наш аналитический центр провел независимую проверку вашего профиля по алгоритмам Яндекса 2026 года. "
            f"Из {total_params} обязательных параметров ранжирования в вашей карточке корректно настроены только {filled_params}.\n\n"
            f"Вот 3 главные причины, почему теряются записи:\n\n"
            f"{failures_text.strip()}\n\n"
            f"**Откуда берется цифра потерь:**\n"
            f"Теряя всего ~{ll} первичных обращений в месяц при минимальном чеке {mapping['[[CLIENT_CHECK_FMT]]']} ₽, "
            f"бизнес ежемесячно недополучает около {mapping['[[REV_LOSS_FMT]]']} рублей прямого приема (не считая LTV за повторные визиты).\n\n"
            f"Все {missing_params} незаполненных параметров и детальный расчет мы оформили в наглядный 4-страничный PDF-отчет. "
            f"Если вам интересно взглянуть на цифры, ответьте на это письмо словом «Да», и я пришлю файл.\n\n"
            f"--\n"
            f"Павел Венков\n"
            f"Основатель аналитического центра PIN100\n"
            f"Оцифровка и аналитика гео-карт для бизнеса\n"
            f"🌐 Сайт: pin100.ru\n"
            f"📱 Telegram / WhatsApp: +7 (921) 966-26-89"
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
        with open(tpl, "w", encoding="utf-8") as f:
            f.write(DEFAULT_TYPST_TEMPLATE)
            
        with open(tpl, "r", encoding="utf-8") as f: content = f.read()
        
        for k, v in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
            v_str = escape_typst(v)
            content = content.replace(k, v_str)
            
        if compile_pdf(content, p_pdf, out_dir, logger):
            st.session_state.pdf_path = str(p_pdf)
            logger.log("PDF скомпилирован успешно.", "SUCCESS")
        else:
            st.session_state.pdf_path = None
            logger.log("Сбой компиляции PDF-отчета.", "ERROR")

    except Exception as ex:
        logger.log(f"Критическая ошибка конвейера: {ex}", "ERROR")
        send_telegram_error(str(ex), "Pipeline Run")

def app():
    criteria_registry, sync_status = fetch_criteria_from_google()
    
    with st.sidebar:
        st.header("⚙️ Настройки системы")
        if st.button("🔄 Синхронизировать критерии", use_container_width=True):
            _load_google_rules.clear()
            st.rerun()
            
        st.caption(f"Загружено правил: {len(criteria_registry)}")
        if sync_status != "OK":
            st.error(f"⚠️ Сбой таблицы:\n{sync_status}")
            
    st.title("📍 PIN100 Analytics: Генератор аудитов гео-выдачи")
    tab_json, tab_url, tab_batch, tab_apify_search = st.tabs([
        "📋 Одиночный (JSON)", 
        "🔗 Одиночный (Ссылка)", 
        "📂 Пакетный (JSON)", 
        "🌍 Парсинг района (Apify)"
    ])

    with tab_json:
        col1, col2 = st.columns([1, 2])
        file = col1.file_uploader("Файл .json из Apify:", type=["json"], key="single_file")
        txt = col2.text_area("Или код JSON:", height=100)
        btn_json = st.button("🚀 Запустить конвейер по JSON", type="primary", use_container_width=True)

    with tab_url:
        url = st.text_input("Ссылка на Яндекс Карты:")
        btn_url = st.button("🚀 Запустить краулинг и конвейер", type="primary", use_container_width=True)

    with tab_batch:
        st.info("💡 Загрузите готовый массив выгрузки (от 10 до 200 клиник). Скрипт отскорит их все, найдет слабые звенья и подберет идеального лидера в радиусе 2 км для записи видеоразбора.")
        batch_file = st.file_uploader("Массив .json из Apify:", type=["json"], key="batch_file")
        btn_batch = st.button("🔥 Запустить Predictive Matchmaking", type="primary", use_container_width=True)

    with tab_apify_search:
        st.info("💡 Задайте локацию и нишу. Скрипт сам запросит Apify собрать карточки, отскорит их, найдет лидеров и занесет готовые связки в Google Таблицу (Вкладка 'Lead').")
        c1, c2 = st.columns(2)
        search_city = c1.text_input("Город:", value="Санкт-Петербург")
        search_district = c2.text_input("Район / Метро / Улица:", value="Васильевский остров")
        search_niche = st.selectbox("Выберите нишу:", options=list(NICHE_CONFIG.keys()), format_func=lambda x: NICHE_CONFIG[x]["niche_name"])
        search_max = st.slider("Лимит сбора карточек (чем больше, тем дольше парсинг):", 5, 100, 20)
        btn_apify_search = st.button("🗺️ Запустить автоматический сбор и анализ", type="primary", use_container_width=True)

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

    if btn_batch:
        if batch_file:
            data = json.load(batch_file)
            if isinstance(data, list):
                process_batch(data, logger, criteria_registry)
            else:
                logger.log("Файл не является массивом (ожидался список объектов).", "ERROR")
        else:
            logger.log("Загрузите файл с массивом.", "ERROR")

    if btn_apify_search:
        if not search_city.strip() or not search_district.strip():
            logger.log("Укажите город и район для поиска.", "ERROR")
        else:
            query = f"{search_city} {search_district} {NICHE_CONFIG[search_niche]['niche_name']}"
            try:
                data = fetch_apify_batch_search(query, search_max, logger)
                process_batch(data, logger, criteria_registry)
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
            
            pdf_path = st.session_state.get("pdf_path")
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                st.download_button("📥 Скачать PDF", data=pdf_bytes, file_name=Path(pdf_path).name, mime="application/pdf", type="primary", use_container_width=True)
            else:
                st.error("⚠️ Кнопка недоступна: PDF-отчет не сгенерирован.")

if __name__ == "__main__":
    app()
