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
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
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
# 1.5. БАЗА ДАННЫХ НИШ И БЕНЧМАРКОВ
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

def determine_niche_by_expert(title, category):
    if not expert_engine: raise Exception("Модуль экспертной оценки не инициализирован.")
    prompt = f"""Проведи экспертную оценку бизнеса по названию "{title}" и категории "{category}".
ВНИМАНИЕ: Если в категории есть слова "стоматология", "клиника", "медицина", "красота", "салон" - это СТРОГО BEAUTY_MEDICAL.
Определи ОДИН наиболее подходящий сегмент: HORECA, B2B, RETAIL, AUTO, SERVICES, BEAUTY_MEDICAL, OTHER.
Верни ТОЛЬКО ОДНО СЛОВО - ключ на английском."""
    try:
        response = expert_engine.generate_content(prompt)
        key = response.text.strip().upper()
        for v in ["BEAUTY_MEDICAL", "HORECA", "B2B", "RETAIL", "AUTO", "SERVICES", "OTHER"]:
            if v in key: return v
        return "OTHER"
    except Exception as e:
        raise Exception(f"Сбой модуля экспертной оценки (Ниша): {str(e)}")

# ==========================================
# 2. ПАРСЕР GOOGLE ТАБЛИЦЫ И APIFY
# ==========================================
@st.cache_resource(ttl=600) 
def init_google_sheets():
    try:
        creds_str = st.secrets.get("GCP_CREDENTIALS", "{}")
        creds_dict = json.loads(creds_str)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(credentials).open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"Ошибка подключения к Google Sheets: {e}")
        st.stop()

def get_database_from_sheets():
    doc = init_google_sheets()
    raw_rules = doc.worksheet("Rules").get_all_values()
    headers_rules = raw_rules[0]
    rules = [dict(zip(headers_rules, row)) for row in raw_rules[1:] if any(row)]
    
    raw_prompts = doc.worksheet("Prompts").get_all_values()
    headers_prompts = raw_prompts[0]
    prompts = [dict(zip(headers_prompts, row)) for row in raw_prompts[1:] if any(row)]
    
    return rules, prompts, doc

def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: 
        err_msg = f"Ошибка Apify API: {run_req['error']}"
        send_telegram_alert(err_msg, yandex_url)
        raise Exception(err_msg)
        
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: 
            err_msg = "Таймаут парсера Apify (Яндекс слишком долго отвечает)."
            send_telegram_alert(err_msg, yandex_url)
            raise Exception(err_msg)
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": 
        err_msg = f"Парсер упал со статусом {status}."
        send_telegram_alert(err_msg, yandex_url)
        raise Exception(err_msg)
        
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset: 
        err_msg = "Яндекс отдал пустой результат (сработала капча или блокировка парсера)."
        send_telegram_alert(err_msg, yandex_url)
        raise Exception(err_msg)
        
    data = dataset[0]
    if not data.get('title') or len(str(data.get('title'))) < 2:
        err_msg = "Яндекс вернул пустую заглушку вместо реальной карточки бизнеса. Вероятно, включилась защита от ботов."
        send_telegram_alert(err_msg, yandex_url)
        raise Exception(err_msg)
        
    return data

# ==========================================
# 3. АЛГОРИТМЫ ОЦЕНКИ PIN100
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
    except:
        return None

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
        if latest_date and (now - latest_date).days <= 14:
            scores['REP-29.1'] = True
            
        for r in recent_reviews[:20]:
            r_rating = float(r.get('rating') or 0.0)
            reply_text = str(r.get('businessComment') or r.get('reply', {}).get('text') or '').strip()
            
            if reply_text:
                replied += 1
                if r_rating >= 4.0: has_positive_replied = True
                
                bc_date = parse_yandex_date(r.get('businessCommentDate'))
                rev_date = parse_yandex_date(r.get('date'))
                if bc_date and rev_date and (bc_date - rev_date).days <= 3:
                    scores['REP-30.2'] = True
            else:
                if r_rating <= 3.0: has_unanswered_negative = True
                
        if len(recent_reviews[:20]) > 0:
            if replied / len(recent_reviews[:20]) >= 0.9: scores['REP-30.1'] = True
            photos_in_revs = sum(1 for r in recent_reviews[:20] if r.get('photos') or r.get('photoDetails'))
            if photos_in_revs / len(recent_reviews[:20]) >= 0.1: scores['REP-35.1'] = True
            
        if has_positive_replied: scores['REP-30.3'] = True
        if not has_unanswered_negative: scores['REP-32.1'] = True
        
    return scores

def calculate_dynamic_expert_rules(data, prompts_data, target_url):
    scores = {}
    if not expert_engine or not prompts_data: return scores
    
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')[:1000]
    
    now = datetime.now(timezone.utc)
    six_months_ago = now - timedelta(days=180)
    recent_reviews = []
    for r in data.get('reviews') or []:
        r_date = parse_yandex_date(r.get('date'))
        if r_date and r_date >= six_months_ago:
            recent_reviews.append(r)
            
    reviews_text = ""
    for r in recent_reviews[:10]:
        if isinstance(r, dict):
            u_text = r.get('text', '')
            o_reply = r.get('businessComment') or r.get('reply', {}).get('text') if isinstance(r.get('reply'), dict) else ''
            reviews_text += f"Отзыв: {u_text}\nОтвет владельца: {o_reply}\n---\n"
            
    prods = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    prods_text = ", ".join([str(p.get('name')) for p in prods if isinstance(p, dict)][:20])

    rules_list = [f'"{p.get("Код", "").strip()}": {p.get("Промпт для ИИ", "").strip()}' for p in prompts_data if p.get('Код', '').strip()]
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

ВНИМАНИЕ! Ты - строгий аудитор. 
Верни строго JSON формата {{"CODE": true/false}}. 
В ответе ОБЯЗАТЕЛЬНО должны присутствовать абсолютно все {len(rules_list)} кодов из списка критериев. Не теряй ни одной метрики. Никакого текста, кроме JSON.
"""
    try:
        response = expert_engine.generate_content(batch_prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
            for code, result in res_json.items():
                if str(result).lower() in ["1", "true"]: scores[code] = True
        else:
            raise ValueError("Ответ ИИ не содержит валидного JSON.")
    except Exception as e:
        err_msg = f"Сбой обработки Gemini (AI): {str(e)}"
        send_telegram_alert(err_msg, target_url)
        st.warning(f"🤖 **ИИ временно недоступен:** {err_msg}. Сложные метрики не были оценены.")
    return scores

# ==========================================
# 3.5. TYPST: ГЕНЕРАЦИЯ ПРЕМИУМ PDF
# ==========================================
def clean_typography(text):
    """Филологическая очистка текстов: тире, запятые и безопасный код для Typst"""
    t = str(text)
    t = t.replace(" это ", " — это ")
    t = t.replace(" реквизитов красный ", " реквизитов — красный ")
    t = t.replace("сегодня вы", "сегодня, вы")
    t = t.replace("капитал за счет", "капитал, за счет")
    t = t.replace("описание это", "описание — это")
    t = t.replace("контакты это", "контакты — это")
    t = t.replace("записи это", "записи — это")
    
    # Экранируем символы, которые могут сломать синтаксис Typst
    t = t.replace('[', '\\[').replace(']', '\\]').replace('"', '\\"').replace('#', '\\#')
    return t

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, report_type="PRO"):
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    score_color = "16A34A" if score >= 80 else ("C5A880" if score >= 50 else "DC2626")
    dev = round(100 - score, 1)
    lost_clients = int(round(dev / 10))
    lost_leads = int(client_leads * (dev / 100))
    ltv_loss = revenue_loss * 12
    
    # Форматируем числа безопасно, чтобы не сломать запятыми синтаксис внутри Typst
    rev_loss_fmt = f"{revenue_loss:,}".replace(',', ' ')
    cc_fmt = f"{client_check:,}".replace(',', ' ')
    ltv_loss_fmt = f"{ltv_loss:,}".replace(',', ' ')
    
    rev_str = f"- {rev_loss_fmt} ₽ / мес"
    
    title_safe = str(title).replace('"', '').replace('[', '').replace(']', '').replace('\\', '').replace('#', '')
    doc_title = "Экспресс-аудит#linebreak()упущенной выручки" if report_type == "LITE" else "Экспертный аудит#linebreak()упущенной выручки"

    typ_source = f"""
#set document(title: "Аудит PIN100 - {title_safe}", author: "PIN100 Analytics")
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

#set text(font: ("Inter", "Arial", "sans-serif"), size: 11pt, fill: rgb("334155"), lang: "ru")
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// --- ОБЛОЖКА ---
#v(150pt)
#text(16pt, fill: rgb("C5A880"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(10pt)
#text(38pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[{doc_title}]
#v(10pt)
#line(length: 80mm, stroke: 3pt + rgb("C5A880"))
#v(30pt)
#text(14pt, fill: rgb("475569"))[
  Подготовлено для бизнеса: #strong(text(fill: rgb("0A1128"))[{title_safe}]) #linebreak()
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

    # --- ВОРОНКА ---
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

        # --- СИЛЬНЫЙ ОФФЕР ---
        typ_source += f"""
#pagebreak()
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Что делать дальше?]
#v(5pt)
#line(length: 80mm, stroke: 3pt + rgb("C5A880"))
#v(20pt)
#text(12pt, fill: rgb("475569"))[Вы получили подробный Экшн-план по захвату органического трафика. У вас есть два пути реализации:]
#v(30pt)

#grid(
    columns: (1fr, 1fr),
    gutter: 20pt,
    rect(width: 100%, fill: rgb("F8FAFC"), stroke: (top: 6pt + rgb("94A3B8"), bottom: 1pt + rgb("E2E8F0"), left: 1pt + rgb("E2E8F0"), right: 1pt + rgb("E2E8F0")), radius: 12pt, inset: 25pt)[
        #text(16pt, weight: "bold", fill: rgb("64748B"))[Путь 1: Самостоятельно]
        #v(20pt)
        #set list(marker: text(fill: rgb("94A3B8"))[•])
        #set par(leading: 0.5em)
        #text(11pt, fill: rgb("475569"))[
          - Передать этот документ вашему маркетологу или ассистенту.
          - Потратить 30-45 дней на погружение в алгоритмы геосервисов.
          - Взять на себя риски прохождения модерации Яндекса.
        ]
    ],
    rect(width: 100%, fill: rgb("0A1128"), stroke: (top: 6pt + rgb("C5A880"), bottom: 1pt + rgb("0A1128"), left: 1pt + rgb("0A1128"), right: 1pt + rgb("0A1128")), radius: 12pt, inset: 25pt)[
        #text(16pt, weight: "bold", fill: rgb("C5A880"))[Путь 2: Сделаем за вас]
        #v(20pt)
        #set list(marker: text(fill: rgb("C5A880"))[✓])
        #set par(leading: 0.5em)
        #text(11pt, fill: rgb("F8FAFC"))[
          - Наша команда экспертов берет на себя *100% рутины*.
          - Внедряем Экшн-план за *5-7 дней под ключ*. Вы платите за результат, а не за часы работы.
          - Гарантия прохождения модерации и защита от теневых банов.
        ]
    ]
)
#v(40pt)

#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1pt + rgb("E2E8F0"), radius: 12pt, inset: 30pt)[
    #align(center)[
        #text(20pt, font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Готовы остановить потерю лидов?]
        #v(15pt)
        #text(12pt, fill: rgb("475569"))[Напишите мне в Telegram кодовое слово *«{title_safe.upper()}»*, и я пришлю вам 3 ключевых шага, которые мы внедрим в первые 24 часа работы.]
        #v(25pt)
        #rect(fill: rgb("0A1128"), radius: 8pt, inset: (x: 30pt, y: 15pt))[
            #text(14pt, weight: "bold", fill: white, tracking: 0.5pt)[Telegram: @paulvenkov | pin100.ru]
        ]
    ]
]
"""

    # --- LITE ОФФЕР ---
    if report_type == "LITE":
        typ_source += """
#pagebreak()
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Почему вам нужен PRO-аудит?]
#v(5pt)
#line(length: 80mm, stroke: 3pt + rgb("C5A880"))
#v(20pt)

#set par(leading: 0.6em)
#text(12pt, fill: rgb("475569"))[В экспресс-версии мы подсветили лишь верхушку айсберга и показали реальную цифру ваших потерь. PRO-аудит — это инструмент тотального контроля и ваш пошаговый план по захвату топа в геосервисах.]
#v(20pt)

#rect(width: 100%, fill: rgb("F8FAFC"), stroke: (left: 4pt + rgb("C5A880"), top: 1pt + rgb("E2E8F0"), bottom: 1pt + rgb("E2E8F0"), right: 1pt + rgb("E2E8F0")), inset: 20pt, radius: 4pt)[
    #text(12pt, weight: "bold", fill: rgb("0A1128"))[Независимый контроль подрядчиков:]
    #linebreak()
    #v(5pt)
    #set par(leading: 0.5em)
    #text(11pt, fill: rgb("475569"))[Узнайте реальное положение дел без «розовых очков» маркетинговых агентств. Отчет покажет, за что вы платите деньги и где подрядчики недорабатывают.]
]
#v(30pt)

#text(18pt, font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Что внутри PRO-версии:]
#v(15pt)
#set list(marker: text(fill: rgb("0A1128"))[•])
#set par(leading: 0.6em)
#text(11.5pt, fill: rgb("334155"))[
  - *Полная декомпозиция:* Разбор, значение и объяснение всех параметров ранжирования Яндекса для вашей карточки.
  - *Дорожная карта:* Пошаговый Экшн-план исправления ошибок по дням.
  - *Скрытые лайфхаки:* Практические фишки алгоритмов, которые знают только топ-5% бизнесов в топе выдачи.
]
#v(30pt)

#rect(width: 100%, fill: rgb("0A1128"), radius: 12pt, inset: 30pt)[
    #text(12pt, fill: rgb("94A3B8"), weight: "bold", tracking: 1pt)[ИНВЕСТИЦИЯ В РОСТ:]
    #v(10pt)
    #text(32pt, weight: "bold", fill: rgb("C5A880"))[4 880 ₽]
    #v(15pt)
    #line(length: 100%, stroke: 1pt + rgb("334155"))
    #v(15pt)
    #text(11pt, fill: rgb("F1F5F9"))[🎁 *Бонус:* Если вы решите делегировать работу профессионалам и закажете заполнение карточки у нашей команды, мы полностью вычтем стоимость этого аудита из чека.]
]

#v(20pt)
#text(10pt, fill: rgb("94A3B8"), style: "italic")[* Мы ценим ваш комфорт: никаких спам-рассылок, холодных прозвонов и агрессивных продаж. Вы обращаетесь к нам, только если сами надумаете.]

#v(40pt)
#align(center)[
    #text(12pt, fill: rgb("475569"))[Запросить полную версию без обязательств:]
    #v(15pt)
    #rect(stroke: 2pt + rgb("0A1128"), radius: 8pt, inset: (x: 30pt, y: 15pt))[
        #text(14pt, weight: "bold", fill: rgb("0A1128"))[Telegram: @paulvenkov | pin100.ru]
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
# 4. СБОРКА И ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title=f"{PROJECT_NAME} | Экспертный Аудит", layout="wide", page_icon="📍")
rules_data, prompts_data, doc_sheets = get_database_from_sheets()

with st.sidebar: 
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База бенчмарков подключена.")

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
            try: niche_key = determine_niche_by_expert(title, cat)
            except: niche_key = "OTHER"
            
            raw_scores = calculate_hard_facts(data)
            exp_sc = calculate_dynamic_expert_rules(data, prompts_data, url)
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
