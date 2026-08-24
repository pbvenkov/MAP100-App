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
    """
    Разворачивает короткие ссылки (/-/CT...), 
    принудительно переводит домен на yandex.ru 
    и очищает URL для корректной работы Apify.
    """
    url = raw_url.strip()
    
    # 1. Распаковываем короткую ссылку через HTTP Redirect
    if "/-/" in url:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        })
        try:
            res = session.get(url, allow_redirects=True, timeout=12)
            if res.url:
                url = res.url
        except Exception:
            pass

    # 2. Принудительно меняем .com / .by / .kz / navi на yandex.ru/maps/
    url = re.sub(r'yandex\.(?:com|by|kz|uz)/', 'yandex.ru/', url)
    url = url.replace("yandex.ru/navi/", "yandex.ru/maps/")
    
    # 3. Отрезаем поисковые GET-параметры (?ll=..., &sctx=...)
    if "?" in url:
        url = url.split("?")[0]
        
    # 4. Убираем вкладки (/reviews, /gallery, /menu и т.д.)
    url = re.sub(r'/(reviews|gallery|features|menu|goods|prices|posts)/?$', '', url)
    
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
    
    if not isinstance(dataset, list) or len(dataset) == 0:
        raise Exception(f"Яндекс не вернул данные по адресу: {cleaned_url}")
        
    first_item = dataset[0]
    if not isinstance(first_item, dict) or not first_item.get('title'):
        raise Exception(f"Яндекс вернул пустую карточку по адресу: {cleaned_url}")
        
    return first_item

def enrich_lpr_contacts_from_vk(social_links):
    if not VK_API_TOKEN or not social_links: 
        return {}
    vk_url = next((link.get('url', '') for link in social_links if 'vk.com' in link.get('url', '') or 'vk.ru' in link.get('url', '')), None)
    if not vk_url: 
        return {}
    try:
        group_id = vk_url.rstrip('/').split('/')[-1]
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

# ==========================================
# 5. АЛГОРИТМЫ СКОРИНГА И АНАЛИТИКА
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

def rewrite_errors_by_ai(niche_label, company_name, failed_rules, expert_engine):
    if not expert_engine or not failed_rules: 
        return failed_rules
    payload_text = "".join([f"ID: {r['Код']} | Ошибка: {r['Критерий']} | Текст: {r['Обоснование']}\n" for r in failed_rules])
    prompt = f"""Ты — B2B-эксперт по локальному маркетингу. Ниша: {niche_label}. Компания: {company_name}.
Перепиши обоснование каждой ошибки под боли этой ниши. Опирайся на упущенную выручку и потерю клиентов.
Ошибки:
{payload_text}
Верни строго JSON объект вида: {{"Код_ошибки": "Новый текст обоснования"}}"""
    try:
        raw_resp = expert_engine.generate_content(prompt).text
        cleaned_json = raw_resp.replace("```json", "").replace("
