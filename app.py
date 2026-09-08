import streamlit as st

# ==========================================
# 0. ИНИЦИАЛИЗАЦИЯ СТРАНИЦЫ (СТРОГО ПЕРВЫЙ ВЫЗОВ)
# ==========================================
st.set_page_config(
    page_title="PIN100 | Аналитический Отчет",
    layout="wide",
    page_icon="📍"
)

import requests
import os
import time
import json
import re
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import tempfile
import typst

try:
    from utils import generate_icebreaker_text
except ImportError:
    def generate_icebreaker_text(data, templates_dict=None):
        return f"Здравствуйте! Подготовлен аудит для {data.get('title', 'организации')}."

try:
    from drive_manager import DriveManager
except ImportError:
    DriveManager = None

# ==========================================
# 1. КОНФИГУРАЦИЯ И СЛУЖЕБНЫЕ УТИЛИТЫ
# ==========================================
PROJECT_NAME = "PIN100"
EXPERT_TITLE = "Генератор B2B Воронки (Аналитический Отчет)"

APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper"
VK_API_TOKEN = st.secrets.get("VK_API_TOKEN", "")
DADATA_API_KEY = st.secrets.get("DADATA_API_KEY", "")

try:
    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    if gemini_key:
        genai.configure(api_key=gemini_key)
        generation_config = {"temperature": 0.0, "top_p": 0.1, "top_k": 1}
        expert_engine = genai.GenerativeModel('gemini-2.5-flash', generation_config=generation_config)
    else:
        expert_engine = None
except Exception:
    expert_engine = None

def plural_ru(n, forms):
    """Склонение существительных: ('пациент', 'пациента', 'пациентов')"""
    n = abs(int(n)) % 100
    n1 = n % 10
    if 10 < n < 20:
        return forms[2]
    if 1 < n1 < 5:
        return forms[1]
    if n1 == 1:
        return forms[0]
    return forms[2]

def safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(str(val).replace(',', '.').strip())
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    if val is None:
        return default
    try:
        clean = re.sub(r'[^\d]', '', str(val))
        return int(clean) if clean else default
    except (ValueError, TypeError):
        return default

def clean_typography(text):
    if not text:
        return ""
    t = str(text).replace(" - ", " — ").replace(">=", "≥").replace("<=", "≤").replace("->", "→")
    t = t.replace("<", " меньше ").replace(">", " больше ")
    # Экранирование и очистка спецсимволов для безопасной вставки в Typst
    for c in ['\\', '[', ']', '{', '}', '$', '*', '_', '#', '@', '"', "'", '`', '~', '^']:
        t = t.replace(c, ' ')
    return " ".join(t.split())

# ==========================================
# 2. УВЕДОМЛЕНИЯ В TELEGRAM
# ==========================================
def send_telegram_alert(error_msg, target_url="Неизвестно"):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    if tg_token and tg_admin_id:
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        text = f"🚨 *{PROJECT_NAME}: Сбой системы*\n\n*Цель:* {target_url}\n*Ошибка:* {error_msg}"
        try:
            requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except Exception:
            pass

def send_telegram_business_alert(title, category, unique_keys):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    if not (tg_token and tg_admin_id):
        return

    ai_reasoning = "Потенциально высокий LTV. Требует ручной бизнес-оценки."
    if expert_engine:
        try:
            prompt = f"Кратко (в 2 предложениях) оцени нишу '{category}' (компания '{title}'). Почему B2B-консалтинг окупится в этом сегменте?"
            response = expert_engine.generate_content(prompt)
            ai_reasoning = response.text.strip()
        except Exception:
            pass

    tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    text = (
        f"🚨 *Обнаружена новая ниша!*\n\n"
        f"🏢 *Компания:* {title}\n"
        f"🏷 *Категория:* {category}\n"
        f"🔑 *Ключи:* {', '.join(unique_keys)}\n\n"
        f"💡 *Оценка ИИ:*\n_{ai_reasoning}_"
    )
    try:
        requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
    except Exception:
        pass

# ==========================================
# 3. ПОИСК ЛПР И ИНН (КАСКАДНЫЙ WATERFALL)
# ==========================================
def extract_inn(data, dadata_token=None):
    """Каскадный поиск ИНН: Apify JSON -> Регулярные выражения -> DaData API"""
    legal_info = data.get('legalInfo') or data.get('companyLegalInfo') or {}
    if isinstance(legal_info, dict) and legal_info.get('inn'):
        clean_inn = re.sub(r'[^\d]', '', str(legal_info.get('inn')))
        if len(clean_inn) in (10, 12):
            return clean_inn

    text_corpus = " ".join([
        str(data.get('description') or ''),
        str(data.get('legalName') or ''),
        str(data.get('companyName') or ''),
        str(data.get('features') or '')
    ])
    
    inn_match = re.search(r'(?:ИНН\D{0,5})?(\b\d{10}\b|\b\d{12}\b)', text_corpus, re.IGNORECASE)
    if inn_match:
        return inn_match.group(1)

    if dadata_token:
        query_target = data.get("legalName") or data.get("companyName") or data.get("title")
        if query_target and len(query_target) > 3:
            url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Token {dadata_token}"
            }
            try:
                res = requests.post(url, json={"query": query_target, "count": 1}, headers=headers, timeout=4).json()
                suggestions = res.get("suggestions", [])
                if suggestions:
                    inn_val = suggestions[0].get("data", {}).get("inn")
                    if inn_val:
                        return str(inn_val)
            except Exception:
                pass

    return ""

def extract_lpr_from_reviews(reviews_data, engine=None):
    """Поиск подписи руководства в официальных ответах на отзывы"""
    if not reviews_data or not engine:
        return {}
        
    replies = []
    for r in reviews_data[:20]:
        if not isinstance(r, dict):
            continue
        reply_obj = r.get('reply') or {}
        text = reply_obj.get('text', '') if isinstance(reply_obj, dict) else (r.get('businessComment') or '')
        if text and len(text) > 15:
            replies.append(text.strip())

    if not replies:
        return {}

    prompt = f"""Ниже приведены официальные ответы организации на отзывы клиентов:
{chr(10).join(replies[:8])}

Найди, кем и как подписываются ответы (имя и должность ЛПР: главврач, директор, управляющий, владелица).
Верни строго JSON:
{{"name": "Имя или Имя Отчество", "role": "Должность", "status": "found"}}
Если подписи нет или она обезличена (например, "Администрация" или "Команда"), верни: {{"status": "not_found"}}"""

    try:
        raw_res = engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if data.get("status") == "found" and data.get("name"):
                return data
    except Exception:
        pass
    return {}

def enrich_lpr_contacts_from_vk(social_links):
    """Поиск контактов руководителя через VK API"""
    if not VK_API_TOKEN or not social_links:
        return {}
    vk_url = next((link.get('url', '') for link in social_links if isinstance(link, dict) and ('vk.com' in link.get('url', '') or 'vk.ru' in link.get('url', ''))), None)
    if not vk_url:
        return {}
    try:
        clean_vk = vk_url.split('?')[0].rstrip('/')
        group_id = clean_vk.split('/')[-1]
        res = requests.get("https://api.vk.com/method/groups.getById", params={"group_id": group_id, "fields": "contacts", "access_token": VK_API_TOKEN, "v": "5.199"}, timeout=5).json()
        if 'response' in res and res['response']:
            contacts = res['response'][0].get('contacts', [])
            if not contacts:
                return {"status": "hidden", "vk_url": vk_url}
            contact = contacts[0]
            lpr_data = {"name": "", "role": contact.get('desc', 'Администратор'), "link": "", "email": contact.get('email', ''), "status": "found"}
            if 'user_id' in contact:
                lpr_data["link"] = f"https://vk.com/id{contact['user_id']}"
                u_res = requests.get("https://api.vk.com/method/users.get", params={"user_ids": contact['user_id'], "access_token": VK_API_TOKEN, "v": "5.199"}, timeout=5).json()
                if 'response' in u_res and u_res['response']:
                    lpr_data["name"] = f"{u_res['response'][0].get('first_name', '')} {u_res['response'][0].get('last_name', '')}".strip()
            return lpr_data
    except Exception:
        pass
    return {}

def enrich_lpr_by_dadata(query_str, dadata_token=None):
    """Поиск ФИО генерального директора или ИП через DaData API по ИНН или названию"""
    if not dadata_token or not query_str:
        return {}
        
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Token {dadata_token}"
    }
    try:
        res = requests.post(url, json={"query": query_str, "count": 1}, headers=headers, timeout=4).json()
        suggestions = res.get("suggestions", [])
        if suggestions:
            party_data = suggestions[0].get("data", {})
            management = party_data.get("management") or {}
            
            if management.get("name"):
                return {
                    "name": management.get("name"),
                    "role": management.get("post", "Руководитель"),
                    "status": "found"
                }
            if party_data.get("type") == "INDIVIDUAL":
                fio = party_data.get("name", {}).get("full", "")
                clean_fio = fio.replace("ИП", "").strip()
                return {
                    "name": clean_fio,
                    "role": "Индивидуальный предприниматель",
                    "status": "found"
                }
    except Exception:
        pass
    return {}

# ==========================================
# 4. БАЗА ДАННЫХ, CRM И УМНАЯ ЭКОНОМИКА
# ==========================================
NICHE_ECONOMICS = {
    "DENTISTRY": {"leads": 70, "check": 6500, "label": "Стоматология", "ltv_months": 12},
    "HORECA": {"leads": 150, "check": 1500, "label": "HORECA / Рестораны", "ltv_months": 12},
    "B2B": {"leads": 40, "check": 25000, "label": "Легкий B2B / Опт", "ltv_months": 12},
    "B2B_HEAVY": {"leads": 10, "check": 300000, "label": "Сложный B2B / Производство", "ltv_months": 1},
    "RETAIL": {"leads": 200, "check": 1200, "label": "Ритейл", "ltv_months": 12},
    "AUTO": {"leads": 100, "check": 5500, "label": "Автосервис / Автосалон", "ltv_months": 6},
    "SERVICES": {"leads": 60, "check": 4000, "label": "Услуги B2C", "ltv_months": 6},
    "BEAUTY_MEDICAL": {"leads": 80, "check": 3500, "label": "Медицина / Бьюти", "ltv_months": 12},
    "EDUCATION": {"leads": 30, "check": 18000, "label": "Образование", "ltv_months": 12},
    "OTHER": {"leads": 50, "check": 3000, "label": "Прочее", "ltv_months": 6}
}

NICHE_MIN_FLOOR = {
    "DENTISTRY": 4500,
    "AUTO": 3000,
    "BEAUTY_MEDICAL": 2500,
    "EDUCATION": 8000,
    "B2B": 15000,
    "B2B_HEAVY": 100000,
    "HORECA": 900,
    "RETAIL": 900,
    "SERVICES": 2000,
    "OTHER": 1500
}

GEO_TIERS = {
    "TIER_1": {
        "cities": ["москва", "санкт-петербург", "петербург", "зеленоград", "сочи"],
        "multiplier": 1.45
    },
    "TIER_2": {
        "cities": [
            "новосибирск", "екатеринбург", "казань", "нижний новгород", "челябинск",
            "красноярск", "самара", "уфа", "ростов-на-дону", "омск", "краснодар",
            "воронеж", "пермь", "волгоград", "тюмень", "владивосток"
        ],
        "multiplier": 1.15
    }
}

def _calculate_geo_check(data: dict, niche_key: str) -> tuple[int, str]:
    base_eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
    base_check = base_eco["check"]
    
    address = str(data.get("address") or "").lower()
    geo_mult = 1.0
    geo_label = "Регионы РФ"

    if any(city in address for city in GEO_TIERS["TIER_1"]["cities"]):
        geo_mult = GEO_TIERS["TIER_1"]["multiplier"]
        geo_label = "Москва / СПб"
    elif any(city in address for city in GEO_TIERS["TIER_2"]["cities"]):
        geo_mult = GEO_TIERS["TIER_2"]["multiplier"]
        geo_label = "Город-миллионник"

    final_check = int(round(base_check * geo_mult / 500) * 500)
    return final_check, f"Консервативный базис ({geo_label})"

def determine_smart_check(data: dict, niche_key: str) -> tuple[int, str]:
    address = str(data.get("address") or "").lower()
    geo_mult = 1.0
    if any(city in address for city in GEO_TIERS["TIER_1"]["cities"]):
        geo_mult = GEO_TIERS["TIER_1"]["multiplier"]
    elif any(city in address for city in GEO_TIERS["TIER_2"]["cities"]):
        geo_mult = GEO_TIERS["TIER_2"]["multiplier"]

    base_floor = NICHE_MIN_FLOOR.get(niche_key, 1500)
    floor_val = int(round(base_floor * geo_mult / 100) * 100)

    # 1. B2B сегмент сразу рассчитываем по гео-матрице
    if niche_key in ["B2B", "B2B_HEAVY"]:
        val, src = _calculate_geo_check(data, niche_key)
        return max(val, floor_val), src

    # 2. HORECA: атрибут averageBill Яндекса
    raw_bill = data.get("averageBill") or data.get("priceCategory") or ""
    bill_digits = re.findall(r'\d+', str(raw_bill).replace(' ', ''))
    if bill_digits:
        nums = [int(n) for n in bill_digits if int(n) >= 300]
        if nums:
            avg_bill = int(sum(nums) / len(nums))
            final_val = max(avg_bill, floor_val)
            return final_val, "Средний счёт из профиля Яндекса"

    # 3. Анализ прайс-листа карточки
    menu_data = data.get('menu')
    m_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    c_items = data.get('productCatalog') or []
    all_items = [p for p in (m_items + c_items) if isinstance(p, dict)]

    extracted_prices = []
    lower_price_limit = max(400, int(base_floor * 0.5))

    for item in all_items:
        raw_price = str(item.get("price") or item.get("cost") or "")
        clean_p = re.sub(r'[^\d]', '', raw_price)
        if clean_p:
            p_val = int(clean_p)
            if lower_price_limit <= p_val <= 90000:
                extracted_prices.append(p_val)

    if len(extracted_prices) >= 5:
        extracted_prices.sort()
        idx = int(len(extracted_prices) * 0.35)
        smart_price = round(extracted_prices[idx] / 100) * 100
        multiplier = 1.8 if niche_key == "HORECA" else 1.0
        final_val = int(round(smart_price * multiplier / 100) * 100)
        
        if final_val < floor_val:
            return floor_val, f"Базовый порог ниши ({floor_val:,} ₽)".replace(',', ' ')
            
        return final_val, f"Прайс-лист карточки ({len(extracted_prices)} позиций)"

    # 4. Резервный расчет по гео-матрице
    val, src = _calculate_geo_check(data, niche_key)
    return max(val, floor_val), src

def get_google_credentials():
    creds_raw = st.secrets.get("GCP_CREDENTIALS", {})
    if isinstance(creds_raw, str):
        creds_dict = json.loads(creds_raw)
    else:
        creds_dict = dict(creds_raw)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)

@st.cache_data(ttl=300)
def fetch_cached_database():
    try:
        client = gspread.authorize(get_google_credentials())
        doc = client.open_by_url(st.secrets["SPREADSHEET_URL"])
        
        raw_rules = doc.worksheet("Rules").get_all_values()
        rules = [dict(zip(raw_rules[0], row)) for row in raw_rules[1:] if any(row)]
        
        raw_prompts = doc.worksheet("Prompts").get_all_values()
        prompts = [dict(zip(raw_prompts[0], row)) for row in raw_prompts[1:] if any(row)]
        
        templates = {}
        try:
            raw_templates = doc.worksheet("Templates").get_all_values()
            if len(raw_templates) > 1:
                for row in raw_templates[1:]:
                    if len(row) >= 2 and row[0].strip():
                        templates[row[0].strip().upper()] = row[1].strip()
        except Exception:
            templates = {}
            
        return rules, prompts, templates
    except Exception as e:
        st.error(f"Ошибка подключения к Google Sheets: {e}")
        return [], [], {}

def check_oid_history(oid):
    """Каскадная проверка наличия OID в CRM и истории замеров"""
    if not oid or oid == "UNKNOWN":
        return {"exists": False, "source": None, "base_score": None, "last_score": None, "count": 0}
    
    try:
        client = gspread.authorize(get_google_credentials())
        doc = client.open_by_url(st.secrets["SPREADSHEET_URL"])
        
        try:
            cp_ws = doc.worksheet("Client_Progress")
            cp_rows = cp_ws.get_all_values()
            if len(cp_rows) > 1:
                matches = [r for r in cp_rows[1:] if len(r) > 1 and str(r[1]).strip() == str(oid)]
                if matches:
                    base_score = safe_float(matches[0][4])
                    last_score = safe_float(matches[-1][4])
                    return {"exists": True, "source": "Client_Progress", "base_score": base_score, "last_score": last_score, "count": len(matches)}
        except Exception:
            pass

        try:
            res_ws = doc.worksheet("Results")
            res_rows = res_ws.get_all_values()
            if len(res_rows) > 1:
                for r in res_rows[1:]:
                    if len(r) > 1 and str(r[1]).strip() == str(oid):
                        base_score = safe_float(r[5])
                        return {"exists": True, "source": "Results", "base_score": base_score, "last_score": base_score, "count": 1}
        except Exception:
            pass

    except Exception:
        pass

    return {"exists": False, "source": None, "base_score": None, "last_score": None, "count": 0}

def save_lead_to_results(oid, url, title, niche, total_score, lost_revenue, lpr_data=None, inn=""):
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Results")
        
        lpr_name = lpr_data.get("name", "") if lpr_data else ""
        lpr_role = lpr_data.get("role", "") if lpr_data else ""
        lpr_contact = (lpr_data.get("link", "") or lpr_data.get("email", "")) if lpr_data else ""
        
        row = [
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"),
            str(oid),
            title,
            url,
            niche,
            str(round(total_score, 1)).replace('.', ','),
            lpr_name,
            lpr_role,
            lpr_contact,
            f"{lost_revenue:,}".replace(',', ' ') + " ₽",
            "1. Новый лид",
            f"'{inn}" if inn else ""
        ]
        ws.append_row(row)
    except Exception:
        pass

def save_progress_measurement(oid, title, audit_type, total_score, delta_start, delta_last, lost_revenue, pdf_url, json_url, clean_url):
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Client_Progress")
        
        row = [
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"),
            str(oid),
            title,
            audit_type,
            str(round(total_score, 1)).replace('.', ','),
            f"+{round(delta_start, 1)}".replace('.', ',') if delta_start > 0 else str(round(delta_start, 1)).replace('.', ','),
            f"+{round(delta_last, 1)}".replace('.', ',') if delta_last > 0 else str(round(delta_last, 1)).replace('.', ','),
            f"{lost_revenue:,}".replace(',', ' ') + " ₽",
            pdf_url,
            json_url,
            clean_url
        ]
        ws.append_row(row)
    except Exception:
        pass

# ==========================================
# 5. НОРМАЛИЗАЦИЯ, OID И ПАРСИНГ (С ДИАГНОСТИКОЙ)
# ==========================================
def extract_oid_and_url(raw_url):
    url = str(raw_url).strip()
    
    # 1. Разворачиваем короткие ссылки Яндекса вида maps/-/CCU...
    if "/-/" in url:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        })
        try:
            res = session.get(url, allow_redirects=True, timeout=12)
            if res.url:
                url = res.url
        except Exception:
            pass

    url = re.sub(r'yandex\.(?:com|by|kz|uz)/', 'yandex.ru/', url)
    url = url.replace("yandex.ru/navi/", "yandex.ru/maps/")
    
    oid = "UNKNOWN"
    clean_url = url
    
    # 2. Проверяем каноничный формат Яндекс Карт: /org/{slug}/{oid}
    org_match = re.search(r'/org/([^/?#]+)/(\d+)', url)
    if org_match:
        slug = org_match.group(1)
        oid = org_match.group(2)
        clean_url = f"https://yandex.ru/maps/org/{slug}/{oid}/"
    else:
        # 3. Резервный поиск OID, если ссылка вида ?oid=123 или /org/123
        oid_match = re.search(r'(?:oid(?:%3D|=)|/org/)(\d{6,})', url)
        if not oid_match:
            oid_match = re.search(r'\b(\d{7,13})\b', url)
            
        if oid_match:
            oid = oid_match.group(1)
            clean_url = f"https://yandex.ru/maps/org/_/{oid}/"
        else:
            if "?" in url:
                url = url.split("?")[0]
            clean_url = re.sub(r'/(reviews|gallery|features|menu|goods|prices|posts)/?$', '', url).rstrip('/') + '/'

    return oid, clean_url

def get_apify_run_details(run_id):
    """Извлекает statusMessage и последние строки лога запуска из Apify"""
    log_text = ""
    status_msg = ""
    try:
        meta_res = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}",
            timeout=8
        ).json()
        status_msg = meta_res.get("data", {}).get("statusMessage", "")

        log_res = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/log?token={APIFY_API_TOKEN}",
            timeout=8
        )
        if log_res.status_code == 200:
            lines = [line.strip() for line in log_res.text.strip().split("\n") if line.strip()]
            log_text = " | ".join(lines[-6:])
    except Exception:
        pass
        
    return status_msg, log_text

def fetch_apify_data(cleaned_url):
    # Передаем полный URL во внутренний поиск для защиты от сбоев резолва OID
    payload = {
        "startUrls": [{"url": cleaned_url}],
        "searchStringsArray": [cleaned_url],
        "enrichBusinessData": True,
        "includeReviews": True,
        "maxReviews": 20,
        "maxPhotos": 60,
        "maxPosts": 20,
        "proxyConfiguration": {
            "useApifyProxy": True
        }
    }
    
    run_req = requests.post(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}",
        json=payload,
        timeout=15
    ).json()
    
    if 'error' in run_req:
        err_type = run_req['error'].get('type', 'Unknown')
        err_msg = run_req['error'].get('message', 'Неизвестная ошибка')
        raise Exception(f"Apify API Error [{err_type}]: {err_msg}")
        
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
        if retries >= 75:
            _, log_tail = get_apify_run_details(run_id)
            raise Exception(f"Таймаут сбора данных. Лог Apify: {log_tail or 'нет ответа'}")
        time.sleep(4)
        status_req = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}", 
            timeout=10
        ).json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED":
        status_msg, log_tail = get_apify_run_details(run_id)
        reason = status_msg or log_tail or "Неизвестная ошибка контейнера"
        raise Exception(f"Актор завершился со статусом [{status}]: {reason}")
        
    dataset = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}", 
        timeout=15
    ).json()
    
    if not isinstance(dataset, list) or len(dataset) == 0:
        _, log_tail = get_apify_run_details(run_id)
        
        if "captcha" in log_tail.lower():
            diag = "Яндекс запросил SmartCaptcha (IP датацентра заблокирован)"
        elif "navigation timeout" in log_tail.lower():
            diag = "Страница организации не загрузилась вовремя (таймаут сети)"
        elif "found 0" in log_tail.lower() or "not found" in log_tail.lower():
            diag = "Организация не найдена поисковым селектором Яндекса"
        else:
            diag = log_tail or "Датасет пуст"
            
        raise Exception(f"Яндекс вернул пустой ответ (Run ID: {run_id}). Диагностика: {diag}")
        
    first_item = dataset[0]
    if not isinstance(first_item, dict):
        raise Exception("Некорректный формат данных ответа от актора.")
        
    resolved_title = (
        first_item.get('title') or 
        first_item.get('name') or 
        first_item.get('companyName') or 
        first_item.get('header') or 
        "Организация"
    )
    first_item['title'] = resolved_title
    return first_item

# ==========================================
# 6. СКОРИНГ И СЕМАНТИЧЕСКИЙ АНАЛИЗ
# ==========================================
def parse_yandex_date(date_val):
    if not date_val:
        return None
    try:
        if isinstance(date_val, (int, float)) or (isinstance(date_val, str) and str(date_val).isdigit()):
            return datetime.fromtimestamp(int(date_val) / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(date_val).replace('Z', '+00:00'))
    except Exception:
        return None

def determine_niche_by_expert(title, category, prompts_data):
    full_context = f"{title} {category}".lower()
    
    if any(w in full_context for w in ["стомат", "зуб", "дентал", "ортодонт"]):
        return "DENTISTRY"
    if any(w in full_context for w in ["авто", "сервис", "шиномонтаж", "мойка", "сто "]):
        return "AUTO"
    if any(w in full_context for w in ["ресторан", "кафе", "бар", "кофейня", "пицц", "бургер"]):
        return "HORECA"
    if any(w in full_context for w in ["клиник", "мед", "косметолог", "бьюти", "салон красоты"]):
        return "BEAUTY_MEDICAL"
    if any(w in full_context for w in ["школ", "курс", "обучен", "центр развития", "язык"]):
        return "EDUCATION"
    if any(w in full_context for w in ["завод", "производ", "пром", "фабрик"]):
        return "B2B_HEAVY"
    if any(w in full_context for w in ["опт", "поставщик", "склад"]):
        return "B2B"

    if not expert_engine:
        return "OTHER"
        
    raw_prompt = next((p.get("Промпт для ИИ") for p in prompts_data if p.get("Код") == "NICHE_PROMPT"), "")
    if not raw_prompt:
        raw_prompt = "Определи нишу для компании {title}, категория {category}. Варианты: DENTISTRY, HORECA, B2B, B2B_HEAVY, RETAIL, AUTO, BEAUTY_MEDICAL, EDUCATION, SERVICES, OTHER. Верни только код ниши."
    prompt = raw_prompt.replace("{title}", title).replace("{category}", category)
    try:
        key = expert_engine.generate_content(prompt).text.strip().upper()
        for v in ["B2B_HEAVY", "BEAUTY_MEDICAL", "DENTISTRY", "HORECA", "B2B", "RETAIL", "AUTO", "EDUCATION", "SERVICES", "OTHER"]:
            if v in key:
                return v
    except Exception:
        pass
    return "OTHER"

def rewrite_errors_by_ai(niche_label, company_name, failed_rules, engine):
    if not engine or not failed_rules:
        return
    
    payload_text = "".join([f"ID: {r['Код']} | Ошибка: {r['Критерий']} | Текст: {r['Обоснование']}\n" for r in failed_rules[:15]])
    prompt = f"""Ты — эксперт по локальному маркетингу. Ниша: {niche_label}. Компания: {company_name}.
Перепиши обоснование каждой ошибки под боли этой ниши простым языком руководителя без технического жаргона (без XML, LSI, B2B, контрактов). 
Опирайся на потери клиентов и выручки.
Строго соблюдай правила Яндекса: не предлагай накрутку или скидки за отзывы, не советуй добавлять спам-слова в название (это запрещено модерацией).

Ошибки:
{payload_text}
Верни строго JSON объект: {{"Код_ошибки": "Новый текст обоснования"}}"""
    try:
        raw_resp = engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
        if match:
            new_texts = json.loads(match.group(0))
            for r in failed_rules:
                if r['Код'] in new_texts and str(new_texts[r['Код']]).strip():
                    r['Обоснование'] = new_texts[r['Код']]
    except Exception:
        pass

def calculate_hard_facts(data, niche_key="OTHER", inn_code=""):
    scores = {}
    now = datetime.now(timezone.utc)
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')
    
    raw_url = data.get('url') or data.get('website') or ''
    url = str(raw_url).lower()
    
    # PROF-03.1 & PROF-03.2 (Основная рубрика и семантическое ядро 3+ из 5)
    cat_list = data.get('categories') or []
    cat_name = ""
    if isinstance(cat_list, list) and cat_list:
        first_cat = cat_list[0]
        cat_name = first_cat.get('name', str(first_cat)) if isinstance(first_cat, dict) else str(first_cat)
        scores['PROF-03.1'] = True
        if len(cat_list) >= 3:
            scores['PROF-03.2'] = True
    
    if data.get('isVerifiedOwner') or len(title) > 2:
        scores['PROF-01.1'] = True
        
    # PROF-04.1 (Сайт компании) & PROF-04.2 (UTM-разметка)
    if url:
        scores['PROF-04.1'] = True
        if "utm_" in url:
            scores['PROF-04.2'] = True
        
    phones = data.get('phones') or []
    if phones:
        scores['PROF-05.1'] = True
        for p in phones:
            p_val = p.get('number', '') if isinstance(p, dict) else str(p)
            clean_digits = re.sub(r'[^\d+]', '', p_val)
            if clean_digits.startswith('+7') or clean_digits.startswith('8'):
                scores['PROF-05.2'] = True
                break
            
    schedule = data.get('schedule') or data.get('workingHours') or []
    if (isinstance(schedule, list) and len(schedule) >= 5) or (isinstance(schedule, dict) and len(schedule.keys()) >= 5):
        scores['PROF-07.1'] = True
    
    features = data.get('features') or {}
    if features:
        scores['PROF-08.1'] = True

    # PROF-08.3 (Доступная среда и парковка)
    if isinstance(features, dict):
        if any(k in features for k in ['wheelchair_access', 'accessible_entrance', 'parking', 'parking_disabled', 'wheelchair_accessible']):
            scores['PROF-08.3'] = True

    niche_mapping = {
        "DENTISTRY": ["dentist_services", "uni_medic_specialization"],
        "AUTO": ["car_wash_services", "auto_repair_features"],
        "HORECA": ["restaurant_services", "cuisine_type"],
        "EDUCATION": ["school_direction", "specialized_schools", "classes for children"]
    }
    if isinstance(features, dict):
        target_keys = niche_mapping.get(niche_key, [])
        for k in target_keys:
            if features.get(k):
                scores['PROF-08.2'] = True
                break
        if niche_key in ["OTHER", "SERVICES"]:
            std_keys = {'payment_method', 'wi_fi', 'toilet', 'parking', 'street_entrance', 'parking_disabled', 'promotions', 'wheelchair_access'}
            client_unique_keys = [k for k in features.keys() if k not in std_keys]
            if len(client_unique_keys) >= 2:
                send_telegram_business_alert(title, cat_name, client_unique_keys[:5])
    
    # PROF-09.1 (Длина описания > 1200) & PROF-09.2 (Структурированное описание)
    if len(desc) > 1200:
        scores['PROF-09.1'] = True
    if desc.count('\n') >= 2 or any(bullet in desc for bullet in ['-', '—', '•', '1.', '2.', '*']):
        scores['PROF-09.2'] = True

    if data.get('isVerifiedOwner'):
        scores['PROF-12.1'] = True

    # PROF-15.1 (Юридические данные и ИНН)
    if data.get('legalInfo') or data.get('companyLegalInfo') or (inn_code and len(inn_code) in (10, 12)):
        scores['PROF-15.1'] = True
    
    social_items = data.get('socialLinks') or data.get('links') or []
    owner_links = (url + " " + desc + " " + " ".join([str(l) for l in social_items])).lower()
    
    if any(s in owner_links for s in ["t.me", "wa.me", "whatsapp", "viber"]):
        scores['PROF-13.1'] = True
    if any(s in owner_links for s in ["vk.com", "vk.ru", "youtube", "dzen", "instagram"]):
        scores['PROF-13.2'] = True
    
    menu_data = data.get('menu')
    menu_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    catalog_items = data.get('productCatalog') or []
    if not isinstance(catalog_items, list):
        catalog_items = []
    
    valid_prods = [p for p in (menu_items + catalog_items) if isinstance(p, dict)]
    if valid_prods:
        total_vp = len(valid_prods)
        if total_vp >= 10:
            scores['PROF-11.1'] = True
        if sum(1 for p in valid_prods if p.get('photoUrl') or p.get('photo')) / total_vp >= 0.7:
            scores['PROF-11.2'] = True
        if sum(1 for p in valid_prods if any(c.isdigit() for c in str(p.get('price') or ''))) / total_vp >= 0.7:
            scores['PROF-11.3'] = True
        if sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 40) / total_vp >= 0.6:
            scores['PROF-11.4'] = True
        if len(set(p.get('category') for p in valid_prods if p.get('category'))) >= 2:
            scores['PROF-11.5'] = True
        
    if len(str(data.get('address') or '')) > 5:
        scores['SEO-18.1'] = True
        
    # GEO-18.4 (Точный маркер входа)
    if data.get('entrances') or data.get('entranceCoordinates') or data.get('doors'):
        scores['GEO-18.4'] = True

    if safe_int(data.get('videoCount')) > 0 or data.get('videos') or data.get('mobileVideos'):
        scores['CONT-42.1'] = True
    
    photos = data.get('photos') or []
    photo_count = safe_int(data.get('photoCount'), len(photos))
    if photo_count >= 15:
        scores['CONT-36.1'] = True
    if photo_count >= 30:
        scores['CONT-36.2'] = True
    
    tags = []
    for p in photos:
        if isinstance(p, dict):
            for tag in (p.get('tags') or []):
                if isinstance(tag, dict) and tag.get('id'):
                    tags.append(tag['id'])
            if p.get('tag') == 'interior':
                tags.append('Interior')
                
    if "Interior" in tags:
        scores['CONT-38.1'] = True
    if photo_count >= 25:
        scores['CONT-37.2'] = True
        scores['CONT-37.3'] = True
    
    posts = data.get('mobilePosts') or data.get('posts') or []
    if posts:
        scores['CONV-51.1'] = True
        for p in posts:
            pd_date = parse_yandex_date(p.get('publicationTime') or p.get('date'))
            if pd_date and (now - pd_date).days <= 30:
                scores['ACT-68.1'] = True
                break
            
    rating = safe_float(data.get('rating'))
    if rating >= 4.5:
        scores['REP-27.1'] = True
    if rating >= 4.8:
        scores['REP-27.2'] = True
        
    rev_count = safe_int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount'))
    if rev_count >= 40:
        scores['REP-28.1'] = True
    
    raw_reviews = data.get('reviews') or []
    all_reviews = [r for r in raw_reviews if isinstance(r, dict)]
    if not all_reviews:
        scores['META_NO_RECENT_REVIEWS'] = True
    else:
        top_20 = all_reviews[:20]
        first_date = parse_yandex_date(all_reviews[0].get('date'))
        if first_date and (now - first_date).days <= 14:
            scores['REP-29.1'] = True
            
        replied = 0
        has_photos = 0
        good_reply = False
        quick_reply = False
        expert_authors = 0
        reply_lengths = []
        recent_reply = False
        
        for r in top_20:
            author_lvl = safe_int(r.get('author', {}).get('level') or r.get('userLevel') or 0)
            if author_lvl >= 3:
                expert_authors += 1

            if isinstance(r.get('reply'), dict):
                bc_text = str(r.get('reply', {}).get('text') or '').strip()
                bc_date_raw = r.get('reply', {}).get('date')
            else:
                bc_text = str(r.get('businessComment') or r.get('reply') or '').strip()
                bc_date_raw = r.get('businessCommentDate')
                
            if bc_text:
                replied += 1
                reply_lengths.append(len(bc_text))
                
            if r.get('photos') or r.get('photoDetails'):
                has_photos += 1
            if safe_float(r.get('rating')) >= 4.0 and bc_text:
                good_reply = True
            
            bc_date = parse_yandex_date(bc_date_raw)
            rev_date = parse_yandex_date(r.get('date'))
            if bc_text and bc_date and rev_date and 0 <= (bc_date - rev_date).days <= 3:
                quick_reply = True
                
            if bc_text:
                if bc_date and (now - bc_date).days <= 30:
                    recent_reply = True
                elif not bc_date and rev_date and (now - rev_date).days <= 30:
                    recent_reply = True
        
        if top_20:
            if replied / len(top_20) >= 0.7:
                scores['REP-30.1'] = True
            if has_photos / len(top_20) >= 0.05:
                scores['REP-35.1'] = True
            if expert_authors / len(top_20) >= 0.25:
                scores['REP-34.1'] = True
                
        if good_reply:
            scores['REP-30.3'] = True
        if quick_reply:
            scores['REP-30.2'] = True
        if reply_lengths and (sum(reply_lengths) / len(reply_lengths)) >= 80:
            scores['REP-30.4'] = True
        if recent_reply:
            scores['REP-85.1'] = True
            
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    if not expert_engine or not prompts_data:
        return {}
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')[:1000]
    recent_reviews = [r for r in (data.get('reviews') or []) if isinstance(r, dict)][:10]
    
    reviews_lines = []
    for r in recent_reviews:
        r_text = r.get('text', '')
        rep_text = r.get('reply', {}).get('text', '') if isinstance(r.get('reply'), dict) else (r.get('businessComment') or r.get('reply') or '')
        reviews_lines.append(f"Отзыв: {r_text}\nОтвет: {rep_text}\n")
    
    menu_data = data.get('menu')
    m_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    c_items = data.get('productCatalog') or []
    if not isinstance(c_items, list):
        c_items = []
    prods = [p for p in m_items + c_items if isinstance(p, dict)][:20]
    prods_text = ", ".join([str(p.get('name') or p.get('title')) for p in prods])
    
    rules_list = [f'"{p.get("Код")}": {p.get("Промпт для ИИ")}' for p in prompts_data if p.get("Код") and p.get("Код") != 'NICHE_PROMPT']
    if not rules_list:
        return {}
        
    prompt = f"Контекст:\nНазвание: {title}\nОписание: {desc}\nТовары: {prods_text}\nОтзывы:\n{''.join(reviews_lines)[:1500]}\nКритерии:\n{chr(10).join(rules_list)}\nВерни строго JSON объект {{CODE: true/false}}."
    try:
        raw_resp = expert_engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
        if match:
            return {k: True for k, v in json.loads(match.group(0)).items() if str(v).lower() in ["1", "true"]}
    except Exception:
        pass
    return {}

# ==========================================
# 7. ГЕНЕРАЦИЯ PDF (ШАБЛОН TYPST, 4 СТР.)
# ==========================================
def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, client_ltv, competitors_text=""):
    current_date = datetime.now().strftime("%d.%m.%Y")
    score_color = "166534" if score >= 80 else ("8B7355" if score >= 50 else "9F1239")
    dev = round(100 - score, 1)
    lost_leads = int(client_leads * (dev / 100))
    
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    weekly_loss = int(revenue_loss / 4)
    weekly_loss_fmt = f"{weekly_loss:,}".replace(',', ' ')
    client_check_fmt = f"{client_check:,}".replace(',', ' ')
    ltv_loss = int(revenue_loss * max(1, client_ltv))
    ltv_loss_fmt = f"{ltv_loss:,}".replace(',', ' ')
    
    title_safe = clean_typography(title)
    niche_safe = clean_typography(niche)
    comp_safe = clean_typography(competitors_text)
    
    niche_str = str(niche).lower()
    if "стом" in niche_str or "зуб" in niche_str:
        quality_phrase = "стоматологических услуг, квалификации врачей и стандартов лечения"
        target_forms = ("пациент", "пациента", "пациентов")
        service_example = "имплантацию, лечение кариеса, коронки или брекеты"
    elif "мед" in niche_str or "клиник" in niche_str or "бьют" in niche_str or "салон" in niche_str:
        quality_phrase = "медицинских услуг, опыта специалистов и уровня заботы о клиентах"
        target_forms = ("пациент", "пациента", "пациентов")
        service_example = "прием врачей, комплексные чекапы или косметологические процедуры"
    elif "horeca" in niche_str or "ресторан" in niche_str or "кафе" in niche_str or "бар" in niche_str:
        quality_phrase = "кухни, сервиса и гостеприимной атмосферы заведения"
        target_forms = ("гость", "гостя", "гостей")
        service_example = "банкеты, меню кухни, бизнес-ланчи или бронь столов"
    elif "авто" in niche_str or "мойка" in niche_str or "сервис" in niche_str:
        quality_phrase = "ремонта, запчастей и квалификации автомехаников"
        target_forms = ("автовладелец", "автовладельца", "автовладельцев")
        service_example = "диагностику, ремонт ходовой, сход-развал или ТО"
    elif "образ" in niche_str or "школ" in niche_str or "курс" in niche_str:
        quality_phrase = "учебной программы и преподавательского состава"
        target_forms = ("ученик", "ученика", "учеников")
        service_example = "подготовку к экзаменам, профильные курсы или интенсивы"
    elif "b2b_heavy" in niche_str or "производ" in niche_str or "завод" in niche_str:
        quality_phrase = "производственных мощностей, стандартов ГОСТ и надежности поставок"
        target_forms = ("заказчик", "заказчика", "заказчиков")
        service_example = "серийное производство, изготовление партий или поставку под проект"
    elif "b2b" in niche_str or "опт" in niche_str:
        quality_phrase = "надежности поставок, ассортимента склада и условий отгрузки"
        target_forms = ("партнер", "партнера", "партнеров")
        service_example = "оптовые закупки, регулярные поставки или спецзаказы"
    elif "ритейл" in niche_str or "retail" in niche_str or "магазин" in niche_str:
        quality_phrase = "качества товаров, широты ассортимента и обслуживания"
        target_forms = ("покупатель", "покупателя", "покупателей")
        service_example = "наличие нужного ассортимента, цены и условия доставки"
    else:
        quality_phrase = "товаров, услуг и стандартов клиентского сервиса"
        target_forms = ("клиент", "клиента", "клиентов")
        service_example = "ключевой перечень услуг и условия сотрудничества"

    audience_declension = plural_ru(lost_leads, target_forms)

    template_path = os.path.join(os.path.dirname(__file__), "report_template.typ")
    if not os.path.exists(template_path):
        st.error("Файл report_template.typ не найден рядом с app.py!")
        return b""

    with open(template_path, "r", encoding="utf-8") as f:
        typ_source = f.read()

    replacements = {
        "[[TITLE]]": title_safe,
        "[[NICHE]]": niche_safe,
        "[[DATE]]": current_date,
        "[[SCORE]]": str(round(score, 1)),
        "[[SCORE_COLOR]]": score_color,
        "[[REV_LOSS_FMT]]": rev_loss_fmt,
        "[[WEEKLY_LOSS_FMT]]": weekly_loss_fmt,
        "[[DEV]]": str(dev),
        "[[LOST_LEADS]]": str(lost_leads),
        "[[AUDIENCE_DECLENSION]]": audience_declension,
        "[[CLIENT_LEADS]]": str(client_leads),
        "[[CLIENT_CHECK_FMT]]": client_check_fmt,
        "[[CLIENT_LTV]]": str(client_ltv),
        "[[LTV_LOSS_FMT]]": ltv_loss_fmt,
        "[[QUALITY_PHRASE]]": quality_phrase,
        "[[SERVICE_EXAMPLE]]": service_example,
        "[[COMP_SAFE]]": comp_safe
    }

    for marker, val in replacements.items():
        typ_source = typ_source.replace(marker, val)

    with tempfile.NamedTemporaryFile(suffix=".typ", delete=False, mode="w", encoding="utf-8") as tf:
        tf.write(typ_source)
        typ_path = tf.name
        
    try:
        pdf_bytes = typst.compile(typ_path)
    except Exception as e:
        st.error(f"Ошибка компиляции Typst: {e}")
        with st.expander("🔍 Диагностика Typst: исходный скомпилированный код"):
            st.code(typ_source, language="typst", line_numbers=True)
        pdf_bytes = b""
    finally:
        if os.path.exists(typ_path):
            os.remove(typ_path)
        
    return pdf_bytes

# ==========================================
# 8. ПОЛЬЗОВАТЕЛЬСКИЙ ИНТЕРФЕЙС
# ==========================================
rules_data, prompts_data, templates_data = fetch_cached_database()

with st.sidebar:
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База данных подключена.")
    st.divider()
    sender_name = st.text_input("Ваше имя (для подписи аутрича):", value="Павел")
    audit_stage = st.selectbox("Тип замера:", ["0. Базовый (Аудит)", "1. Контроль (Этап 1)", "2. Финал (Этап 2)", "3. Мониторинг"])

st.title(f"📍 {PROJECT_NAME}: {EXPERT_TITLE}")

tab_link, tab_file = st.tabs(["🌐 По ссылке (Яндекс Карты)", "📁 Из JSON файла"])

with tab_link:
    url_input = st.text_input("Вставьте ссылку на карточку организации", placeholder="https://yandex.ru/maps/...")
    if st.button("🚀 Сгенерировать Отчет по ссылке", type="primary"):
        if "yandex" not in url_input.lower():
            st.error("❌ Введите корректную ссылку на Яндекс Карты.")
        else:
            with st.spinner("Извлечение OID и сбор свежих данных..."):
                try:
                    detected_oid, clean_yandex_url = extract_oid_and_url(url_input)
                    st.session_state["data_to_process"] = fetch_apify_data(clean_yandex_url)
                    st.session_state["source_url"] = clean_yandex_url
                    st.session_state["current_oid"] = detected_oid
                except Exception as e:
                    send_telegram_alert(str(e), url_input)
                    st.error(f"⚠️ Ошибка парсинга: {str(e)}")

with tab_file:
    uploaded_file = st.file_uploader("Загрузите предварительно сохраненный JSON", type=["json"])
    if uploaded_file and st.button("🚀 Сформировать Отчет из файла"):
        try:
            parsed_data = json.load(uploaded_file)
            st.session_state["data_to_process"] = parsed_data
            raw_u = parsed_data.get('url') or "Файл JSON"
            detected_oid, clean_yandex_url = extract_oid_and_url(raw_u)
            st.session_state["source_url"] = clean_yandex_url
            st.session_state["current_oid"] = detected_oid
        except Exception as e:
            st.error(f"Ошибка чтения JSON: {e}")

data_to_process = st.session_state.get("data_to_process")
source_url = st.session_state.get("source_url", "")
current_oid = st.session_state.get("current_oid", "UNKNOWN")

# ==========================================
# 9. ОСНОВНОЙ ПАЙПЛАЙН РАСЧЕТА И ВЫВОДА
# ==========================================
if data_to_process:
    data = data_to_process
    title = data.get('title', 'Без названия')
    c_list = data.get('categories', [])
    cat = c_list[0].get('name', '') if (isinstance(c_list, list) and c_list and isinstance(c_list[0], dict)) else (str(c_list[0]) if (isinstance(c_list, list) and c_list) else '')
    client_reviews = safe_int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []))
    
    # Резервный поиск OID внутри данных Apify
    if current_oid == "UNKNOWN":
        for cand in [data.get('id'), data.get('yandexId'), data.get('permalink'), data.get('url'), data.get('uri')]:
            if cand:
                m_cand = re.search(r'\b(\d{7,13})\b', str(cand))
                if m_cand:
                    current_oid = m_cand.group(1)
                    st.session_state["current_oid"] = current_oid
                    break

    safe_title = re.sub(r'[^\w\-]', '_', title).strip('_')
    if not safe_title:
        safe_title = "Company"

    # 1. Извлечение ИНН
    inn_code = extract_inn(data, DADATA_API_KEY)
    
    # 2. Каскадный поиск ЛПР (Отзывы -> VK -> DaData)
    social_links = data.get('socialLinks') or data.get('links') or []
    if not isinstance(social_links, list):
        social_links = []
        
    lpr_data = extract_lpr_from_reviews(data.get('reviews') or [], expert_engine)
    if not lpr_data or lpr_data.get("status") != "found":
        lpr_data = enrich_lpr_contacts_from_vk(social_links)
    if not lpr_data or lpr_data.get("status") != "found":
        search_target = inn_code if inn_code else (data.get("legalName") or data.get("companyName") or title)
        lpr_data = enrich_lpr_by_dadata(search_target, DADATA_API_KEY)
    
    # 3. Конкуренты
    raw_related = data.get('relatedPlaces') or []
    if isinstance(raw_related, dict):
        raw_related = raw_related.get('items') or raw_related.get('places') or [raw_related]
    competitors_list = [str(c.get('name')).strip() for c in raw_related if isinstance(c, dict) and c.get('name')][:2] if isinstance(raw_related, list) else []
    competitors_text = f" (например, {', '.join(competitors_list)})" if competitors_list else ""
    
    with st.spinner("Расчет юнит-экономики и запуск алгоритмов..."):
        niche_key = determine_niche_by_expert(title, cat, prompts_data)
        
        # Передаем inn_code для расчета PROF-15.1
        raw_scores = calculate_hard_facts(data, niche_key, inn_code=inn_code)
        exp_sc = calculate_dynamic_expert_rules(data, prompts_data)
        raw_scores.update(exp_sc)
        
        results = []
        final_total_score = 0.0
        target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
        
        for r in rules_data:
            code = str(r.get('Код', '')).strip()
            if not code:
                continue
            name = str(r.get('Критерий', '')).strip()
            group = str(r.get('Группа метрик', 'Прочее')).strip()
            
            reason_success = str(r.get('Обоснование_УСПЕХА', '')).strip() or f"Параметр «{name}» настроен верно."
            niche_error_col = f"Обоснование_ОШИБКИ_{niche_key}"
            reason_error = str(r.get(niche_error_col, '')).strip()
            if not reason_error or reason_error.lower() == 'nan':
                reason_error = str(r.get('Обоснование_ОШИБКИ', '')).strip()
            if not reason_error or reason_error.lower() == 'nan':
                reason_error = f"Отсутствие параметра «{name}» снижает видимость карточки в локальном поиске."

            stage_val = safe_int(r.get('Этап_Внедрения'), 3)
            max_s = safe_float(r.get(target_column, r.get('Балл', 0.0)))
            
            if max_s > 0.0:
                val = max_s if raw_scores.get(code) else 0.0
                final_total_score += val
                
                results.append({
                    "Код": code,
                    "Критерий": name,
                    "Результат": "ДА" if val > 0 else "НЕТ",
                    "Обоснование": reason_success if val > 0 else reason_error,
                    "Группа": group,
                    "Этап": stage_val,
                    "Earned": val,
                    "Max": max_s
                })

        eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
        niche_label = eco.get("label", "Прочее")

        failed_items = [r for r in results if r['Результат'] == 'НЕТ' and r['Max'] > 0]
        if failed_items and expert_engine:
            with st.spinner("ИИ адаптирует выводы под специфику ниши..."):
                rewrite_errors_by_ai(niche_label, title, failed_items, expert_engine)

        smart_check_val, check_source = determine_smart_check(data, niche_key)

        with st.sidebar:
            st.divider()
            st.markdown(f"### 🧮 Экономика: {niche_key}")
            st.caption(f"Источник чека: *{check_source}*")
            client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
            client_check = st.number_input("Средний чек (₽)", value=smart_check_val, step=500)
            client_ltv = st.number_input("Цикл LTV (месяцев)", value=eco["ltv_months"], step=1)

        lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
        lost_revenue = int(client_leads * lost_percentage * client_check)

        history_info = check_oid_history(current_oid)

        st.divider()
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"🏢 {title}")
            inn_badge = f" | 🏛 ИНН: **{inn_code}**" if inn_code else ""
            st.caption(f"🔑 Яндекс OID: **{current_oid}**{inn_badge} | 🧠 Сегмент: **{niche_label}**")
            
            if history_info["exists"]:
                st.info(f"🔄 **Карточка уже в базе ({history_info['source']}).** Базовый балл: {history_info['base_score']} | Замеров: {history_info['count']}")
            else:
                st.success("✨ **Новая организация.** Будет зафиксирована в CRM Results.")
                
            if lpr_data and lpr_data.get('status') == 'found':
                contact_info = f" ({lpr_data.get('link')})" if lpr_data.get('link') else ""
                st.success(f"🕵️‍♂️ **Найден ЛПР:** {lpr_data.get('name')} — {lpr_data.get('role')}{contact_info}")
            elif lpr_data and lpr_data.get('status') == 'hidden':
                st.warning("⚠️ **Группа ВК найдена, но блок «Контакты» скрыт.**")
            
        with col2:
            delta = "Отличный результат" if final_total_score >= 80 else ("Требует оптимизации" if final_total_score >= 50 else "Критический уровень")
            st.metric(f"Индекс {PROJECT_NAME}", f"{round(final_total_score, 1)} / 100", delta=delta, delta_color="normal" if final_total_score >= 80 else "inverse")

        st.error(f"Потери: **{lost_revenue:,} ₽** ежемесячно.".replace(',', ' '))
        
        pdf_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, client_ltv, competitors_text)
        
        if pdf_bytes:
            st.download_button(
                label="💎 Скачать Аналитический Отчет (PDF, 4 стр.)",
                data=pdf_bytes,
                file_name=f"{safe_title}_Аудит_PIN100.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

            st.divider()
            st.markdown("### ✉️ Персональное письмо первого касания (Icebreaker)")
            
            comp_1 = competitors_list[0] if len(competitors_list) > 0 else ""
            comp_2 = competitors_list[1] if len(competitors_list) > 1 else ""
            leads_min = max(5, int(client_leads * lost_percentage * 0.8))
            leads_max = max(10, int(client_leads * lost_percentage))

            template_payload = {
                "niche_key": niche_key,
                "lpr_name": lpr_data.get("name") if (lpr_data and lpr_data.get("name")) else "",
                "title": title,
                "rating": round(safe_float(data.get("rating"), 4.5), 1),
                "comp_1": comp_1,
                "comp_2": comp_2,
                "lost_leads": f"{leads_min}–{leads_max}",
                "lost_revenue": lost_revenue,
                "sender_name": sender_name
            }
            
            icebreaker_text = generate_icebreaker_text(template_payload, templates_data)
            st.code(icebreaker_text, language="markdown")
            
            date_str = datetime.now().strftime("%Y-%m-%d")
            file_prefix = f"{safe_title}_{current_oid}" if current_oid != "UNKNOWN" else safe_title

            session_save_key = f"saved_{file_prefix}_{round(final_total_score, 1)}"
            if session_save_key not in st.session_state:
                st.session_state[session_save_key] = False

            if not st.session_state[session_save_key]:
                with st.spinner("☁️ Сохранение артефактов на Google Диск и фиксация в БД..."):
                    try:
                        if not DriveManager:
                            st.warning("Файл drive_manager.py не обнаружен. Сохранение на Диск пропущено.")
                        else:
                            dm = DriveManager()
                            
                            pdf_url = dm.upload_file(f"{file_prefix}_{date_str}_audit.pdf", pdf_bytes, "application/pdf", dm.pdf_root_id)
                            json_url = dm.upload_file(f"{file_prefix}_{date_str}_audit.json", json.dumps(data, ensure_ascii=False, indent=2), "application/json", dm.json_root_id)
                            txt_url = dm.upload_file(f"{file_prefix}_{date_str}_icebreaker.txt", icebreaker_text, "text/plain", dm.letters_root_id)
                            
                            if not history_info["exists"]:
                                save_lead_to_results(
                                    current_oid, source_url, title, niche_key, 
                                    final_total_score, lost_revenue, lpr_data, inn=inn_code
                                )
                            else:
                                b_sc = history_info["base_score"] or final_total_score
                                l_sc = history_info["last_score"] or final_total_score
                                d_start = final_total_score - b_sc
                                d_last = final_total_score - l_sc
                                save_progress_measurement(
                                    current_oid, title, audit_stage, final_total_score, 
                                    d_start, d_last, lost_revenue, pdf_url, json_url, source_url
                                )

                            st.session_state[f"links_{session_save_key}"] = [
                                f"🔗 [PDF на Диске]({pdf_url})" if pdf_url else "",
                                f"🔗 [Письмо на Диске]({txt_url})" if txt_url else "",
                                f"🔗 [Снапшот JSON]({json_url})" if json_url else ""
                            ]
                            st.session_state[session_save_key] = True
                    except Exception as e:
                        st.error(f"Ошибка сохранения: {e}")

            if st.session_state.get(session_save_key):
                st.success("✅ Замер синхронизирован с Google Диском и Google Таблицей!")
                active_links = [l for l in st.session_state.get(f"links_{session_save_key}", []) if l]
                if active_links:
                    st.markdown(" | ".join(active_links))
