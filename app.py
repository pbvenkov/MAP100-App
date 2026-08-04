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
from weasyprint import HTML
import base64

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
    
    # PROF-01.1: Название
    if data.get('isVerifiedOwner') or len(title) > 2: scores['PROF-01.1'] = True
    
    # PROF-03.1: Категории
    if data.get('categories'): scores['PROF-03.1'] = True
    
    # PROF-04.1: Ссылка на сайт
    url = str(data.get('url') or data.get('website') or '').lower()
    if url: scores['PROF-04.1'] = True
    
    # PROF-05.1 и 05.2: Телефон и его формат
    phones = data.get('phones') or []
    if phones: 
        scores['PROF-05.1'] = True
        if any(str(p).startswith('+7') or str(p).startswith('8') for p in phones):
            scores['PROF-05.2'] = True
        
    # PROF-07.1: График работы
    schedule = data.get('schedule') or data.get('workingHours') or []
    if isinstance(schedule, list) and len(schedule) >= 7: scores['PROF-07.1'] = True
    elif isinstance(schedule, dict) and len(schedule.keys()) >= 7: scores['PROF-07.1'] = True
    
    # PROF-08.1: Атрибуты (Особенности) - обработка словаря
    features = data.get('features')
    if isinstance(features, dict) and len(features.keys()) > 0: scores['PROF-08.1'] = True
    elif isinstance(features, list) and len(features) > 0: scores['PROF-08.1'] = True
    
    # PROF-09.1: Длина описания
    if len(desc) > 1500: scores['PROF-09.1'] = True
    
    # PROF-12.1: Синяя Галочка
    if data.get('isVerifiedOwner'): scores['PROF-12.1'] = True
    
    # PROF-13.1, PROF-13.2: Мессенджеры и Соцсети
    links_data = data.get('socialLinks') or data.get('links') or []
    owner_links = url + " " + desc + " " + " ".join([str(l) for l in links_data])
    if any(s in owner_links.lower() for s in ["t.me", "wa.me", "whatsapp", "viber"]): scores['PROF-13.1'] = True
    if any(s in owner_links.lower() for s in ["vk.com", "youtube", "dzen", "instagram", "inst:"]): scores['PROF-13.2'] = True
    
    # КАТАЛОГ ТОВАРОВ (PROF-11.1 - 11.5)
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
        
    # SEO-18.1: Адрес
    addr = str(data.get('address') or '')
    if len(addr) > 5: scores['SEO-18.1'] = True
    
    # ВИЗУАЛ И АКТИВНОСТЬ
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
            
    # РЕПУТАЦИЯ (Отзывы, Охват, Негатив)
    rating = float(data.get('rating') or 0.0)
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    
    rev_count = int(data.get('reviewsCount') or data.get('ratingsCount') or data.get('reviewCount') or 0)
    if rev_count >= 50: scores['REP-28.1'] = True
    
    # Пагинация и 6-месячный фильтр
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
# 3.5. WEASYPRINT: ГЕНЕРАЦИЯ ПРЕМИУМ PDF
# ==========================================
def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, report_type="PRO"):
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    score_class = "text-success" if score >= 80 else ("text-gold" if score >= 50 else "text-error")
    dev = round(100 - score, 1)
    lost_clients = int(round(dev / 10))
    lost_leads = int(client_leads * (dev / 100))
    ltv_loss = revenue_loss * 12
    rev_str = f"- {revenue_loss:,}".replace(',', ' ') + " ₽ / мес"

    logo_b64 = ""
    logo_path = "logo.png" if os.path.exists("logo.png") else ("PIN100 big logo.png" if os.path.exists("PIN100 big logo.png") else None)
    if logo_path:
        try:
            with open(logo_path, "rb") as img_file:
                logo_b64 = base64.b64encode(img_file.read()).decode('utf-8')
        except: pass

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Playfair+Display:wght@700&display=swap');
            
            @page {{
                size: A4; margin: 25mm 20mm;
                @bottom-left {{ content: "PIN100 Analytics | Строго конфиденциально"; font-family: 'Inter', sans-serif; font-size: 8.5pt; color: #94A3B8; }}
                @bottom-right {{ content: "Стр. " counter(page); font-family: 'Inter', sans-serif; font-size: 8.5pt; color: #94A3B8; }}
            }}
            body {{ font-family: 'Inter', sans-serif; color: #334155; font-size: 11pt; line-height: 1.6; }}
            h1, h2, h3, .playfair {{ font-family: 'Playfair Display', serif; color: #0A1128; }}
            
            /* Cover */
            .cover-page {{ margin-top: 200px; }}
            .cover-logo {{ font-size: 16pt; font-weight: bold; font-family: 'Playfair Display', serif; color: #C5A880; margin-bottom: 50px; letter-spacing: 2px; text-transform: uppercase; }}
            .cover-title {{ font-size: 38pt; line-height: 1.15; margin-bottom: 30px; }}
            .gold-line-large {{ width: 80mm; height: 3px; background-color: #C5A880; margin-bottom: 40px; }}
            .cover-subtitle {{ font-size: 14pt; color: #475569; line-height: 1.6; }}
            
            /* Typography & Blocks */
            h2 {{ font-size: 24pt; margin-bottom: 25px; padding-bottom: 10px; border-bottom: 2px solid #C5A880; page-break-after: avoid; }}
            .bento-container {{ width: 100%; margin-bottom: 25px; border-collapse: separate; border-spacing: 0; }}
            .bento-box {{ background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 25px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); }}
            .bento-title {{ font-size: 11pt; color: #64748B; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
            .bento-value {{ font-size: 28pt; font-weight: 700; }}
            
            /* Colors */
            .text-success {{ color: #16A34A; }} .text-error {{ color: #DC2626; }} .text-gold {{ color: #C5A880; }} .text-navy {{ color: #0A1128; }}
            
            /* Layout */
            .page-break {{ page-break-before: always; }}
            .avoid-break {{ page-break-inside: avoid; }}
            
            /* Roadmap Items */
            .group-badge {{ display: inline-block; background: #0A1128; color: #FFFFFF; padding: 6px 16px; border-radius: 4px; font-size: 10.5pt; font-weight: 600; margin-bottom: 15px; margin-top: 25px; text-transform: uppercase; letter-spacing: 1px; }}
            .roadmap-item {{ margin-bottom: 20px; padding-left: 20px; border-left: 3px solid #E2E8F0; }}
            .roadmap-title {{ font-weight: 700; color: #0F172A; font-size: 12pt; margin-bottom: 6px; }}
            .roadmap-desc {{ font-size: 10.5pt; color: #475569; line-height: 1.5; }}
            
            .watermark {{ position: fixed; top: 0; right: 0; width: 40mm; opacity: 0.02; z-index: -1000; }}
        </style>
    </head>
    <body>
    """

    if logo_b64:
        html += f'<img src="data:image/png;base64,{logo_b64}" class="watermark">'

    doc_title = 'Экспресс-аудит<br>упущенной выручки' if report_type == "LITE" else 'Экспертный аудит<br>упущенной выручки'
    
    # Cover Page
    html += f"""
        <div class="cover-page">
            <div class="cover-logo">PIN100 Analytics</div>
            <h1 class="cover-title">{doc_title}</h1>
            <div class="gold-line-large"></div>
            <div class="cover-subtitle">
                Подготовлено для бизнеса: <b style="color: #0A1128;">{title}</b><br>
                Дата аудита: <b>{current_date}</b>
            </div>
        </div>
        <div class="page-break"></div>
        
        <h2>Резюме для руководителя</h2>
        <div class="bento-box"><div class="bento-title">Индекс готовности профиля:</div><div class="bento-value {score_class}">{round(score, 1)} / 100</div></div>
        <div class="bento-box"><div class="bento-title">Упущенная выручка (Lost Revenue):</div><div class="bento-value text-error">{rev_str}</div></div>
        <p style="font-size: 12pt; line-height: 1.6; margin-top: 30px;"><b>Вывод эксперта:</b> Отличное качество вашего продукта теряется из-за слабого присутствия в геосервисах. Из-за критических ошибок в заполнении карточки и отсутствии системной работы с отзывами вы уступаете позиции в поиске и ежемесячно отдаете горячих клиентов своим конкурентам.</p>
        <div class="page-break"></div>
        
        <h2>Декомпозиция потерь</h2>
    """
    
    blocks_fin = [
        ("А. Видимость бизнеса (Кто забирает клиентов)", f"Ваш профиль соответствует стандартам площадки лишь на <b>{round(score, 1)}%</b>. В реалиях алгоритмов Яндекса это означает, что из каждых 10 человек, которые прямо сейчас ищут ваши услуги, <b>{lost_clients}</b> до вас просто не доходят. Они видят в топе конкурентов с более грамотно упакованными карточками и оставляют деньги там."),
        ("Б. Цена простоя (Ваши прямые убытки)", f"В вашей нише через геосервисы ежемесячно проходит около <b>{client_leads}</b> целевых запросов. Из-за пробелов в оптимизации профиля мимо вас проходит порядка <b>{lost_leads}</b> сделок. При вашем среднем чеке ({client_check:,} ₽) это превращается в кассовый разрыв на <b class='text-error'>{revenue_loss:,} ₽</b> каждый месяц.".replace(',', ' ')),
        ("В. Скрытая угроза (Недополученный LTV)", f"Привлеченный клиент — это не разовая сделка, он остается с бизнесом надолго (в среднем от 12 месяцев). Упуская заказчиков сегодня, вы лишаете компанию будущих регулярных платежей. В годовом выражении эта недополученная выручка достигает <b class='text-error'>{ltv_loss:,} ₽</b>. Это капитал, за счет которого прямо сейчас масштабируются ваши конкуренты.".replace(',', ' '))
    ]
    
    for bt, text in blocks_fin:
        html += f"""
        <div class="avoid-break" style="margin-bottom: 35px;">
            <div style="font-family: 'Playfair Display', serif; font-size: 16pt; color: #0A1128; margin-bottom: 8px;">{bt}</div>
            <div style="width: 40mm; height: 2px; background-color: #C5A880; margin-bottom: 15px;"></div>
            <p style="color: #475569;">{text}</p>
        </div>
        """
    
    html += '<div class="page-break"></div><h2>Аналитика воронки продаж</h2><p style="margin-bottom: 35px; color: #475569; font-size: 11.5pt;">Ниже представлена оцифровка вашего профиля по ключевым этапам конверсии.</p>'
    
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
        bar_color = "#16A34A" if percentage >= 80 else ("#C5A880" if percentage >= 50 else "#DC2626")

        html += f"""
        <div class="bento-box avoid-break">
            <table style="width: 100%; border: none; margin-bottom: 12px;">
                <tr>
                    <td style="text-align: left; padding: 0;"><span style="font-size: 14pt; font-weight: 700; font-family: 'Playfair Display', serif; color: #0A1128;">{block['title']}</span></td>
                    <td style="text-align: right; padding: 0;"><span style="font-size: 14pt; font-weight: 700; color: {bar_color};">{round(earned_score, 1)} / {round(max_score, 1)}</span></td>
                </tr>
            </table>
            <div style="background: #F1F5F9; width: 100%; height: 10px; border-radius: 5px; margin-bottom: 15px;">
                <div style="background: {bar_color}; width: {percentage}%; height: 10px; border-radius: 5px;"></div>
            </div>
            <p style="margin-bottom: 0; font-size: 10.5pt; color: #64748B; line-height: 1.5;"><i>{block['desc']}</i></p>
        </div>
        """

    # --- ДОРОЖНАЯ КАРТА (ТОЛЬКО ДЛЯ PRO) ---
    if report_type == "PRO":
        html += """<div class="page-break"></div><h1 style="margin-top: 20px;">Пошаговая дорожная карта</h1><div class="gold-line-large"></div><p style="font-size: 12pt; margin-bottom: 35px; color: #475569;">Мы собрали все выявленные уязвимости и распределили их по приоритету. Следуйте этому Экшн-плану, чтобы за 30 дней забрать максимум органического трафика в вашей нише.</p>"""
        stages = {
            1: {"title": "Этап 1: Быстрые победы (Дни 1-3)", "desc": "Срочные исправления. Эти ошибки сжигают вашу конверсию прямо сейчас.", "color": "#DC2626"},
            2: {"title": "Этап 2: Упаковка смыслов (Дни 4-14)", "desc": "Базовое заполнение. Сделайте профиль понятным и привлекательным для клиента.", "color": "#C5A880"},
            3: {"title": "Этап 3: Масштабирование (Дни 15-30)", "desc": "Работа с репутацией и скрытыми алгоритмами Яндекса для захвата топа.", "color": "#16A34A"}
        }
        failed_items = [i for i in results_data if i['Результат'] == 'НЕТ']
        for stage_num, stage_info in stages.items():
            stage_items = [i for i in failed_items if i.get('Этап', 3) == stage_num]
            if stage_items:
                html += f"""<div class="avoid-break" style="margin-bottom: 40px;"><h2 style="color: {stage_info['color']}; border-bottom-color: {stage_info['color']}; font-size: 22pt;">{stage_info['title']}</h2><p style="font-size: 11.5pt; margin-bottom: 25px; color: #475569;"><i>{stage_info['desc']}</i></p>"""
                groups_in_stage = {}
                for item in stage_items:
                    g = item['Группа']
                    if g not in groups_in_stage: groups_in_stage[g] = []
                    groups_in_stage[g].append(item)
                for g_name, items in groups_in_stage.items():
                    html += f"""<div style="margin-bottom: 30px;"><div class="group-badge" style="background-color: {stage_info['color']};">{g_name}</div>"""
                    for item in items:
                        html += f"""<div class="roadmap-item avoid-break"><div class="roadmap-title">{item['Критерий']}</div><div class="roadmap-desc">{item['Обоснование']}</div></div>"""
                    html += "</div>"
                html += "</div>"
        if not failed_items: html += "<div class='bento-box avoid-break' style='border-left: 4px solid #16A34A;'><p style='color: #16A34A; font-weight: bold; font-size: 14pt; margin: 0;'>Ваш профиль идеален! Все этапы дорожной карты выполнены.</p></div>"

        # CLOSING OFFER
        html += """
        <div class="page-break"></div>
        <h1 style="margin-top: 50px;">Что делать дальше?</h1>
        <div class="gold-line-large"></div>
        <p style="font-size: 12pt; margin-bottom: 40px; color: #475569;">Вы получили подробный Экшн-план по захвату органического трафика. У вас есть два пути реализации:</p>

        <table style="width: 100%; border-collapse: separate; border-spacing: 20px 0; margin-left: -20px; margin-bottom: 50px; page-break-inside: avoid;">
            <tr>
                <td style="width: 50%; padding: 30px; background: #F8FAFC; border-radius: 12px; border-top: 6px solid #94A3B8; vertical-align: top;">
                    <h3 style="margin-top: 0; color: #64748B; font-family: 'Inter', sans-serif; font-size: 16pt;">Путь 1: Самостоятельно</h3>
                    <ul style="padding-left: 20px; font-size: 11pt; color: #475569; line-height: 1.6; margin-bottom: 0;">
                        <li style="margin-bottom: 10px;">Передать этот документ вашему маркетологу или ассистенту.</li>
                        <li style="margin-bottom: 10px;">Потратить 30-45 дней на погружение в алгоритмы геосервисов.</li>
                        <li>Взять на себя риски прохождения модерации Яндекса.</li>
                    </ul>
                </td>
                <td style="width: 50%; padding: 30px; background: #0A1128; border-radius: 12px; border-top: 6px solid #C5A880; vertical-align: top;">
                    <h3 style="margin-top: 0; color: #C5A880; font-family: 'Inter', sans-serif; font-size: 16pt;">Путь 2: Сделаем за вас</h3>
                    <ul style="padding-left: 20px; font-size: 11pt; color: #F8FAFC; line-height: 1.6; margin-bottom: 0;">
                        <li style="margin-bottom: 10px;">Наша команда экспертов берет на себя <b>100% рутины</b>.</li>
                        <li style="margin-bottom: 10px;">Внедрение всей Дорожной карты за <b>5-7 дней</b> без вашего участия.</li>
                        <li>Гарантия прохождения модерации и защита от теневых банов.</li>
                    </ul>
                </td>
            </tr>
        </table>

        <div class="avoid-break" style="background: #F8FAFC; border: 1px solid #E2E8F0; text-align: center; padding: 40px 20px; border-radius: 12px;">
            <div style="font-size: 20pt; font-family: 'Playfair Display', serif; margin-bottom: 15px; color: #0A1128;">Готовы делегировать и получать горячие лиды?</div>
            <p style="font-size: 12pt; color: #475569; margin-bottom: 30px;">Свяжитесь с нами для бесплатной консультации и оценки сроков внедрения.</p>
            <div style="display: inline-block; background: #0A1128; color: #FFF; padding: 15px 30px; border-radius: 8px; font-size: 14pt; font-weight: 700; letter-spacing: 0.5px;">Telegram: @paulvenkov | pin100.ru</div>
        </div>
        """

    # --- ОФФЕР (ТОЛЬКО ДЛЯ LITE) ---
    if report_type == "LITE":
        html += f"""
            <div class="page-break"></div>
            <h1 style="margin-top: 50px;">Почему вам нужен<br>PRO-аудит?</h1>
            <div class="gold-line-large"></div>
            
            <p style="font-size: 12pt; margin-bottom: 30px; color: #475569; line-height: 1.6;">
                В экспресс-версии мы подсветили лишь верхушку айсберга и показали реальную цифру ваших потерь. PRO-аудит — это инструмент тотального контроля и ваш пошаговый план по захвату топа в геосервисах.
            </p>
            
            <div class="bento-box avoid-break" style="border-left: 4px solid #C5A880; margin-bottom: 40px;">
                <b style="color: #0A1128; font-size: 12pt;">Независимый контроль подрядчиков:</b><br>
                Узнайте реальное положение дел без «розовых очков» маркетинговых агентств. Отчет покажет, за что вы платите деньги и где подрядчики недорабатывают.
            </div>

            <h3 style="color: #0A1128; font-family: 'Playfair Display', serif; font-size: 18pt; margin-bottom: 20px;">Что внутри PRO-версии:</h3>
            <ul style="margin-bottom: 40px; line-height: 1.8; color: #334155; font-size: 11.5pt;">
                <li><b>Полная декомпозиция:</b> Разбор, значение и объяснение всех 79 параметров ранжирования Яндекса для вашей карточки.</li>
                <li><b>Дорожная карта:</b> Пошаговый Экшн-план исправления ошибок по дням (от критических и срочных до долгосрочных).</li>
                <li><b>Скрытые лайфхаки:</b> Практические фишки алгоритмов, которые знают только топ-5% бизнесов в топе выдачи.</li>
            </ul>
            
            <div class="bento-box avoid-break" style="background: #0A1128; color: #FFF; border: none;">
                <div style="font-size: 12pt; color: #94A3B8; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;">Инвестиция в рост:</div>
                <div style="font-size: 32pt; font-weight: 700; color: #C5A880; margin-bottom: 15px;">4 880 ₽</div>
                <p style="font-size: 10.5pt; color: #F1F5F9; line-height: 1.5; padding-top: 15px; border-top: 1px solid #334155;">
                    🎁 <b>Бонус:</b> Если вы решите делегировать работу профессионалам и закажете заполнение карточки у нашей команды, мы полностью вычтем стоимость этого аудита из чека.
                </p>
            </div>
            
            <p style="font-size: 10pt; color: #94A3B8; font-style: italic; margin-bottom: 30px; margin-top: 20px;">
                * Мы ценим ваш комфорт: никаких спам-рассылок, холодных прозвонов и агрессивных продаж. Вы обращаетесь к нам, только если сами надумаете.
            </p>
            
            <div style="text-align: center; margin-top: 40px;">
                <p style="font-size: 12pt; color: #475569; margin-bottom: 15px;">Запросить полную версию без обязательств:</p>
                <div style="display: inline-block; border: 2px solid #0A1128; color: #0A1128; padding: 12px 30px; border-radius: 8px; font-size: 14pt; font-weight: 700;">Telegram: @paulvenkov | pin100.ru</div>
            </div>
        """

    html += "</body></html>"
    return HTML(string=html).write_pdf()

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
                st.download_button(label="📄 Скачать Экспресс-аудит (LITE)", data=pdf_lite_bytes, file_name=f"PIN100_LITE_{title.replace(' ', '_')}.pdf", mime="application/pdf")
            with col_pro:
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
                            st.success(f"**✅ {item['Критерий']}**\n\n{item['Обоснование']}")
                        else:
                            st.error(f"**❌ {item['Критерий']}**\n\n{item['Обоснование']}")
