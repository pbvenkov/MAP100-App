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
        if data.get("score", 0) >= 75:
            return (
                f"Добрый день!\n\n"
                f"Меня зовут {data.get('sender_name', 'Павел')}. Анализирую поисковую гео-выдачу Яндекса в вашем районе.\n\n"
                f"У «{data.get('title', 'организации')}» сформирована сильная репутация (оценка {data.get('rating', '5.0')}), "
                f"однако в карточке есть несколько скрытых технических точек роста, из-за которых часть первичных обращений "
                f"перехватывают ближайшие соседи ({data.get('comp_1', 'конкуренты')}).\n\n"
                f"По трафику локации клиника недополучает порядка {data.get('lost_leads', '2–4')} первичных пациентов в месяц "
                f"(около {data.get('lost_revenue', 0):,} ₽ выручки).\n\n"
                f"Свели детальный аудит в короткий 4-страничный отчет. Отправить PDF руководителю?"
            ).replace(',', ' ')
        return (
            f"Добрый день!\n\n"
            f"Меня зовут {data.get('sender_name', 'Павел')}. Анализирую поисковую выдачу стоматологий на Яндекс Картах вашего района.\n\n"
            f"У «{data.get('title', 'организации')}» отличная репутация, но по общим целевым запросам карточка уступает ТОП-позиции конкурентам.\n\n"
            f"Клиника ежемесячно упускает около {data.get('lost_leads', '3–5')} первичных обращений "
            f"(порядка {data.get('lost_revenue', 0):,} ₽ недополученной выручки первого визита).\n\n"
            f"Подготовили 4-страничный аналитический разбор с точками роста. Куда удобнее прислать PDF?"
        ).replace(',', ' ')

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

# Реестр правил: 50 активных критериев (включая Hard Facts 2.0)
PROGRAMMED_CODES = {
    'PROF-01.1', 'PROF-03.1', 'PROF-03.2', 'PROF-04.1', 'PROF-04.2',
    'PROF-05.1', 'PROF-05.2', 'PROF-07.1', 'PROF-08.1', 'PROF-08.2',
    'PROF-08.3', 'PROF-09.1', 'PROF-09.2', 'PROF-11.1', 'PROF-11.2',
    'PROF-11.3', 'PROF-11.4', 'PROF-11.5', 'PROF-12.1', 'PROF-13.1',
    'PROF-13.2', 'PROF-14.1', 'PROF-15.1', 'SEO-18.1',  'SEO-18.2',
    'SEO-18.3',  'GEO-18.4',  'REP-27.1',  'REP-27.2',  'REP-28.1',
    'REP-29.1',  'REP-30.1',  'REP-30.2',  'REP-30.3',  'REP-30.4',
    'REP-34.1',  'REP-35.1',  'CONT-36.1', 'CONT-36.2', 'CONT-37.2',
    'CONT-37.3', 'CONT-38.1', 'CONT-42.1', 'CONV-46.1', 'CONV-48.1',
    'CONV-50.1', 'CONV-51.1', 'CONV-52.1', 'CONV-53.1', 'ACT-68.1',
    'REP-85.1'
}

def plural_ru_gen(n, forms_gen):
    """Склонение в родительном падеже после предлогов 'около', 'порядка' ('пациента', 'пациентов')"""
    n = abs(int(n)) % 100
    n1 = n % 10
    if 10 < n < 20:
        return forms_gen[1]
    if n1 == 1:
        return forms_gen[0]
    return forms_gen[1]

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

# ==========================================
# 3. КАСКАДНАЯ РАЗВЕДКА: DADATA, САЙТ И ЛПР
# ==========================================
def extract_inn_from_text(text):
    if not text:
        return ""
    matches = re.findall(r'(?:ИНН\D{0,5})?(\b\d{10}\b|\b\d{12}\b)', text, re.IGNORECASE)
    for m in matches:
        if len(m) in (10, 12):
            return m
    return ""

def scrape_inn_from_website(website_url):
    if not website_url or not str(website_url).startswith("http"):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(website_url, headers=headers, timeout=5)
        if res.status_code == 200:
            inn = extract_inn_from_text(res.text)
            if inn:
                return inn
    except Exception:
        pass
    return ""

def query_dadata_party(query_val, dadata_token):
    if not dadata_token or not query_val:
        return None
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Token {dadata_token}"
    }
    try:
        res = requests.post(url, json={"query": str(query_val).strip(), "count": 1}, headers=headers, timeout=5).json()
        suggestions = res.get("suggestions", [])
        if suggestions:
            return suggestions[0].get("data", {})
    except Exception:
        pass
    return None

def fetch_extended_dadata_info(data, dadata_token):
    inn_code = ""
    legal_info = data.get('legalInfo') or data.get('companyLegalInfo') or {}
    if isinstance(legal_info, dict) and legal_info.get('inn'):
        clean = re.sub(r'[^\d]', '', str(legal_info.get('inn')))
        if len(clean) in (10, 12):
            inn_code = clean

    if not inn_code:
        corpus = " ".join([str(data.get('description') or ''), str(data.get('legalName') or ''), str(data.get('companyName') or '')])
        inn_code = extract_inn_from_text(corpus)

    website_url = data.get('url') or data.get('website')
    if not inn_code and website_url:
        inn_code = scrape_inn_from_website(website_url)

    party_data = None
    if inn_code:
        party_data = query_dadata_party(inn_code, dadata_token)
    
    if not party_data:
        search_target = data.get("legalName") or data.get("companyName") or data.get("title")
        if search_target and len(search_target) > 3:
            party_data = query_dadata_party(search_target, dadata_token)
            if party_data and party_data.get("inn"):
                inn_code = party_data.get("inn")

    dossier = {
        "inn": inn_code if inn_code else "Поиск вручную",
        "legal_name": "Не определено",
        "lpr_name": "",
        "lpr_role": "Руководство",
        "business_age_str": "—",
        "revenue_str": "—",
        "employees_str": "—",
        "okved_str": "—",
        "legal_status": "—",
        "found": False
    }

    if party_data:
        dossier["found"] = True
        dossier["inn"] = party_data.get("inn", inn_code or "Поиск вручную")
        dossier["legal_name"] = party_data.get("name", {}).get("full_with_opf") or party_data.get("name", {}).get("short_with_opf") or "Юрлицо найдено"
        
        management = party_data.get("management") or {}
        if management.get("name"):
            dossier["lpr_name"] = management.get("name")
            dossier["lpr_role"] = management.get("post", "Генеральный директор")
        elif party_data.get("type") == "INDIVIDUAL":
            fio = party_data.get("name", {}).get("full", "").replace("ИП", "").strip()
            dossier["lpr_name"] = fio
            dossier["lpr_role"] = "Индивидуальный предприниматель"

        reg_date_raw = party_data.get("state", {}).get("registration_date")
        if reg_date_raw:
            reg_year = datetime.fromtimestamp(reg_date_raw / 1000, tz=timezone.utc).year
            age = max(0, datetime.now().year - reg_year)
            dossier["business_age_str"] = f"{age} лет (с {reg_year} г.)" if age > 0 else f"Менее 1 года (с {reg_year} г.)"

        finance = party_data.get("finance") or {}
        rev = finance.get("revenue")
        if rev and safe_int(rev) > 0:
            rev_val = safe_int(rev)
            if rev_val >= 1_000_000:
                dossier["revenue_str"] = f"{round(rev_val / 1_000_000, 1)} млн ₽/год"
            else:
                dossier["revenue_str"] = f"{rev_val:,} ₽/год".replace(',', ' ')

        emp = party_data.get("employee_count")
        if emp:
            dossier["employees_str"] = f"{emp} чел."

        okv = party_data.get("okved", "")
        okv_name = party_data.get("okved_data", {}).get("name", "") if party_data.get("okved_data") else ""
        if okv:
            dossier["okved_str"] = f"{okv} {okv_name}".strip()

        st_val = party_data.get("state", {}).get("status", "ACTIVE")
        status_map = {
            "ACTIVE": "Действующее",
            "LIQUIDATING": "В процессе ликвидации",
            "LIQUIDATED": "Ликвидировано",
            "BANKRUPT": "Банкротство"
        }
        dossier["legal_status"] = status_map.get(st_val, st_val)

    return dossier

def extract_direct_messengers(data):
    links = data.get('socialLinks') or data.get('links') or []
    candidate_links = []
    if isinstance(links, list):
        for item in links:
            u = item.get('url', '') if isinstance(item, dict) else str(item)
            if u:
                candidate_links.append(u)
                
    phones = data.get('phones') or []
    phone_numbers = []
    for p in phones:
        val = p.get('number', '') if isinstance(p, dict) else str(p)
        clean_num = re.sub(r'[^\d+]', '', val)
        if clean_num:
            phone_numbers.append(clean_num)
            
    contact_info = {}
    for link in candidate_links:
        low = link.lower()
        if "t.me/" in low and not any(k in low for k in ["bot", "joinchat", "share"]):
            contact_info["tg_link"] = link
        if "wa.me/" in low or "whatsapp.com" in low:
            contact_info["wa_link"] = link

    return contact_info, phone_numbers

def extract_lpr_from_reviews(reviews_data, engine=None):
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
Если подписи нет или она обезличена, верни: {{"status": "not_found"}}"""

    try:
        raw_res = engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_res, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if data.get("status") == "found" and data.get("name"):
                return data
    except Exception:
        pass
    return {}

def enrich_lpr_contacts_from_vk(social_links):
    if not VK_API_TOKEN or not social_links:
        return {}
    vk_url = next((link.get('url', '') for link in social_links if isinstance(link, dict) and ('vk.com' in link.get('url', '') or 'vk.ru' in link.get('url', ''))), None)
    if not vk_url:
        return {}
    try:
        clean_vk = vk_url.split('?')[0].rstrip('/')
        group_id = clean_vk.split('/')[-1]
        res = requests.get(
            "https://api.vk.com/method/groups.getById", 
            params={"group_id": group_id, "fields": "contacts", "access_token": VK_API_TOKEN, "v": "5.199"}, 
            timeout=5
        ).json()
        
        if 'response' in res and res['response']:
            contacts = res['response'][0].get('contacts', [])
            if not contacts:
                return {"status": "hidden", "channel": "VK", "link": vk_url, "source": "Группа VK"}
                
            contact = contacts[0]
            lpr_data = {
                "name": "",
                "role": contact.get('desc', 'Руководитель'),
                "link": "",
                "phone": contact.get('phone', ''),
                "email": contact.get('email', ''),
                "channel": "VK",
                "source": "VK (контакты группы)",
                "status": "found"
            }
            if 'user_id' in contact:
                uid = contact['user_id']
                lpr_data["link"] = f"https://vk.com/id{uid}"
                u_res = requests.get(
                    "https://api.vk.com/method/users.get", 
                    params={"user_ids": uid, "fields": "contacts,site,connections", "access_token": VK_API_TOKEN, "v": "5.199"}, 
                    timeout=5
                ).json()
                if 'response' in u_res and u_res['response']:
                    u = u_res['response'][0]
                    lpr_data["name"] = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                    if u.get('mobile_phone'):
                        lpr_data["phone"] = u.get('mobile_phone')
                    site_val = str(u.get('site', '')).lower()
                    if "t.me/" in site_val:
                        lpr_data["link"] = u.get('site')
                        lpr_data["channel"] = "Telegram"
            return lpr_data
    except Exception:
        pass
    return {}

def resolve_lpr_and_dossier(data, expert_engine, dadata_token):
    social_links = data.get('socialLinks') or data.get('links') or []
    if not isinstance(social_links, list):
        social_links = []
        
    direct_messengers, phones = extract_direct_messengers(data)
    dossier = fetch_extended_dadata_info(data, dadata_token)

    lpr = extract_lpr_from_reviews(data.get('reviews') or [], expert_engine)
    if lpr and lpr.get("status") == "found":
        lpr["source"] = "Ответы на отзывы Яндекса"
        lpr["channel"] = "Яндекс Отзывы"

    if not lpr or lpr.get("status") != "found":
        lpr = enrich_lpr_contacts_from_vk(social_links)

    if (not lpr or lpr.get("status") != "found") and dossier["lpr_name"]:
        lpr = {
            "name": dossier["lpr_name"],
            "role": dossier["lpr_role"],
            "channel": "DaData / Реестр",
            "source": "ЕГРЮЛ / ЕГРИП",
            "status": "found"
        }

    if not lpr:
        lpr = {"name": "", "role": "Руководство", "status": "not_found", "source": "Не определен"}

    if direct_messengers.get("tg_link"):
        lpr["direct_tg"] = direct_messengers["tg_link"]
        if not lpr.get("link"):
            lpr["link"] = direct_messengers["tg_link"]
            lpr["channel"] = "Telegram"
            
    if direct_messengers.get("wa_link"):
        lpr["direct_wa"] = direct_messengers["wa_link"]
        if not lpr.get("link"):
            lpr["link"] = direct_messengers["wa_link"]
            lpr["channel"] = "WhatsApp"

    emails = data.get('emails') or []
    direct_email = ""
    if emails and isinstance(emails, list):
        first_e = emails[0]
        direct_email = first_e.get('address', str(first_e)) if isinstance(first_e, dict) else str(first_e)

    clinic_phone = phones[0] if phones else ""
    return lpr, dossier, direct_email, clinic_phone

# ==========================================
# 4. БАЗА ДАННЫХ, CRM И УМНАЯ ЭКОНОМИКА
# ==========================================
NICHE_ECONOMICS = {
    "DENTISTRY": {"leads": 70, "check": 4500, "label": "Стоматология", "ltv_months": 12},
    "HORECA": {"leads": 150, "check": 1500, "label": "HORECA / Рестораны", "ltv_months": 12},
    "B2B": {"leads": 40, "check": 25000, "label": "Легкий B2B / Опт", "ltv_months": 12},
    "B2B_HEAVY": {"leads": 10, "check": 300000, "label": "Сложный B2B / Производство", "ltv_months": 1},
    "RETAIL": {"leads": 200, "check": 1200, "label": "Ритейл", "ltv_months": 12},
    "AUTO": {"leads": 100, "check": 4500, "label": "Автосервис / Автосалон", "ltv_months": 6},
    "SERVICES": {"leads": 60, "check": 3500, "label": "Услуги B2C", "ltv_months": 6},
    "BEAUTY_MEDICAL": {"leads": 80, "check": 3500, "label": "Медицина / Бьюти", "ltv_months": 12},
    "EDUCATION": {"leads": 30, "check": 18000, "label": "Образование", "ltv_months": 12},
    "OTHER": {"leads": 50, "check": 3000, "label": "Прочее", "ltv_months": 6}
}

NICHE_MIN_FLOOR = {
    "DENTISTRY": 3500,
    "AUTO": 2500,
    "BEAUTY_MEDICAL": 2500,
    "EDUCATION": 6000,
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
        "multiplier": 1.25
    },
    "TIER_2": {
        "cities": [
            "новосибирск", "екатеринбург", "казань", "нижний новгород", "челябинск",
            "красноярск", "самара", "уфа", "ростов-на-дону", "омск", "краснодар",
            "воронеж", "пермь", "волгоград", "тюмень", "владивосток"
        ],
        "multiplier": 1.10
    }
}

def determine_smart_check(data: dict, niche_key: str) -> tuple[int, str]:
    address = str(data.get("address") or "").lower()
    geo_mult = 1.0
    if any(city in address for city in GEO_TIERS["TIER_1"]["cities"]):
        geo_mult = GEO_TIERS["TIER_1"]["multiplier"]
    elif any(city in address for city in GEO_TIERS["TIER_2"]["cities"]):
        geo_mult = GEO_TIERS["TIER_2"]["multiplier"]

    base_floor = NICHE_MIN_FLOOR.get(niche_key, 1500)
    floor_val = int(round(base_floor * geo_mult / 100) * 100)

    menu_data = data.get('menu')
    m_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    c_items = data.get('productCatalog') or []
    if not isinstance(c_items, list):
        c_items = []
    goods_items = data.get('goods') or []
    if not isinstance(goods_items, list):
        goods_items = []

    all_items = [p for p in (m_items + c_items + goods_items) if isinstance(p, dict)]

    consultation_prices = []
    for item in all_items:
        name = str(item.get("name") or item.get("title") or "").lower()
        if any(w in name for w in ["консультац", "осмотр", "первичн", "диагностик", "прием"]):
            clean_p = re.sub(r'[^\d]', '', str(item.get("price") or item.get("cost") or ""))
            if clean_p and 500 <= int(clean_p) <= 15000:
                consultation_prices.append(int(clean_p))

    if consultation_prices:
        consultation_prices.sort()
        target_p = consultation_prices[len(consultation_prices) // 2]
        return max(target_p, floor_val), "Стоимость первичного приема из прейскуранта"

    raw_bill = data.get("averageBill") or data.get("priceCategory") or ""
    bill_digits = re.findall(r'\d+', str(raw_bill).replace(' ', ''))
    if bill_digits:
        nums = [int(n) for n in bill_digits if int(n) >= 300]
        if nums:
            avg_bill = int(sum(nums) / len(nums))
            return max(avg_bill, floor_val), "Средний счёт из профиля Яндекса"

    eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
    calc_val = int(round(eco["check"] * geo_mult / 500) * 500)
    return max(calc_val, floor_val), "Консервативный порог первого визита"

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

def save_lead_to_results(oid, url, title, niche, total_score, lost_revenue, lpr_data, dossier, direct_email, clinic_phone):
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Results")
        
        lpr_name = lpr_data.get("name", "") if lpr_data else ""
        lpr_role = lpr_data.get("role", "") if lpr_data else ""
        
        direct_channel = lpr_data.get("channel", "") if lpr_data else ""
        direct_coord = lpr_data.get("link", "") or lpr_data.get("phone", "") if lpr_data else ""
        contact_display = f"[{direct_channel}] {direct_coord}".strip() if direct_channel else direct_coord

        inn_val = dossier.get("inn", "Поиск вручную")
        inn_formatted = f"'{inn_val}" if inn_val and inn_val != "Поиск вручную" else inn_val

        row = [
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"), # A: Дата
            str(oid),                                              # B: OID
            title,                                                 # C: Компания
            url,                                                   # D: URL
            niche,                                                 # E: Ниша
            str(round(total_score, 1)).replace('.', ','),          # F: PIN Score
            lpr_name,                                              # G: ЛПР
            lpr_role,                                              # H: Должность
            contact_display,                                       # I: Личный контакт
            f"{lost_revenue:,}".replace(',', ' ') + " ₽",          # J: Кассовый разрыв
            "1. Новый лид",                                        # K: Статус
            inn_formatted,                                         # L: ИНН
            direct_email,                                          # M: Прямой Email
            dossier.get("legal_name", "—"),                        # N: Юр. наименование
            dossier.get("business_age_str", "—"),                  # O: Возраст бизнеса
            dossier.get("revenue_str", "—"),                       # P: Выручка за год (ФНС)
            dossier.get("employees_str", "—"),                     # Q: Штат сотрудников
            dossier.get("okved_str", "—"),                         # R: Основной ОКВЭД
            clinic_phone,                                          # S: Телефон клиники
            dossier.get("legal_status", "—")                       # T: Статус юрлица
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
# 5. НОРМАЛИЗАЦИЯ, OID И ПАРСИНГ
# ==========================================
def extract_oid_and_url(raw_url):
    url = str(raw_url).strip()
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
    
    org_match = re.search(r'/org/([^/?#]+)/(\d+)', url)
    if org_match:
        slug = org_match.group(1)
        oid = org_match.group(2)
        clean_url = f"https://yandex.ru/maps/org/{slug}/{oid}/"
    else:
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

def fetch_apify_data(cleaned_url):
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
            raise Exception("Таймаут сбора данных от Яндекс Карт.")
        time.sleep(4)
        status_req = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}", 
            timeout=10
        ).json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED":
        raise Exception(f"Актор завершился со статусом [{status}].")
        
    dataset = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}", 
        timeout=15
    ).json()
    
    if not isinstance(dataset, list) or len(dataset) == 0:
        raise Exception(f"Яндекс вернул пустой ответ (Run ID: {run_id}).")
        
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
# 6. СКОРИНГ: ВАЛИДАЦИЯ ПРАВИЛ И FAIR SCORE
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

def calculate_hard_facts(data, niche_key="OTHER", inn_code="", dossier=None):
    scores = {}
    now = datetime.now(timezone.utc)
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')
    raw_url = data.get('url') or data.get('website') or ''
    url = str(raw_url).lower()
    
    # PROF-03.1 & 03.2 Рубрикатор
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
        
    # PROF-04.1 & 04.2 Сайт и UTM
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
    
    if len(desc) > 1200:
        scores['PROF-09.1'] = True
    if desc.count('\n') >= 2 or any(bullet in desc for bullet in ['-', '—', '•', '1.', '2.', '*']):
        scores['PROF-09.2'] = True

    if data.get('isVerifiedOwner'):
        scores['PROF-12.1'] = True

    if data.get('legalInfo') or data.get('companyLegalInfo') or (inn_code and inn_code != "Поиск вручную" and len(inn_code) in (10, 12)):
        scores['PROF-15.1'] = True
    
    social_items = data.get('socialLinks') or data.get('links') or []
    owner_links = (url + " " + desc + " " + " ".join([str(l) for l in social_items])).lower()
    
    if any(s in owner_links for s in ["t.me", "wa.me", "whatsapp", "viber"]):
        scores['PROF-13.1'] = True
    if any(s in owner_links for s in ["vk.com", "vk.ru", "youtube", "dzen", "instagram"]):
        scores['PROF-13.2'] = True

    # ----------------------------------------------------
    # HARD FACTS 2.0: PROF-14.1 (ГОД ОСНОВАНИЯ БИЗНЕСА)
    # ----------------------------------------------------
    if dossier and dossier.get("business_age_str") and dossier["business_age_str"] != "—":
        scores['PROF-14.1'] = True
    elif re.search(r'(?:с|основан[ао]?\s*в?|работаем\s*с)\s*(19\d\d|20\d\d)\s*г', desc.lower()):
        scores['PROF-14.1'] = True
    
    # ----------------------------------------------------
    # ОНЛАЙН-ЗАПИСЬ (CONV-48.1 - 3 БАЛЛА В DENTISTRY)
    # ----------------------------------------------------
    has_booking = False
    if data.get('bookingUrl') or data.get('actionButtons') or data.get('appointmentUrl') or data.get('widgetUrl') or data.get('bookingLinks'):
        has_booking = True
    booking_domains = ["yclients", "medesk", "booking", "dikidi", "infoclinica", "dental-booking", "online-zapis"]
    if any(bd in owner_links for bd in booking_domains):
        has_booking = True
    if has_booking:
        scores['CONV-48.1'] = True
        
    # ПРЯМОЙ ЧАТ В КАРТАХ (CONV-50.1)
    if data.get('isChatEnabled') or (isinstance(features, dict) and features.get('chat')) or data.get('chat'):
        scores['CONV-50.1'] = True
    
    # ----------------------------------------------------
    # КАТАЛОГ И ПРЕЙСКУРАНТ (PROF-11 + CONV-53.1 БЕЙДЖИ)
    # ----------------------------------------------------
    menu_data = data.get('menu')
    menu_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    catalog_items = data.get('productCatalog') or []
    if not isinstance(catalog_items, list):
        catalog_items = []
    goods_items = data.get('goods') or []
    if not isinstance(goods_items, list):
        goods_items = []
        
    valid_prods = [p for p in (menu_items + catalog_items + goods_items) if isinstance(p, dict)]
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

        # HARD FACTS 2.0: CONV-53.1 Маркетинговые бейджи и скидки в витрине
        has_badges = False
        for p in valid_prods:
            p_text = f"{p.get('title', '')} {p.get('name', '')} {p.get('description', '')}".lower()
            if p.get('oldPrice') or p.get('badge') or p.get('badges') or any(w in p_text for w in ['скидк', 'акци', 'хит', 'спецпредложен', 'выгод', '%']):
                has_badges = True
                break
        if has_badges or (isinstance(features, dict) and features.get('promotions')):
            scores['CONV-53.1'] = True
        
    if len(str(data.get('address') or '')) > 5:
        scores['SEO-18.1'] = True
        
    if data.get('entrances') or data.get('entranceCoordinates') or data.get('doors'):
        scores['GEO-18.4'] = True

    # ----------------------------------------------------
    # HARD FACTS 2.0: SEO-18.2 (ЗОНА ОБСЛУЖИВАНИЯ / ВЫЕЗД)
    # ----------------------------------------------------
    if data.get('serviceArea') or data.get('delivery') or (isinstance(features, dict) and any(k in features for k in ['delivery', 'car_park', 'street_entrance', 'parking'])):
        scores['SEO-18.2'] = True

    # ----------------------------------------------------
    # HARD FACTS 2.0: SEO-18.3 (ТОПОНИМЫ В ТЕКСТЕ ОПИСАНИЯ)
    # ----------------------------------------------------
    corpus_geo = f"{desc} {title} {data.get('address', '')}".lower()
    metro_names = [str(m.get('name', '')).lower() for m in (data.get('nearbyMetro') or []) if isinstance(m, dict)]
    toponym_stems = ['улиц', 'проспект', 'набережн', 'переулок', 'линия', 'шоссе', 'бульвар', 'площад', 'район', 'остров', 'метро', 'в.о.', 'васильевск', 'москва', 'петербург', 'спб']
    if any(mn in corpus_geo for mn in metro_names if len(mn) > 3) or any(ts in corpus_geo for ts in toponym_stems):
        scores['SEO-18.3'] = True

    # ----------------------------------------------------
    # HARD FACTS 2.0: CONV-52.1 (НАЛИЧИЕ БЛОКА FAQ)
    # ----------------------------------------------------
    if data.get('faq') or data.get('questionsAndAnswers') or data.get('qna'):
        scores['CONV-52.1'] = True

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

    # ----------------------------------------------------
    # HARD FACTS 2.0: CONV-46.1 (КАСТОМНАЯ ОБЛОЖКА ПРОФИЛЯ)
    # ----------------------------------------------------
    if photos:
        first_p = photos[0] if isinstance(photos[0], dict) else {}
        first_tags = [t.get('id', '') for t in (first_p.get('tags') or []) if isinstance(t, dict)]
        if "Panorama" not in first_tags and first_p.get('copyright') != "Яндекс":
            scores['CONV-46.1'] = True
        elif data.get('logoUrl') or (len(photos) > 1 and any(p.get('copyright') != "Яндекс" for p in photos[:3])):
            scores['CONV-46.1'] = True
    
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
    
    # Анализ отзывов с адаптивным окном свежести и извлечением authorLevel
    raw_reviews = data.get('reviews') or []
    all_reviews = [r for r in raw_reviews if isinstance(r, dict)]
    if all_reviews:
        all_reviews.sort(
            key=lambda x: parse_yandex_date(x.get('date')) or datetime(1970, 1, 1, tzinfo=timezone.utc), 
            reverse=True
        )
        top_20 = all_reviews[:20]
        first_date = parse_yandex_date(all_reviews[0].get('date'))
        
        freshness_window = 30 if niche_key in ["DENTISTRY", "BEAUTY_MEDICAL"] else 21
        if first_date and (now - first_date).days <= freshness_window:
            scores['REP-29.1'] = True
            
        replied = 0
        has_photos = 0
        good_reply = False
        quick_reply = False
        expert_authors = 0
        reply_lengths = []
        recent_reply = False
        
        for r in top_20:
            # Парсинг уровня автора (прямое поле authorLevel в Apify)
            author_lvl = safe_int(r.get('authorLevel') or r.get('author', {}).get('level') or r.get('userLevel') or 0)
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
                if bc_date and (now - bc_date).days <= 45:
                    recent_reply = True
                elif not bc_date and rev_date and (now - rev_date).days <= 45:
                    recent_reply = True
        
        if top_20:
            if replied / len(top_20) >= 0.7:
                scores['REP-30.1'] = True
            if has_photos / len(top_20) >= 0.05:
                scores['REP-35.1'] = True
            if expert_authors / len(top_20) >= 0.20:
                scores['REP-34.1'] = True
                
        if good_reply:
            scores['REP-30.3'] = True
        if quick_reply:
            scores['REP-30.2'] = True
        if reply_lengths and (sum(reply_lengths) / len(reply_lengths)) >= 60:
            scores['REP-30.4'] = True
        if recent_reply:
            scores['REP-85.1'] = True
            
    return scores

# ==========================================
# 7. ГЕНЕРАЦИЯ ДИНАМИЧЕСКОГО PDF (TYPST)
# ==========================================
def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, client_ltv, competitors_text=""):
    current_date = datetime.now().strftime("%d.%m.%Y")
    score_color = "166534" if score >= 75 else ("8B7355" if score >= 50 else "9F1239")
    dev = round(100 - score, 1)
    
    if score >= 75:
        lost_leads = max(2, int(client_leads * (dev / 100)))
        revenue_loss = max(revenue_loss, int(lost_leads * client_check))
    else:
        lost_leads = int(client_leads * (dev / 100))
        
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    weekly_loss = max(1, int(revenue_loss / 4))
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
        target_forms_gen = ("пациента", "пациентов")
    elif "мед" in niche_str or "клиник" in niche_str or "бьют" in niche_str or "салон" in niche_str:
        quality_phrase = "медицинских услуг, опыта специалистов и уровня заботы о клиентах"
        target_forms_gen = ("пациента", "пациентов")
    elif "horeca" in niche_str or "ресторан" in niche_str or "кафе" in niche_str or "бар" in niche_str:
        quality_phrase = "кухни, сервиса и гостеприимной атмосферы заведения"
        target_forms_gen = ("гостя", "гостей")
    elif "авто" in niche_str or "мойка" in niche_str or "сервис" in niche_str:
        quality_phrase = "ремонта, запчастей и квалификации автомехаников"
        target_forms_gen = ("автовладельца", "автовладельцев")
    else:
        quality_phrase = "товаров, услуг и стандартов клиентского сервиса"
        target_forms_gen = ("клиента", "клиентов")

    audience_declension = plural_ru_gen(lost_leads, target_forms_gen)

    failed_items = [
        r for r in results_data 
        if r.get('Evaluated') and r['Результат'] == 'НЕТ' and r['Max'] > 0
    ]
    failed_items.sort(key=lambda x: x['Max'], reverse=True)

    if score >= 75:
        p3_heading = "Точки скрытого роста и удержания лидерства"
        p3_subtitle = f"Профиль занимает прочные позиции в районе, однако следующие детали позволят закрепить преимущество над конкурентами{comp_safe}:"
        exec_summary = f"Карточка входит в группу лидеров локации (Индекс: *{round(score, 1)} / 100*). Репутация и рейтинг сформированы на высоком уровне. Выявленные недочеты носят точечный характер, однако их устранение позволит защитить кассу от перехвата трафика ближайшими соседями."
    else:
        p3_heading = "Три главные причины потери клиентов"
        p3_subtitle = f"Почему потенциальные клиенты из вашего района обращаются к прямым конкурентам{comp_safe}:"
        exec_summary = f"Прямо сейчас профиль скрыт от *{dev}% целевых клиентов* вашего района. Из-за технических недочетов в оформлении карточки вы каждый месяц отдаете конкурентам локации около *{lost_leads} {audience_declension}*. Высокий рейтинг подтверждает доверие постоянных гостей, однако по общим запросам алгоритмы опускают карточку ниже активных соседей."

    slots = []
    for i in range(3):
        if i < len(failed_items):
            item = failed_items[i]
            slots.append({
                "title": clean_typography(item["Критерий"]),
                "desc": clean_typography(item["Обоснование"])
            })
        else:
            slots.append({
                "title": "Резерв для масштабирования видимости",
                "desc": "Регулярный аудит актуальности услуг, фотографий интерьера и защиты карточки от недостоверных правок со стороны конкурентов."
            })

    template_path = os.path.join(os.path.dirname(__file__), "report_template.typ")
    if not os.path.exists(template_path):
        st.error("Файл report_template.typ не найден рядом с app.py!")
        return b""

    with open(template_path, "r", encoding="utf-8") as f:
        typ_source = f.read()

    # Защита от сбоя режима формул Typst ($P,$ -> ~₽)
    typ_source = typ_source.replace("$P,$", "~₽").replace("$P$", "~₽").replace(" $P ", " ~₽ ")

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
        "[[EXECUTIVE_SUMMARY]]": exec_summary,
        "[[PAGE_3_HEADING]]": p3_heading,
        "[[PAGE_3_SUBTITLE]]": p3_subtitle,
        "[[FAIL_1_TITLE]]": slots[0]["title"],
        "[[FAIL_1_DESC]]": slots[0]["desc"],
        "[[FAIL_2_TITLE]]": slots[1]["title"],
        "[[FAIL_2_DESC]]": slots[1]["desc"],
        "[[FAIL_3_TITLE]]": slots[2]["title"],
        "[[FAIL_3_DESC]]": slots[2]["desc"]
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
        with st.expander("🔍 Диагностика Typst: исходный код"):
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

    lpr_data, dossier, direct_email, clinic_phone = resolve_lpr_and_dossier(data, expert_engine, DADATA_API_KEY)
    
    raw_related = data.get('relatedPlaces') or []
    if isinstance(raw_related, dict):
        raw_related = raw_related.get('items') or raw_related.get('places') or [raw_related]
    competitors_list = [str(c.get('name')).strip() for c in raw_related if isinstance(c, dict) and c.get('name')][:2] if isinstance(raw_related, list) else []
    competitors_text = f" (например, {', '.join(competitors_list)})" if competitors_list else ""
    
    with st.spinner("Расчет юнит-экономики и скоринг профиля..."):
        niche_key = determine_niche_by_expert(title, cat, prompts_data)
        
        # Запуск скоринга с передачей досье DaData для Hard Facts 2.0
        raw_scores = calculate_hard_facts(data, niche_key, inn_code=dossier["inn"], dossier=dossier)
        
        results = []
        earned_sum = 0.0
        evaluated_max_sum = 0.0
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
            
            # Строгий фильтр: оцениваются только реализованные правила
            is_evaluated = code in PROGRAMMED_CODES
            is_passed = bool(raw_scores.get(code, False))
            earned_val = max_s if is_passed else 0.0
            
            if is_evaluated and max_s > 0.0:
                earned_sum += earned_val
                evaluated_max_sum += max_s
                
            results.append({
                "Код": code,
                "Критерий": name,
                "Результат": "ДА" if is_passed else "НЕТ",
                "Обоснование": reason_success if is_passed else reason_error,
                "Группа": group,
                "Этап": stage_val,
                "Earned": earned_val,
                "Max": max_s,
                "Evaluated": is_evaluated
            })

        # Расчет итогового балла (Fair Score)
        if evaluated_max_sum > 0:
            final_total_score = round((earned_sum / evaluated_max_sum) * 100, 1)
        else:
            final_total_score = 50.0

        if earned_sum < evaluated_max_sum and final_total_score >= 100.0:
            final_total_score = 94.0

        eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
        niche_label = eco.get("label", "Прочее")

        smart_check_val, check_source = determine_smart_check(data, niche_key)

        with st.sidebar:
            st.divider()
            st.markdown(f"### 🧮 Экономика: {niche_key}")
            st.caption(f"Источник чека: *{check_source}*")
            client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
            client_check = st.number_input("Средний чек первого визита (₽)", value=smart_check_val, step=500)
            client_ltv = st.number_input("Цикл LTV (месяцев)", value=eco["ltv_months"], step=1)

        lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
        
        # Унифицированный порог 75 баллов для лидеров
        if final_total_score >= 75:
            lost_leads_calc = max(2, int(client_leads * lost_percentage))
            lost_revenue = max(int(lost_leads_calc * client_check), int(client_leads * lost_percentage * client_check))
        else:
            lost_revenue = int(client_leads * lost_percentage * client_check)

        history_info = check_oid_history(current_oid)

        st.divider()
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"🏢 {title}")
            inn_badge = f" | 🏛 ИНН: **{dossier['inn']}**" if dossier['inn'] != "Поиск вручную" else " | 🏛 ИНН: *поиск по сайту/вручную*"
            st.caption(f"🔑 Яндекс OID: **{current_oid}**{inn_badge} | 🧠 Сегмент: **{niche_label}**")
            
            if history_info["exists"]:
                st.info(f"🔄 **Карточка уже в базе ({history_info['source']}).** Базовый балл: {history_info['base_score']} | Замеров: {history_info['count']}")
            else:
                st.success("✨ **Новая организация.** Будет зафиксирована в CRM Results.")
                
            if lpr_data and lpr_data.get('status') == 'found':
                lpr_fio = lpr_data.get('name') or 'Руководитель'
                lpr_pos = lpr_data.get('role', 'Руководство')
                src_info = f" *(источник: {lpr_data.get('source')})*"
                st.success(f"🕵️‍♂️ **Найден ЛПР:** {lpr_fio} — {lpr_pos}{src_info}")
                
                badges = []
                if lpr_data.get('direct_tg'):
                    badges.append(f"✈️ [Telegram]({lpr_data['direct_tg']})")
                if lpr_data.get('direct_wa'):
                    badges.append(f"💬 [WhatsApp]({lpr_data['direct_wa']})")
                if lpr_data.get('link') and "vk.com" in lpr_data.get('link', ''):
                    badges.append(f"🌐 [Профиль VK]({lpr_data['link']})")
                if lpr_data.get('phone'):
                    badges.append(f"📞 Телефон ЛПР: `{lpr_data['phone']}`")
                elif clinic_phone:
                    badges.append(f"📞 Клиника: `{clinic_phone}`")
                if direct_email:
                    badges.append(f"✉️ `{direct_email}`")
                if badges:
                    st.markdown("Прямые координаты: " + " | ".join(badges))
            else:
                st.caption("ℹ️ Прямой контакт руководителя скрыт. Доступны общие контакты организации.")

            if dossier["found"]:
                with st.expander("🏛 Юридическое досье компании (ФНС / DaData)", expanded=False):
                    dc1, dc2, dc3 = st.columns(3)
                    dc1.markdown(f"**Юрлицо:** {dossier['legal_name']}\n\n**Статус:** {dossier['legal_status']}")
                    dc2.markdown(f"**Возраст:** {dossier['business_age_str']}\n\n**Штат:** {dossier['employees_str']}")
                    dc3.markdown(f"**Выручка ФНС:** {dossier['revenue_str']}\n\n**ОКВЭД:** {dossier['okved_str']}")
            
        with col2:
            delta = "Отличный результат (Лидер)" if final_total_score >= 75 else ("Требует оптимизации" if final_total_score >= 50 else "Критический уровень")
            st.metric(f"Индекс {PROJECT_NAME}", f"{round(final_total_score, 1)} / 100", delta=delta, delta_color="normal" if final_total_score >= 75 else "inverse")

        st.error(f"Потери: **{lost_revenue:,} ₽** ежемесячно.".replace(',', ' '))
        
        with st.expander(f"🔍 Статус аудита критериев: проверено {len(PROGRAMMED_CODES)} из {len(rules_data)}", expanded=False):
            st.caption("Балл нормализован строго по реализованным правилам (Fair Score).")
            active_list = [f"`{r['Код']}` {r['Критерий']} ({r['Результат']})" for r in results if r['Evaluated']]
            st.write(" | ".join(active_list[:30]) + " ...")

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
            
            if final_total_score >= 75:
                leads_min = 2
                leads_max = 4
                lost_revenue_adj = max(lost_revenue, int(leads_min * client_check))
            else:
                leads_min = max(3, int(client_leads * lost_percentage * 0.8))
                leads_max = max(5, int(client_leads * lost_percentage))
                lost_revenue_adj = lost_revenue

            template_payload = {
                "niche_key": niche_key,
                "lpr_name": lpr_data.get("name") if (lpr_data and lpr_data.get("name")) else "",
                "title": title,
                "score": final_total_score,
                "is_leader": final_total_score >= 75,
                "rating": round(safe_float(data.get("rating"), 4.5), 1),
                "comp_1": comp_1,
                "comp_2": comp_2,
                "lost_leads": f"{leads_min}–{leads_max}",
                "lost_revenue": lost_revenue_adj,
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
                                    final_total_score, lost_revenue, lpr_data, dossier, direct_email, clinic_phone
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
