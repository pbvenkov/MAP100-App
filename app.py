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
    try:
        client = gspread.authorize(get_google_credentials())
        ws = client.open_by_url(st.secrets["SPREADSHEET_URL"]).worksheet("Results")
        lpr_name = lpr_data.get("name", "") if lpr_data else ""
        lpr_role = lpr_data.get("role", "") if lpr_data else ""
        lpr_contact = (lpr_data.get("link", "") or lpr_data.get("email", "")) if lpr_data else ""
        
        row = [
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"),
            url, title, niche,
            str(round(total_score, 1)).replace('.', ','),
            lpr_name, lpr_role, lpr_contact, "",
            f"{lost_revenue:,}".replace(',', ' ') + " ₽",
            "1. Новый лид"
        ]
        ws.append_row(row)
    except Exception:
        pass

# ==========================================
# 4. НОРМАЛИЗАЦИЯ И СБОР ДАННЫХ
# ==========================================
def normalize_yandex_url(raw_url):
    url = raw_url.strip()
    if "/-/" in url:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        try:
            res = session.get(url, allow_redirects=True, timeout=12)
            if res.url: url = res.url
        except Exception: pass
    url = re.sub(r'yandex\.(?:com|by|kz|uz)/', 'yandex.ru/', url)
    url = url.replace("yandex.ru/navi/", "yandex.ru/maps/")
    if "?" in url: url = url.split("?")[0]
    url = re.sub(r'/(reviews|gallery|features|menu|goods|prices|posts)/?$', '', url)
    return url.rstrip('/') + '/'

def fetch_apify_data(yandex_url):
    cleaned_url = normalize_yandex_url(yandex_url)
    payload = {"startUrls": [{"url": cleaned_url}], "enrichBusinessData": True, "includeReviews": True, "maxPhotos": 80, "maxPosts": 30}
    run_req = requests.post(f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}", json=payload, timeout=15).json()
    if 'error' in run_req: raise Exception(f"Ошибка Apify API: {run_req['error']}")
    
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 75: raise Exception("Таймаут сбора данных. Яндекс долго отвечает.")
        time.sleep(4)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}", timeout=10).json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": raise Exception(f"Парсер завершился со статусом {status}.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}", timeout=15).json()
    if not isinstance(dataset, list) or len(dataset) == 0: raise Exception(f"Яндекс не вернул данные по адресу: {cleaned_url}")
    
    first_item = dataset[0]
    first_item['title'] = first_item.get('title') or first_item.get('name') or "Организация"
    return first_item

def enrich_lpr_contacts_from_vk(social_links):
    if not VK_API_TOKEN or not social_links: return {}
    vk_url = next((link.get('url', '') for link in social_links if isinstance(link, dict) and ('vk.com' in link.get('url', '') or 'vk.ru' in link.get('url', ''))), None)
    if not vk_url: return {}
    try:
        group_id = vk_url.rstrip('/').split('/')[-1]
        res = requests.get("https://api.vk.com/method/groups.getById", params={"group_id": group_id, "fields": "contacts", "access_token": VK_API_TOKEN, "v": "5.199"}, timeout=5).json()
        if 'response' in res and res['response']:
            contacts = res['response'][0].get('contacts', [])
            if not contacts: return {"status": "hidden", "vk_url": vk_url}
            contact = contacts[0]
            lpr_data = {"name": "", "role": contact.get('desc', 'Администратор'), "link": "", "email": contact.get('email', ''), "status": "found"}
            if 'user_id' in contact:
                lpr_data["link"] = f"https://vk.com/id{contact['user_id']}"
                u_res = requests.get("https://api.vk.com/method/users.get", params={"user_ids": contact['user_id'], "access_token": VK_API_TOKEN, "v": "5.199"}, timeout=5).json()
                if 'response' in u_res and u_res['response']:
                    lpr_data["name"] = f"{u_res['response'][0].get('first_name', '')} {u_res['response'][0].get('last_name', '')}".strip()
            return lpr_data
    except Exception: pass
    return {}

# ==========================================
# 5. АЛГОРИТМЫ СКОРИНГА И АНАЛИТИКА
# ==========================================
def parse_yandex_date(date_val):
    if not date_val: return None
    try:
        if isinstance(date_val, (int, float)) or (isinstance(date_val, str) and str(date_val).isdigit()):
            return datetime.fromtimestamp(int(date_val) / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(date_val).replace('Z', '+00:00'))
    except Exception: return None

def determine_niche_by_expert(title, category, prompts_data):
    if not expert_engine: return "OTHER"
    raw_prompt = next((p.get("Промпт для ИИ") for p in prompts_data if p.get("Код") == "NICHE_PROMPT"), "")
    if not raw_prompt: raw_prompt = "Определи нишу для компании {title}, категория {category}. Варианты: DENTISTRY, HORECA, B2B, B2B_HEAVY, RETAIL, AUTO, BEAUTY_MEDICAL, EDUCATION, SERVICES, OTHER. Верни только код ниши."
    prompt = raw_prompt.replace("{title}", title).replace("{category}", category)
    try:
        key = expert_engine.generate_content(prompt).text.strip().upper()
        for v in ["B2B_HEAVY", "BEAUTY_MEDICAL", "DENTISTRY", "HORECA", "B2B", "RETAIL", "AUTO", "EDUCATION", "SERVICES", "OTHER"]:
            if v in key: return v
    except Exception: pass
    return "OTHER"

def rewrite_errors_by_ai(niche_label, company_name, failed_rules, expert_engine):
    if not expert_engine or not failed_rules: return failed_rules
    payload_text = "".join([f"ID: {r['Код']} | Ошибка: {r['Критерий']} | Текст: {r['Обоснование']}\n" for r in failed_rules])
    prompt = f"Ты — B2B-эксперт. Ниша: {niche_label}. Компания: {company_name}. Перепиши обоснование каждой ошибки.\n{payload_text}\nВерни строго JSON: {{\"Код\": \"Текст\"}}"
    try:
        raw_resp = expert_engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
        if match:
            new_texts = json.loads(match.group(0))
            for r in failed_rules:
                if r['Код'] in new_texts and str(new_texts[r['Код']]).strip():
                    r['Обоснование'] = new_texts[r['Код']]
    except Exception: pass
    return failed_rules

def calculate_hard_facts(data, niche_key="OTHER"):
    scores = {}
    now = datetime.now(timezone.utc)
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')
    raw_url = data.get('url') or data.get('website') or ''
    url = str(raw_url).lower()
    cat_list = data.get('categories') or []
    
    if data.get('isVerifiedOwner') or len(title) > 2: scores['PROF-01.1'] = True
    if cat_list: scores['PROF-03.1'] = True
    if url: scores['PROF-04.1'] = True
        
    phones = data.get('phones') or []
    if phones:
        scores['PROF-05.1'] = True
        for p in phones:
            if str(p).startswith('+7') or str(p).startswith('8'):
                scores['PROF-05.2'] = True
                break
            
    schedule = data.get('schedule') or data.get('workingHours') or []
    if isinstance(schedule, list) and len(schedule) >= 5: scores['PROF-07.1'] = True
    elif isinstance(schedule, dict) and len(schedule.keys()) >= 5: scores['PROF-07.1'] = True
    
    features = data.get('features') or {}
    if features: scores['PROF-08.1'] = True

    if len(desc) > 1200: scores['PROF-09.1'] = True
    if data.get('isVerifiedOwner'): scores['PROF-12.1'] = True
    
    social_items = data.get('socialLinks') or data.get('links') or []
    owner_links = (url + " " + desc + " " + " ".join([str(l) for l in social_items])).lower()
    
    if any(s in owner_links for s in ["t.me", "wa.me", "whatsapp", "viber"]): scores['PROF-13.1'] = True
    if any(s in owner_links for s in ["vk.com", "vk.ru", "youtube", "dzen", "instagram"]): scores['PROF-13.2'] = True
    
    menu_data = data.get('menu')
    menu_items = menu_data.get('items', []) if isinstance(menu_data, dict) else []
    catalog_items = data.get('productCatalog') or []
    valid_prods = [p for p in (menu_items + catalog_items) if isinstance(p, dict)]
            
    if valid_prods:
        total_vp = len(valid_prods)
        if total_vp >= 10: scores['PROF-11.1'] = True
        if sum(1 for p in valid_prods if p.get('photoUrl') or p.get('photo')) / total_vp >= 0.7: scores['PROF-11.2'] = True
        if sum(1 for p in valid_prods if any(c.isdigit() for c in str(p.get('price') or ''))) / total_vp >= 0.7: scores['PROF-11.3'] = True
        if sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 40) / total_vp >= 0.6: scores['PROF-11.4'] = True
        if len(set(p.get('category') for p in valid_prods if p.get('category'))) >= 2: scores['PROF-11.5'] = True
        
    if len(str(data.get('address') or '')) > 5: scores['SEO-18.1'] = True
    if data.get('videoCount', 0) > 0 or data.get('videos'): scores['CONT-42.1'] = True
    
    photos = data.get('photos') or []
    photo_count = int(data.get('photoCount') or len(photos) or 0)
    if photo_count >= 15: scores['CONT-36.1'] = True
    if photo_count >= 30: scores['CONT-36.2'] = True
    
    tags = []
    for p in photos:
        if isinstance(p, dict):
            for tag in (p.get('tags') or []):
                if isinstance(tag, dict) and tag.get('id'): tags.append(tag['id'])
            if p.get('tag') == 'interior': tags.append('Interior')
                
    if "Interior" in tags: scores['CONT-38.1'] = True
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
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
        
    rev_count = int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount') or 0)
    if rev_count >= 40: scores['REP-28.1'] = True
    
    raw_reviews = data.get('reviews') or []
    all_reviews = [r for r in raw_reviews if isinstance(r, dict)]
    if not all_reviews:
        scores['META_NO_RECENT_REVIEWS'] = True
    else:
        top_20 = all_reviews[:20]
        first_date = parse_yandex_date(all_reviews[0].get('date'))
        if first_date and (now - first_date).days <= 14: scores['REP-29.1'] = True
        replied = sum(1 for r in top_20 if str(r.get('businessComment') or r.get('reply') or '').strip())
        if replied / len(top_20) >= 0.7: scores['REP-30.1'] = True
            
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    if not expert_engine or not prompts_data: return {}
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')[:1000]
    rules_list = [f'"{p.get("Код")}": {p.get("Промпт для ИИ")}' for p in prompts_data if p.get("Код") and p.get("Код") != 'NICHE_PROMPT']
    if not rules_list: return {}
    prompt = f"Название: {title}\nОписание: {desc}\nКритерии:\n{chr(10).join(rules_list)}\nВерни строго JSON объект {{CODE: true/false}}."
    try:
        raw_resp = expert_engine.generate_content(prompt).text
        match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
        if match: return {k: True for k, v in json.loads(match.group(0)).items() if str(v).lower() in ["1", "true"]}
    except Exception: pass
    return {}

# ==========================================
# 6. ВЕРСТКА TYPST И ГЕНЕРАЦИЯ PDF
# ==========================================
def clean_typography(text):
    if not text: return ""
    t = str(text).replace(" - ", " — ").replace(">=", "≥").replace("<=", "≤").replace("->", "→")
    t = t.replace("<", " меньше ").replace(">", " больше ")
    for c in ['\\', '[', ']', '{', '}', '$', '*', '_', '#', '@', '"', "'", '`', '~']: t = t.replace(c, ' ')
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

// --- СТР. 2 ---
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
  #text(13pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Критический вывод:]
  #v(8pt)
  #text(10.5pt, fill: rgb("334155"))[Прямо сейчас ваша компания фактически невидима для *{dev}% целевых клиентов*. Вы ежемесячно уступаете конкурентам около *{lost_leads} горячих сделок*.]
]
#pagebreak()
#heading(level: 2)[Инвестиционное предложение]
#v(12pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 12pt)[
  #grid(
    columns: (1fr, auto),
    gutter: 10pt,
    [
      #text(9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Забронировать 20-минутный стратегический Zoom-разбор]
    ],
    [
      #align(center + horizon)[#text(9.5pt, weight: "bold", fill: rgb("8B7355"))[Telegram: \\ t.me/paulvenkov]]
    ]
  )
]
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
        if not block_items: continue
        earned = sum(r.get('Earned', 0.0) for r in block_items)
        max_s = sum(r.get('Max', 0.0) for r in block_items)
        perc = (earned / max_s * 100) if max_s > 0 else 100
        bc = "166534" if perc >= 80 else ("8B7355" if perc >= 50 else "9F1239")
        
        passed_t = ", ".join([clean_typography(r.get('Критерий', '')) for r in block_items if r.get('Результат') == 'ДА']) or "Нет данных"
        failed_cards = "".join([f'#v(3pt)\n#block(breakable: false)[\n  #rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 3pt, inset: 6pt)[\n    #text(9pt, weight: "bold", fill: rgb("9F1239"))[× {clean_typography(f.get("Критерий", ""))}] \\\n    #v(2pt)\n    #text(8.5pt, fill: rgb("475569"))[{clean_typography(f.get("Обоснование", ""))}]\n  ]\n]\n' for f in block_items if f.get('Результат') == 'НЕТ']) or '#v(4pt)\n#text(9pt, fill: rgb("166534"))[Ошибок не обнаружено.]\n'

        typ_source += f"""
#v(10pt)
#heading(level: 3)[{block['title']} (#text(fill: rgb("{bc}"))[{round(earned, 1)} / {round(max_s, 1)}])]
#v(4pt)
#rect(width: 100%, fill: rgb("F0FDF4"), stroke: 0.5pt + rgb("BBF7D0"), radius: 3pt, inset: 6pt)[
  #text(8pt, weight: "bold", fill: rgb("166534"), tracking: 0.5pt)[В НОРМЕ:] \\
  #v(2pt)
  #text(8.5pt, fill: rgb("475569"))[{passed_t}]
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
        if os.path.exists(typ_path): os.remove(typ_path)
    return pdf_bytes

# ==========================================
# 7. ИНТЕРФЕЙС И ЗАПУСК
# ==========================================
rules_data, prompts_data = fetch_cached_database()

with st.sidebar:
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База данных подключена.")
    st.divider()
    sender_name = st.text_input("Ваше имя (для подписи аутрича):", value="Павел")
    # Поля с root УДАЛЕНЫ отсюда, чтобы не было конфликтов!

st.title(f"📍 {PROJECT_NAME}: {EXPERT_TITLE}")

tab_link, tab_file = st.tabs(["🌐 По ссылке (Яндекс Карты)", "📁 Из JSON файла"])

data_to_process = None
source_url = ""

with tab_link:
    url_input = st.text_input("Вставьте ссылку на карточку", placeholder="https://yandex.ru/maps/...")
    if st.button("🚀 Сгенерировать Отчет по ссылке", type="primary"):
        if "yandex" not in url_input.lower():
            st.error("❌ Введите корректную ссылку.")
        else:
            with st.spinner("Сбор данных..."):
                try:
                    data_to_process = fetch_apify_data(url_input)
                    source_url = url_input
                except Exception as e:
                    st.error(f"⚠️ Ошибка парсинга: {str(e)}")

with tab_file:
    uploaded_file = st.file_uploader("Загрузите JSON", type=["json"])
    if uploaded_file and st.button("🚀 Сформировать из файла"):
        data_to_process = json.load(uploaded_file)
        source_url = data_to_process.get('url') or "Файл JSON"

if data_to_process:
    data = data_to_process
    title = data.get('title', 'Без названия')
    c_list = data.get('categories', [])
    cat = c_list[0].get('name', '') if (isinstance(c_list, list) and c_list and isinstance(c_list[0], dict)) else (str(c_list[0]) if (isinstance(c_list, list) and c_list) else '')
    client_reviews = int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []) or 0)
    
    lpr_data = enrich_lpr_contacts_from_vk(data.get('socialLinks') or data.get('links') or [])
    
    raw_related = data.get('relatedPlaces') or []
    comp_list = [str(c.get('name')).strip() for c in (raw_related if isinstance(raw_related, list) else (raw_related.get('items') or [raw_related])) if isinstance(c, dict) and c.get('name')][:2]
    comp_text = f" (например, {', '.join(comp_list)})" if comp_list else ""
    
    with st.spinner("Расчет юнит-экономики..."):
        niche_key = determine_niche_by_expert(title, cat, prompts_data)
        raw_scores = calculate_hard_facts(data, niche_key)
        raw_scores.update(calculate_dynamic_expert_rules(data, prompts_data))
        
        results = []
        final_total = 0.0
        target_col = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
        
        for r in rules_data:
            code = str(r.get('Код', '')).strip()
            if not code: continue
            name = str(r.get('Критерий', '')).strip()
            max_s = float(str(r.get(target_col, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
            if max_s > 0.0:
                val = max_s if raw_scores.get(code) else 0.0
                final_total += val
                comm = "ДА" if val > 0 else "НЕТ"
                results.append({"Код": code, "Критерий": name, "Результат": comm, "Обоснование": r.get('Обоснование_ОШИБКИ', ''), "Группа": str(r.get('Группа метрик', 'Прочее')), "Earned": val, "Max": max_s})

        eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
        niche_label = eco.get("label", "Прочее")
        
        with st.sidebar:
            st.divider()
            st.markdown(f"### 🧮 Экономика: {niche_key}")
            client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
            client_check = st.number_input("Средний чек (₽)", value=eco["check"], step=5000)
            client_ltv = st.number_input("Цикл LTV", value=eco["ltv_months"], step=1)

        lost_perc = max(0.0, 100.0 - final_total) / 100.0
        lost_rev = int(client_leads * lost_perc * client_check)
        
        save_audit_to_sheets(source_url, title, niche_key, final_total, lost_rev, lpr_data)
        
        st.divider()
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"🏢 {title}")
            st.caption(f"🧠 Сегмент: **{niche_label}**")
        with col2:
            st.metric(f"Индекс {PROJECT_NAME}", f"{round(final_total, 1)} / 100")
        
        pdf_bytes = create_pdf_report(title, niche_label, final_total, lost_rev, results, client_leads, client_check, client_ltv, comp_text)
        
        if pdf_bytes:
            st.download_button("💎 Скачать PDF", data=pdf_bytes, file_name=f"Report_{title}.pdf", mime="application/pdf", type="primary")

            # ==========================================
            # 8. АВТО-СОХРАНЕНИЕ НА ДИСК С ПРОВЕРКОЙ ОШИБОК
            # ==========================================
            st.divider()
            st.markdown("### ✉️ Персональное письмо (Icebreaker)")
            
            c_1 = comp_list[0] if len(comp_list) > 0 else "соседним клиникам"
            c_2 = comp_list[1] if len(comp_list) > 1 else "конкурентам"
            icebreaker_text = generate_icebreaker_text({
                "lpr_name": lpr_data.get("name") if (lpr_data and lpr_data.get("name")) else "Добрый день",
                "title": title, "rating": round(float(data.get("rating", 4.5)), 1),
                "comp_1": c_1, "comp_2": c_2,
                "lost_leads": f"{max(5, int(client_leads * lost_perc * 0.8))}–{max(10, int(client_leads * lost_perc))}",
                "lost_revenue": lost_rev, "sender_name": sender_name
            })
            st.code(icebreaker_text, language="markdown")
            
            upload_key = f"upload_done_{title}"
            links_key = f"drive_links_{title}"

            if upload_key not in st.session_state:
                st.session_state[upload_key] = False

            if not st.session_state[upload_key]:
                with st.spinner("☁️ Авто-сохранение файлов на Google Диск..."):
                    try:
                        creds = get_google_credentials()
                        if not DriveManager:
                            st.error("❌ Модуль drive_manager.py не найден.")
                            st.session_state[upload_key] = True
                        else:
                            dm = DriveManager(creds)
                            safe_n = title.replace(" ", "_").replace('"', '').replace("'", "")
                            
                            pdf_url = dm.upload_file(f"{safe_n}_Аудит.pdf", pdf_bytes, "application/pdf", dm.pdf_root_id)
                            json_url = dm.upload_file(f"{safe_n}.json", json.dumps(data, ensure_ascii=False), "application/json", dm.json_root_id)
                            txt_url = dm.upload_file(f"{safe_n}_Ice.txt", icebreaker_text, "text/plain", dm.letters_root_id)
                            
                            if pdf_url or txt_url:
                                links = []
                                if pdf_url: links.append(f"🔗 [PDF]({pdf_url})")
                                if txt_url: links.append(f"🔗 [Письмо]({txt_url})")
                                if json_url: links.append(f"🔗 [JSON]({json_url})")
                                st.session_state[links_key] = links
                                st.session_state[upload_key] = True
                            else:
                                st.error("❌ Google Диск отклонил загрузку. Проверьте, что в настройках доступа ваших папок на Диске вы выдали права РЕДАКТОРА сервисному аккаунту (адрес заканчивается на iam.gserviceaccount.com)!")
                                st.session_state[upload_key] = True
                    except Exception as e:
                        st.error(f"❌ Ошибка Google API: {e}")
                        st.session_state[upload_key] = True

            if st.session_state.get(upload_key) and st.session_state.get(links_key):
                st.success("✅ Сделка зафиксирована в облаке!")
                st.markdown(" | ".join(st.session_state[links_key]))
