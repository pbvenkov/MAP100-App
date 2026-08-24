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

# ==========================================
# 1. КОНФИГУРАЦИЯ И БРЕНДИНГ
# ==========================================
PROJECT_NAME = "PIN100"
EXPERT_TITLE = "Генератор B2B Воронки (Аналитический Отчет)"

APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 
VK_API_TOKEN = st.secrets.get("VK_API_TOKEN", "")

# Инициализация ИИ Gemini
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
            prompt = f"Кратко (в 2 предложениях) оцени нишу '{category}' (компания '{title}'). Почему B2B-консалтинг за 85 000 руб. окупится в этом сегменте?"
            response = expert_engine.generate_content(prompt)
            ai_reasoning = response.text.strip()
        except Exception:
            pass

    tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    text = (
        f"🚨 *Обнаружена новая ниша!*\n\n"
        f"🏢 *Компания:* {title}\n"
        f"🏷 *Категория:* {category}\n"
        f"🔑 *Скрытые ключи Яндекса:* {', '.join(unique_keys)}\n\n"
        f"💡 *Оценка ИИ:*\n_{ai_reasoning}_"
    )
    try: 
        requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
    except Exception: 
        pass

# ==========================================
# 3. БАЗЫ ДАННЫХ И GOOGLE SHEETS
# ==========================================
NICHE_ECONOMICS = {
    "DENTISTRY": {"leads": 70, "check": 25000, "label": "Стоматология", "ltv_months": 12},
    "HORECA": {"leads": 150, "check": 2000, "label": "HORECA / Рестораны", "ltv_months": 12},
    "B2B": {"leads": 40, "check": 30000, "label": "Легкий B2B / Опт", "ltv_months": 12},
    "B2B_HEAVY": {"leads": 10, "check": 500000, "label": "Сложный B2B / Производство", "ltv_months": 1},
    "RETAIL": {"leads": 200, "check": 1500, "label": "Ритейл", "ltv_months": 12},
    "AUTO": {"leads": 100, "check": 12000, "label": "Автосервис / Автосалон", "ltv_months": 6},
    "SERVICES": {"leads": 60, "check": 7000, "label": "Услуги B2C", "ltv_months": 6},
    "BEAUTY_MEDICAL": {"leads": 80, "check": 6000, "label": "Медицина / Бьюти", "ltv_months": 12},
    "EDUCATION": {"leads": 30, "check": 50000, "label": "Образование", "ltv_months": 12},
    "OTHER": {"leads": 50, "check": 5000, "label": "Прочее", "ltv_months": 6}
}

def get_google_credentials():
    creds_str = st.secrets.get("GCP_CREDENTIALS", "{}")
    creds_dict = json.loads(creds_str)
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
        return rules, prompts
    except Exception as e:
        st.error(f"Ошибка подключения к Google Sheets: {e}")
        return [], []

def save_audit_to_sheets(url, title, niche, total_score, lost_revenue, lpr_data=None):
    """Компактная CRM-фиксация лида"""
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Results")
        
        lpr_name = lpr_data.get("name", "") if lpr_data else ""
        lpr_role = lpr_data.get("role", "") if lpr_data else ""
        lpr_contact = lpr_data.get("link", "") or lpr_data.get("email", "") if lpr_data else ""
        lpr_full = f"{lpr_name} ({lpr_role})".strip(" ()")
        
        row = [
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"),
            title,
            niche,
            str(round(total_score, 1)).replace('.', ','),
            f"{lost_revenue:,}".replace(',', ' ') + " ₽",
            lpr_full,
            lpr_contact,
            url,
            "1. Новый лид",
            ""
        ]
        ws.append_row(row)
    except Exception:
        pass

# ==========================================
# 4. НОРМАЛИЗАЦИЯ ССЫЛОК И СБОР ДАННЫХ
# ==========================================
def normalize_yandex_url(raw_url):
    """Очищает URL от параметров поиска, сохраняя структуру карточки организации"""
    url = raw_url.strip()
    
    if "/-/" in url:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            res = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
            url = res.url
        except Exception:
            pass

    url = url.replace("yandex.ru/navi/", "yandex.ru/maps/").replace("yandex.com/navi/", "yandex.com/maps/")
    
    if "?" in url:
        url = url.split("?")[0]
        
    url = re.sub(r'/(reviews|gallery|features|menu|goods)/?$', '', url)
    return url.rstrip('/') + '/'

def fetch_apify_data(yandex_url):
    cleaned_url = normalize_yandex_url(yandex_url)
    
    run_req = requests.post(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}",
        json={
            "startUrls": [{"url": cleaned_url}],
            "maxItems": 1,
            "enrichBusinessData": True,
            "maxPhotos": 80,
            "maxPosts": 30
        },
        timeout=15
    ).json()
    
    if 'error' in run_req: 
        raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: 
            raise Exception("Таймаут сбора данных. Яндекс долго отвечает.")
        time.sleep(4)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}", timeout=10).json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": 
        raise Exception(f"Парсер завершился со статусом {status}.")
        
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}", timeout=15).json()
    
    if not dataset or not isinstance(dataset,
