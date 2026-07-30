import streamlit as st
import requests
import os
import time
import json
import numpy as np
import pandas as pd
import re
import urllib.request
import itertools
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image
from fpdf import FPDF
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
    expert_engine = genai.GenerativeModel('gemini-1.5-pro') 
except Exception as e:
    expert_engine = None

def send_telegram_alert(error_msg, target_url="Неизвестно"):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    
    if tg_token and tg_admin_id:
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        text = f"🚨 *{PROJECT_NAME}: Сбой системы*\n\n*Цель:* {target_url}\n*Ошибка:* {error_msg}\n\n🛑 *Действие:* Генерация остановлена."
        try:
            requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except Exception:
            pass

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
    if not expert_engine: 
        raise Exception("Модуль экспертной оценки не инициализирован.")
        
    prompt = f"""
    Проведи экспертную оценку бизнеса по названию "{title}" и категории "{category}".
    ВНИМАНИЕ: Если в категории есть слова "стоматология", "клиника", "медицина", "красота", "салон" - это СТРОГО BEAUTY_MEDICAL.
    Определи ОДИН наиболее подходящий сегмент из списка:
    - HORECA (Рестораны, кафе, бары)
    - B2B (Обслуживание бизнеса: канцелярия, пурифайеры, IT-аутсорс, клининг)
    - RETAIL (Магазины B2C)
    - AUTO (Автосервисы, детейлинг)
    - SERVICES (Услуги B2C, ремонт)
    - BEAUTY_MEDICAL (Медицина, салоны)
    - OTHER (Прочее)
    Верни ТОЛЬКО ОДНО СЛОВО - ключ на английском.
    """
    try:
        response = expert_engine.generate_content(prompt)
        key = response.text.strip().upper()
        valid_keys = ["BEAUTY_MEDICAL", "HORECA", "B2B", "RETAIL", "AUTO", "SERVICES", "OTHER"]
        for v in valid_keys:
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
    rules = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    prompts = doc.worksheet("Prompts").get_all_records()
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
            err_msg = f"Таймаут парсера. Логи: https://console.apify.com/actors/runs/{run_id}"
            send_telegram_alert(err_msg, yandex_url)
            raise Exception(err_msg)
        time.sleep(5)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": 
        err_msg = f"Парсер упал со статусом {status}."
        send_telegram_alert(err_msg, yandex_url)
        raise Exception(err_msg)
        
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset or len(dataset) == 0: 
        err_msg = "Парсер отработал, но Яндекс не отдал данные (вероятно капча). Повторите запрос."
        send_telegram_alert(err_msg, yandex_url)
        raise Exception(err_msg)
    
    data = dataset[0]
    if not data.get('title'):
        raise Exception(f"Сбой ключа 'title'.")
        
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

def calculate_prof_rules(data):
    scores = {}
    title = str(data.get('title') or '')
    description = str(data.get('description') or '')
    if data.get('isVerifiedOwner'):
        for k in ['PROF-12.1', 'PROF-01.1', 'PROF-03.1', 'PROF-05.1', 'PROF-07.1']: scores[k] = True
    else:
        if len(title) > 2: scores['PROF-01.1'] = True
        if data.get('categories'): scores['PROF-03.1'] = True
        if data.get('phones'): scores['PROF-05.1'] = True
        schedule = data.get('schedule') or data.get('workingHours') or []
        if isinstance(schedule, list) and len(schedule) >= 7: scores['PROF-07.1'] = True
        elif isinstance(schedule, dict) and len(schedule.keys()) >= 7: scores['PROF-07.1'] = True
    feat = data.get('features')
    if isinstance(feat, list):
        if len(feat) > 0: scores['PROF-08.1'] = True
        if len(feat) >= 5: scores['PROF-08.2'] = True
    if len(description) > 1500: scores['PROF-09.1'] = True
    url = str(data.get('url') or data.get('website') or '').lower()
    if url: scores['PROF-04.1'] = True
    prods = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    valid_prods = [p for p in prods if isinstance(p, dict)]
    if len(valid_prods) >= 10: scores['PROF-11.1'] = True
    owner_links = url + " " + description + " "
    links_data = data.get('links') or data.get('socialLinks') or data.get('socials') or []
    if isinstance(links_data, list): owner_links += " ".join(str(l) for l in links_data)
    elif isinstance(links_data, dict): owner_links += " ".join(str(v) for v in links_data.values())
    if any(s in owner_links.lower() for s in ["vk.com", "youtube", "dzen", "instagram", "inst:"]): scores['PROF-13.2'] = True
    return scores

def calculate_rep_rules(data):
    scores = {}
    try: rating = float(data.get('rating') or 0.0)
    except: rating = 0.0
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    try: rev_count = int(data.get('reviewsCount') or data.get('ratingsCount') or 0)
    except: rev_count = 0
    if rev_count >= 50: scores['REP-28.1'] = True
    reviews_raw = data.get('reviews')
    if not isinstance(reviews_raw, list): return scores
    reviews = [r for r in reviews_raw if isinstance(r, dict)]
    if not reviews: return scores
    ow_txt = []
    for r in reviews[:20]:
        is_replied = False
        rep_text = ""
        if r.get('businessComment'):
            rep_text = str(r.get('businessComment')).strip()
            if rep_text: is_replied = True
        else:
            rep = r.get('reply') or r.get('ownerAnswer') or r.get('businessResponse') or r.get('response')
            if isinstance(rep, dict):
                rep_text = str(rep.get('text') or '').strip()
                if rep_text: is_replied = True
        if is_replied and rep_text: ow_txt.append(rep_text.lower())
    if ow_txt:
        stop_words = ['не были', 'не находим', 'уточните', 'нет в базе']
        if any(w in t for t in ow_txt for w in stop_words): scores['REP-33.1'] = True
    return scores

def calculate_dynamic_expert_rules(data, prompts_data):
    scores, reasons = {}, {}
    if not expert_engine or not prompts_data: return scores, reasons
    title = str(data.get('title') or '')
    desc = str(data.get('description') or '')[:1200]
    feat = data.get('features')
    feat_str = ", ".join([str(f) for f in feat]) if isinstance(feat, list) else ""
    reviews_data = data.get('reviews')
    reviews_text = []
    if isinstance(reviews_data, list):
        for r in reviews_data[:10]:
            if isinstance(r, dict):
                txt = str(r.get('text') or '').strip()
                rep_txt = ""
                if r.get('businessComment'):
                    rep_txt = str(r.get('businessComment')).strip()
                if txt: reviews_text.append(f"Отзыв: {txt} | Ответ: {rep_txt}")

    context = f"Название: {title}\nОписание: {desc}\nОсобенности: {feat_str}\n"
    if reviews_text: context += "Отзывы:\n" + "\n".join(reviews_text)
    rules_list = [f'"{str(p.get("Код", "")).strip()}": {str(p.get("Промпт для ИИ", "")).strip()}' for p in prompts_data if str(p.get('Код', '')).strip()]
    if not rules_list: return scores, reasons

    batch_prompt = f"""Ты эксперт по аудиту. Оцени карточку по критериям.
Контекст: {context}
Критерии: {chr(10).join(rules_list)}
Верни СТРОГО один JSON: ключи — коды, значения — объекты {{"score": boolean, "reason": "обоснование"}}.
"""
    try:
        response = expert_engine.generate_content(batch_prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
            for code, result in res_json.items():
                if isinstance(result, dict):
                    if result.get('score') in [1, True, "1", "true"]: scores[code] = True
                    reasons[code] = result.get('reason', 'Нет объяснения')
    except Exception as e:
        pass
    return scores, reasons

# ==========================================
# 3.5. ГЕНЕРАЦИЯ PDF-ОТЧЕТА (ПРЕМИУМ ДИЗАЙН)
# ==========================================
DEFAULT_MISSING_REASON = "DEFAULT_MISSING"

def safe_text(text):
    if not text: return ""
    text = str(text).replace('\xa0', ' ').replace('\r', '').replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s\.,!?:;\-\(\)\[\]"\'«»/%&₽$€+*=]', '', text)
    return text.strip()

class PIN100Report(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_margins(left=25, top=25, right=25)
        self.set_auto_page_break(auto=True, margin=25)
        
        # Надежные прямые ссылки RAW
        fonts = {
            "Inter-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/static/Inter-Regular.ttf",
            "Inter-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/static/Inter-Bold.ttf",
            "PlayfairDisplay-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/static/PlayfairDisplay-Bold.ttf"
        }
        
        # Скачивание с имитацией браузера (User-Agent)
        for font_name, url in fonts.items():
            # Если файла нет или он весит меньше 50Кб (битый HTML), скачиваем заново
            if not os.path.exists(font_name) or os.path.getsize(font_name) < 50000:
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(req, timeout=15) as response, open(font_name, 'wb') as f:
                        f.write(response.read())
                except Exception as e:
                    print(f"Ошибка загрузки {font_name}: {e}")

        # Строгая регистрация шрифтов (без Arial!)
        self.add_font("Inter", "", "Inter-Regular.ttf")
        self.add_font("Inter", "B", "Inter-Bold.ttf")
        self.add_font("Playfair", "B", "PlayfairDisplay-Bold.ttf")
            
        # Корпоративные цвета
        self.color_navy = (10, 17, 40)
        self.color_ink_main = (51, 65, 85)
        self.color_ink_light = (148, 163, 184)
        self.color_gold = (197, 168, 128)
        self.color_surface = (248, 250, 252)
        self.color_border = (226, 232, 240)
        self.color_success = (22, 163, 74)
        self.color_error = (220, 38, 38)
        self.content_w = 160 # Ширина контента (210 - 25 - 25)

    def footer(self):
        self.set_y(-20)
        self.set_font('Inter', '', 8)
        self.set_text_color(*self.color_ink_light)
        self.cell(100, 10, 'PIN100 Analytics | Строго конфиденциально', 0, 0, 'L')
        self.cell(60, 10, f'Стр. {self.page_no()}', 0, 0, 'R')

def draw_bento_box(pdf, title, value, value_color, is_red_value=False):
    pdf.set_fill_color(*pdf.color_surface)
    pdf.set_draw_color(*pdf.color_border)
    pdf.set_line_width(0.3)
    start_y = pdf.get_y()
    pdf.rect(25, start_y, pdf.content_w, 28, 'DF')
    
    pdf.set_y(start_y + 5)
    pdf.set_x(30)
    pdf.set_font('Inter', '', 11)
    pdf.set_text_color(*pdf.color_ink_main)
    pdf.cell(0, 6, safe_text(title), 0, 1, 'L')
    
    pdf.set_x(30)
    pdf.set_font('Inter', 'B', 22)
    pdf.set_text_color(*value_color)
    pdf.cell(0, 10, safe_text(value), 0, 1, 'L')
    pdf.set_y(start_y + 32)

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, report_type="PRO"):
    pdf = PIN100Report()
    title = safe_text(title)
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    # ---------------- СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ ----------------
    pdf.add_page()
    
    logo_path = "logo.png"
    if not os.path.exists(logo_path):
        logo_path = "PIN100 big logo.png"
        
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=25, y=25, w=30)
    else:
        pdf.set_font('Playfair', 'B', 20)
        pdf.set_text_color(*pdf.color_navy)
        pdf.set_xy(25, 25)
        pdf.cell(30, 10, 'PIN100', 0, 0, 'L')
        
    pdf.set_y(90)
    pdf.set_font('Playfair', 'B', 32)
    pdf.set_text_color(*pdf.color_navy)
    
    doc_title = 'Экспресс-аудит\nупущенной выручки' if report_type == "LITE" else 'Экспертный аудит\nупущенной выручки'
    pdf.multi_cell(pdf.content_w, 14, safe_text(doc_title), align='L')
    
    pdf.set_draw_color(*pdf.color_gold)
    pdf.set_line_width(0.6)
    pdf.line(25, pdf.get_y() + 5, 85, pdf.get_y() + 5)
    
    pdf.ln(15)
    pdf.set_font('Inter', '', 12)
    pdf.set_text_color(*pdf.color_ink_main)
    pdf.cell(0, 8, f'Подготовлено для бизнеса: {title}', 0, 1, 'L')
    pdf.cell(0, 8, f'Дата аудита: {current_date}', 0, 1, 'L')
    
    # ---------------- СТРАНИЦА 2: EXECUTIVE SUMMARY ----------------
    pdf.add_page()
    pdf.set_font('Playfair', 'B', 24)
    pdf.set_text_color(*pdf.color_navy)
    pdf.cell(0, 12, safe_text('Резюме для руководителя'), 0, 1, 'L')
    
    pdf.set_draw_color(*pdf.color_gold)
    pdf.set_line_width(0.4)
    pdf.line(25, pdf.get_y() + 2, 25 + pdf.content_w, pdf.get_y() + 2)
    pdf.ln(10)
    
    score_color = pdf.color_success if score >= 80 else (pdf.color_gold if score >= 50 else pdf.color_error)
    draw_bento_box(pdf, 'Индекс готовности профиля:', f'{round(score, 1)} / 100', score_color)
    
    rev_str = f"- {revenue_loss:,}".replace(',', ' ') + " ₽ / мес"
    draw_bento_box(pdf, 'Упущенная выручка (Lost Revenue):', rev_str, pdf.color_error, is_red_value=True)
    
    pdf.ln(5)
    pdf.set_font('Inter', '', 11)
    pdf.set_text_color(*pdf.color_ink_main)
    summary_text = safe_text("Вывод эксперта: Отличное качество вашего продукта теряется из-за слабого присутствия в геосервисах. Из-за критических ошибок в заполнении карточки и отсутствии системной работы с отзывами вы уступаете позиции в поиске и ежемесячно отдаете горячих клиентов своим конкурентам.")
    pdf.multi_cell(pdf.content_w, 7, summary_text, align='L')
    
    # ---------------- СТРАНИЦА 3: ФИНАНСОВЫЙ АУДИТ ----------------
    pdf.add_page()
    pdf.set_font('Playfair', 'B', 24)
    pdf.set_text_color(*pdf.color_navy)
    pdf.cell(0, 12, safe_text('Декомпозиция потерь'), 0, 1, 'L')
    
    pdf.set_draw_color(*pdf.color_gold)
    pdf.set_line_width(0.4)
    pdf.line(25, pdf.get_y() + 2, 25 + pdf.content_w, pdf.get_y() + 2)
    pdf.ln(10)
    
    dev = round(100 - score, 1)
    lost_clients = int(round(dev / 10))
    lost_leads = int(client_leads * (dev / 100))
    ltv_loss = revenue_loss * 12
    
    blocks_fin = [
        ("А. Оценка капитала бренда (Бенчмарк PIN100)", f"Отклонение от алгоритмического эталона составляет {dev}%. В коммерческой выдаче это приводит к падению охватов. Из каждых 10 потенциальных клиентов вашей ниши, {lost_clients} либо вообще не видят вашу компанию в топе, либо уходят к конкурентам из-за ошибок в оформлении."),
        ("Б. Ежемесячная упущенная выручка", f"Органический спрос в геосервисах по вашей нише составляет {client_leads} горячих обращений в месяц. Из-за низкого рейтинга вы теряете около {lost_leads} потенциальных сделок. При среднем чеке в {client_check:,} ₽, ваш прямой убыток составляет {revenue_loss:,} ₽ в месяц.".replace(',', ' ')),
        ("В. Скрытые убытки (Удар ниже пояса)", f"В вашей сфере средний срок жизни клиента (LTV) составляет минимум 12 месяцев. Потерянные сегодня контракты лишают бизнес будущих стабильных платежей на сумму около {ltv_loss:,} ₽ в год. Это ваши реальные деньги, которые забирают более заметные конкуренты.".replace(',', ' '))
    ]
    
    for block_title, text in blocks_fin:
        pdf.set_font('Playfair', 'B', 16)
        pdf.set_text_color(*pdf.color_navy)
        pdf.cell(pdf.content_w, 10, safe_text(block_title), 0, 1, 'L')
        
        pdf.set_draw_color(*pdf.color_gold)
        pdf.set_line_width(0.3)
        pdf.line(25, pdf.get_y(), 65, pdf.get_y())
        pdf.ln(4)
        
        pdf.set_font('Inter', '', 11)
        pdf.set_text_color(*pdf.color_ink_main)
        pdf.multi_cell(pdf.content_w, 7, safe_text(text), align='L')
        pdf.ln(8)
    
    # ---------------- СТРАНИЦА 4: МАТРИЦА ПРОБЛЕМ ----------------
    pdf.add_page()
    pdf.set_font('Playfair', 'B', 24)
    pdf.set_text_color(*pdf.color_navy)
    pdf.cell(0, 12, safe_text('Аналитика воронки продаж'), 0, 1, 'L')
    
    pdf.set_draw_color(*pdf.color_gold)
    pdf.line(25, pdf.get_y() + 2, 25 + pdf.content_w, pdf.get_y() + 2)
    pdf.ln(8)
    
    blocks = [
        {"title": "Блок 1. Видимость и Охваты", "groups": ['SEO и Трафик', 'Активность'], "desc": "Зона ответственности: Попадание карточки в топ выдачи Яндекса по целевым B2B-запросам."},
        {"title": "Блок 2. Упаковка и Конверсия", "groups": ['Конверсия', 'Базовое заполнение', 'Контент и Визуал'], "desc": "Зона ответственности: Превращение «просмотров» в реальные звонки и переходы на сайт."},
        {"title": "Блок 3. Репутационный капитал", "groups": ['Репутация'], "desc": "Зона ответственности: Готовность клиента доверить вам деньги на основе мнений других."},
        {"title": "Блок 4. Скрытые алгоритмы", "groups": ['Технологии и ИИ'], "desc": "Зона ответственности: Невидимая техническая оптимизация, которую считывают роботы Яндекса."}
    ]

    for block in blocks:
        block_items = [r for r in results_data if r['Группа'] in block['groups']]
        if not block_items: continue
        
        passed_items = [r for r in block_items if r['Результат'] == "ДА"]
        failed_items = [r for r in block_items if r['Результат'] == "НЕТ"]
        
        if pdf.get_y() > 220: pdf.add_page()
        
        pdf.set_font('Playfair', 'B', 16)
        pdf.set_text_color(*pdf.color_navy)
        pdf.cell(pdf.content_w, 10, safe_text(block['title']), 0, 1, 'L')
        
        pdf.set_draw_color(*pdf.color_gold)
        pdf.set_line_width(0.3)
        pdf.line(25, pdf.get_y(), 65, pdf.get_y())
        pdf.ln(3)
        
        pdf.set_font('Inter', '', 11)
        pdf.set_text_color(*pdf.color_ink_main)
        pdf.multi_cell(pdf.content_w, 6, safe_text(block['desc']), align='L')
        pdf.ln(3)
        
        if report_type == "LITE":
            pdf.set_font('Inter', 'B', 10)
            pdf.set_text_color(*pdf.color_success)
            pdf.cell(0, 6, safe_text(f"В НОРМЕ: {len(passed_items)} ПАРАМЕТРОВ"), 0, 1, 'L')

            if failed_items:
                pdf.set_font('Inter', 'B', 10)
                pdf.set_text_color(*pdf.color_error)
                pdf.cell(0, 6, safe_text(f"КРИТИЧЕСКИХ ОШИБОК: {len(failed_items)}"), 0, 1, 'L')

            pdf.set_font('Inter', '', 10)
            pdf.set_text_color(*pdf.color_ink_light)
            pdf.multi_cell(pdf.content_w, 6, safe_text("Детализация скрыта в экспресс-версии. Отсутствие данных настроек приводит к пессимизации профиля алгоритмами Яндекса."), align='L')
            pdf.ln(6)
            continue
            
        if failed_items:
            pdf.set_font('Inter', 'B', 10)
            pdf.set_text_color(*pdf.color_error)
            pdf.cell(0, 6, safe_text("ОБНАРУЖЕННЫЕ УЯЗВИМОСТИ:"), 0, 1, 'L')
            pdf.set_font('Inter', '', 10)
            pdf.set_text_color(*pdf.color_ink_main)
            for item in failed_items:
                pdf.multi_cell(pdf.content_w, 5, safe_text(f"• {item['Критерий']}"))
            pdf.ln(4)

    # ---------------- СТРАНИЦЫ 5 И 6: ОФФЕР ----------------
    if report_type == "LITE":
        pdf.add_page()
        pdf.set_y(80)
        pdf.set_font('Playfair', 'B', 28)
        pdf.set_text_color(*pdf.color_navy)
        pdf.multi_cell(pdf.content_w, 12, safe_text('Хотите получить\nполный разбор?'), align='L')
        
        pdf.set_draw_color(*pdf.color_gold)
        pdf.set_line_width(0.6)
        pdf.line(25, pdf.get_y() + 5, 85, pdf.get_y() + 5)
        pdf.ln(15)
        
        pdf.set_font('Inter', '', 12)
        pdf.set_text_color(*pdf.color_ink_main)
        txt_offer = safe_text("В экспресс-версии мы показали сумму ваших потерь. Детализация каждой ошибки, экспертная аналитика и пошаговая Дорожная карта доступны в полной PRO-версии отчета.")
        pdf.multi_cell(pdf.content_w, 7, txt_offer, align='L')
        
        pdf.ln(15)
        draw_bento_box(pdf, 'Стоимость PRO-аудита:', '4 880 ₽', pdf.color_navy)
        
        pdf.ln(10)
        pdf.set_font('Inter', '', 12)
        pdf.cell(0, 8, safe_text('Свяжитесь с нами для получения полной версии:'), 0, 1, 'L')
        pdf.set_font('Inter', 'B', 14)
        pdf.set_text_color(*pdf.color_navy)
        pdf.cell(0, 8, safe_text('Telegram: @paulvenkov | pin100.ru'), 0, 1, 'L')

    return bytes(pdf.output())

# ==========================================
# 4. СБОРКА И ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title=f"{PROJECT_NAME} | Экспертный Аудит", layout="wide", page_icon="📍")
rules_data, prompts_data, doc = get_database_from_sheets()

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
                st.error(str(e))
                st.stop()
            title = data.get('title', 'Без названия')
            c_list = data.get('categories', [])
            cat = c_list[0].get('name', '') if c_list and isinstance(c_list[0], dict) else (str(c_list[0]) if c_list else '')
            client_reviews = int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []) or 0)
            
        with st.spinner("Экспертная оценка и расчет экономики..."):
            try: niche_key = determine_niche_by_expert(title, cat)
            except: niche_key = "OTHER"
            
            raw_scores = {}
            for f in [calculate_prof_rules, calculate_rep_rules]:
                raw_scores.update(f(data))
            
            try:
                exp_sc, exp_reasons = calculate_dynamic_expert_rules(data, prompts_data)
                raw_scores.update(exp_sc)
            except: pass
            
            results = []
            final_total_score = 0.0
            target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                group = str(r.get('Группа метрик', 'Прочее')).strip()
                
                try: max_s = float(str(r.get(target_column, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
                except: max_s = float(r.get('Балл', 0.0))
                
                if max_s > 0.0:
                    val = max_s if raw_scores.get(code) else 0.0
                    final_total_score += val
                    comm = "ДА" if val > 0 else "НЕТ"
                    reason = exp_reasons.get(code, "Соответствует эталону." if val > 0 else DEFAULT_MISSING_REASON)
                        
                    results.append({"Код": code, "Критерий": name, "Результат": comm, "Обоснование": reason, "Группа": group})

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
            
            st.divider()
            st.markdown("### 📥 Выгрузка отчетов")
            
            pdf_lite_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, report_type="LITE")
            pdf_pro_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check, report_type="PRO")
            
            col_lite, col_pro = st.columns(2)
            with col_lite:
                st.download_button(label="📄 Скачать Экспресс-аудит (LITE)", data=pdf_lite_bytes, file_name=f"PIN100_LITE_{title.replace(' ', '_')}.pdf", mime="application/pdf")
            with col_pro:
                st.download_button(label="💎 Скачать PRO-аудит", data=pdf_pro_bytes, file_name=f"PIN100_PRO_{title.replace(' ', '_')}.pdf", mime="application/pdf", type="primary")
