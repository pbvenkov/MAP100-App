import streamlit as st
import requests
import os
import time
import json
import numpy as np
import pandas as pd
import re
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
import base64
import tempfile
import typst

# ==========================================
# 0. НАСТРОЙКИ БРЕНДИНГА PIN100
# ==========================================
PROJECT_NAME = "PIN100"
EXPERT_TITLE = "Генератор B2B Воронки (LITE / PRO Отчеты)"

# ==========================================
# 1. СЕКРЕТЫ И ИНИЦИАЛИЗАЦИЯ ИИ
# ==========================================
APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

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
        text = f"🚨 *{PROJECT_NAME}: Сбой системы*\n\n*Цель:* {target_url}\n*Ошибка:* {error_msg}\n\n🛑 *Действие:* Записано в лог ошибок."
        try: requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except Exception: pass

# ==========================================
# 2. БАЗЫ ДАННЫХ И GOOGLE SHEETS
# ==========================================
NICHE_ECONOMICS = {
    "HORECA": {"leads": 150, "check": 2000, "label": "HORECA"},
    "B2B": {"leads": 40, "check": 30000, "label": "Легкий B2B / Обеспечение бизнеса"},
    "RETAIL": {"leads": 200, "check": 1500, "label": "Ритейл"},
    "AUTO": {"leads": 100, "check": 12000, "label": "Авто"},
    "SERVICES": {"leads": 60, "check": 7000, "label": "Услуги B2C"},
    "BEAUTY_MEDICAL": {"leads": 80, "check": 6000, "label": "Медицина / Бьюти"},
    "OTHER": {"leads": 50, "check": 5000, "label": "Прочее"}
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

def save_audit_to_sheets(url, title, niche, total_score, results_data):
    try:
        client = gspread.authorize(get_google_credentials())
        doc = client.open_by_url(st.secrets["SPREADSHEET_URL"])
        ws = doc.worksheet("Results")
        headers = ws.row_values(1)
        
        row_dict = {
            "Дата": datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S"),
            "Ссылка": url,
            "Компания": title,
            "Ниша": niche,
            "Общий балл": str(round(total_score, 1)).replace('.', ',')
        }
        
        for r in results_data:
            code = r.get("Код")
            if code:
                row_dict[code] = str(round(r.get("Earned", 0), 1)).replace('.', ',')
                
        row_to_append = [row_dict.get(h, "") for h in headers]
        ws.append_row(row_to_append)
    except Exception as e:
        pass 

# ==========================================
# 3. ПАРСЕР APIFY
# ==========================================
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: 
        raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: raise Exception("Таймаут парсера Apify (Яндекс слишком долго отвечает).")
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": raise Exception(f"Парсер упал со статусом {status}.")
        
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset: raise Exception("Яндекс отдал пустой результат (вероятна капча).")
    
    data = dataset[0]
    if not data.get('title') or len(str(data.get('title'))) < 2:
        raise Exception("Яндекс вернул пустую заглушку вместо карточки.")
    return data

# ==========================================
# 4. АЛГОРИТМЫ ОЦЕНКИ И ИИ
# ==========================================
def get_safe_list(data, keys):
    res = []
    for k in keys:
        if isinstance(data.get(k), list): res.extend(data[k])
        elif isinstance(data.get(k), dict): res.append(data[k])
    return res

def parse_yandex_date(date_val):
    if not date_val: return None
    try:
        if isinstance(date_val, (int, float)) or (isinstance(date_val, str) and str(date_val).isdigit()):
            return datetime.fromtimestamp(int(date_val)/1000, tz=timezone.utc)
        return datetime.fromisoformat(str(date_val).replace('Z', '+00:00'))
    except: return None

def determine_niche_by_expert(title, category, prompts_data):
    if not expert_engine: raise Exception("ИИ не инициализирован.")
    
    niche_prompt = next((p.get("Промпт для ИИ") for p in prompts_data if p.get("Код") == "NICHE_PROMPT"), None)
    if not niche_prompt:
        niche_prompt = """Проведи экспертную оценку бизнеса по названию "{title}" и категории "{category}".
ВНИМАНИЕ: Если в категории есть слова "стоматология", "клиника", "медицина", "красота", "салон" - это СТРОГО BEAUTY_MEDICAL.
Определи ОДИН наиболее подходящий сегмент: HORECA, B2B, RETAIL, AUTO, SERVICES, BEAUTY_MEDICAL, OTHER.
Верни ТОЛЬКО ОДНО СЛОВО - ключ на английском."""
    
    prompt = niche_prompt.replace("{title}", title).replace("{category}", category)
    try:
        response = expert_engine.generate_content(prompt)
        key = response.text.strip().upper()
        for v in ["BEAUTY_MEDICAL", "HORECA", "B2B", "RETAIL", "AUTO", "SERVICES", "OTHER"]:
            if v in key: return v
        return "OTHER"
    except Exception as e:
        raise Exception(f"Сбой ИИ (Ниша): {str(e)}")

def calculate_hard_facts(data):
    scores = {}
    now = datetime.now(timezone.utc)
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')
    
    if data.get('isVerifiedOwner') or len(title) > 2: scores['PROF-01.1'] = True
    if data.get('categories'): scores['PROF-03.1'] = True
    url = str(data.get('url') or data.get('website') or '').lower()
    if url: scores['PROF-04.1'] = True
    
    phones = data.get('phones') or []
    if phones: 
        scores['PROF-05.1'] = True
        if any(str(p).startswith('+7') or str(p).startswith('8') for p in phones):
            scores['PROF-05.2'] = True
        
    schedule = data.get('schedule') or data.get('workingHours') or []
    if isinstance(schedule, list) and len(schedule) >= 7: scores['PROF-07.1'] = True
    elif isinstance(schedule, dict) and len(schedule.keys()) >= 7: scores['PROF-07.1'] = True
    
    features = data.get('features')
    if isinstance(features, dict) and len(features.keys()) > 0: scores['PROF-08.1'] = True
    elif isinstance(features, list) and len(features) > 0: scores['PROF-08.1'] = True
    
    if len(desc) > 1500: scores['PROF-09.1'] = True
    if data.get('isVerifiedOwner'): scores['PROF-12.1'] = True
    
    links_data = data.get('socialLinks') or data.get('links') or []
    owner_links = url + " " + desc + " " + " ".join([str(l) for l in links_data])
    if any(s in owner_links.lower() for s in ["t.me", "wa.me", "whatsapp", "viber"]): scores['PROF-13.1'] = True
    if any(s in owner_links.lower() for s in ["vk.com", "youtube", "dzen", "instagram", "inst:"]): scores['PROF-13.2'] = True
    
    prods = []
    if isinstance(data.get('menu'), dict): prods.extend(data['menu'].get('items', []))
    if isinstance(data.get('productCatalog'), list): prods.extend(data['productCatalog'])
        
    valid_prods = [p for p in prods if isinstance(p, dict)]
    if valid_prods:
        if len(valid_prods) >= 10: scores['PROF-11.1'] = True
        photos_count = sum(1 for p in valid_prods if p.get('photoUrl') or p.get('photo'))
        if photos_count / len(valid_prods) >= 0.8: scores['PROF-11.2'] = True
        prices_count = sum(1 for p in valid_prods if any(char.isdigit() for char in str(p.get('price') or '')))
        if prices_count / len(valid_prods) >= 0.8: scores['PROF-11.3'] = True
        desc_count = sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 50)
        if desc_count / len(valid_prods) >= 0.8: scores['PROF-11.4'] = True
        cats = set([p.get('category') for p in valid_prods if p.get('category')])
        if len(cats) >= 2: scores['PROF-11.5'] = True
        
    addr = str(data.get('address') or '')
    if len(addr) > 5: scores['SEO-18.1'] = True
    
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
    
    rev_count = int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount') or 0)
    if rev_count >= 50: scores['REP-28.1'] = True
    
    reviews_raw = data.get('reviews') or []
    six_months_ago = now - timedelta(days=180)
    recent_reviews = []
    for r in reviews_raw:
        if not isinstance(r, dict): continue
        r_date = parse_yandex_date(r.get('date') or r.get('time'))
        if r_date and r_date >= six_months_ago:
            recent_reviews.append(r)
            
    if not recent_reviews:
        scores['META_NO_RECENT_REVIEWS'] = True
    else:
        replied = 0
        has_positive_replied = False
        has_unanswered_negative = False
        
        latest_date = parse_yandex_date(recent_reviews[0].get('date'))
        if latest_date and (now - latest_date).days <= 14: scores['REP-29.1'] = True
            
        for r in recent_reviews[:20]:
            r_rating = float(r.get('rating') or 0.0)
            reply_text = str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip()
            
            if reply_text:
                replied += 1
                if r_rating >= 4.0: has_positive_replied = True
                bc_date = parse_yandex_date(r.get('businessCommentDate'))
                rev_date = parse_yandex_date(r.get('date'))
                if bc_date and rev_date and (bc_date - rev_date).days <= 3: scores['REP-30.2'] = True
            else:
                if r_rating <= 3.0: has_unanswered_negative = True
                
        if len(recent_reviews[:20]) > 0:
            if replied / len(recent_reviews[:20]) >= 0.9: scores['REP-30.1'] = True
            photos_in_revs = sum(1 for r in recent_reviews[:20] if r.get('photos') or r.get('photoDetails'))
            if photos_in_revs / len(recent_reviews[:20]) >= 0.1: scores['REP-35.1'] = True
            
        if has_positive_replied: scores['REP-30.3'] = True
        if not has_unanswered_negative: scores['REP-32.1'] = True
        
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    scores = {}
    if not expert_engine or not prompts_data: return scores
    
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')[:1000]
    
    now = datetime.now(timezone.utc)
    six_months_ago = now - timedelta(days=180)
    recent_reviews = []
    for r in data.get('reviews') or []:
        r_date = parse_yandex_date(r.get('date'))
        if r_date and r_date >= six_months_ago: recent_reviews.append(r)
            
    reviews_text = ""
    for r in recent_reviews[:10]:
        if isinstance(r, dict):
            u_text = r.get('text', '')
            o_reply = r.get('businessComment') or r.get('reply', {}).get('text') if isinstance(r.get('reply'), dict) else ''
            reviews_text += f"Отзыв: {u_text}\nОтвет владельца: {o_reply}\n---\n"
            
    prods = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    prods_text = ", ".join([str(p.get('name')) for p in prods if isinstance(p, dict)][:20])

    rules_list = [f'"{p.get("Код", "").strip()}": {p.get("Промпт для ИИ", "").strip()}' for p in prompts_data if p.get('Код', '').strip() and p.get('Код') != 'NICHE_PROMPT']
    if not rules_list: return scores

    batch_prompt = f"""
Контекст о бизнесе:
Название: {title}
Описание: {desc}
Товары/Услуги: {prods_text}
Последние отзывы и ответы:
{reviews_text[:2000]} 

Критерии для оценки:
{chr(10).join(rules_list)}

ВНИМАНИЕ! Верни строго JSON формата {{"CODE": true/false}}. В ответе ОБЯЗАТЕЛЬНО должны присутствовать абсолютно все кодов из списка критериев.
"""
    try:
        response = expert_engine.generate_content(batch_prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
            for code, result in res_json.items():
                if str(result).lower() in ["1", "true"]: scores[code] = True
    except: pass
    return scores

# ==========================================
# 5. ТИПОГРАФИКА И PDF (TYPST)
# ==========================================
def clean_typography(text):
    """Филологическая очистка текстов и безопасность Typst"""
    t = str(text)
    
    t = re.sub(r'[-—]\s*[-—]', '—', t)
    t = t.replace(" - ", " — ")
    
    t = t.replace(" это ", " — это ")
    t = t.replace(" реквизитов красный ", " реквизитов — красный ")
    t = t.replace("сегодня вы", "сегодня, вы")
    t = t.replace("капитал за счет", "капитал, за счет")
    t = t.replace("описание это", "описание — это")
    t = t.replace("контакты это", "контакты — это")
    t = t.replace("записи это", "записи — это")
    
    t = t.replace('\\', r'\\')
    t = t.replace('[', r'\[').replace(']', r'\]')
    t = t.replace('{', r'\{').replace('}', r'\}')
    t = t.replace('$', r'\$')
    t = t.replace('*', r'\*').replace('_', r'\_')
    t = t.replace('#', r'\#')
    return t

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, report_type="PRO"):
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    score_color = "16A34A" if score >= 80 else ("C5A880" if score >= 50 else "DC2626")
    dev = round(100 - score, 1)
    lost_clients = int(round(dev / 10))
    lost_leads = int(client_leads * (dev / 100))
    ltv_loss = revenue_loss * 12
    
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    cc_fmt = f"{client_check:,}".replace(',', ' ')
    ltv_loss_fmt = f"{ltv_loss:,}".replace(',', ' ')
    rev_str = f"- {rev_loss_fmt} ₽ / мес"
    
    title_safe = str(title).replace('"', '').replace('[', '').replace(']', '').replace('\\', '').replace('#', '').replace('*', '').replace('$', '')
    doc_title = "Экспертная оценка качества ведения#linebreak()карточки компании и работы#linebreak()с отзывами в Яндекс.Бизнес"

    typ_source = f"""
#set document(title: "Аудит PIN100 - {title_safe}", author: "PIN100 Analytics")
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

#set text(font: ("Inter", "Arial", "sans-serif"), size: 11pt, fill: rgb("334155"), lang: "ru")
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// --- ОБЛОЖКА ---
#v(150pt)
#text(16pt, fill: rgb("C5A880"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(10pt)
#text(26pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[{doc_title}]
#v(10pt)
#line(length: 80mm, stroke: 3pt + rgb("C5A880"))
#v(30pt)
#text(14pt, fill: rgb("475569"))[
  Подготовлено для: #strong(text(fill: rgb("0A1128"))[{title_safe}]) #linebreak()
  Дата аудита: #strong[{current_date}]
]
#pagebreak()

// --- РЕЗЮМЕ ---
#heading(level: 2)[Резюме для руководителя]
#v(10pt)
#grid(
  columns: (1fr, 1fr),
  gutter: 20pt,
  rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 8pt, inset: 20pt)[
    #text(10.5pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ИНДЕКС ГОТОВНОСТИ ПРОФИЛЯ]
    #linebreak()
    #v(8pt)
    #text(28pt, weight: "bold", fill: rgb("{score_color}"))[{round(score, 1)} / 100]
  ],
  rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 8pt, inset: 20pt)[
    #text(10.5pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[УПУЩЕННАЯ ВЫРУЧКА (LOST REVENUE)]
    #linebreak()
    #v(8pt)
    #text(28pt, weight: "bold", fill: rgb("DC2626"))[{rev_str}]
  ]
)
#v(20pt)
#set par(leading: 0.6em)
#text(12pt, fill: rgb("334155"))[*Вывод эксперта:* Отличное качество вашего продукта теряется из-за слабого присутствия в геосервисах. Из-за критических ошибок в заполнении карточки и отсутствии системной работы с отзывами вы уступаете позиции в поиске и ежемесячно отдаете горячих клиентов своим конкурентам.]
#v(30pt)

// --- МЕТОДОЛОГИЯ ---
#heading(level: 2)[Как работает этот аудит?]
#v(10pt)
#set par(leading: 0.6em)
#text(11.5pt, fill: rgb("475569"))[
  В зависимости от сферы деятельности вашей компании, мы оцениваем правильность заполнения карточки в Яндекс.Бизнес и работу с отзывами по матрице из *79 параметров*, каждый из которых критически важен для алгоритмов площадки. Идеально заполненная карточка получает ровно *100 баллов*.

  Для вашего удобства все параметры разбиты на 4 смысловых блока, которые решают две фундаментальные задачи:
]
#v(15pt)
#grid(
  columns: (1fr, 1fr),
  gutter: 15pt,
  rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 8pt, inset: 15pt)[
    #text(11pt, weight: "bold", fill: rgb("0A1128"))[1. Приоритет в выдаче]
    #v(5pt)
    #set par(leading: 0.5em)
    #text(10.5pt, fill: rgb("475569"))[Обеспечивают высокую видимость. Это то, благодаря чему клиент вообще *увидит вашу карточку* среди десятков конкурентов.\n_Примеры: нишевые атрибуты, SEO-ключи в товарах и ответах, регулярные публикации._]
  ],
  rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 8pt, inset: 15pt)[
    #text(11pt, weight: "bold", fill: rgb("0A1128"))[2. Целевое действие (ЦД)]
    #v(5pt)
    #set par(leading: 0.5em)
    #text(10.5pt, fill: rgb("475569"))[Работают на конверсию. Убеждают клиента позвонить, построить маршрут или перейти на сайт, когда он *уже находится внутри*.\n_Примеры: понятный прайс-лист, яркие кнопки CTA, качественные фото, закрытие страхов в FAQ._]
  ]
)
#v(20pt)
#rect(width: 100%, fill: rgb("FFF1F2"), stroke: (left: 4pt + rgb("E11D48")), inset: 15pt)[
    #text(11.5pt, weight: "bold", fill: rgb("BE123C"))[Важный вывод:]
    #v(5pt)
    #set par(leading: 0.5em)
    #text(10.5pt, fill: rgb("475569"))[Просто показывать клиентам плохо оформленную карточку — это *слив рекламного бюджета* и неизбежное *падение в органической выдаче*. \n\nПочему? Если Яндекс выводит вас в топ, но люди заходят и уходят без звонка (из-за скрытых цен, отсутствия фото или старых отзывов), система считывает это как "отказ". Алгоритм делает вывод, что бизнес некачественный, и принудительно опускает карточку на самое дно рейтинга.]
]
#v(15pt)
#rect(width: 100%, fill: rgb("FFFBEB"), stroke: (left: 4pt + rgb("F59E0B")), inset: 15pt)[
    #text(11.5pt, weight: "bold", fill: rgb("B45309"))[⚠️ Важно для плательщиков Рекламной подписки Яндекса:]
    #v(5pt)
    #set par(leading: 0.5em)
    #text(10.5pt, fill: rgb("475569"))[Если вы уже используете или планируете подключать платное продвижение, помните: *алгоритм подписки продает вам показы и клики, а не продажи*. При готовности профиля ниже 80% запуск платной рекламы ведет к прямому сливу бюджета. Упаковка карточки по стандартам PIN100 перед запуском рекламы снижает стоимость привлеченного клиента в среднем на 40–60%.]
]

#pagebreak()
// --- ДЕКОМПОЗИЦИЯ ---
#heading(level: 2)[Декомпозиция потерь]
#v(10pt)
"""

    blocks_fin = [
        ("А. Видимость бизнеса (Кто забирает клиентов)", f"Ваш профиль соответствует стандартам площадки лишь на *{round(score, 1)}%*. В реалиях алгоритмов Яндекса это означает, что из каждых 10 человек, которые прямо сейчас ищут ваши услуги, *{lost_clients}* до вас просто не доходят. Они видят в топе конкурентов с более грамотно упакованными карточками и оставляют деньги там."),
        ("Б. Цена простоя (Ваши прямые убытки)", f"В вашей нише через геосервисы ежемесячно проходит около *{client_leads}* целевых запросов. Из-за пробелов в оптимизации профиля мимо вас проходит порядка *{lost_leads}* сделок. При вашем среднем чеке ({cc_fmt} ₽) это превращается в кассовый разрыв на #text(fill: rgb(\"DC2626\"), weight: \"bold\")[{rev_loss_fmt} ₽] каждый месяц."),
        ("В. Скрытая угроза (Недополученный LTV)", f"Привлеченный клиент — это не разовая сделка, он остается с бизнесом надолго (в среднем от 12 месяцев). Упуская заказчиков сегодня, вы лишаете компанию будущих регулярных платежей. В годовом выражении эта недополученная выручка достигает #text(fill: rgb(\"DC2626\"), weight: \"bold\")[{ltv_loss_fmt} ₽]. Это капитал, за счет которого прямо сейчас масштабируются ваши конкуренты.")
    ]
    
    for bt, text in blocks_fin:
        typ_source += f"""
#block(breakable: false)[
    #text(16pt, font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"), weight: "bold")[{bt}]
    #v(5pt)
    #line(length: 40mm, stroke: 2pt + rgb("C5A880"))
    #v(10pt)
    #set par(leading: 0.6em)
    #text(11.5pt, fill: rgb("475569"))[{text}]
]
#v(20pt)
"""

    # --- ВОРОНКА С КОЛОНКАМИ УСПЕХОВ И ОШИБОК ---
    typ_source += """
#pagebreak()
#heading(level: 2)[Аналитика воронки продаж]
#text(11.5pt, fill: rgb("475569"))[Ниже представлена оцифровка вашего профиля по ключевым этапам конверсии.]
#v(20pt)
"""
    blocks = [
        {"title": "Блок 1. Видимость и Охваты", "groups": ['SEO и Трафик', 'Активность'], "desc": "Отвечает за то, как часто вас находят потенциальные клиенты в поиске Яндекса. Правильная настройка позволяет алгоритмам показывать вашу карточку выше конкурентов."},
        {"title": "Блок 2. Упаковка и Конверсия", "groups": ['Конверсия', 'Базовое заполнение', 'Контент и Визуал'], "desc": "Оцениваем, насколько карточка привлекательна для клиента. Качественный визуал, полные цены и удобные кнопки превращают обычный просмотр в реальный звонок."},
        {"title": "Блок 3. Репутационный капитал", "groups": ['Репутация'], "desc": "Клиенты всегда читают отзывы перед покупкой, особенно при высоких чеках. Системная работа с обратной связью повышает лояльность и траст профиля."},
        {"title": "Блок 4. Скрытые алгоритмы", "groups": ['Технологии и ИИ'], "desc": "Это невидимая для пользователя, но критически важная для роботов Яндекса часть. Разметка данных помогает нейросетям лучше понимать бизнес."}
    ]

    for block in blocks:
        block_items = [r for r in results_data if r['Группа'] in block['groups']]
        if not block_items: continue
        earned_score = sum(r.get('Earned', 0.0) for r in block_items)
        max_score = sum(r.get('Max', 0.0) for r in block_items)
        percentage = (earned_score / max_score * 100) if max_score > 0 else 100
        bar_color = "16A34A" if percentage >= 80 else ("C5A880" if percentage >= 50 else "DC2626")
        
        passed_items = [clean_typography(r['Критерий']) for r in block_items if r['Результат'] == 'ДА']
        failed_items_block = [clean_typography(r['Критерий']) for r in block_items if r['Результат'] == 'НЕТ']
        
        passed_list = "\n".join([f"  - {item}" for item in passed_items]) if passed_items else "  - Нет данных"
        failed_list = "\n".join([f"  - {item}" for item in failed_items_block]) if failed_items_block else "  - Ошибок не найдено"

        typ_source += f"""
#block(breakable: false)[
    #rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 8pt, inset: 20pt)[
        #grid(
            columns: (1fr, auto),
            text(14pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[{block['title']}],
            text(14pt, weight: "bold", fill: rgb("{bar_color}"))[{round(earned_score, 1)} / {round(max_score, 1)}]
        )
        #v(10pt)
        #box(width: 100%, height: 8pt, fill: rgb("E2E8F0"), radius: 4pt, clip: true)[
            #box(width: {percentage}%, height: 8pt, fill: rgb("{bar_color}"), radius: 4pt)
        ]
        #v(10pt)
        #text(10.5pt, fill: rgb("64748B"), style: "italic")[{block['desc']}]
        #v(15pt)
        #line(length: 100%, stroke: 0.5pt + rgb("E2E8F0"))
        #v(15pt)
        #grid(
            columns: (1fr, 1fr),
            gutter: 15pt,
            [
                #text(9pt, weight: "bold", fill: rgb("16A34A"), tracking: 0.5pt)[ПРАВИЛЬНО УКАЗАНЫ:]
                #v(6pt)
                #set text(size: 8.5pt, fill: rgb("475569"))
                #set list(marker: text(fill: rgb("16A34A"))[✓])
{passed_list}
            ],
            [
                #text(9pt, weight: "bold", fill: rgb("DC2626"), tracking: 0.5pt)[ТРЕБУЮТ ВНИМАНИЯ:]
                #v(6pt)
                #set text(size: 8.5pt, fill: rgb("475569"))
                #set list(marker: text(fill: rgb("DC2626"))[×])
{failed_list}
            ]
        )
    ]
]
#v(15pt)
"""

    # --- ДОРОЖНАЯ КАРТА (ТОЛЬКО ДЛЯ PRO) ---
    if report_type == "PRO":
        typ_source += """
#pagebreak()
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Пошаговая дорожная карта]
#v(5pt)
#line(length: 80mm, stroke: 3pt + rgb("C5A880"))
#v(20pt)
#text(12pt, fill: rgb("475569"))[Мы собрали все выявленные уязвимости и распределили их по приоритету. Следуйте этому Экшн-плану, чтобы за 30 дней забрать максимум органического трафика в вашей нише.]
#v(20pt)
"""
        stages = {
            1: {"title": "Этап 1: Быстрые победы (Дни 1-3)", "desc": "Срочные исправления. Эти ошибки сжигают вашу конверсию прямо сейчас.", "color": "DC2626"},
            2: {"title": "Этап 2: Упаковка смыслов (Дни 4-14)", "desc": "Базовое заполнение. Сделайте профиль понятным и привлекательным для клиента.", "color": "C5A880"},
            3: {"title": "Этап 3: Масштабирование (Дни 15-30)", "desc": "Работа с репутацией и скрытыми алгоритмами Яндекса для захвата топа.", "color": "16A34A"}
        }
        
        failed_items = [i for i in results_data if i['Результат'] == 'НЕТ']
        for stage_num, stage_info in stages.items():
            stage_items = [i for i in failed_items if i.get('Этап', 3) == stage_num]
            if stage_items:
                typ_source += f"""
#block(breakable: false)[
    #text(22pt, font: ("Playfair Display", "Georgia", "serif"), fill: rgb("{stage_info['color']}"))[{stage_info['title']}]
    #v(5pt)
    #text(11.5pt, fill: rgb("475569"), style: "italic")[{stage_info['desc']}]
    #v(20pt)
]
"""
                groups_in_stage = {}
                for item in stage_items:
                    g = item['Группа']
                    if g not in groups_in_stage: groups_in_stage[g] = []
                    groups_in_stage[g].append(item)
                    
                for g_name, items in groups_in_stage.items():
                    typ_source += f"""
#rect(fill: rgb("{stage_info['color']}"), radius: 4pt, inset: (x: 10pt, y: 6pt))[
    #text(10pt, weight: "bold", fill: white, tracking: 1pt)[{g_name.upper()}]
]
#v(10pt)
"""
                    for item in items:
                        reason = clean_typography(item['Обоснование'])
                        crit = clean_typography(item['Критерий'])
                        typ_source += f"""
#block(breakable: false)[
    #grid(
        columns: (10pt, 1fr),
        gutter: 10pt,
        circle(radius: 3pt, fill: rgb("{stage_info['color']}")),
        [
            #text(12pt, weight: "bold", fill: rgb("0A1128"))[{crit}]
            #v(5pt)
            #set par(leading: 0.5em)
            #text(10.5pt, fill: rgb("475569"))[{reason}]
        ]
    )
]
#v(15pt)
"""
        if not failed_items: 
            typ_source += "\n#rect(stroke: (left: 4pt + rgb(\"16A34A\")), fill: rgb(\"F8FAFC\"), inset: 20pt)[#text(14pt, weight: \"bold\", fill: rgb(\"16A34A\"))[Ваш профиль идеален! Все этапы дорожной карты выполнены.]]\n"

    # --- УНИВЕРСАЛЬНЫЙ СИЛЬНЫЙ ОФФЕР (ДЛЯ LITE И PRO) ---
    typ_source += f"""
#pagebreak()
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Что делать дальше?]
#v(5pt)
#line(length: 80mm, stroke: 3pt + rgb("C5A880"))
#v(20pt)
#text(12pt, fill: rgb("475569"))[Выберите подходящий формат сотрудничества для кратного роста вашей выручки:]
#v(30pt)

#grid(
    columns: (1fr, 1fr),
    gutter: 20pt,
    row-gutter: 20pt,
    
    rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 12pt, inset: 25pt)[
        #text(10pt, fill: rgb("64748B"), weight: "bold", tracking: 1pt)[TRIPWIRE]
        #v(8pt)
        #text(16pt, weight: "bold", fill: rgb("0A1128"))[Глубокий аудит]
        #v(5pt)
        #text(20pt, weight: "bold", fill: rgb("C5A880"))[4 880 ₽]
        #v(15pt)
        #set par(leading: 0.5em)
        #text(11pt, fill: rgb("475569"))[Глубокий аудит и пошаговый план (для тех, кто хочет всё настраивать самостоятельно или проверить своего маркетолога).]
    ],
    
    rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 12pt, inset: 25pt)[
        #text(10pt, fill: rgb("64748B"), weight: "bold", tracking: 1pt)[CORE-ПРОДУКТ]
        #v(8pt)
        #text(16pt, weight: "bold", fill: rgb("0A1128"))[Базовая упаковка]
        #v(5pt)
        #text(20pt, weight: "bold", fill: rgb("C5A880"))[14 880 ₽]
        #v(15pt)
        #set par(leading: 0.5em)
        #text(11pt, fill: rgb("475569"))[Аудит + Базовая упаковка. Идеальный фундамент перед запуском Рекламной подписки Яндекса (мы сами исправляем всё, что нашли).]
    ],
    
    rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 12pt, inset: 25pt)[
        #text(10pt, fill: rgb("64748B"), weight: "bold", tracking: 1pt)[RECURRING]
        #v(8pt)
        #text(16pt, weight: "bold", fill: rgb("0A1128"))[ИИ-помощник]
        #v(5pt)
        #text(20pt, weight: "bold", fill: rgb("C5A880"))[3 880 ₽ / мес]
        #v(15pt)
        #set par(leading: 0.5em)
        #text(11pt, fill: rgb("475569"))[Системная защита рейтинга и умные ответы на все новые отзывы клиентов.]
    ],
    
    rect(width: 100%, fill: rgb("0A1128"), stroke: 1pt + rgb("0A1128"), radius: 12pt, inset: 25pt)[
        #text(10pt, fill: rgb("94A3B8"), weight: "bold", tracking: 1pt)[VIP]
        #v(8pt)
        #text(16pt, weight: "bold", fill: rgb("FFFFFF"))[Всё под ключ]
        #v(5pt)
        #text(20pt, weight: "bold", fill: rgb("C5A880"))[28 880 ₽ / мес]
        #v(15pt)
        #set par(leading: 0.5em)
        #text(11pt, fill: rgb("94A3B8"))[Всё под ключ с гарантией. Упаковка + ИИ-отзывы + стратегическое управление вашей Рекламной подпиской.]
    ]
)
#v(40pt)

#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 12pt, inset: 30pt)[
    #align(center)[
        #text(20pt, font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Готовы кратно увеличить поток клиентов?]
        #v(15pt)
        #text(12pt, fill: rgb("475569"))[Выберите тариф и напишите мне в Telegram кодовое слово *«{title_safe.upper()}»*.]
        #v(25pt)
        #link("https://t.me/paulvenkov")[
            #rect(fill: rgb("0A1128"), radius: 8pt, inset: (x: 30pt, y: 15pt))[
                #text(14pt, weight: "bold", fill: white, tracking: 0.5pt)[Написать в Telegram: \@paulvenkov]
            ]
        ]
        #v(20pt)
        #link("https://pin100.ru")[
            #underline[#text(12pt, fill: rgb("0A1128"), weight: "bold")[Перейти на сайт pin100.ru]]
        ]
    ]
]
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
# 6. СБОРКА И ИНТЕРФЕЙС (STREAMLIT)
# ==========================================
st.set_page_config(page_title=f"{PROJECT_NAME} | Экспертный Аудит", layout="wide", page_icon="📍")

rules_data, prompts_data = fetch_cached_database()

with st.sidebar: 
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База данных подключена (Кэш активен).")

st.title(f"📍 {PROJECT_NAME}: {EXPERT_TITLE}")
url = st.text_input("Ссылка на карточку Яндекс.Бизнес")

if st.button("🚀 Запустить генерацию отчетов", type="primary"):
    if "yandex" not in url.lower(): 
        st.error("❌ Неверная ссылка.")
    else:
        with st.spinner("Сбор свежих фактических данных..."):
            try: 
                data = fetch_apify_data(url)
            except Exception as e:
                st.error(f"⚠️ {str(e)}")
                st.stop()
                
            title = data.get('title', 'Без названия')
            c_list = data.get('categories', [])
            cat = c_list[0].get('name', '') if c_list and isinstance(c_list[0], dict) else (str(c_list[0]) if c_list else '')
            client_reviews = int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []) or 0)
            
        with st.spinner("Экспертная оценка и расчет экономики..."):
            try: niche_key = determine_niche_by_expert(title, cat, prompts_data)
            except: niche_key = "OTHER"
            
            raw_scores = calculate_hard_facts(data)
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
                reason_error = str(r.get('Обоснование_ОШИБКИ', '')).strip() or f"Отсутствие параметра «{name}» пессимизирует карточку и лишает вас органического трафика."
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
                        
                        if raw_scores.get('META_NO_RECENT_REVIEWS') and group == 'Репутация' and code not in ['REP-27.1', 'REP-27.2', 'REP-28.1', 'REP-83.1', 'REP-85.1']:
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

            # АВТОСОХРАНЕНИЕ В GOOGLE SHEETS
            save_audit_to_sheets(url, title, niche_key, final_total_score, results)

            eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
            niche_label = eco.get("label", "Прочее")
            
            with st.sidebar:
                st.divider()
                st.markdown(f"### 🧮 Калькулятор: {niche_key}")
                client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
                client_check = st.number_input("Средний чек (₽)", value=eco["check"], step=5000)

            lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
            lost_revenue = int(client_leads * lost_percentage * client_check)
            
            st.divider()
            col1, col2 = st.columns([2, 1])
            with col1: 
                st.subheader(f"🏢 {title}")
                st.caption(f"🧠 Сегмент: **{niche_label}** | 📍 Фактических отзывов: {client_reviews}")
            with col2: 
                delta = "Отличный результат" if final_total_score >= 80 else ("Требует оптимизации" if final_total_score >= 50 else "Критический уровень")
                st.metric(f"Индекс {PROJECT_NAME}", f"{round(final_total_score, 1)} / 100", delta=delta, delta_color="normal" if final_total_score>=80 else "inverse")

            st.error(f"Потери: **{lost_revenue:,} ₽** ежемесячно.".replace(',', ' '))
            
            with st.expander("🛠 Режим разработчика: Сырой JSON от Яндекса (Проверка на галлюцинации)"):
                json_string = json.dumps(data, ensure_ascii=False, indent=4)
                st.download_button(
                    label="💾 Скачать сырой JSON",
                    data=json_string,
                    file_name=f"{title.replace(' ', '_')}_yandex_data.json",
                    mime="application/json"
                )
                st.json(data)

            st.divider()
            st.markdown("### 📥 Выгрузка отчетов")
            
            pdf_lite_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, report_type="LITE")
            pdf_pro_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, report_type="PRO")
            
            col_lite, col_pro = st.columns(2)
            with col_lite:
                if pdf_lite_bytes:
                    st.download_button(label="📄 Скачать Экспресс-аудит (LITE)", data=pdf_lite_bytes, file_name=f"PIN100_LITE_{title.replace(' ', '_')}.pdf", mime="application/pdf")
            with col_pro:
                if pdf_pro_bytes:
                    st.download_button(label="💎 Скачать PRO-аудит", data=pdf_pro_bytes, file_name=f"PIN100_PRO_{title.replace(' ', '_')}.pdf", mime="application/pdf", type="primary")

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
