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
    
    if not dataset or not isinstance(dataset, list) or len(dataset) == 0 or not dataset[0].get('title'): 
        raise Exception(f"Яндекс не вернул данные по адресу: {cleaned_url}")
        
    return dataset[0]

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
        cleaned_json = re.sub(r'```json|```', '', raw_resp).strip()
        match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
        if match:
            new_texts = json.loads(match.group(0))
            for r in failed_rules:
                if r['Код'] in new_texts and str(new_texts[r['Код']]).strip(): 
                    r['Обоснование'] = new_texts[r['Код']]
    except Exception: 
        pass
    return failed_rules

def calculate_hard_facts(data, niche_key="OTHER"):
    scores = {}
    now = datetime.now(timezone.utc)
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')
    url = str(data.get('url') or data.get('website') or '').lower()
    
    cat_list = data.get('categories', [''])
    cat_name = cat_list[0].get('name', cat_list[0]) if isinstance(cat_list[0], dict) else str(cat_list[0])
    
    if data.get('isVerifiedOwner') or len(title) > 2: 
        scores['PROF-01.1'] = True
    if data.get('categories'): 
        scores['PROF-03.1'] = True
    if url: 
        scores['PROF-04.1'] = True
        
    phones = data.get('phones') or []
    if phones: 
        scores['PROF-05.1'] = True
        if any(str(p).startswith('+7') or str(p).startswith('8') for p in phones): 
            scores['PROF-05.2'] = True
            
    schedule = data.get('schedule') or data.get('workingHours') or []
    if (isinstance(schedule, list) and len(schedule) >= 5) or (isinstance(schedule, dict) and len(schedule.keys()) >= 5): 
        scores['PROF-07.1'] = True
    
    features = data.get('features', {})
    if isinstance(features, (dict, list)) and len(features) > 0: 
        scores['PROF-08.1'] = True

    NICHE_MAPPING = {
        "DENTISTRY": ["dentist_services", "uni_medic_specialization"], 
        "AUTO": ["car_wash_services", "auto_repair_features"], 
        "HORECA": ["restaurant_services", "cuisine_type"], 
        "EDUCATION": ["school_direction", "specialized_schools", "classes for children"]
    }
    if isinstance(features, dict):
        if any(features.get(key) for key in NICHE_MAPPING.get(niche_key, [])): 
            scores['PROF-08.2'] = True
        if niche_key in ["OTHER", "SERVICES"]:
            client_unique_keys = [k for k in features.keys() if k not in {'payment_method', 'wi_fi', 'toilet', 'parking', 'street_entrance', 'parking_disabled', 'promotions', 'wheelchair_access'}]
            if len(client_unique_keys) >= 2: 
                send_telegram_business_alert(title, cat_name, client_unique_keys[:5])
    
    if len(desc) > 1200: 
        scores['PROF-09.1'] = True
    if data.get('isVerifiedOwner'): 
        scores['PROF-12.1'] = True
    
    owner_links = url + " " + desc + " " + " ".join([str(l) for l in (data.get('socialLinks') or data.get('links') or [])])
    if any(s in owner_links.lower() for s in ["t.me", "wa.me", "whatsapp", "viber"]): 
        scores['PROF-13.1'] = True
    if any(s in owner_links.lower() for s in ["vk.com", "vk.ru", "youtube", "dzen", "instagram"]): 
        scores['PROF-13.2'] = True
    
    valid_prods = [p for p in (data.get('menu', {}).get('items', []) if isinstance(data.get('menu'), dict) else []) + (data.get('productCatalog') or []) if isinstance(p, dict)]
    if valid_prods:
        if len(valid_prods) >= 10: 
            scores['PROF-11.1'] = True
        if sum(1 for p in valid_prods if p.get('photoUrl') or p.get('photo')) / len(valid_prods) >= 0.7: 
            scores['PROF-11.2'] = True
        if sum(1 for p in valid_prods if any(char.isdigit() for char in str(p.get('price') or ''))) / len(valid_prods) >= 0.7: 
            scores['PROF-11.3'] = True
        if sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 40) / len(valid_prods) >= 0.6: 
            scores['PROF-11.4'] = True
        if len(set([p.get('category') for p in valid_prods if p.get('category')])) >= 2: 
            scores['PROF-11.5'] = True
        
    if len(str(data.get('address') or '')) > 5: 
        scores['SEO-18.1'] = True
    if data.get('videoCount', 0) > 0 or data.get('videos') or data.get('mobileVideos'): 
        scores['CONT-42.1'] = True
    
    photos = data.get('photos', [])
    photo_count = int(data.get('photoCount') or len(photos) or 0)
    if photo_count >= 15: 
        scores['CONT-36.1'] = True
    if photo_count >= 30: 
        scores['CONT-36.2'] = True
    
    tags = [tag.get('id', '') for p in photos for tag in p.get('tags', []) if isinstance(tag, dict)]
    if "Interior" in tags or any(p.get('tag') == 'interior' for p in photos):
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
            
    rating = float(data.get('rating') or 0.0)
    if rating >= 4.5: 
        scores['REP-27.1'] = True
    if rating >= 4.8: 
        scores['REP-27.2'] = True
    if int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount') or 0) >= 40: 
        scores['REP-28.1'] = True
    
    all_reviews = [r for r in (data.get('reviews') or []) if isinstance(r, dict)]
    if not all_reviews: 
        scores['META_NO_RECENT_REVIEWS'] = True
    else:
        replied = sum(1 for r in all_reviews[:20] if str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip())
        first_date = parse_yandex_date(all_reviews[0].get('date'))
        if first_date and (now - first_date).days <= 14: 
            scores['REP-29.1'] = True
        if len(all_reviews[:20]) > 0:
            if replied / len(all_reviews[:20]) >= 0.7: 
                scores['REP-30.1'] = True
            if sum(1 for r in all_reviews[:20] if r.get('photos') or r.get('photoDetails')) / len(all_reviews[:20]) >= 0.05: 
                scores['REP-35.1'] = True
        if any(float(r.get('rating') or 0.0) >= 4.0 and str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() for r in all_reviews[:20]): 
            scores['REP-30.3'] = True
            
        for r in all_reviews[:20]:
            bc_date = parse_yandex_date(r.get('businessCommentDate'))
            rev_date = parse_yandex_date(r.get('date'))
            if str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() and bc_date and rev_date and (bc_date - rev_date).days <= 3: 
                scores['REP-30.2'] = True
                break
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    if not expert_engine or not prompts_data: 
        return {}
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')[:1000]
    recent_reviews = [r for r in data.get('reviews', []) if isinstance(r, dict)][:10]
    reviews_text = "".join([f"Отзыв: {r.get('text', '')}\nОтвет: {r.get('businessComment') or r.get('reply', {}).get('text') if isinstance(r.get('reply'), dict) else ''}\n" for r in recent_reviews])
    prods = [p for p in (data.get('menu', {}).get('items', []) if isinstance(data.get('menu'), dict) else []) + (data.get('productCatalog') or []) if isinstance(p, dict)][:20]
    prods_text = ", ".join([str(p.get('name') or p.get('title')) for p in prods])
    
    rules_list = [f'"{p.get("Код", "").strip()}": {p.get("Промпт для ИИ", "").strip()}' for p in prompts_data if p.get('Код', '').strip() and p.get('Код') != 'NICHE_PROMPT']
    if not rules_list: 
        return {}
        
    prompt = f"Контекст:\nНазвание: {title}\nОписание: {desc}\nТовары: {prods_text}\nОтзывы:\n{reviews_text[:1500]}\nКритерии:\n{chr(10).join(rules_list)}\nВерни строго JSON объект {{CODE: true/false}}."
    try:
        raw_resp = expert_engine.generate_content(prompt).text
        cleaned_json = re.sub(r'```json|
