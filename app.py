import streamlit as st
import requests
import os
import time
import json
import numpy as np
import pandas as pd
import re
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
EXPERT_TITLE = "Аудит упущенной выручки и точек потери клиентов"

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

try:
    genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))
    expert_engine = genai.GenerativeModel('gemini-3.6-flash') 
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
        debug_keys = list(data.keys())
        debug_info = json.dumps(data, ensure_ascii=False)[:1000]
        tg_msg = f"Критический сбой: не найден ключ 'title'.\nДоступные ключи: {str(debug_keys[:10])}..."
        send_telegram_alert(tg_msg, yandex_url)
        raise Exception(f"Сбой ключа 'title'. \nДоступные ключи: {debug_keys}\n\nСырые данные: {debug_info}")
        
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
    if not expert_engine or not prompts_data: 
        raise Exception("Модуль экспертной оценки не инициализирован.")

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
                else:
                    rep = r.get('reply') or r.get('ownerAnswer') or r.get('businessResponse') or r.get('response')
                    if isinstance(rep, dict): rep_txt = str(rep.get('text') or '').strip()
                if txt: reviews_text.append(f"Отзыв: {txt} | Ответ: {rep_txt if rep_txt else 'ОТВЕТ ОТСУТСТВУЕТ'}")

    context = f"Название: {title}\nОписание: {desc}\nОсобенности: {feat_str}\n"
    if reviews_text: context += "Отзывы и ответы:\n" + "\n".join(reviews_text)

    rules_list = [f'"{str(p.get("Код", "")).strip()}": {str(p.get("Промпт для ИИ", "")).strip()}' for p in prompts_data if str(p.get('Код', '')).strip()]
    if not rules_list: return scores, reasons

    batch_prompt = f"""
Ты — ведущий эксперт по репутационному аудиту. Оцени карточку компании по критериям.
Контекст:
{context}
Критерии:
{chr(10).join(rules_list)}
Верни СТРОГО один JSON, ключи — коды, значения — объекты {{"score": boolean, "reason": "краткое экспертное обоснование"}}.
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
        raise Exception(f"Сбой экспертного модуля: {str(e)}")
    return scores, reasons

# ==========================================
# 3.5. ГЕНЕРАЦИЯ PDF-ОТЧЕТА PIN100 (ПРЕМИУМ ДИЗАЙН С ЛОГО)
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
        font_reg = "Roboto-Regular.ttf"
        font_bold = "Roboto-Bold.ttf"
        font_italic = "Roboto-Italic.ttf"
        
        if not os.path.exists(font_reg):
            open(font_reg, 'wb').write(requests.get("https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf").content)
        if not os.path.exists(font_bold):
            open(font_bold, 'wb').write(requests.get("https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf").content)
        if not os.path.exists(font_italic):
            open(font_italic, 'wb').write(requests.get("https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Italic.ttf").content)
        
        self.add_font("Roboto", "", font_reg)
        self.add_font("Roboto", "B", font_bold)
        self.add_font("Roboto", "I", font_italic)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() > 1:
            logo_path = "logo.png"
            if not os.path.exists(logo_path):
                logo_path = "PIN100 big logo.png"
            
            if os.path.exists(logo_path):
                self.image(logo_path, x=175, y=10, w=22)
            else:
                self.set_font('Roboto', 'B', 12)
                self.set_text_color(240, 100, 0)
                self.set_xy(175, 10)
                self.cell(20, 10, 'PIN100', 0, 0, 'R')
            
            self.set_y(25) # Задаем начальную точку для текста, чтобы он не наезжал на лого

    def footer(self):
        self.set_y(-15)
        self.set_font('Roboto', '', 9)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, f'PIN100 Confidential Analytics | Страница {self.page_no()}', 0, 0, 'C')

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check):
    pdf = PIN100Report()
    title = safe_text(title)
    niche = safe_text(niche)
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    # ---------------- СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ ----------------
    pdf.add_page()
    
    logo_path = "logo.png"
    if not os.path.exists(logo_path):
        logo_path = "PIN100 big logo.png"
        
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=75, y=40, w=60)
        pdf.set_y(120)
    else:
        pdf.set_y(80)
        pdf.set_font('Roboto', 'B', 48)
        pdf.set_text_color(240, 100, 0)
        pdf.cell(0, 20, 'PIN100', 0, 1, 'C')
        pdf.set_y(120)
    
    pdf.set_font('Roboto', 'B', 24)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 12, safe_text('Экспертный аудит упущенной выручки'), 0, 1, 'C')
    pdf.cell(0, 12, safe_text('и скрытых точек потери клиентов'), 0, 1, 'C')
    
    pdf.ln(25)
    pdf.set_font('Roboto', '', 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, f'Подготовлено для бизнеса: {title}', 0, 1, 'C')
    pdf.cell(0, 10, f'Дата аудита: {current_date}', 0, 1, 'C')
    
    pdf.set_y(-50)
    pdf.set_font('Roboto', 'B', 12)
    pdf.set_text_color(240, 100, 0) # Фирменный оранжевый акцент
    pdf.cell(0, 10, safe_text('СТРОГО КОНФИДЕНЦИАЛЬНО'), 0, 1, 'C')
    
    # ---------------- СТРАНИЦА 2: EXECUTIVE SUMMARY ----------------
    pdf.add_page()
    pdf.set_y(30)
    pdf.set_font('Roboto', 'B', 24)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, safe_text('Резюме для руководителя'), 0, 1, 'L')
    pdf.ln(10)
    
    pdf.set_font('Roboto', '', 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, safe_text('Индекс готовности профиля:'), 0, 1, 'L')
    
    pdf.set_font('Roboto', 'B', 36)
    if score >= 80: color = (40, 160, 40)
    elif score >= 50: color = (240, 140, 0) # Оранжево-желтый
    else: color = (180, 30, 30)
    pdf.set_text_color(*color)
    pdf.cell(0, 15, f'{round(score, 1)} / 100', 0, 1, 'L')
    
    pdf.set_fill_color(240, 240, 240)
    pdf.rect(10, pdf.get_y(), 190, 4, 'F')
    pdf.set_fill_color(*color)
    pdf.rect(10, pdf.get_y(), 190 * (score/100), 4, 'F')
    pdf.ln(20)
    
    pdf.set_font('Roboto', '', 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, safe_text('Упущенная выручка (Lost Revenue):'), 0, 1, 'L')
    
    pdf.set_fill_color(255, 240, 240)
    y_pos = pdf.get_y()
    pdf.rect(10, y_pos, 190, 24, 'F')
    pdf.set_y(y_pos + 5)
    pdf.set_font('Roboto', 'B', 32)
    pdf.set_text_color(180, 30, 30)
    pdf.cell(0, 15, f'- {revenue_loss:,} ₽ / мес'.replace(',', ' '), 0, 1, 'C')
    pdf.ln(20)
    
    pdf.set_font('Roboto', '', 13)
    pdf.set_text_color(60, 60, 60)
    summary_text = safe_text("Вывод эксперта: Отличное качество вашего продукта теряется из-за слабого присутствия в геосервисах. Из-за критических ошибок в заполнении карточки и отсутствии системной работы с отзывами вы уступаете позиции в поиске и ежемесячно отдаете горячих клиентов своим конкурентам.")
    pdf.set_x(10)
    pdf.multi_cell(190, 8, summary_text)
    
    # ---------------- СТРАНИЦА 3: ФИНАНСОВЫЙ АУДИТ ----------------
    pdf.add_page()
    pdf.set_y(30)
    pdf.set_font('Roboto', 'B', 24)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, safe_text('Декомпозиция потерь'), 0, 1, 'L')
    pdf.ln(10)
    
    dev = round(100 - score, 1)
    lost_clients = int(round(dev / 10))
    lost_leads = int(client_leads * (dev / 100))
    ltv_loss = revenue_loss * 12
    
    pdf.set_font('Roboto', 'B', 14)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(190, 10, safe_text('А. Оценка капитала бренда (Бенчмарк PIN100)'), 0, 1, 'L')
    pdf.set_font('Roboto', '', 12)
    pdf.set_text_color(80)
    block_a = safe_text(f"Отклонение от алгоритмического эталона составляет {dev}%. В коммерческой выдаче это приводит к падению охватов. Из каждых 10 потенциальных клиентов вашей ниши, {lost_clients} либо вообще не видят вашу компанию в топе, либо уходят к конкурентам из-за ошибок в оформлении.")
    pdf.set_x(10)
    pdf.multi_cell(190, 7, block_a)
    pdf.ln(8)
    
    pdf.set_font('Roboto', 'B', 14)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(190, 10, safe_text('Б. Ежемесячная упущенная выручка'), 0, 1, 'L')
    pdf.set_font('Roboto', '', 12)
    pdf.set_text_color(80)
    block_b = safe_text(f"Органический спрос в геосервисах по вашей нише составляет ~{client_leads} горячих обращений в месяц. Из-за низкого рейтинга вы теряете около {lost_leads} потенциальных сделок. При среднем чеке в {client_check:,} ₽, ваш прямой убыток составляет {revenue_loss:,} ₽ / мес.".replace(',', ' '))
    pdf.set_x(10)
    pdf.multi_cell(190, 7, block_b)
    pdf.ln(8)
    
    pdf.set_font('Roboto', 'B', 14)
    pdf.set_text_color(180, 30, 30)
    pdf.cell(190, 10, safe_text('В. Скрытые убытки (Удар ниже пояса)'), 0, 1, 'L')
    pdf.set_font('Roboto', '', 12)
    pdf.set_text_color(80)
    block_c = safe_text(f"В вашей сфере средний срок жизни клиента (LTV) составляет минимум 12 месяцев. Потерянные сегодня контракты лишают бизнес будущих стабильных платежей на сумму около {ltv_loss:,} ₽ в год. Это ваши реальные деньги, которые забирают более заметные конкуренты.".replace(',', ' '))
    pdf.set_x(10)
    pdf.multi_cell(190, 7, block_c)
    
    # ---------------- СТРАНИЦА 4: МАТРИЦА ПРОБЛЕМ (ВОРОНКА) ----------------
    pdf.add_page()
    pdf.set_y(30)
    pdf.set_font('Roboto', 'B', 24)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, safe_text('Аналитика воронки продаж'), 0, 1, 'L')
    pdf.ln(5)
    
    blocks = [
        {
            "title": "Блок 1. Видимость и Охваты (Генерация трафика)",
            "groups": ['SEO и Трафик', 'Активность'],
            "desc": "Зона ответственности: Попадание карточки в топ выдачи Яндекса по целевым B2B-запросам.",
            "rec": "Отсутствие этих настроек прячет бизнес от поисковых роботов. Яндекс пессимизирует карточку в выдаче, отдавая ваш законный бесплатный трафик конкурентам. Необходима ручная настройка SEO-параметров."
        },
        {
            "title": "Блок 2. Упаковка и Конверсия (Захват лида)",
            "groups": ['Конверсия', 'Базовое заполнение', 'Контент и Визуал'],
            "desc": "Зона ответственности: Превращение «просмотров» в реальные звонки и переходы на сайт.",
            "rec": "Без этих элементов карточка превращается в безликий справочник. Клиент не видит конкурентных преимуществ за 3 секунды и закрывает вкладку. Требуется комплексная смысловая упаковка профиля."
        },
        {
            "title": "Блок 3. Репутационный капитал (Удержание и Доверие)",
            "groups": ['Репутация'],
            "desc": "Зона ответственности: Готовность клиента доверить вам деньги на основе мнений других.",
            "rec": "В B2B сегменте клиенты проверяют надежность подрядчика. Отсутствие системной работы с отзывами или брошенный негатив вызывают недоверие и срывают крупные сделки."
        },
        {
            "title": "Блок 4. Скрытые алгоритмы (Техническая монополия)",
            "groups": ['Технологии и ИИ'],
            "desc": "Зона ответственности: Невидимая техническая оптимизация, которую считывают роботы Яндекса.",
            "rec": "Вы упускаете техническую монополию в выдаче. Отсутствие скрытой микроразметки (EXIF, фиды) лишает профиль приоритета над конкурентами."
        }
    ]

    for block in blocks:
        block_items = [r for r in results_data if r['Группа'] in block['groups']]
        if not block_items: continue
        
        passed_items = [r for r in block_items if r['Результат'] == "ДА"]
        failed_items = [r for r in block_items if r['Результат'] == "НЕТ"]
        
        ai_fails = [r for r in failed_items if r['Обоснование'] != DEFAULT_MISSING_REASON]
        std_fails = [r for r in failed_items if r['Обоснование'] == DEFAULT_MISSING_REASON]
        
        if pdf.get_y() > 220: pdf.add_page()
        
        # Дизайн заголовка блока
        pdf.set_fill_color(245, 245, 245)
        pdf.set_font('Roboto', 'B', 14)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(190, 12, safe_text(f"  {block['title']}"), 0, 1, 'L', fill=True)
        
        pdf.set_font('Roboto', 'I', 11)
        pdf.set_text_color(100, 100, 100)
        pdf.set_x(10)
        pdf.multi_cell(190, 6, safe_text(block['desc']))
        pdf.ln(4)
        
        # Сильные стороны
        if passed_items:
            pdf.set_font('Roboto', 'B', 10)
            pdf.set_text_color(40, 140, 40)
            passed_names = ", ".join([safe_text(r['Критерий']) for r in passed_items])
            pdf.set_x(10)
            pdf.multi_cell(190, 6, safe_text(f"✅ Успешно: {passed_names}"))
            pdf.ln(4)
            
        # Экспертные ошибки (AI)
        if ai_fails:
            for r in ai_fails:
                if pdf.get_y() > 250: pdf.add_page()
                pdf.set_font('Roboto', 'B', 11)
                pdf.set_text_color(40, 40, 40)
                pdf.cell(0, 7, safe_text(f"• {r['Критерий']}"), 0, 1, 'L')
                
                pdf.set_font('Roboto', '', 11)
                pdf.set_text_color(180, 50, 50) # Красный акцент для ошибок
                pdf.set_x(15)
                pdf.multi_cell(180, 6, safe_text(f"Аналитика: {r['Обоснование']}"))
                pdf.ln(3)

        # Сгруппированные пустые метрики
        if std_fails:
            if pdf.get_y() > 250: pdf.add_page()
            pdf.set_font('Roboto', 'B', 11)
            pdf.set_text_color(180, 50, 50)
            pdf.set_x(10)
            pdf.cell(0, 7, safe_text("Точки уязвимости (отсутствуют настройки):"), 0, 1, 'L')
            
            pdf.set_font('Roboto', '', 11)
            pdf.set_text_color(60, 60, 60)
            std_names = ", ".join([safe_text(r['Критерий']) for r in std_fails])
            pdf.set_x(15)
            pdf.multi_cell(180, 6, std_names)
            
            # Рекомендация
            pdf.set_font('Roboto', 'I', 11)
            pdf.set_text_color(240, 100, 0) # Фирменный оранжевый
            pdf.set_x(15)
            pdf.multi_cell(180, 6, safe_text(f"Резюме эксперта: {block['rec']}"))
            pdf.ln(5)
            
        pdf.ln(8)

    # ---------------- СТРАНИЦА 5: ДОРОЖНАЯ КАРТА ----------------
    pdf.add_page()
    pdf.set_y(30)
    pdf.set_font('Roboto', 'B', 24)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, safe_text('Дорожная карта (Roadmap)'), 0, 1, 'L')
    pdf.ln(8)
    
    failed_items_all = [r for r in results_data if r['Результат'] == "НЕТ"]
    stages = sorted(list(set([r['Этап'] for r in results_data])))
    
    for stage in stages:
        stage_tasks = [r for r in failed_items_all if r['Этап'] == stage]
        
        if stage_tasks:
            pdf.set_fill_color(245, 245, 245)
            pdf.set_font('Roboto', 'B', 12)
            pdf.set_text_color(40, 40, 40)
            pdf.cell(190, 12, safe_text(f"  {stage}"), 0, 1, 'L', fill=True)
            
            pdf.set_font('Roboto', '', 12)
            pdf.set_text_color(80, 80, 80)
            
            top_tasks = stage_tasks[:3]
            for t in top_tasks:
                task_text = safe_text(f"— {t['Критерий']}")
                pdf.set_x(10)
                pdf.multi_cell(190, 7, task_text)
                
            if len(stage_tasks) > 3:
                hidden_count = len(stage_tasks) - 3
                pdf.set_font('Roboto', 'I', 11)
                pdf.set_text_color(160, 160, 160)
                pdf.set_x(10)
                pdf.cell(0, 7, safe_text(f"...и еще {hidden_count} интеграций согласно стандарту PIN100"), 0, 1, 'L')
            
            pdf.ln(8)
        
    # ---------------- СТРАНИЦА 6: ОФФЕР ----------------
    pdf.add_page()
    pdf.set_y(100)
    pdf.set_font('Roboto', 'B', 26)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, safe_text('Готовы остановить потерю прибыли?'), 0, 1, 'C')
    pdf.ln(10)
    
    pdf.set_font('Roboto', '', 16)
    pdf.set_text_color(80, 80, 80)
    txt_offer = safe_text("Данный аудит выявил ключевые уязвимости вашей воронки продаж. Мы предлагаем внедрение разработанной дорожной карты «под ключ», чтобы закрыть утечку конверсии и превратить профиль в генератор лидов.")
    pdf.set_x(10)
    pdf.multi_cell(190, 8, txt_offer, align='C')
    
    pdf.ln(25)
    pdf.set_font('Roboto', 'B', 14)
    pdf.set_text_color(240, 100, 0) # Фирменный оранжевый
    pdf.cell(0, 10, safe_text('Свяжитесь с нами для старта проекта и интеграции системы'), 0, 1, 'C')

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

if st.button("🚀 Запустить экспертный аудит", type="primary"):
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
            except Exception as e:
                send_telegram_alert(str(e), url); st.error(e); st.stop()
            
            raw_scores = {}
            for f in [calculate_prof_rules, calculate_rep_rules]:
                raw_scores.update(f(data))
            
            try:
                exp_sc, exp_reasons = calculate_dynamic_expert_rules(data, prompts_data)
                raw_scores.update(exp_sc)
            except Exception as e:
                send_telegram_alert(str(e), url); st.error(e); st.stop()
            
            results = []
            final_total_score = 0.0
            target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                roadmap = str(r.get('Этап внедрения (Roadmap)', 'Прочее'))
                priority = str(r.get('Приоритет', '2 - Средний'))
                group = str(r.get('Группа метрик', 'Прочее')).strip()
                
                try: max_s = float(str(r.get(target_column, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
                except: max_s = float(r.get('Балл', 0.0))
                
                if max_s > 0.0:
                    val = max_s if raw_scores.get(code) else 0.0
                    final_total_score += val
                    comm = "ДА" if val > 0 else "НЕТ"
                    
                    if code in exp_reasons:
                        reason = exp_reasons[code]
                    else:
                        reason = "Соответствует эталону." if val > 0 else DEFAULT_MISSING_REASON
                        
                    results.append({
                        "Этап": roadmap, "Приоритет": priority, "Код": code, 
                        "Критерий": name, "Результат": comm, "Балл": val, 
                        "Макс": max_s, "Обоснование": reason, "Группа": group
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
            
            st.divider()
            pdf_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, results, client_leads, client_check)
            st.download_button(
                label="📄 Скачать премиум-отчет PIN100 (PDF)",
                data=pdf_bytes,
                file_name=f"PIN100_{title.replace(' ', '_')}.pdf",
                mime="application/pdf",
                type="primary"
            )
