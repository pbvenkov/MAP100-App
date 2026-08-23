import streamlit as st
import requests
import os
import time
import json
import re
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import tempfile
import typst

# ==========================================
# 0. НАСТРОЙКИ БРЕНДИНГА PIN100
# ==========================================
PROJECT_NAME = "PIN100"
EXPERT_TITLE = "Генератор B2B Воронки (Аналитический Отчет)"

# ==========================================
# 1. СЕКРЕТЫ И ИНИЦИАЛИЗАЦИЯ ИИ
# ==========================================
APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 
VK_API_TOKEN = st.secrets.get("VK_API_TOKEN", "")

try:
    genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))
    generation_config = {"temperature": 0.0, "top_p": 0.1, "top_k": 1}
    expert_engine = genai.GenerativeModel('gemini-3.5-flash-lite', generation_config=generation_config) 
except Exception as e:
    expert_engine = None

def send_telegram_alert(error_msg, target_url="Неизвестно"):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    if tg_token and tg_admin_id:
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        text = f"🚨 *{PROJECT_NAME}: Сбой системы*\n\n*Цель:* {target_url}\n*Ошибка:* {error_msg}\n\n🛑 *Действие:* Остановлено."
        try: 
            requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except Exception: 
            pass

def send_telegram_business_alert(title, category, unique_keys):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    if not (tg_token and tg_admin_id): return

    ai_reasoning = ""
    if expert_engine:
        try:
            prompt = f"Кратко (в 2-3 предложениях) оцени нишу '{category}' (на примере '{title}'). Почему продажа B2B-консалтинга за 85 000 руб. может быть интересна этой нише? Оцени примерный LTV и средний чек клиента в этом бизнесе."
            response = expert_engine.generate_content(prompt)
            ai_reasoning = response.text.strip()
        except:
            ai_reasoning = "Потенциально высокий LTV. Требует ручной бизнес-оценки."

    tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    text = (
        f"🚨 *Обнаружена новая ниша, которой еще нет в нашей программе!*\n\n"
        f"🏢 *Компания:* {title}\n"
        f"🏷 *Категория:* {category}\n"
        f"🔑 *Скрытые ключи Яндекса:* {', '.join(unique_keys)}\n\n"
        f"💡 *Почему это может быть нам интересно:*\n_{ai_reasoning}_\n\n"
        f"❓ *Действие:* Передайте эти ключи разработчику для добавления в NICHE_MAPPING."
    )
    try: 
        requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
    except Exception: 
        pass

# ==========================================
# 2. БАЗЫ ДАННЫХ И GOOGLE SHEETS
# ==========================================
NICHE_ECONOMICS = {
    "DENTISTRY": {"leads": 70, "check": 25000, "label": "Стоматология", "ltv_months": 12},
    "HORECA": {"leads": 150, "check": 2000, "label": "HORECA", "ltv_months": 12},
    "B2B": {"leads": 40, "check": 30000, "label": "Легкий B2B / Опт", "ltv_months": 12},
    "B2B_HEAVY": {"leads": 10, "check": 500000, "label": "Сложный B2B / Производство", "ltv_months": 1},
    "RETAIL": {"leads": 200, "check": 1500, "label": "Ритейл", "ltv_months": 12},
    "AUTO": {"leads": 100, "check": 12000, "label": "Авто", "ltv_months": 6},
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
        st.error(f"Ошибка чтения Google Sheets: {e}")
        return [], []

def save_audit_to_sheets(url, title, niche, total_score, results_data, lpr_data=None):
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Results")
        headers = ws.row_values(1)
        row_dict = {
            "Дата": datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S"),
            "Ссылка": url, "Компания": title, "Ниша": niche,
            "Общий балл": str(round(total_score, 1)).replace('.', ',')
        }
        if lpr_data and lpr_data.get("name"):
            row_dict.update({"ФИО ЛПР": lpr_data.get("name", ""), "Должность": lpr_data.get("role", ""), "Личный контакт": lpr_data.get("link", ""), "Прямой Email": lpr_data.get("email", "")})
        for r in results_data:
            if r.get("Код"): row_dict[r.get("Код")] = str(round(r.get("Earned", 0), 1)).replace('.', ',')
        ws.append_row([row_dict.get(h, "") for h in headers])
    except Exception: pass 

# ==========================================
# 3. ПАРСЕРЫ И СБОР ДАННЫХ
# ==========================================
def fetch_apify_data(yandex_url):
    if "/-/" in yandex_url:
        try: yandex_url = requests.get(yandex_url, allow_redirects=True, timeout=10).url
        except Exception as e: raise Exception(f"Не удалось расшифровать ссылку: {e}")
    run_req = requests.post(f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}", json={"startUrls": [{"url": yandex_url}], "maxItems": 1, "enrichBusinessData": True, "maxPhotos": 150, "maxPosts": 50}).json()
    if 'error' in run_req: raise Exception(f"Ошибка Apify API: {run_req['error']}")
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: raise Exception("Таймаут парсера.")
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1
    if status != "SUCCEEDED": raise Exception(f"Парсер упал со статусом {status}.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset or not dataset[0].get('title'): raise Exception("Пустой результат.")
    return dataset[0]

def enrich_lpr_contacts_from_vk(social_links):
    if not VK_API_TOKEN or not social_links: return {}
    vk_url = next((link.get('url', '') for link in social_links if 'vk.com' in link.get('url', '') or 'vk.ru' in link.get('url', '')), None)
    if not vk_url: return {}
    try:
        res = requests.get("https://api.vk.com/method/groups.getById", params={"group_id": vk_url.rstrip('/').split('/')[-1], "fields": "contacts", "access_token": VK_API_TOKEN, "v": "5.199"}, timeout=5).json()
        if 'response' in res and res['response']:
            contacts = res['response'][0].get('contacts', [])
            if not contacts: return {"status": "hidden", "vk_url": vk_url}
            contact = contacts[0] 
            lpr_data = {"name": "", "role": contact.get('desc', 'Администратор'), "link": "", "email": contact.get('email', ''), "status": "found"}
            if 'user_id' in contact:
                lpr_data["link"] = f"https://vk.com/id{contact['user_id']}"
                u_res = requests.get("https://api.vk.com/method/users.get", params={"user_ids": contact['user_id'], "access_token": VK_API_TOKEN, "v": "5.199"}).json()
                if 'response' in u_res and u_res['response']: lpr_data["name"] = f"{u_res['response'][0].get('first_name', '')} {u_res['response'][0].get('last_name', '')}".strip()
            return lpr_data
    except Exception: pass
    return {}

# ==========================================
# 4. АЛГОРИТМЫ И ИИ
# ==========================================
def parse_yandex_date(date_val):
    if not date_val: return None
    try:
        if isinstance(date_val, (int, float)) or (isinstance(date_val, str) and str(date_val).isdigit()): return datetime.fromtimestamp(int(date_val)/1000, tz=timezone.utc)
        return datetime.fromisoformat(str(date_val).replace('Z', '+00:00'))
    except: return None

def determine_niche_by_expert(title, category, prompts_data):
    if not expert_engine: return "OTHER"
    prompt = next((p.get("Промпт для ИИ") for p in prompts_data if p.get("Код") == "NICHE_PROMPT"), "").replace("{title}", title).replace("{category}", category)
    try:
        key = expert_engine.generate_content(prompt).text.strip().upper()
        for v in ["B2B_HEAVY", "BEAUTY_MEDICAL", "DENTISTRY", "HORECA", "B2B", "RETAIL", "AUTO", "EDUCATION", "SERVICES", "OTHER"]:
            if v in key: return v
    except: pass
    return "OTHER"

def rewrite_errors_by_ai(niche_label, company_name, failed_rules, expert_engine):
    if not expert_engine or not failed_rules: return failed_rules
    payload_text = "".join([f"ID: {r['Код']} | Ошибка: {r['Критерий']} | Текст: {r['Обоснование']}\n" for r in failed_rules])
    prompt = f"""Ты — премиальный B2B-маркетолог. Ниша: {niche_label}. Компания: {company_name}.
Перепиши обоснование каждой ошибки под боли этой ниши. Используй точную терминологию (например, "родители", "пациенты", "ученики" вместо "клиентов"). Текст должен быть емким, деловым, без воды, показывающим упущенную прибыль.
Ошибки:
{payload_text}
Верни строго JSON: {{"Код_ошибки": "Переписанный текст"}}"""
    try:
        match = re.search(r'\{.*\}', expert_engine.generate_content(prompt).text, re.DOTALL)
        if match:
            new_texts = json.loads(match.group(0))
            for r in failed_rules:
                if r['Код'] in new_texts and str(new_texts[r['Код']]).strip(): r['Обоснование'] = new_texts[r['Код']]
    except Exception: pass
    return failed_rules

def calculate_hard_facts(data, niche_key="OTHER"):
    scores = {}
    now = datetime.now(timezone.utc)
    title, desc, url = str(data.get('title') or ''), str(data.get('description') or ''), str(data.get('url') or data.get('website') or '').lower()
    cat_list = data.get('categories', [''])
    cat_name = cat_list[0].get('name', cat_list[0]) if isinstance(cat_list[0], dict) else str(cat_list[0])
    
    if data.get('isVerifiedOwner') or len(title) > 2: scores['PROF-01.1'] = True
    if data.get('categories'): scores['PROF-03.1'] = True
    if url: scores['PROF-04.1'] = True
    phones = data.get('phones') or []
    if phones: 
        scores['PROF-05.1'] = True
        if any(str(p).startswith('+7') or str(p).startswith('8') for p in phones): scores['PROF-05.2'] = True
    schedule = data.get('schedule') or data.get('workingHours') or []
    if (isinstance(schedule, list) and len(schedule) >= 7) or (isinstance(schedule, dict) and len(schedule.keys()) >= 7): scores['PROF-07.1'] = True
    
    features = data.get('features', {})
    if isinstance(features, dict) and len(features.keys()) > 0: scores['PROF-08.1'] = True
    elif isinstance(features, list) and len(features) > 0: scores['PROF-08.1'] = True

    NICHE_MAPPING = {"DENTISTRY": ["dentist_services", "uni_medic_specialization"], "AUTOSERVICES": ["car_wash_services", "auto_repair_features"], "HORECA": ["restaurant_services", "cuisine_type"], "EDUCATION": ["school_direction", "specialized_schools", "classes for children"]}
    if isinstance(features, dict):
        if any(features.get(key) for key in NICHE_MAPPING.get(niche_key, [])): scores['PROF-08.2'] = True
        if niche_key in ["OTHER", "SERVICES"]:
            client_unique_keys = [k for k in features.keys() if k not in {'payment_method', 'wi_fi', 'toilet', 'parking', 'street_entrance', 'parking_disabled', 'promotions', 'wheelchair_access'}]
            if len(client_unique_keys) >= 2: send_telegram_business_alert(title, cat_name, client_unique_keys[:5])
    
    if len(desc) > 1500: scores['PROF-09.1'] = True
    if data.get('isVerifiedOwner'): scores['PROF-12.1'] = True
    
    owner_links = url + " " + desc + " " + " ".join([str(l) for l in (data.get('socialLinks') or data.get('links') or [])])
    if any(s in owner_links.lower() for s in ["t.me", "wa.me", "whatsapp", "viber"]): scores['PROF-13.1'] = True
    if any(s in owner_links.lower() for s in ["vk.com", "vk.ru", "youtube", "dzen", "instagram", "inst:"]): scores['PROF-13.2'] = True
    
    valid_prods = [p for p in (data.get('menu', {}).get('items', []) if isinstance(data.get('menu'), dict) else []) + (data.get('productCatalog') or []) if isinstance(p, dict)]
    if valid_prods:
        if len(valid_prods) >= 10: scores['PROF-11.1'] = True
        if sum(1 for p in valid_prods if p.get('photoUrl') or p.get('photo')) / len(valid_prods) >= 0.8: scores['PROF-11.2'] = True
        if sum(1 for p in valid_prods if any(char.isdigit() for char in str(p.get('price') or ''))) / len(valid_prods) >= 0.8: scores['PROF-11.3'] = True
        if sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 50) / len(valid_prods) >= 0.8: scores['PROF-11.4'] = True
        if len(set([p.get('category') for p in valid_prods if p.get('category')])) >= 2: scores['PROF-11.5'] = True
        
    if len(str(data.get('address') or '')) > 5: scores['SEO-18.1'] = True
    if data.get('videoCount', 0) > 0 or data.get('videos') or data.get('mobileVideos'): scores['CONT-42.1'] = True
    
    # Фотографии и проверка тегов интерьера
    photos = data.get('photos', [])
    photo_count = int(data.get('photoCount') or len(photos) or 0)
    if photo_count >= 15: scores['CONT-36.1'] = True
    if photo_count >= 30: scores['CONT-36.2'] = True
    
    tags = [tag.get('id', '') for p in photos for tag in p.get('tags', []) if isinstance(tag, dict)]
    if "Interior" in tags or any(p.get('tag') == 'interior' for p in photos):
        scores['CONT-38.1'] = True
    if photo_count >= 30:
        scores['CONT-37.2'] = True
        scores['CONT-37.3'] = True
    
    posts = data.get('mobilePosts') or data.get('posts') or []
    if posts: scores['CONV-51.1'] = True
    for p in posts:
        pd_date = parse_yandex_date(p.get('publicationTime') or p.get('date'))
        if pd_date and (now - pd_date).days <= 30:
            scores['ACT-68.1'] = True
            break
            
    rating = float(data.get('rating') or 0.0)
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    if int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount') or 0) >= 50: scores['REP-28.1'] = True
    
    all_reviews = [r for r in (data.get('reviews') or []) if isinstance(r, dict)]
    if not all_reviews: scores['META_NO_RECENT_REVIEWS'] = True
    else:
        replied = sum(1 for r in all_reviews[:20] if str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip())
        if parse_yandex_date(all_reviews[0].get('date')) and (now - parse_yandex_date(all_reviews[0].get('date'))).days <= 14: scores['REP-29.1'] = True
        if len(all_reviews[:20]) > 0:
            if replied / len(all_reviews[:20]) >= 0.7: scores['REP-30.1'] = True
            if sum(1 for r in all_reviews[:20] if r.get('photos') or r.get('photoDetails')) / len(all_reviews[:20]) >= 0.05: scores['REP-35.1'] = True
        if any(float(r.get('rating') or 0.0) >= 4.0 and str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() for r in all_reviews[:20]): scores['REP-30.3'] = True
        scores['REP-32.2'] = True  # Без агрессии по умолчанию
        for r in all_reviews[:20]:
            bc_date, rev_date = parse_yandex_date(r.get('businessCommentDate')), parse_yandex_date(r.get('date'))
            if str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() and bc_date and rev_date and (bc_date - rev_date).days <= 3: 
                scores['REP-30.2'] = True
                break
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    if not expert_engine or not prompts_data: return {}
    title, desc = str(data.get('title') or ''), str(data.get('description') or '')[:1000]
    recent_reviews = [r for r in data.get('reviews', []) if isinstance(r, dict)][:10]
    reviews_text = "".join([f"Отзыв: {r.get('text', '')}\nОтвет: {r.get('businessComment') or r.get('reply', {}).get('text') if isinstance(r.get('reply'), dict) else ''}\n" for r in recent_reviews])
    prods = [p for p in (data.get('menu', {}).get('items', []) if isinstance(data.get('menu'), dict) else []) + (data.get('productCatalog') or []) if isinstance(p, dict)][:20]
    prods_text = ", ".join([str(p.get('name')) for p in prods])
    rules_list = [f'"{p.get("Код", "").strip()}": {p.get("Промпт для ИИ", "").strip()}' for p in prompts_data if p.get('Код', '').strip() and p.get('Код') != 'NICHE_PROMPT']
    
    if not rules_list: return {}
    prompt = f"Контекст:\nНазвание: {title}\nОписание: {desc}\nТовары/Услуги: {prods_text}\nОтзывы:\n{reviews_text[:2000]}\nКритерии:\n{chr(10).join(rules_list)}\nВерни JSON {{CODE: true/false}}."
    try:
        match = re.search(r'\{.*\}', expert_engine.generate_content(prompt).text, re.DOTALL)
        if match: return {k: True for k, v in json.loads(match.group(0)).items() if str(v).lower() in ["1", "true"]}
    except: pass
    return {}

# ==========================================
# 5. ТИПОГРАФИКА И PDF (ПРЕМИУМ BIG4 ВЕРСТКА)
# ==========================================
def clean_typography(text):
    if not text: return ""
    t = str(text).replace(" - ", " — ")
    t = t.replace(">=", "≥").replace("<=", "≤")
    t = t.replace(">", ">").replace("<", "<")
    for c in ['\\', '[', ']', '{', '}', '$', '*', '_', '#', '@', '"', "'", '`', '✓', '✔', '×', '✖']:
        t = t.replace(c, ' ')
    return " ".join(t.split())

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, client_ltv, competitors_text=""):
    current_date = datetime.now().strftime("%d.%m.%Y")
    score_color = "166534" if score >= 80 else ("8B7355" if score >= 50 else "9F1239")
    dev = round(100 - score, 1)
    lost_leads = int(client_leads * (dev / 100))
    
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    cc_fmt = f"{client_check:,}".replace(',', ' ')
    ltv_loss_fmt = f"{revenue_loss * client_ltv:,}".replace(',', ' ')
    
    title_safe = clean_typography(title)
    comp_safe = clean_typography(competitors_text)
    
    if niche == "Образование":
        package_name = "Интеграция Education PRO"
        package_price = "85 000 ₽"
        package_roi = f"1-2 закрытых договора (при чеке {cc_fmt} ₽)"
    elif niche in ["Стоматология", "Медицина / Бьюти"]:
        package_name = "Интеграция Medical PRO"
        package_price = "85 000 ₽"
        package_roi = f"1-2 первичных пациента (при чеке {cc_fmt} ₽)"
    elif niche in ["Сложный B2B / Производство", "Легкий B2B / Опт"]:
        package_name = "Интеграция B2B Enterprise"
        package_price = "85 000 ₽"
        package_roi = f"1 закрытая сделка (при чеке {cc_fmt} ₽)"
    else:
        package_name = "Комплексная Бизнес-Упаковка"
        package_price = "35 000 ₽"
        package_roi = f"3-5 новых клиентов (при чеке {cc_fmt} ₽)"

    typ_source = f"""
#set document(title: "Аналитический Отчет - {title_safe}", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 25mm),
  footer: [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Строго конфиденциально
    #h(1fr)
    Стр. #context counter(page).display()
  ]
)

#set text(font: ("Inter", "Arial", "sans-serif"), size: 10.5pt, fill: rgb("334155"), lang: "ru")
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// --- ОБЛОЖКА ---
#v(100pt)
#text(12pt, fill: rgb("8B7355"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(10pt)
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Аналитический Отчет:#linebreak()Оцифровка упущенной выручки]
#v(10pt)
#line(length: 60mm, stroke: 1.5pt + rgb("8B7355"))
#v(30pt)
#text(11pt, fill: rgb("475569"))[
  Подготовлено для: #strong[{title_safe}] #linebreak()
  Ниша: #strong[{clean_typography(niche)}] #linebreak()
  Дата расчета: #strong[{current_date}]
]
#pagebreak()

// --- РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ (СРАЗУ НА СТР. 2) ---
#heading(level: 2)[Executive Summary (Резюме для руководителя)]
#v(15pt)
#grid(
  columns: (1fr, 1fr),
  gutter: 20pt,
  rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 18pt)[
    #text(9pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ИНДЕКС ГОТОВНОСТИ ПРОФИЛЯ]
    #linebreak()
    #v(8pt)
    #text(26pt, weight: "bold", fill: rgb("{score_color}"))[{round(score, 1)} / 100]
    #v(4pt)
    #text(8.5pt, fill: rgb("94A3B8"), style: "italic")[Оценка по 79 параметрам алгоритмов]
  ],
  rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 18pt)[
    #text(9pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[УПУЩЕННАЯ ВЫРУЧКА]
    #linebreak()
    #v(8pt)
    #text(24pt, weight: "bold", fill: rgb("9F1239"))[- {rev_loss_fmt} ₽/мес]
  ]
)
#v(15pt)

#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 15pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Критический вывод аналитики:]
  #v(8pt)
  #set par(leading: 0.6em)
  #text(10.5pt, fill: rgb("334155"))[Прямо сейчас ваша компания фактически невидима для *{dev}% целевых клиентов* в поисковой выдаче Яндекс Карт. Из-за алгоритмических ошибок вы ежемесячно уступаете конкурентам около *{lost_leads} горячих сделок*. Попытки заливать рекламный бюджет в текущий профиль приведут к прямому финансовому убытку.]
]

#v(12pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 4pt, inset: 10pt)[
  #text(8.5pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Оценка #strong[{round(score, 1)} / 100] отражает исключительно техническую видимость профиля для поисковых роботов Яндекса и конверсионную готовность витрины, а не реальное высокое качество образовательного процесса вашей компании.
  ]
]

#pagebreak()
// --- 3 ГЛАВНЫЕ ТОЧКИ СЛИВА ---
#heading(level: 2)[Три главные пробоины в воронке продаж]
#v(10pt)
#text(10.5pt, fill: rgb("475569"))[Мы не будем утомлять вас техническими терминами. Вот три главных бизнес-смысла, из-за которых компания теряет деньги прямо сегодня:]
#v(15pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 16pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. «Слепая витрина» и потеря поискового трафика]
  #v(8pt)
  #set par(leading: 0.6em)
  #text(10pt, fill: rgb("475569"))[Алгоритмы Яндекса не видят ваши высокомаржинальные услуги. Из-за отсутствия правильной LSI-разметки, продающих SEO-текстов и технических фидов, вы просто не показываетесь клиентам, которые ищут конкретные дорогие программы или услуги. Этот самый горячий трафик забирают конкуренты{comp_safe} с правильно настроенными каталогами.]
]
#v(12pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 16pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. Барьер первого контакта (Обрыв конверсии)]
  #v(8pt)
  #set par(leading: 0.6em)
  #text(10pt, fill: rgb("475569"))[Ваша карточка заставляет клиента совершать лишние усилия. Сегодня отсутствие виджетов прямой онлайн-записи и ярких кнопок действия (СТА) приводит к тому, что клиенты закрывают ваш профиль. Вы безвозвратно теряете огромный пласт «вечернего» трафика и аудиторию, которая не любит звонить.]
]
#v(12pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 16pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. Скрытые репутационные угрозы]
  #v(8pt)
  #set par(leading: 0.6em)
  #text(10pt, fill: rgb("475569"))[Даже один оставленный без грамотного ответа негативный отзыв работает как токсичный якорь. Для новых клиентов, готовых оставить у вас крупную сумму, отсутствие эмпатичного ответа руководства на проблему равносильно признанию вины. Это рушит конверсию на самом финальном этапе принятия решения.]
]

#pagebreak()
// --- ROADMAP, ЭКОНОМИКА И 3-УРОВНЕВЫЙ ТАРИФ ---
#heading(level: 2)[Инвестиционное предложение и Окупаемость]
#v(8pt)
#text(10pt, fill: rgb("475569"))[Мы предлагаем вам не покупку «маркетинговых услуг», а остановку вашего кассового разрыва. Вот объем работ, который мы реализуем под ключ:]
#v(12pt)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 10pt,
  rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
    #text(9pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 1]
    #v(3pt)
    #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[SEO-перепрошивка]
    #v(3pt)
    #set par(leading: 0.5em)
    #text(8.5pt, fill: rgb("475569"))[Интеграция всех ваших услуг в поисковые алгоритмы Яндекса для захвата органики.]
  ],
  rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
    #text(9pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 2]
    #v(3pt)
    #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Снятие барьеров]
    #v(3pt)
    #set par(leading: 0.5em)
    #text(8.5pt, fill: rgb("475569"))[Внедрение систем онлайн-бронирования и триггеров для захвата лидов 24/7.]
  ],
  rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
    #text(9pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 3]
    #v(3pt)
    #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Защита бренда]
    #v(3pt)
    #set par(leading: 0.5em)
    #text(8.5pt, fill: rgb("475569"))[Антикризисная зачистка негатива и формирование образа надежного партнера.]
  ]
)

#v(10pt)
#text(11pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Тарифная сетка внедрения:]
#v(6pt)
#grid(
  columns: (1fr, 1.15fr, 1fr),
  gutter: 8pt,
  rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
    #text(8.5pt, weight: "bold", fill: rgb("64748B"))[БАЗОВЫЙ (Quick Fix)]
    #v(3pt)
    #text(12pt, weight: "bold", fill: rgb("0A1128"))[35 000 ₽]
    #v(3pt)
    #set par(leading: 0.5em)
    #text(8pt, fill: rgb("475569"))[Базовое SEO, устранение ошибок витрины, чистка дублей.]
  ],
  rect(fill: rgb("F8FAFC"), stroke: 1.5pt + rgb("8B7355"), radius: 4pt, inset: 10pt)[
    #text(8.5pt, weight: "bold", fill: rgb("8B7355"))[★ {package_name}]
    #v(3pt)
    #text(13pt, weight: "bold", fill: rgb("8B7355"))[{package_price}]
    #v(3pt)
    #set par(leading: 0.5em)
    #text(8pt, fill: rgb("0A1128"), weight: "bold")[Комплекс под ключ: SEO + UX-конверсия + Защита бренда + XML-фиды.]
  ],
  rect(fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
    #text(8.5pt, weight: "bold", fill: rgb("64748B"))[ENTERPRISE (ГОД)]
    #v(3pt)
    #text(12pt, weight: "bold", fill: rgb("0A1128"))[150 000 ₽]
    #v(3pt)
    #set par(leading: 0.5em)
    #text(8pt, fill: rgb("475569"))[Полное сопровождение воронки на 6 месяцев + реклама.]
  ]
)

#v(8pt)
#rect(width: 100%, fill: rgb("F0FDF4"), stroke: 0.5pt + rgb("BBF7D0"), radius: 4pt, inset: 8pt)[
  #set par(leading: 0.55em)
  #text(8.5pt, fill: rgb("166534"))[
    *💡 Вечный органический трафик:* Пакет настраивается разово, после чего карточка стабильно собирает бесплатные целевые обращения годами — без постоянных затрат на клики в платной рекламе.
  ]
]

#v(8pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 10pt)[
  #grid(
    columns: (1fr, auto),
    gutter: 10pt,
    [
      #text(9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Забронировать 20-минутный стратегический Zoom-разбор] #linebreak()
      #v(2pt)
      #set par(leading: 0.5em)
      #text(8pt, fill: rgb("CBD5E1"))[Покажем экран вашего профиля в закрытой аналитике Яндекса и передадим пошаговый план устранения ТОП-5 ошибок.]
    ],
    [
      #align(center + horizon)[
        #text(9.5pt, weight: "bold", fill: rgb("8B7355"))[Telegram:\ @paulvenkov]
      ]
    ]
  )
]
"""

    # --- ТЕХНИЧЕСКОЕ ПРИЛОЖЕНИЕ ---
    typ_source += """
#pagebreak()
#heading(level: 2)[Техническое приложение (Детализация аудита)]
#v(8pt)
#text(9.5pt, fill: rgb("64748B"))[Материал ниже предназначен для технических специалистов, маркетологов и службы контроля качества. Здесь представлена развернутая диагностика вашей карточки по 79 скрытым алгоритмическим параметрам Яндекса.]
#v(15pt)
"""
    blocks = [
        {"title": "Блок 1. Видимость и Охваты (SEO)", "groups": ['SEO и Трафик', 'Активность']},
        {"title": "Блок 2. Упаковка и Конверсия (UX)", "groups": ['Конверсия', 'Базовое заполнение', 'Контент и Визуал']},
        {"title": "Блок 3. Репутационный капитал", "groups": ['Репутация']},
        {"title": "Блок 4. Нейросети и Скрытые данные", "groups": ['Технологии и ИИ']}
    ]

    for block in blocks:
        block_items = [r for r in results_data if r['Группа'] in block['groups']]
        if not block_items: continue
        earned_score = sum(r.get('Earned', 0.0) for r in block_items)
        max_score = sum(r.get('Max', 0.0) for r in block_items)
        percentage = (earned_score / max_score * 100) if max_score > 0 else 100
        bar_color = "166534" if percentage >= 80 else ("8B7355" if percentage >= 50 else "9F1239")
        
        passed_items = [clean_typography(r['Критерий']) for r in block_items if r['Результат'] == 'ДА']
        passed_text = ", ".join(passed_items) if passed_items else "Нет данных"

        failed_items_block = [r for r in block_items if r['Результат'] == 'НЕТ']
        failed_cards = ""
        if failed_items_block:
            for f in failed_items_block:
                c_name = clean_typography(f.get('Критерий', ''))
                c_reason = clean_typography(f.get('Обоснование', ''))
                failed_cards += f"""
#v(4pt)
#block(breakable: false)[
  #rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 3pt, inset: 7pt)[
    #text(9pt, weight: "bold", fill: rgb("9F1239"))[× {c_name}] #linebreak()
    #v(2pt)
    #set par(leading: 0.55em)
    #text(8.5pt, fill: rgb("475569"))[{c_reason}]
  ]
]
"""
        else:
            failed_cards = """
#v(4pt)
#text(9pt, fill: rgb("166534"))[Уязвимостей не обнаружено. Отличный результат.]
"""

        typ_source += f"""
#v(12pt)
#heading(level: 3)[{block['title']} (#text(fill: rgb("{bar_color}"))[{round(earned_score, 1)} / {round(max_score, 1)}])]
#v(4pt)
#rect(width: 100%, fill: rgb("F0FDF4"), stroke: 0.5pt + rgb("BBF7D0"), radius: 3pt, inset: 7pt)[
  #text(8pt, weight: "bold", fill: rgb("166534"), tracking: 0.5pt)[В НОРМЕ:] #linebreak()
  #v(2pt)
  #set par(leading: 0.55em)
  #text(8.5pt, fill: rgb("475569"))[{passed_text}]
]
#v(4pt)
#text(8pt, weight: "bold", fill: rgb("9F1239"), tracking: 0.5pt)[ЗОНЫ УЯЗВИМОСТИ (ОШИБКИ):]
{failed_cards}
"""
    
    # --- FINAL CTA PAGE С ДИСКЛЕЙМЕРОМ В СНОСКЕ ---
    typ_source += """
#pagebreak()
#v(30pt)
#heading(level: 2)[Следующие шаги и Стратегический разбор]
#v(12pt)
#line(length: 40mm, stroke: 1.5pt + rgb("8B7355"))
#v(15pt)
#set par(leading: 0.7em)
#text(10.5pt, fill: rgb("475569"))[
  Надеемся, этот отчет помог вам взглянуть на цифровой маркетинг вашей компании под новым углом. Наша цель — не просто указать на ошибки, а помочь вам выстроить надежный фундамент, который будет приносить качественные лиды годами.

  Если вы готовы остановить кассовый разрыв и вернуть упущенный трафик, давайте обсудим результаты этого отчета в удобном для вас формате.
]
#v(25pt)

#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("0A1128"), radius: 4pt, inset: 18pt)[
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Бесплатный следующий шаг:]
  #v(6pt)
  #set par(leading: 0.6em)
  #text(10pt, fill: rgb("334155"))[
    *Забронировать 20-минутный стратегический Zoom-разбор:* покажем экран вашего профиля в закрытой аналитике Яндекса и передадим пошаговый план исправления ТОП-5 критических ошибок без давления и лишних обязательств.
  ]
  #v(12pt)
  #line(length: 100%, stroke: 0.5pt + rgb("CBD5E1"))
  #v(8pt)
  #grid(columns: (80pt, 1fr), gutter: 10pt,
    text(10.5pt, fill: rgb("64748B"))[Telegram:], text(10.5pt, weight: "bold", fill: rgb("0A1128"))[\@paulvenkov],
    text(10.5pt, fill: rgb("64748B"))[Сайт:], text(10.5pt, weight: "bold", fill: rgb("0A1128"))[pin100.ru]
  )
]

#v(30pt)
#heading(level: 3)[Ограничение ответственности и методология]
#v(6pt)
#set par(leading: 0.55em)
#text(8pt, fill: rgb("94A3B8"))[
  Настоящий аналитический отчет подготовлен центром PIN100 Analytics исключительно в информационных целях для руководства компании. Выводы базируются на алгоритмическом сборе открытых данных из геосервисов на дату формирования документа. Данные об упущенной выручке являются расчетными (Predictive Analytics) и опираются на отраслевые бенчмарки ниши. Отчет отражает алгоритмические уязвимости профиля и их прямое влияние на потерю органического поискового трафика.
]
"""

    with tempfile.NamedTemporaryFile(suffix=".typ", delete=False, mode="w", encoding="utf-8") as tf:
        tf.write(typ_source)
        typ_path = tf.name
        
    try:
        pdf_bytes = typst.compile(typ_path)
    except Exception as e:
        st.error(f"Ошибка компиляции Typst: {e}")
        with st.expander("🛠 Исходный код Typst (Отладка)"):
            st.code(typ_source, language="typst")
        pdf_bytes = b""
    finally:
        if os.path.exists(typ_path): os.remove(typ_path)
        
    return pdf_bytes

# ==========================================
# 6. СБОРКА И ИНТЕРФЕЙС (STREAMLIT)
# ==========================================
st.set_page_config(page_title=f"{PROJECT_NAME} | Аналитический Отчет", layout="wide", page_icon="📍")

rules_data, prompts_data = fetch_cached_database()

with st.sidebar: 
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База данных подключена (Кэш активен).")

st.title(f"📍 {PROJECT_NAME}: {EXPERT_TITLE}")
url = st.text_input("Ссылка на карточку Яндекс.Бизнес")

if st.button("🚀 Сгенерировать Аналитический Отчет", type="primary"):
    if "yandex" not in url.lower(): 
        st.error("❌ Неверная ссылка.")
    else:
        with st.spinner("Сбор свежих фактических данных..."):
            try: 
                data = fetch_apify_data(url)
            except Exception as e:
                send_telegram_alert(str(e), url)
                st.error(f"⚠️ Ошибка парсинга: {str(e)}")
                st.stop()
                
            title = data.get('title', 'Без названия')
            c_list = data.get('categories', [])
            cat = c_list[0].get('name', '') if c_list and isinstance(c_list[0], dict) else (str(c_list[0]) if c_list else '')
            client_reviews = int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []) or 0)
            
            social_links = data.get('socialLinks') or data.get('links') or []
            lpr_data = enrich_lpr_contacts_from_vk(social_links)
            
            related_places = data.get('relatedPlaces', [])
            competitors_list = [str(c.get('name')) for c in related_places if c.get('name')][:2]
            competitors_text = f" (например, {', '.join(competitors_list)})" if competitors_list else ""
            
        with st.spinner("Бизнес-оценка и расчет юнит-экономики..."):
            try: 
                niche_key = determine_niche_by_expert(title, cat, prompts_data)
            except Exception as e:
                send_telegram_alert(str(e), url)
                niche_key = "OTHER"
            
            raw_scores = calculate_hard_facts(data, niche_key)
            exp_sc = calculate_dynamic_expert_rules(data, prompts_data)
            raw_scores.update(exp_sc)
            
            results = []
            final_total_score = 0.0
            target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                group = str(r.get('Группа метрик', 'Прочее')).strip()
                
                reason_success = str(r.get('Обоснование_УСПЕХА', '')).strip() or f"Отлично! Параметр «{name}» настроен верно и усиливает ваш профиль."
                
                niche_error_col = f"Обоснование_ОШИБКИ_{niche_key}"
                reason_error = str(r.get(niche_error_col, '')).strip()
                if not reason_error or reason_error.lower() == 'nan':
                    reason_error = str(r.get('Обоснование_ОШИБКИ', '')).strip()
                if not reason_error or reason_error.lower() == 'nan':
                    reason_error = f"Отсутствие параметра «{name}» пессимизирует карточку и лишает вас органического трафика."

                try: stage_val = int(r.get('Этап_Внедрения', 3))
                except: stage_val = 3
                
                try: max_s = float(str(r.get(target_column, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
                except: max_s = float(r.get('Балл', 0.0))
                
                if max_s > 0.0:
                    val = max_s if raw_scores.get(code) else 0.0
                    final_total_score += val
                    
                    if val > 0:
                        comm = "ДА"
                        final_reason = reason_success
                    else:
                        comm = "НЕТ"
                        final_reason = reason_error
                        
                        dynamic_rep_metrics = ['REP-29.1', 'REP-29.2', 'REP-30.1', 'REP-30.2', 'REP-30.3', 'REP-31.1', 'REP-31.2', 'REP-32.1', 'REP-32.2', 'REP-35.1', 'REP-84.1', 'REP-32.3']
                        if raw_scores.get('META_NO_RECENT_REVIEWS') and group == 'Репутация' and code in dynamic_rep_metrics:
                            final_reason = "За последние 6 месяцев нет ни одного свежего отзыва. Метрика обнулена, так как алгоритмам Яндекса нужны актуальные данные для ранжирования."
                        
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
            if failed_items:
                with st.spinner("ИИ адаптирует смыслы отчета под нишу клиента..."):
                    results = rewrite_errors_by_ai(niche_label, title, results, expert_engine)

            save_audit_to_sheets(url, title, niche_key, final_total_score, results, lpr_data)
            
            with st.sidebar:
                st.divider()
                st.markdown(f"### 🧮 Экономика: {niche_key}")
                client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
                client_check = st.number_input("Средний чек (₽)", value=eco["check"], step=5000)
                client_ltv = st.number_input("Цикл LTV (месяцев)", value=eco["ltv_months"], step=1)

            lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
            lost_revenue = int(client_leads * lost_percentage * client_check)
            
            st.divider()
            col1, col2 = st.columns([2, 1])
            with col1: 
                st.subheader(f"🏢 {title}")
                st.caption(f"🧠 Сегмент: **{niche_label}** | 📍 Фактических отзывов: {client_reviews}")
                
                if lpr_data and lpr_data.get('status') == 'found':
                    st.success(f"🕵️‍♂️ **Найден ЛПР:** {lpr_data.get('name')} ({lpr_data.get('role')})\n\n🔗 {lpr_data.get('link')}")
                elif lpr_data and lpr_data.get('status') == 'hidden':
                    st.warning("⚠️ **Группа ВК найдена, но блок «Контакты» скрыт настройками приватности.** Ищите ЛПР через сайт!")
                
            with col2: 
                delta = "Отличный результат" if final_total_score >= 80 else ("Требует оптимизации" if final_total_score >= 50 else "Критический уровень")
                st.metric(f"Индекс {PROJECT_NAME}", f"{round(final_total_score, 1)} / 100", delta=delta, delta_color="normal" if final_total_score>=80 else "inverse")

            st.error(f"Потери: **{lost_revenue:,} ₽** ежемесячно.".replace(',', ' '))
            
            with st.expander("🛠 Режим разработчика (Сырой JSON)"):
                json_string = json.dumps(data, ensure_ascii=False, indent=4)
                st.download_button(label="💾 Скачать сырой JSON", data=json_string, file_name=f"{title.replace(' ', '_')}.json", mime="application/json")

            st.divider()
            st.markdown("### 📥 Выгрузка отчетов")
            
            pdf_business_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, client_ltv, competitors_text)
            
            if pdf_business_bytes:
                st.download_button(
                    label="💎 Скачать Аналитический Отчет (PDF)", 
                    data=pdf_business_bytes, 
                    file_name=f"PIN100_Report_{title.replace(' ', '_')}.pdf", 
                    mime="application/pdf", 
                    type="primary",
                    use_container_width=True
                )

            st.markdown("---")
            st.markdown("### 🔎 Просмотр полного аудита")
            
            grouped_results = {}
            for r in results:
                g = r['Группа']
                if g not in grouped_results: grouped_results[g] = []
                grouped_results[g].append(r)
                
            for g_name, items in grouped_results.items():
                passed_count = sum(1 for x in items if x['Результат'] == 'ДА')
                total_count = len(items)
                earned_score = sum(r.get('Earned', 0.0) for r in items)
                max_score = sum(r.get('Max', 0.0) for r in items)
                
                with st.expander(f"📁 {g_name} ({passed_count} из {total_count} в норме) | {round(earned_score, 1)} / {round(max_score, 1)} баллов"):
                    for item in items:
                        if item['Результат'] == 'ДА':
                            st.success(f"**✅ {item['Критерий']}**\n\n{item['Обоснование']}")
                        else:
                            st.error(f"**❌ {item['Критерий']}**\n\n{item['Обоснование']}")
