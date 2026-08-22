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
    payload_text = "".join([f"ID: {r['Код']} | Ошибка: {r['Критерий']} | Стандартный текст: {r['Обоснование']}\n" for r in failed_rules])
    prompt = f"""Ты — премиальный B2B-маркетолог. Ниша клиента: {niche_label}. Компания: {company_name}.
Перепиши "Стандартный текст" каждой ошибки под боли этой ниши. Используй правильную терминологию (например, "пациенты", "ученики" вместо "клиентов"). Текст должен быть экспертным, строгим, без воды, показывать упущенную выгоду.
Ошибки:
{payload_text}
Верни строго JSON: {{"Код_ошибки": "Твой переписанный текст"}}"""
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
    photo_count = int(data.get('photoCount') or len(data.get('photos') or []) or 0)
    if photo_count >= 15: scores['CONT-36.1'] = True
    if photo_count >= 30: scores['CONT-36.2'] = True
    
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
    
    recent_reviews = [r for r in (data.get('reviews') or []) if isinstance(r, dict) and parse_yandex_date(r.get('date') or r.get('time')) and parse_yandex_date(r.get('date') or r.get('time')) >= now - timedelta(days=180)]
    if not recent_reviews: scores['META_NO_RECENT_REVIEWS'] = True
    else:
        replied = sum(1 for r in recent_reviews[:20] if str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip())
        if parse_yandex_date(recent_reviews[0].get('date')) and (now - parse_yandex_date(recent_reviews[0].get('date'))).days <= 14: scores['REP-29.1'] = True
        if len(recent_reviews[:20]) > 0:
            if replied / len(recent_reviews[:20]) >= 0.9: scores['REP-30.1'] = True
            if sum(1 for r in recent_reviews[:20] if r.get('photos') or r.get('photoDetails')) / len(recent_reviews[:20]) >= 0.1: scores['REP-35.1'] = True
        if any(float(r.get('rating') or 0.0) >= 4.0 and str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() for r in recent_reviews[:20]): scores['REP-30.3'] = True
        if not any(float(r.get('rating') or 0.0) <= 3.0 and not str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() for r in recent_reviews[:20]): scores['REP-32.1'] = True
        for r in recent_reviews[:20]:
            bc_date, rev_date = parse_yandex_date(r.get('businessCommentDate')), parse_yandex_date(r.get('date'))
            if str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip() and bc_date and rev_date and (bc_date - rev_date).days <= 3: 
                scores['REP-30.2'] = True
                break
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    if not expert_engine or not prompts_data: return {}
    title, desc = str(data.get('title') or ''), str(data.get('description') or '')[:1000]
    recent_reviews = [r for r in data.get('reviews', []) if parse_yandex_date(r.get('date')) and parse_yandex_date(r.get('date')) >= datetime.now(timezone.utc) - timedelta(days=180)][:10]
    reviews_text = "".join([f"Отзыв: {r.get('text', '')}\nОтвет: {r.get('businessComment') or r.get('reply', {}).get('text') if isinstance(r.get('reply'), dict) else ''}\n" for r in recent_reviews if isinstance(r, dict)])
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
# 5. ТИПОГРАФИКА И PDF (ПРЕМИУМ BIG4 СТИЛЬ)
# ==========================================
def clean_typography(text):
    if not text: return ""
    t = str(text).replace(" - ", " — ")
    for c in ['\\', '#', '$', '*', '_', '[', ']', '<', '>', '@', '"', "'", '`', '{', '}']:
        t = t.replace(c, ' ')
    return " ".join(t.split())

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, client_ltv, competitors_text=""):
    current_date = datetime.now().strftime("%d.%m.%Y")
    score_color = "166534" if score >= 80 else ("9A6A38" if score >= 50 else "9F1239")
    dev = round(100 - score, 1)
    lost_leads = int(client_leads * (dev / 100))
    
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    cc_fmt = f"{client_check:,}".replace(',', ' ')
    ltv_loss_fmt = f"{revenue_loss * client_ltv:,}".replace(',', ' ')
    
    title_safe = clean_typography(title)
    comp_safe = clean_typography(competitors_text)
    
    package_name = "Интеграция Medical/B2B PRO" if niche in ["Стоматология", "Медицина / Бьюти", "Сложный B2B / Производство", "Образование"] else "Комплексная Бизнес-Упаковка"
    package_price = "85 000 ₽" if niche in ["Стоматология", "Медицина / Бьюти", "Сложный B2B / Производство", "Образование"] else "35 000 ₽"
    package_roi = f"1-2 закрытых клиента (при чеке {cc_fmt} ₽)" if niche in ["Стоматология", "Медицина / Бьюти", "Сложный B2B / Производство", "Образование"] else f"3-5 новых клиентов (при чеке {cc_fmt} ₽)"

    typ_source = f"""
#set document(title: "Аналитический Отчет - PIN100", author: "PIN100 Analytics")

#set page(
  paper: "a4",
  margin: (x: 20mm, y: 25mm),
  footer: [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Строго конфиденциально
    #h(1fr)
    Стр. #counter(page).display()
  ]
)

#set text(font: "Arial", size: 10.5pt, fill: rgb("1E293B"), lang: "ru")
#set par(leading: 0.7em)

#show heading: set text(font: "Georgia", fill: rgb("0F172A"))

// --- ОБЛОЖКА ---
#v(80pt)
#text(size: 12pt, fill: rgb("9A6A38"), weight: "bold")[PIN100 ANALYTICS]
#v(15pt)
#text(size: 24pt, weight: "bold", font: "Georgia", fill: rgb("0F172A"))[
  Аналитический Отчет \\
  Оцифровка упущенной выручки
]
#v(15pt)
#line(length: 60mm, stroke: 1.5pt + rgb("9A6A38"))
#v(35pt)
#text(size: 11pt, fill: rgb("475569"))[
  *Субъект аудита:* {title_safe} \\
  *Отраслевой сегмент:* {clean_typography(niche)} \\
  *Дата формирования:* {current_date}
]
#pagebreak()

// --- ДИСКЛЕЙМЕР ---
#v(30pt)
== Ограничение ответственности и методология
#v(15pt)
#line(length: 100%, stroke: 0.5pt + rgb("CBD5E1"))
#v(15pt)
#text(size: 10.5pt, fill: rgb("475569"))[
  Настоящий аналитический отчет подготовлен центром PIN100 Analytics исключительно в информационных целях для внутреннего использования руководством компании. 
  
  Все выводы базируются на автоматизированном сборе открытых данных (алгоритмический парсинг) из геосервисов по состоянию на дату формирования документа. Данные о финансовых потерях и упущенной выручке являются расчетными (Predictive Analytics) и опираются на усредненные бенчмарки вашей ниши (среднерыночная конверсия, стоимость лида, средний чек, жизненный цикл клиента — LTV).
  
  Отчет не является финансовой гарантией, однако с высокой точностью отражает текущие алгоритмические уязвимости цифрового профиля компании и их прямое влияние на потерю органического (бесплатного) трафика.
]
#pagebreak()

// --- РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ ---
== Executive Summary (Резюме для руководителя)
#v(20pt)
#grid(
  columns: (1fr, 1fr),
  gutter: 20pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 15pt)[
      #text(size: 9pt, fill: rgb("64748B"), weight: "bold")[ИНДЕКС ГОТОВНОСТИ] \\
      #v(6pt)
      #text(size: 26pt, font: "Georgia", weight: "bold", fill: rgb("{score_color}"))[{round(score, 1)}] #text(size: 12pt, fill: rgb("94A3B8"))[/ 100] \\
      #v(4pt)
      #text(size: 8.5pt, fill: rgb("64748B"))[_Оценка по 79 параметрам алгоритмов_]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 15pt)[
      #text(size: 9pt, fill: rgb("64748B"), weight: "bold")[ФИНАНСОВЫЙ РИСК] \\
      #v(6pt)
      #text(size: 24pt, font: "Georgia", weight: "bold", fill: rgb("9F1239"))[- {rev_loss_fmt} ₽] \\
      #v(4pt)
      #text(size: 8.5pt, fill: rgb("64748B"))[_Ежемесячная упущенная выручка_]
    ]
  ]
)
#v(20pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 15pt)[
  #text(size: 12pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[Критический вывод аналитики:] \\
  #v(6pt)
  #text(size: 10.5pt, fill: rgb("334155"))[Прямо сейчас ваша компания фактически невидима для *{dev}% целевых клиентов* в поисковой выдаче Яндекс Карт. Из-за алгоритмических ошибок вы ежемесячно уступаете конкурентам около *{lost_leads} горячих сделок*. Попытки заливать рекламный бюджет в текущий профиль приведут к прямому финансовому убытку.]
]
#pagebreak()

// --- 3 ГЛАВНЫЕ ТОЧКИ СЛИВА ---
== Три ключевые точки потери выручки
#v(10pt)
#text(size: 10.5pt, fill: rgb("475569"))[Мы не будем утомлять вас техническими терминами. Вот три главных бизнес-фактора, из-за которых компания теряет клиентов прямо сейчас:]
#v(20pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 15pt)[
  #text(size: 12pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[1. «Слепая витрина» и потеря поискового трафика] \\
  #v(6pt)
  #text(size: 10pt, fill: rgb("475569"))[Алгоритмы Яндекса не видят ваши высокомаржинальные услуги. Из-за отсутствия правильной LSI-разметки, продающих SEO-текстов и технических фидов, вы просто не показываетесь клиентам, которые ищут конкретные дорогие процедуры или программы. Этот самый горячий трафик забирают конкуренты {comp_safe} с правильно настроенными каталогами.]
]
#v(12pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 15pt)[
  #text(size: 12pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[2. Барьер первого контакта (Обрыв конверсии)] \\
  #v(6pt)
  #text(size: 10pt, fill: rgb("475569"))[Ваша карточка заставляет клиента совершать лишние усилия. Сегодня отсутствие виджетов прямой онлайн-записи и ярких кнопок действия (CTA) приводит к тому, что клиенты закрывают ваш профиль. Вы безвозвратно теряете огромный пласт «вечернего» трафика и аудиторию, которая предпочитает мессенджеры звонкам.]
]
#v(12pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 15pt)[
  #text(size: 12pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[3. Скрытые репутационные угрозы] \\
  #v(6pt)
  #text(size: 10pt, fill: rgb("475569"))[Даже один оставленный без грамотного ответа негативный отзыв работает как токсичный якорь. Для новых клиентов, готовых оставить у вас крупную сумму, отсутствие эмпатичного ответа руководства на проблему равносильно признанию вины. Это рушит конверсию на самом финальном этапе принятия решения.]
]
#pagebreak()

// --- ROADMAP & MAFIA OFFER ---
== Инвестиционное предложение и окупаемость
#v(10pt)
#text(size: 10.5pt, fill: rgb("475569"))[Мы предлагаем вам не покупку «маркетинговых услуг», а системную остановку кассового разрыва. План интеграции под ключ:]
#v(20pt)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 10pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 10pt)[
      #text(size: 9pt, weight: "bold", fill: rgb("9A6A38"))[ЭТАП 1] \\
      #v(4pt)
      #text(size: 11pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[SEO-Архитектура] \\
      #v(4pt)
      #text(size: 9pt, fill: rgb("475569"))[Интеграция всех услуг в поисковые алгоритмы для захвата органического трафика.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 10pt)[
      #text(size: 9pt, weight: "bold", fill: rgb("9A6A38"))[ЭТАП 2] \\
      #v(4pt)
      #text(size: 11pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[Снятие барьеров] \\
      #v(4pt)
      #text(size: 9pt, fill: rgb("475569"))[Внедрение систем бронирования и триггеров для захвата обращений 24/7.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 10pt)[
      #text(size: 9pt, weight: "bold", fill: rgb("9A6A38"))[ЭТАП 3] \\
      #v(4pt)
      #text(size: 11pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[Защита бренда] \\
      #v(4pt)
      #text(size: 9pt, fill: rgb("475569"))[Антикризисная зачистка негатива и формирование образа надежного лидера.]
    ]
  ]
)

#v(20pt)
#rect(width: 100%, fill: rgb("FAFAFA"), stroke: 1pt + rgb("0F172A"), radius: 3pt, inset: 18pt)[
  #text(size: 13pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[Экономика решения: «{package_name}»] \\
  #v(14pt)
  #grid(
    columns: (1fr, 1fr),
    gutter: 20pt,
    [
      #text(size: 9pt, fill: rgb("64748B"), weight: "bold")[ТЕКУЩИЕ УБЫТКИ] \\
      #v(4pt)
      #text(size: 15pt, font: "Georgia", weight: "bold", fill: rgb("9F1239"))[{rev_loss_fmt} ₽/мес] \\
      #v(10pt)
      #text(size: 9pt, fill: rgb("64748B"), weight: "bold")[УПУЩЕННЫЙ LTV] \\
      #v(4pt)
      #text(size: 12pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[> {ltv_loss_fmt} ₽]
    ],
    [
      #text(size: 9pt, fill: rgb("64748B"), weight: "bold")[ИНВЕСТИЦИЯ ПОД КЛЮЧ] \\
      #v(4pt)
      #text(size: 15pt, font: "Georgia", weight: "bold", fill: rgb("9A6A38"))[{package_price}] \\
      #v(10pt)
      #text(size: 9pt, fill: rgb("64748B"), weight: "bold")[ТОЧКА ОКУПАЕМОСТИ] \\
      #v(4pt)
      #text(size: 11pt, weight: "bold", fill: rgb("166534"))[{package_roi}]
    ]
  )
  #v(12pt)
  #line(length: 100%, stroke: 0.5pt + rgb("CBD5E1"))
  #v(8pt)
  #text(size: 9.5pt, fill: rgb("0F172A"), weight: "bold")[Мы забираем 100% рутины на себя. Вам не придется разбираться в лимитах Яндекса или SEO-разметке — ваше время останется для управления бизнесом.]
]
#pagebreak()

// --- ДЕТАЛИЗАЦИЯ ---
== Техническое приложение (Детализация аудита)
#v(8pt)
#text(size: 9.5pt, fill: rgb("64748B"))[Развернутая диагностика карточки компании по 79 скрытым алгоритмическим параметрам Яндекса.]
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
        bar_color = "166534" if percentage >= 80 else ("9A6A38" if percentage >= 50 else "9F1239")
        
        passed_items = [clean_typography(r['Критерий']) for r in block_items if r['Результат'] == 'ДА']
        passed_text = ", ".join(passed_items) if passed_items else "Критерии не зафиксированы"

        failed_items_list = [r for r in block_items if r['Результат'] == 'НЕТ']
        failed_typst = ""
        
        if failed_items_list:
            for f_item in failed_items_list:
                c_name = clean_typography(f_item['Критерий'])
                c_reason = clean_typography(f_item['Обоснование'])
                failed_typst += f"""
#v(6pt)
#rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 2pt, inset: 8pt)[
  #text(size: 9.5pt, weight: "bold", fill: rgb("9F1239"))[{c_name}] \\
  #v(2pt)
  #text(size: 8.5pt, fill: rgb("475569"))[{c_reason}]
]
"""
        else:
            failed_typst = """
#v(6pt)
#text(size: 9pt, fill: rgb("166534"))[Уязвимостей не обнаружено. Отличный результат.]
"""

        block_title_clean = clean_typography(block['title'])
        earned_str = str(round(earned_score, 1))
        max_str = str(round(max_score, 1))

        typ_source += f"""
#v(10pt)
#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 3pt, inset: 12pt)[
  #grid(
    columns: (1fr, auto),
    [#text(size: 11pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[{block_title_clean}]],
    [#text(size: 11pt, weight: "bold", fill: rgb("{bar_color}"))[{earned_str} / {max_str}]]
  )
  #v(6pt)
  #text(size: 8pt, weight: "bold", fill: rgb("166534"))[В НОРМЕ:] \\
  #v(2pt)
  #text(size: 8.5pt, fill: rgb("475569"))[{passed_text}]
  #v(8pt)
  #line(length: 100%, stroke: 0.5pt + rgb("E2E8F0"))
  #v(6pt)
  #text(size: 8pt, weight: "bold", fill: rgb("9F1239"))[ЗОНЫ УЯЗВИМОСТИ (ОШИБКИ):]
  {failed_typst}
]
"""
    
    # --- FINAL CTA PAGE ---
    typ_source += """
#pagebreak()
#v(40pt)
== Следующие шаги
#v(15pt)
#line(length: 50mm, stroke: 1.5pt + rgb("9A6A38"))
#v(20pt)
#text(size: 10.5pt, fill: rgb("475569"))[
  Надеемся, этот отчет помог вам взглянуть на цифровой маркетинг вашей компании под новым углом. Наша цель — не просто указать на ошибки, а помочь вам выстроить надежный фундамент, который будет приносить качественные лиды годами.

  Если вы готовы остановить кассовый разрыв и вернуть упущенный трафик, давайте обсудим результаты этого отчета в удобном для вас формате. 
  
  Напишите нам, чтобы задать вопросы по расчетам или согласовать план действий. Мы на связи и готовы предметно разобрать вашу ситуацию без давления и лишних обязательств.
]
#v(35pt)

#rect(width: 100%, stroke: 0.5pt + rgb("CBD5E1"), fill: rgb("F8FAFC"), radius: 3pt, inset: 20pt)[
  #text(size: 13pt, font: "Georgia", weight: "bold", fill: rgb("0F172A"))[Свяжитесь с нами:] \\
  #v(12pt)
  #grid(
    columns: (80pt, 1fr), 
    gutter: 10pt,
    [#text(size: 11pt, fill: rgb("64748B"))[Telegram:]], 
    [#text(size: 11pt, weight: "bold", fill: rgb("0F172A"))[at paulvenkov]],
    [#text(size: 11pt, fill: rgb("64748B"))[Сайт:]], 
    [#text(size: 11pt, weight: "bold", fill: rgb("0F172A"))[pin100.ru]]
  )
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
                            st.success(f"**✅ {item['Критерий']}**\n\n{clean_typography(item['Обоснование'])}")
                        else:
                            st.error(f"**❌ {item['Критерий']}**\n\n{clean_typography(item['Обоснование'])}")
