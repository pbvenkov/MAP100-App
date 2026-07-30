import streamlit as st
import requests
import os
import time
import json
import numpy as np
import pandas as pd
import re
import urllib.request
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import base64

# --- Импорты ReportLab ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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
    rules = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    prompts = doc.worksheet("Prompts").get_all_records()
    return rules, prompts, doc

def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: 
        raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: raise Exception(f"Таймаут парсера.")
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": raise Exception(f"Парсер упал со статусом {status}.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset: raise Exception("Яндекс не отдал данные (капча).")
    return dataset[0]

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
    desc = str(data.get('description') or '')[:1000]
    rules_list = [f'"{p.get("Код", "").strip()}": {p.get("Промпт для ИИ", "").strip()}' for p in prompts_data if p.get('Код', '').strip()]
    if not rules_list: return scores, reasons

    batch_prompt = f"Контекст: {title}\n{desc}\nКритерии: {chr(10).join(rules_list)}\nВерни JSON с ключами-кодами и {{'score': bool, 'reason': 'текст'}}."
    try:
        response = expert_engine.generate_content(batch_prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
            for code, result in res_json.items():
                if result.get('score') in [1, True, "1", "true"]: scores[code] = True
                reasons[code] = result.get('reason', '')
    except Exception: pass
    return scores, reasons

# ==========================================
# 3.5. REPORTLAB: ГЕНЕРАЦИЯ PDF (ENTERPRISE)
# ==========================================

# 1. Корпоративные цвета
COLOR_NAVY = colors.HexColor("#0A1128")
COLOR_INK_MAIN = colors.HexColor("#334155")
COLOR_INK_LIGHT = colors.HexColor("#94A3B8")
COLOR_GOLD = colors.HexColor("#C5A880")
COLOR_SURFACE = colors.HexColor("#F8FAFC")
COLOR_BORDER = colors.HexColor("#E2E8F0")
COLOR_SUCCESS = colors.HexColor("#16A34A")
COLOR_ERROR = colors.HexColor("#DC2626")

def download_and_register_fonts():
    """Безопасная загрузка и регистрация шрифтов TTF"""
    fonts_to_load = {
        "Inter-Regular.ttf": "https://cdn.jsdelivr.net/gh/rsms/inter@3.19/docs/font-files/Inter-Regular.ttf",
        "Inter-Bold.ttf": "https://cdn.jsdelivr.net/gh/rsms/inter@3.19/docs/font-files/Inter-Bold.ttf",
        "PlayfairDisplay-Bold.ttf": "https://cdn.jsdelivr.net/gh/googlefonts/Playfair@main/fonts/ttf/PlayfairDisplay-Bold.ttf"
    }
    
    for font_name, url in fonts_to_load.items():
        is_valid = False
        if os.path.exists(font_name) and os.path.getsize(font_name) > 50000:
            with open(font_name, 'rb') as f:
                if f.read(4) in (b'\x00\x01\x00\x00', b'OTTO', b'true'): is_valid = True
        
        if not is_valid:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    with open(font_name, 'wb') as f:
                        f.write(response.read())
            except Exception: pass

    # Регистрируем в ReportLab. Если падает — используем системный fallback (Helvetica)
    fonts_map = {'Font-Main': 'Helvetica', 'Font-Bold': 'Helvetica-Bold', 'Font-Title': 'Helvetica-Bold'}
    try:
        pdfmetrics.registerFont(TTFont('Inter', 'Inter-Regular.ttf'))
        fonts_map['Font-Main'] = 'Inter'
    except Exception: pass
    try:
        pdfmetrics.registerFont(TTFont('Inter-Bold', 'Inter-Bold.ttf'))
        fonts_map['Font-Bold'] = 'Inter-Bold'
    except Exception: pass
    try:
        pdfmetrics.registerFont(TTFont('Playfair-Bold', 'PlayfairDisplay-Bold.ttf'))
        fonts_map['Font-Title'] = 'Playfair-Bold'
    except Exception: pass
    
    return fonts_map

def build_pdf_styles(f_map):
    """Создание CSS-подобных стилей для ReportLab"""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(name='PIN_Title', fontName=f_map['Font-Title'], fontSize=32, leading=38, textColor=COLOR_NAVY, spaceAfter=20))
    styles.add(ParagraphStyle(name='PIN_H1', fontName=f_map['Font-Title'], fontSize=24, leading=30, textColor=COLOR_NAVY, spaceAfter=15))
    styles.add(ParagraphStyle(name='PIN_H2', fontName=f_map['Font-Title'], fontSize=16, leading=22, textColor=COLOR_NAVY, spaceAfter=10))
    styles.add(ParagraphStyle(name='PIN_Body', fontName=f_map['Font-Main'], fontSize=11, leading=16, textColor=COLOR_INK_MAIN, spaceAfter=10))
    styles.add(ParagraphStyle(name='PIN_BodySmall', fontName=f_map['Font-Main'], fontSize=10, leading=14, textColor=COLOR_INK_LIGHT, spaceAfter=8))
    
    # Стили для Bento-карточек
    styles.add(ParagraphStyle(name='Bento_Value_Red', fontName=f_map['Font-Bold'], fontSize=22, textColor=COLOR_ERROR))
    styles.add(ParagraphStyle(name='Bento_Value_Green', fontName=f_map['Font-Bold'], fontSize=22, textColor=COLOR_SUCCESS))
    styles.add(ParagraphStyle(name='Bento_Value_Gold', fontName=f_map['Font-Bold'], fontSize=22, textColor=COLOR_GOLD))
    
    return styles

def create_bento_box(title, value, value_style, col_width):
    """Создает таблицу-карточку в стиле Bento"""
    # Создаем чистый стиль для заголовка карточки (без Bold)
    base_font = value_style.fontName.replace('-Bold', '').replace('Bold', '')
    title_style = ParagraphStyle(
        name='Bento_Title_Dynamic', 
        fontName=base_font, 
        fontSize=11, 
        textColor=COLOR_INK_MAIN
    )
    
    data = [
        [Paragraph(title, title_style)],
        [Spacer(1, 5*mm)],
        [Paragraph(value, value_style)]
    ]
    t = Table(data, colWidths=[col_width])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), COLOR_SURFACE),
        ('BOX', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 15),
        ('BOTTOMPADDING', (0,0), (-1,-1), 15),
        ('LEFTPADDING', (0,0), (-1,-1), 15),
        ('RIGHTPADDING', (0,0), (-1,-1), 15),
    ]))
    return t

def draw_separator(width):
    """Горизонтальная золотая линия"""
    t = Table([['']], colWidths=[width], rowHeights=[2*mm])
    t.setStyle(TableStyle([('LINEABOVE', (0,0), (-1,-1), 1.5, COLOR_GOLD)]))
    return t

def draw_footer(canvas, doc, f_map):
    """Колонтитулы на каждой странице"""
    canvas.saveState()
    canvas.setFont(f_map['Font-Main'], 8)
    canvas.setFillColor(COLOR_INK_LIGHT)
    canvas.drawString(25*mm, 15*mm, "PIN100 Analytics | Строго конфиденциально")
    canvas.drawRightString(210*mm - 25*mm, 15*mm, f"Стр. {doc.page}")
    canvas.restoreState()

def create_pdf_report(title, niche, score, revenue_loss, results_data, client_leads, client_check, report_type="PRO"):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=25*mm, leftMargin=25*mm, topMargin=25*mm, bottomMargin=25*mm)
    story = []
    
    f_map = download_and_register_fonts()
    styles = build_pdf_styles(f_map)
    content_w = doc.width

    # --- СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ ---
    logo_path = "logo.png" if os.path.exists("logo.png") else ("PIN100 big logo.png" if os.path.exists("PIN100 big logo.png") else None)
    if logo_path:
        story.append(RLImage(logo_path, width=30*mm, height=30*mm, hAlign='LEFT'))
    else:
        story.append(Paragraph("PIN100", styles['PIN_H1']))
        
    story.append(Spacer(1, 40*mm))
    doc_title = 'Экспресс-аудит<br/>упущенной выручки' if report_type == "LITE" else 'Экспертный аудит<br/>упущенной выручки'
    story.append(Paragraph(doc_title, styles['PIN_Title']))
    story.append(draw_separator(60*mm))
    story.append(Spacer(1, 10*mm))
    
    current_date = datetime.now().strftime("%d.%m.%Y")
    story.append(Paragraph(f"Подготовлено для бизнеса: <b>{title}</b>", styles['PIN_Body']))
    story.append(Paragraph(f"Дата аудита: <b>{current_date}</b>", styles['PIN_Body']))
    story.append(PageBreak())
    
    # --- СТРАНИЦА 2: EXECUTIVE SUMMARY ---
    story.append(Paragraph("Резюме для руководителя", styles['PIN_H1']))
    story.append(draw_separator(content_w))
    story.append(Spacer(1, 10*mm))
    
    score_style = styles['Bento_Value_Green'] if score >= 80 else (styles['Bento_Value_Gold'] if score >= 50 else styles['Bento_Value_Red'])
    story.append(create_bento_box('Индекс готовности профиля:', f'{round(score, 1)} / 100', score_style, content_w))
    story.append(Spacer(1, 5*mm))
    
    rev_str = f"- {revenue_loss:,}".replace(',', ' ') + " ₽ / мес"
    story.append(create_bento_box('Упущенная выручка (Lost Revenue):', rev_str, styles['Bento_Value_Red'], content_w))
    story.append(Spacer(1, 10*mm))
    
    story.append(Paragraph("<b>Вывод эксперта:</b> Отличное качество вашего продукта теряется из-за слабого присутствия в геосервисах. Из-за критических ошибок в заполнении карточки и отсутствии системной работы с отзывами вы уступаете позиции в поиске и ежемесячно отдаете горячих клиентов своим конкурентам.", styles['PIN_Body']))
    story.append(PageBreak())

    # --- СТРАНИЦА 3: ФИНАНСОВЫЙ АУДИТ ---
    story.append(Paragraph("Декомпозиция потерь", styles['PIN_H1']))
    story.append(draw_separator(content_w))
    story.append(Spacer(1, 10*mm))
    
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
        story.append(Paragraph(block_title, styles['PIN_H2']))
        story.append(draw_separator(40*mm))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(text, styles['PIN_Body']))
        story.append(Spacer(1, 8*mm))
    
    story.append(PageBreak())
    
    # --- СТРАНИЦА 4: МАТРИЦА ПРОБЛЕМ ---
    story.append(Paragraph("Аналитика воронки продаж", styles['PIN_H1']))
    story.append(draw_separator(content_w))
    story.append(Spacer(1, 8*mm))
    
    blocks = [
        {"title": "Блок 1. Видимость и Охваты", "groups": ['SEO и Трафик', 'Активность'], "desc": "Зона ответственности: Попадание карточки в топ выдачи Яндекса по целевым B2B-запросам."},
        {"title": "Блок 2. Упаковка и Конверсия", "groups": ['Конверсия', 'Базовое заполнение', 'Контент и Визуал'], "desc": "Зона ответственности: Превращение «просмотров» в реальные звонки и переходы на сайт."},
        {"title": "Блок 3. Репутационный капитал", "groups": ['Репутация'], "desc": "Зона ответственности: Готовность клиента доверить вам деньги на основе мнений других."},
        {"title": "Блок 4. Скрытые алгоритмы", "groups": ['Технологии и ИИ'], "desc": "Зона ответственности: Невидимая техническая оптимизация, которую считывают роботы Яндекса."}
    ]

    for block in blocks:
        block_items = [r for r in results_data if r['Группа'] in block['groups']]
        if not block_items: continue
        
        passed = [r for r in block_items if r['Результат'] == "ДА"]
        failed = [r for r in block_items if r['Результат'] == "НЕТ"]
        
        story.append(Paragraph(block['title'], styles['PIN_H2']))
        story.append(draw_separator(40*mm))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(block['desc'], styles['PIN_Body']))
        
        if report_type == "LITE":
            story.append(Paragraph(f"<font color='{COLOR_SUCCESS.hexval()}'><b>В НОРМЕ: {len(passed)} ПАРАМЕТРОВ</b></font>", styles['PIN_Body']))
            if failed:
                story.append(Paragraph(f"<font color='{COLOR_ERROR.hexval()}'><b>КРИТИЧЕСКИХ ОШИБОК: {len(failed)}</b></font>", styles['PIN_Body']))
            story.append(Paragraph("Детализация скрыта в экспресс-версии. Отсутствие данных настроек приводит к пессимизации профиля алгоритмами Яндекса.", styles['PIN_BodySmall']))
            story.append(Spacer(1, 5*mm))
        else:
            if failed:
                story.append(Paragraph(f"<font color='{COLOR_ERROR.hexval()}'><b>ОБНАРУЖЕННЫЕ УЯЗВИМОСТИ:</b></font>", styles['PIN_Body']))
                for item in failed:
                    story.append(Paragraph(f"• {item['Критерий']}", styles['PIN_Body']))
            story.append(Spacer(1, 5*mm))
            
    # --- ОФФЕР ДЛЯ LITE ВЕРСИИ ---
    if report_type == "LITE":
        story.append(PageBreak())
        story.append(Spacer(1, 30*mm))
        story.append(Paragraph("Хотите получить<br/>полный разбор?", styles['PIN_Title']))
        story.append(draw_separator(60*mm))
        story.append(Spacer(1, 10*mm))
        
        story.append(Paragraph("В экспресс-версии мы показали сумму ваших потерь. Детализация каждой ошибки, экспертная аналитика и пошаговая Дорожная карта доступны в полной PRO-версии отчета.", styles['PIN_Body']))
        story.append(Spacer(1, 10*mm))
        
        story.append(create_bento_box('Стоимость PRO-аудита:', '4 880 ₽', styles['PIN_H1'], content_w))
        story.append(Spacer(1, 10*mm))
        
        story.append(Paragraph("Свяжитесь с нами для получения полной версии:", styles['PIN_Body']))
        story.append(Paragraph("<b>Telegram: @paulvenkov | pin100.ru</b>", styles['PIN_H2']))

    doc.build(story, onFirstPage=lambda c, d: draw_footer(c, d, f_map), onLaterPages=lambda c, d: draw_footer(c, d, f_map))
    return buffer.getvalue()

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
            try: data = fetch_apify_data(url)
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
            for f in [calculate_prof_rules, calculate_rep_rules]: raw_scores.update(f(data))
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
                    reason = exp_reasons.get(code, "Соответствует эталону." if val > 0 else "DEFAULT_MISSING")
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
