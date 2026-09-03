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

# Вспомогательные модули проекта
try:
    from utils import generate_icebreaker_text
except ImportError:
    try:
        from Utils import generate_icebreaker_text
    except ImportError:
        def generate_icebreaker_text(data):
            return f"Здравствуйте! Подготовлен аудит для {data.get('title', 'организации')}."

try:
    from drive_manager import DriveManager
except ImportError:
    DriveManager = None

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
# 2. СИСТЕМНЫЕ УВЕДОМЛЕНИЯ В TELEGRAM
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
    """Компактная CRM-фиксация лида со строгим порядком колонок"""
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Results")
        
        lpr_name = lpr_data.get("name", "") if lpr_data else ""
        lpr_role = lpr_data.get("role", "") if lpr_data else ""
        lpr_contact = (lpr_data.get("link", "") or lpr_data.get("email", "")) if lpr_data else ""
        
        row = [
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"), # A: Дата
            url,                                                   # B: Ссылка
            title,                                                 # C: Компания
            niche,                                                 # D: Ниша
            str(round(total_score, 1)).replace('.', ','),          # E: Общий балл
            lpr_name,                                              # F: ФИО ЛПР
            lpr_role,                                              # G: Должность
            lpr_contact,                                           # H: Личный контакт
            "",                                                    # I: Прямой Email
            f"{lost_revenue:,}".replace(',', ' ') + " ₽",          # J: Упущенная выручка
            "1. Новый лид"                                         # K: Статус
        ]
        ws.append_row(row)
    except Exception:
        pass

# ==========================================
# 4. НОРМАЛИЗАЦИЯ ССЫЛОК И СБОР ДАННЫХ
# ==========================================
def normalize_yandex_url(raw_url):
    url = raw_url.strip()
    
    # 1. Раскрываем короткие ссылки (yandex.ru/maps/-/... или yandex.com/maps/-/...)
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

    # 2. Меняем домены для стандартизации
    url = re.sub(r'yandex\.(?:com|by|kz|uz)/', 'yandex.ru/', url)
    url = url.replace("yandex.ru/navi/", "yandex.ru/maps/")
    
    # 3. Ищем скрытый OID (ID организации) в координатных ссылках
    oid_match = re.search(r'oid(?:%3D|=)(\d+)', url)
    if oid_match:
        org_id = oid_match.group(1)
        return f"https://yandex.ru/maps/org/{org_id}/"

    # 4. Если OID не найден, чистим стандартную ссылку от мусора
    if "?" in url:
        url = url.split("?")[0]
        
    url = re.sub(r'/(reviews|gallery|features|menu|goods|prices|posts)/?$', '', url)
    return url.rstrip('/') + '/'

def fetch_apify_data(yandex_url):
    cleaned_url = normalize_yandex_url(yandex_url)
    
    payload = {
        "startUrls": [{"url": cleaned_url}],
        "enrichBusinessData": True,
        "includeReviews": True,
        "maxPhotos": 80,
        "maxPosts": 30
    }
    
    run_req = requests.post(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}",
        json=payload,
        timeout=15
    ).json()
    
    if 'error' in run_req:
        raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 75:  # Увеличенный таймаут
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
    if not isinstance(first_item, dict):
        raise Exception("Некорректный формат данных ответа.")
        
    resolved_title = first_item.get('title') or first_item.get('name') or first_item.get('companyName') or first_item.get('header') or "Организация"
    first_item['title'] = resolved_title
    return first_item

def enrich_lpr_contacts_from_vk(social_links):
    if not VK_API_TOKEN or not social_links:
        return {}
    vk_url = next((link.get('url', '') for link in social_links if isinstance(link, dict) and ('vk.com' in link.get('url', '') or 'vk.ru' in link.get('url', ''))), None)
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
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
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
    
    raw_url = data.get('url') or data.get('website') or ''
    url = str(raw_url).lower()
    
    cat_list = data.get('categories') or []
    cat_name = ""
    if isinstance(cat_list, list) and cat_list:
        first_cat = cat_list[0]
        if isinstance(first_cat, dict):
            cat_name = first_cat.get('name', str(first_cat))
        else:
            cat_name = str(first_cat)
    
    if data.get('isVerifiedOwner') or len(title) > 2:
        scores['PROF-01.1'] = True
    if cat_list:
        scores['PROF-03.1'] = True
    if url:
        scores['PROF-04.1'] = True
        
    phones = data.get('phones') or []
    if phones:
        scores['PROF-05.1'] = True
        for p in phones:
            p_str = str(p)
            if p_str.startswith('+7') or p_str.startswith('8'):
                scores['PROF-05.2'] = True
                break
            
    schedule = data.get('schedule') or data.get('workingHours') or []
    if isinstance(schedule, list) and len(schedule) >= 5:
        scores['PROF-07.1'] = True
    elif isinstance(schedule, dict) and len(schedule.keys()) >= 5:
        scores['PROF-07.1'] = True
    
    features = data.get('features') or {}
    if features:
        scores['PROF-08.1'] = True

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
    
    if len(desc) > 1200:
        scores['PROF-09.1'] = True
    if data.get('isVerifiedOwner'):
        scores['PROF-12.1'] = True
    
    social_items = data.get('socialLinks') or data.get('links') or []
    owner_links = (url + " " + desc + " " + " ".join([str(l) for l in social_items])).lower()
    
    if any(s in owner_links for s in ["t.me", "wa.me", "whatsapp", "viber"]):
        scores['PROF-13.1'] = True
    if any(s in owner_links for s in ["vk.com", "vk.ru", "youtube", "dzen", "instagram"]):
        scores['PROF-13.2'] = True
    
    menu_data = data.get('menu')
    menu_items = []
    if isinstance(menu_data, dict):
        menu_items = menu_data.get('items', [])
    catalog_items = data.get('productCatalog') or []
    
    valid_prods = []
    for p in (menu_items or []) + (catalog_items or []):
        if isinstance(p, dict):
            valid_prods.append(p)
            
    if valid_prods:
        total_vp = len(valid_prods)
        if total_vp >= 10:
            scores['PROF-11.1'] = True
            
        with_photo = sum(1 for p in valid_prods if p.get('photoUrl') or p.get('photo'))
        if with_photo / total_vp >= 0.7:
            scores['PROF-11.2'] = True
            
        with_price = sum(1 for p in valid_prods if any(c.isdigit() for c in str(p.get('price') or '')))
        if with_price / total_vp >= 0.7:
            scores['PROF-11.3'] = True
            
        with_desc = sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 40)
        if with_desc / total_vp >= 0.6:
            scores['PROF-11.4'] = True
            
        categories = set(p.get('category') for p in valid_prods if p.get('category'))
        if len(categories) >= 2:
            scores['PROF-11.5'] = True
        
    if len(str(data.get('address') or '')) > 5:
        scores['SEO-18.1'] = True
    if data.get('videoCount', 0) > 0 or data.get('videos') or data.get('mobileVideos'):
        scores['CONT-42.1'] = True
    
    photos = data.get('photos') or []
    photo_count = int(data.get('photoCount') or len(photos) or 0)
    if photo_count >= 15:
        scores['CONT-36.1'] = True
    if photo_count >= 30:
        scores['CONT-36.2'] = True
    
    tags = []
    for p in photos:
        if isinstance(p, dict):
            p_tags = p.get('tags') or []
            for tag in p_tags:
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
            
    rating = float(data.get('rating') or 0.0)
    if rating >= 4.5:
        scores['REP-27.1'] = True
    if rating >= 4.8:
        scores['REP-27.2'] = True
        
    rev_count = int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount') or 0)
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
        
        for r in top_20:
            bc_text = ""
            if isinstance(r.get('reply'), dict):
                bc_text = str(r.get('reply', {}).get('text') or '').strip()
            else:
                bc_text = str(r.get('businessComment') or r.get('reply') or '').strip()
                
            if bc_text:
                replied += 1
            if r.get('photos') or r.get('photoDetails'):
                has_photos += 1
            if float(r.get('rating') or 0.0) >= 4.0 and bc_text:
                good_reply = True
            
            bc_date = parse_yandex_date(r.get('businessCommentDate'))
            rev_date = parse_yandex_date(r.get('date'))
            if bc_text and bc_date and rev_date and (bc_date - rev_date).days <= 3:
                quick_reply = True
        
        if top_20:
            if replied / len(top_20) >= 0.7:
                scores['REP-30.1'] = True
            if has_photos / len(top_20) >= 0.05:
                scores['REP-35.1'] = True
        if good_reply:
            scores['REP-30.3'] = True
        if quick_reply:
            scores['REP-30.2'] = True
            
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
        rep_text = ""
        if isinstance(r.get('reply'), dict):
            rep_text = r.get('reply', {}).get('text', '')
        else:
            rep_text = r.get('businessComment') or r.get('reply') or ''
        reviews_lines.append(f"Отзыв: {r_text}\nОтвет: {rep_text}\n")
    reviews_text = "".join(reviews_lines)
    
    menu_data = data.get('menu')
    m_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    c_items = data.get('productCatalog') or []
    prods = [p for p in m_items + c_items if isinstance(p, dict)][:20]
    prods_text = ", ".join([str(p.get('name') or p.get('title')) for p in prods])
    
    rules_list = []
    for p in prompts_data:
        p_code = str(p.get("Код", "")).strip()
        p_prompt = str(p.get("Промпт для ИИ", "")).strip()
        if p_code and p_code != 'NICHE_PROMPT':
            rules_list.append(f'"{p_code}": {p_prompt}')
            
    if not rules_list:
        return {}
        
    prompt = f"Контекст:\nНазвание: {title}\nОписание: {desc}\nТовары: {prods_text}\nОтзывы:\n{reviews_text[:1500]}\nКритерии:\n{chr(10).join(rules_list)}\nВерни строго JSON объект {{CODE: true/false}}."
    try:
        raw_resp = expert_engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
        if match:
            return {k: True for k, v in json.loads(match.group(0)).items() if str(v).lower() in ["1", "true"]}
    except Exception:
        pass
    return {}

# ==========================================
# 6. ВЕРСТКА TYPST И ГЕНЕРАЦИЯ PDF
# ==========================================
def clean_typography(text):
    if not text:
        return ""
    t = str(text).replace(" - ", " — ")
    t = t.replace(">=", "≥").replace("<=", "≤").replace("->", "→")
    # Заменяем знаки сравнения, чтобы Typst не путал их с разметкой Labels <label>
    t = t.replace("<", " меньше ").replace(">", " больше ")
    # Заменяем все специальные символы синтаксиса Typst
    for c in ['\\', '[', ']', '{', '}', '$', '*', '_', '#', '@', '"', "'", '`', '~']:
        t = t.replace(c, ' ')
    return " ".join(t.split())

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, client_ltv, competitors_text=""):
    current_date = datetime.now().strftime("%d.%m.%Y")
    score_color = "166534" if score >= 80 else ("8B7355" if score >= 50 else "9F1239")
    dev = round(100 - score, 1)
    lost_leads = int(client_leads * (dev / 100))
    
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    
    title_safe = clean_typography(title)
    niche_safe = clean_typography(niche)
    comp_safe = clean_typography(competitors_text)
    
    niche_str = str(niche).lower()
    if "образ" in niche_str:
        package_name = "Интеграция Education PRO"
        package_price = "85 000 ₽"
        quality_phrase = "образовательного процесса и уровень подготовки в вашей компании"
        target_audience = "родителей и учеников"
    elif "стом" in niche_str or "мед" in niche_str or "бьют" in niche_str:
        package_name = "Интеграция Medical PRO"
        package_price = "85 000 ₽"
        quality_phrase = "медицинских услуг, квалификацию врачей и сервис клиники"
        target_audience = "пациентов"
    elif "b2b" in niche_str or "производ" in niche_str or "опт" in niche_str:
        package_name = "Интеграция B2B Enterprise"
        package_price = "85 000 ₽"
        quality_phrase = "продукции и надежность вашего предприятия"
        target_audience = "клиентов и партнеров"
    elif "horeca" in niche_str or "ресторан" in niche_str or "кафе" in niche_str:
        package_name = "Комплексная Бизнес-Упаковка HoReCa"
        package_price = "35 000 ₽"
        quality_phrase = "кухни, атмосферу и гостеприимство вашего заведения"
        target_audience = "гостей"
    elif "авто" in niche_str:
        package_name = "Комплексная Бизнес-Упаковка Авто"
        package_price = "35 000 ₽"
        quality_phrase = "ремонта, запчастей и обслуживания в вашем автоцентре"
        target_audience = "автовладельцев"
    elif "ритейл" in niche_str or "магаз" in niche_str:
        package_name = "Комплексная Бизнес-Упаковка Ритейл"
        package_price = "35 000 ₽"
        quality_phrase = "товаров, широту ассортимента и качество обслуживания в вашем магазине"
        target_audience = "покупателей"
    else:
        package_name = "Комплексная Бизнес-Упаковка"
        package_price = "35 000 ₽"
        quality_phrase = "товаров, услуг и высокий уровень клиентского сервиса"
        target_audience = "клиентов"

    typ_source = f"""
#set document(title: "Аналитический Отчет - {title_safe}", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 25mm),
  footer: [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Строго конфиденциально
    #h(1fr)
    #context [Стр. #counter(page).display("1")]
  ]
)

#set text(font: ("Inter", "Arial", "sans-serif"), size: 10.5pt, fill: rgb("334155"), lang: "ru")
#set par(leading: 0.55em)
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// --- ОБЛОЖКА ---
#v(100pt)
#text(12pt, fill: rgb("8B7355"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(10pt)
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Аналитический Отчет:\\ Оцифровка упущенной выручки]
#v(10pt)
#line(length: 60mm, stroke: 1.5pt + rgb("8B7355"))
#v(30pt)
#text(11pt, fill: rgb("475569"))[
  Подготовлено для: #strong[{title_safe}] \\
  Ниша: #strong[{niche_safe}] \\
  Дата расчета: #strong[{current_date}]
]
#pagebreak()

// --- СТР. 2 EXECUTIVE SUMMARY ---
#heading(level: 2)[Executive Summary (Резюме для руководителя)]
#v(15pt)
#grid(
  columns: (1fr, 1fr),
  gutter: 20pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 18pt)[
      #text(9pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ИНДЕКС ГОТОВНОСТИ ПРОФИЛЯ]
      \\
      #v(8pt)
      #text(26pt, weight: "bold", fill: rgb("{score_color}"))[{round(score, 1)} / 100]
      #v(4pt)
      #text(8.5pt, fill: rgb("94A3B8"), style: "italic")[Оценка по 79 параметрам алгоритмов]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 18pt)[
      #text(9pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[УПУЩЕННАЯ ВЫРУЧКА]
      \\
      #v(8pt)
      #text(24pt, weight: "bold", fill: rgb("9F1239"))[- {rev_loss_fmt} ₽/мес]
    ]
  ]
)
#v(15pt)

#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 15pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Критический вывод аналитики:]
  #v(8pt)
  #text(10.5pt, fill: rgb("334155"))[Прямо сейчас ваша компания фактически невидима для *{dev}% целевых клиентов* в поисковой выдаче Яндекс Карт. Из-за алгоритмических ошибок вы ежемесячно уступаете конкурентам около *{lost_leads} горячих сделок*. Попытки заливать рекламный бюджет в текущий профиль приведут к прямому финансовому убытку.]
]

#v(12pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 4pt, inset: 10pt)[
  #text(8.5pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Оценка #strong[{round(score, 1)} / 100] отражает исключительно техническую видимость профиля для поисковых роботов Яндекса и конверсионную готовность витрины, а не реальное высокое качество {quality_phrase}.
  ]
]

#pagebreak()
// --- СТР. 3 ТОЧКИ СЛИВА ---
#heading(level: 2)[Три главные пробоины в воронке продаж]
#v(10pt)
#text(10.5pt, fill: rgb("475569"))[Главные бизнес-причины потери поискового трафика прямо сегодня:]
#v(15pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 16pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. «Слепая витрина» и потеря поискового трафика]
  #v(8pt)
  #text(10pt, fill: rgb("475569"))[Алгоритмы Яндекса не видят ваши ключевые позиции. Из-за отсутствия LSI-разметки и фидов вас обходят конкуренты{comp_safe} с правильно настроенными каталогами.]
]
#v(12pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 16pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. Барьер первого контакта (Обрыв конверсии)]
  #v(8pt)
  #text(10pt, fill: rgb("475569"))[Ваша карточка заставляет {target_audience} совершать лишние действия. Отсутствие прямых кнопок записи и онлайн-заказа приводит к уходу потенциальных клиентов.]
]
#v(12pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 16pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. Скрытые репутационные угрозы]
  #v(8pt)
  #text(10pt, fill: rgb("475569"))[Оставленный без ответа негативный отзыв отпугивает новых покупателей с высоким средним чеком на финальном этапе принятия решения.]
]

#pagebreak()
// --- СТР. 4 ТАРИФЫ И ВНЕДРЕНИЕ ---
#heading(level: 2)[Инвестиционное предложение и Окупаемость]
#v(8pt)
#text(10pt, fill: rgb("475569"))[Пакет работ под ключ для остановки кассового разрыва:]
#v(12pt)

#grid(
  columns: (1fr, 1.15fr, 1fr),
  gutter: 8pt,
  [
    #rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
      #text(8.5pt, weight: "bold", fill: rgb("64748B"))[БАЗОВЫЙ (Quick Fix)]
      #v(3pt)
      #text(12pt, weight: "bold", fill: rgb("0A1128"))[35 000 ₽]
      #v(3pt)
      #text(8pt, fill: rgb("475569"))[Базовое SEO, устранение ошибок витрины, чистка дублей.]
    ]
  ],
  [
    #rect(fill: rgb("F8FAFC"), stroke: 1.5pt + rgb("8B7355"), radius: 4pt, inset: 10pt)[
      #text(8.5pt, weight: "bold", fill: rgb("8B7355"))[★ {package_name}]
      #v(3pt)
      #text(13pt, weight: "bold", fill: rgb("8B7355"))[{package_price}]
      #v(3pt)
      #text(8pt, fill: rgb("0A1128"), weight: "bold")[Комплекс под ключ: SEO + UX-конверсия + Защита бренда + XML-фиды.]
    ]
  ],
  [
    #rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
      #text(8.5pt, weight: "bold", fill: rgb("64748B"))[ENTERPRISE (ГОД)]
      #v(3pt)
      #text(12pt, weight: "bold", fill: rgb("0A1128"))[150 000 ₽]
      #v(3pt)
      #text(8pt, fill: rgb("475569"))[Полное сопровождение воронки на 6 месяцев + реклама.]
    ]
  ]
)

#v(12pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 12pt)[
  #grid(
    columns: (1fr, auto),
    gutter: 10pt,
    [
      #text(9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Забронировать 20-минутный стратегический Zoom-разбор] \\
      #v(2pt)
      #text(8pt, fill: rgb("CBD5E1"))[Покажем экран вашего профиля в аналитике Яндекса и передадим план исправления ТОП-5 ошибок.]
    ],
    [
      #align(center + horizon)[
        #text(9.5pt, weight: "bold", fill: rgb("8B7355"))[Telegram: \\ t.me/paulvenkov]
      ]
    ]
  )
]
"""

    # --- ТЕХНИЧЕСКОЕ ПРИЛОЖЕНИЕ ---
    typ_source += """
#pagebreak()
#heading(level: 2)[Техническое приложение (Детализация по 79 параметрам)]
#v(10pt)
"""
    blocks = [
        {"title": "Блок 1. Видимость и Охваты (SEO)", "groups": ['SEO и Трафик', 'Активность']},
        {"title": "Блок 2. Упаковка и Конверсия (UX)", "groups": ['Конверсия', 'Базовое заполнение', 'Контент и Визуал']},
        {"title": "Блок 3. Репутационный капитал", "groups": ['Репутация']},
        {"title": "Блок 4. Нейросети и Скрытые данные", "groups": ['Технологии и ИИ']}
    ]

    for block in blocks:
        block_items = [r for r in results_data if r.get('Группа') in block['groups']]
        if not block_items:
            continue
        earned_score = sum(r.get('Earned', 0.0) for r in block_items)
        max_score = sum(r.get('Max', 0.0) for r in block_items)
        percentage = (earned_score / max_score * 100) if max_score > 0 else 100
        bar_color = "166534" if percentage >= 80 else ("8B7355" if percentage >= 50 else "9F1239")
        
        passed_items = [clean_typography(r.get('Критерий', '')) for r in block_items if r.get('Результат') == 'ДА']
        passed_text = ", ".join(passed_items) if passed_items else "Нет данных"

        failed_items_block = [r for r in block_items if r.get('Результат') == 'НЕТ']
        failed_cards = ""
        if failed_items_block:
            for f in failed_items_block:
                c_name = clean_typography(f.get('Критерий', ''))
                c_reason = clean_typography(f.get('Обоснование', ''))
                failed_cards += f"""
#v(3pt)
#block(breakable: false)[
  #rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 3pt, inset: 6pt)[
    #text(9pt, weight: "bold", fill: rgb("9F1239"))[× {c_name}] \\
    #v(2pt)
    #text(8.5pt, fill: rgb("475569"))[{c_reason}]
  ]
]
"""
        else:
            failed_cards = '#v(4pt)\n#text(9pt, fill: rgb("166534"))[Уязвимостей не обнаружено. Отличный результат.]\n'

        typ_source += f"""
#v(10pt)
#heading(level: 3)[{block['title']} (#text(fill: rgb("{bar_color}"))[{round(earned_score, 1)} / {round(max_score, 1)}])]
#v(4pt)
#rect(width: 100%, fill: rgb("F0FDF4"), stroke: 0.5pt + rgb("BBF7D0"), radius: 3pt, inset: 6pt)[
  #text(8pt, weight: "bold", fill: rgb("166534"), tracking: 0.5pt)[В НОРМЕ:] \\
  #v(2pt)
  #text(8.5pt, fill: rgb("475569"))[{passed_text}]
]
#v(3pt)
#text(8pt, weight: "bold", fill: rgb("9F1239"), tracking: 0.5pt)[ЗОНЫ УЯЗВИМОСТИ (ОШИБКИ):]
{failed_cards}
"""

    with tempfile.NamedTemporaryFile(suffix=".typ", delete=False, mode="w", encoding="utf-8") as tf:
        tf.write(typ_source)
        typ_path = tf.name
        
    try:
        pdf_bytes = typst.compile(typ_path)
    except Exception as e:
        st.error(f"Ошибка компиляции Typst: {e}")
        pdf_bytes = b""
    finally:
        if os.path.exists(typ_path):
            os.remove(typ_path)
        
    return pdf_bytes


# ==========================================
# 7. ОСНОВНОЙ ПОЛЬЗОВАТЕЛЬСКИЙ ИНТЕРФЕЙС
# ==========================================
rules_data, prompts_data = fetch_cached_database()

with st.sidebar:
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База данных подключена.")
    st.divider()
    sender_name = st.text_input("Ваше имя (для подписи аутрича):", value="Павел")

st.title(f"📍 {PROJECT_NAME}: {EXPERT_TITLE}")

tab_link, tab_file = st.tabs(["🌐 По ссылке (Яндекс Карты)", "📁 Из JSON файла"])

data_to_process = None
source_url = ""

with tab_link:
    url_input = st.text_input("Вставьте ссылку на карточку организации", placeholder="https://yandex.ru/maps/...")
    if st.button("🚀 Сгенерировать Отчет по ссылке", type="primary"):
        if "yandex" not in url_input.lower():
            st.error("❌ Введите корректную ссылку на Яндекс Карты.")
        else:
            with st.spinner("Сбор свежих данных через Apify..."):
                try:
                    data_to_process = fetch_apify_data(url_input)
                    source_url = url_input
                except Exception as e:
                    send_telegram_alert(str(e), url_input)
                    st.error(f"⚠️ Ошибка парсинга: {str(e)}")

with tab_file:
    uploaded_file = st.file_uploader("Загрузите предварительно сохраненный JSON", type=["json"])
    if uploaded_file and st.button("🚀 Сформировать Отчет из файла"):
        try:
            data_to_process = json.load(uploaded_file)
            source_url = data_to_process.get('url') or "Файл JSON"
        except Exception as e:
            st.error(f"Ошибка чтения JSON: {e}")

# ПАЙПЛАЙН РАСЧЕТА И ВЫВОДА
if data_to_process:
    data = data_to_process
    title = data.get('title', 'Без названия')
    c_list = data.get('categories', [])
    cat = c_list[0].get('name', '') if (isinstance(c_list, list) and c_list and isinstance(c_list[0], dict)) else (str(c_list[0]) if (isinstance(c_list, list) and c_list) else '')
    client_reviews = int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []) or 0)
    
    social_links = data.get('socialLinks') or data.get('links') or []
    if not isinstance(social_links, list):
        social_links = []
    lpr_data = enrich_lpr_contacts_from_vk(social_links)
    
    # Безопасная обработка relatedPlaces
    raw_related = data.get('relatedPlaces') or []
    if isinstance(raw_related, list):
        competitors_list = [
            str(c.get('name')).strip()
            for c in raw_related
            if isinstance(c, dict) and c.get('name')
        ][:2]
    elif isinstance(raw_related, dict):
        raw_items = raw_related.get('items') or raw_related.get('places') or [raw_related]
        competitors_list = [
            str(c.get('name')).strip()
            for c in raw_items
            if isinstance(c, dict) and c.get('name')
        ][:2]
    else:
        competitors_list = []
    competitors_text = f" (например, {', '.join(competitors_list)})" if competitors_list else ""
    
    with st.spinner("Расчет юнит-экономики и запуск алгоритмов..."):
        try:
            niche_key = determine_niche_by_expert(title, cat, prompts_data)
        except Exception:
            niche_key = "OTHER"
        
        raw_scores = calculate_hard_facts(data, niche_key)
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

            try:
                stage_val = int(r.get('Этап_Внедрения', 3))
            except Exception:
                stage_val = 3
            
            try:
                max_s = float(str(r.get(target_column, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
            except Exception:
                max_s = float(r.get('Балл', 0.0))
            
            if max_s > 0.0:
                val = max_s if raw_scores.get(code) else 0.0
                final_total_score += val
                
                if val > 0:
                    comm = "ДА"
                    final_reason = reason_success
                else:
                    comm = "НЕТ"
                    final_reason = reason_error
                    
                results.append({
                    "Код": code,
                    "Критерий": name,
                    "Результат": comm,
                    "Обоснование": final_reason,
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
                results = rewrite_errors_by_ai(niche_label, title, results, expert_engine)

        with st.sidebar:
            st.divider()
            st.markdown(f"### 🧮 Экономика: {niche_key}")
            client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
            client_check = st.number_input("Средний чек (₽)", value=eco["check"], step=5000)
            client_ltv = st.number_input("Цикл LTV (месяцев)", value=eco["ltv_months"], step=1)

        lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
        lost_revenue = int(client_leads * lost_percentage * client_check)

        # Вызов обновленной функции записи в CRM (с 11 колонками)
        save_audit_to_sheets(source_url, title, niche_key, final_total_score, lost_revenue, lpr_data)
        
        st.divider()
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"🏢 {title}")
            st.caption(f"🧠 Сегмент: **{niche_label}** | 📍 Фактических отзывов: {client_reviews}")
            
            if lpr_data and lpr_data.get('status') == 'found':
                st.success(f"🕵️‍♂️ **Найден ЛПР:** {lpr_data.get('name')} ({lpr_data.get('role')})\n\n🔗 {lpr_data.get('link')}")
            elif lpr_data and lpr_data.get('status') == 'hidden':
                st.warning("⚠️ **Группа ВК найдена, но блок «Контакты» скрыт.**")
            
        with col2:
            delta = "Отличный результат" if final_total_score >= 80 else ("Требует оптимизации" if final_total_score >= 50 else "Критический уровень")
            st.metric(f"Индекс {PROJECT_NAME}", f"{round(final_total_score, 1)} / 100", delta=delta, delta_color="normal" if final_total_score >= 80 else "inverse")

        st.error(f"Потери: **{lost_revenue:,} ₽** ежемесячно.".replace(',', ' '))
        
        with st.expander("🛠 Сохранить сырой JSON карточки"):
            json_string = json.dumps(data, ensure_ascii=False, indent=4)
            st.download_button(label="💾 Скачать JSON", data=json_string, file_name=f"{title.replace(' ', '_')}.json", mime="application/json")

        st.divider()
        st.markdown("### 📥 Выгрузка отчетов")
        
        pdf_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, client_ltv, competitors_text)
        
        if pdf_bytes:
            st.download_button(
                label="💎 Скачать Аналитический Отчет (PDF)",
                data=pdf_bytes,
                file_name=f"PIN100_Report_{title.replace(' ', '_')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

            # ==========================================
            # 8. ГЕНЕРАЦИЯ АУТРИЧА И АВТО-СОХРАНЕНИЕ НА ДИСК
            # ==========================================
            st.divider()
            st.markdown("### ✉️ Персональное письмо первого касания (Icebreaker)")
            st.caption("Отправляется в WhatsApp или на Email без вложений. Задача — получить согласие на аудит.")
            
            comp_1 = competitors_list[0] if len(competitors_list) > 0 else "соседним клиникам"
            comp_2 = competitors_list[1] if len(competitors_list) > 1 else "конкурентам"
            leads_min = max(5, int(client_leads * lost_percentage * 0.8))
            leads_max = max(10, int(client_leads * lost_percentage))
            lost_leads_display = f"{leads_min}–{leads_max}"

            template_payload = {
                "lpr_name": lpr_data.get("name") if (lpr_data and lpr_data.get("name")) else "коллеги",
                "title": title,
                "rating": round(float(data.get("rating", 4.5)), 1),
                "comp_1": comp_1,
                "comp_2": comp_2,
                "competitor_1": comp_1,
                "competitor_2": comp_2,
                "lost_leads": lost_leads_display,
                "lost_revenue": lost_revenue,
                "sender_name": sender_name
            }
            
            icebreaker_text = generate_icebreaker_text(template_payload)
            st.code(icebreaker_text, language="markdown")
            
            # --- ЛОГИКА АВТОМАТИЧЕСКОГО СОХРАНЕНИЯ С ЗАЩИТОЙ ОТ ДУБЛЕЙ ---
            # Создаем уникальный ключ для текущей компании
            upload_flag_key = f"uploaded_{title}"
            links_key = f"links_{title}"

            if upload_flag_key not in st.session_state:
                st.session_state[upload_flag_key] = False

            # Если для этой компании файлы еще не загружены - загружаем
            if not st.session_state[upload_flag_key]:
                with st.spinner("☁️ Автоматическое сохранение файлов на Google Диск..."):
                    try:
                        creds = get_google_credentials()
                        if not DriveManager:
                            st.warning("Файл drive_manager.py не обнаружен. Сохранение на Диск пропущено.")
                        else:
                            dm = DriveManager(creds)
                            
                            safe_name = title.replace(" ", "_").replace('"', '').replace("'", "")
                            
                            pdf_url = dm.upload_file(f"{safe_name}_Аудит_PIN100.pdf", pdf_bytes, "application/pdf", dm.pdf_root_id)
                            json_url = dm.upload_file(f"{safe_name}.json", json.dumps(data, ensure_ascii=False, indent=2), "application/json", dm.json_root_id)
                            txt_url = dm.upload_file(f"{safe_name}_Icebreaker.txt", icebreaker_text, "text/plain", dm.letters_root_id)
                            
                            if pdf_url or txt_url:
                                links_display = []
                                if pdf_url: links_display.append(f"🔗 [Открыть PDF на Диске]({pdf_url})")
                                if txt_url: links_display.append(f"🔗 [Текст письма на Диске]({txt_url})")
                                if json_url: links_display.append(f"🔗 [JSON архив]({json_url})")
                                
                                # Сохраняем ссылки в память сессии и ставим флаг успешной загрузки
                                st.session_state[links_key] = links_display
                                st.session_state[upload_flag_key] = True
                    except Exception as e:
                        st.error(f"Ошибка сохранения на Google Диск: {e}")

            # Отображаем успешный статус и ссылки (выводится всегда, если загрузка уже произошла)
            if st.session_state.get(upload_flag_key):
                st.success("✅ Сделка автоматически зафиксирована в облаке!")
                st.markdown(" | ".join(st.session_state.get(links_key, [])))
