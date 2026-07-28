import streamlit as st
import requests
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
EXPERT_TITLE = "Экспертная оценка репутационных активов"

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# Инициализация модуля экспертной оценки (Gemini 3.6 Flash)
try:
    genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))
    expert_engine = genai.GenerativeModel('gemini-3.6-flash') 
except Exception as e:
    expert_engine = None

# Функция для отправки алертов в Telegram
def send_telegram_alert(error_msg, target_url="Неизвестно"):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    
    if tg_token and tg_admin_id:
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        text = f"🚨 *{PROJECT_NAME}: Критический сбой аудита*\n\n*Аудит:* {target_url}\n*Ошибка:* {error_msg}\n\n🛑 *Действие:* Генерация отчета остановлена."
        try:
            requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except Exception:
            pass

# ==========================================
# 1.5. БАЗА ДАННЫХ НИШ И БЕНЧМАРКОВ
# ==========================================
NICHE_ECONOMICS = {
    "HORECA": {"leads": 150, "check": 2000, "label": "HORECA"},
    "B2B": {"leads": 40, "check": 30000, "label": "B2B / Обеспечение бизнеса"},
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
    if 'error' in run_req: raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: raise Exception(f"Таймаут парсера. Логи: https://console.apify.com/actors/runs/{run_id}")
        time.sleep(5)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": raise Exception(f"Парсер упал со статусом {status}.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset or len(dataset) == 0: raise Exception("Парсер отработал, но Яндекс не отдал данные (защита от ботов). Повторите запрос.")
    
    data = dataset[0]
    if not data.get('title'):
        raise Exception("Критический сбой парсинга: Отсутствует Название компании. Яндекс отдал пустую страницу. Запустите аудит еще раз.")
    return data

# ==========================================
# 3. АЛГОРИТМЫ ОЦЕНКИ PIN100 (АУДИТ)
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
    else: feat = []

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
    owner_links = owner_links.lower()

    if any(s in owner_links for s in ["vk.com", "youtube", "dzen", "instagram", "inst:"]): scores['PROF-13.2'] = True
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
        try: rate = float(r.get('rating') or 0.0)
        except: rate = 0.0
        
        rep_text = ""
        is_replied = False

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
        stop_words = ['не были', 'не находим', 'уточните', 'нет в базе', 'какой номер']
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
                    if isinstance(rep, dict):
                        rep_txt = str(rep.get('text') or '').strip()
                        
                if txt: reviews_text.append(f"Отзыв: {txt} | Ответ владельца: {rep_txt if rep_txt else 'ОТВЕТ ОТСУТСТВУЕТ'}")

    context = f"Название: {title}\nОписание: {desc}\nОсобенности/Услуги: {feat_str}\n"
    if reviews_text: context += "Последние отзывы и ответы:\n" + "\n".join(reviews_text)

    rules_list = []
    for p in prompts_data:
        code = str(p.get('Код', '')).strip()
        prompt_text = str(p.get('Промпт для ИИ', '')).strip()
        if code and prompt_text: rules_list.append(f'"{code}": {prompt_text}')

    if not rules_list: return scores, reasons

    batch_prompt = f"""
Ты — ведущий эксперт по репутационному аудиту геосервисов. Проанализируй контекст карточки компании и дай экспертную оценку по всем перечисленным критериям.

Контекст карточки:
{context}

Критерии для оценки (Код: Экспертное правило):
{chr(10).join(rules_list)}

ТВОЯ ЗАДАЧА:
Верни СТРОГО один JSON-объект, где ключи — это коды критериев, а значения — объекты с полями "score" (boolean: true если выполнено, false если нет) и "reason" (строка: краткое экспертное обоснование на 1 предложение).
Никакого лишнего текста.

Пример ответа:
{{
  "AI-01": {{"score": true, "reason": "В описании четко зафиксировано уникальное торговое предложение (УТП) компании."}},
  "AI-02": {{"score": false, "reason": "Представитель компании игнорирует критические отзывы клиентов."}}
}}
"""
    try:
        response = expert_engine.generate_content(batch_prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
            for code, result in res_json.items():
                if isinstance(result, dict):
                    is_passed = result.get('score') in [1, True, "1", "true"]
                    if is_passed: scores[code] = True
                    reasons[code] = result.get('reason', 'Нет объяснения')
        else:
            raise Exception("Модуль экспертной оценки вернул неверный формат.")
    except Exception as e:
        raise Exception(f"Сбой модуля экспертной оценки (Аудит): {str(e)}")
        
    return scores, reasons

# ==========================================
# 3.5. ГЕНЕРАЦИЯ PDF-ОТЧЕТА PIN100
# ==========================================
class PIN100Report(FPDF):
    def header(self):
        # Заглушка под логотип PIN100
        self.set_font('Arial', 'B', 15)
        self.set_text_color(160, 30, 30) # Красный PIN
        self.cell(20, 10, 'PIN', 0, 0, 'L')
        self.set_text_color(40, 40, 40)
        self.cell(40, 10, '100', 0, 0, 'L')
        self.set_font('Arial', 'I', 8)
        self.set_text_color(100)
        self.cell(0, 10, 'Экспертный аудит репутационных активов', 0, 1, 'R')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Стр. {self.page_no()}', 0, 0, 'C')

def create_pdf_report(title, niche, score, revenue_loss, data_matrix):
    pdf = PIN100Report()
    pdf.add_page()
    
    # 1. Executive Summary
    pdf.set_font('Arial', 'B', 16)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, f'Аудит компании: {title}', 0, 1, 'L')
    
    pdf.set_font('Arial', '', 10)
    pdf.set_text_color(100)
    pdf.cell(0, 7, f'Нишевой сегмент: {niche}', 0, 1, 'L')
    pdf.ln(5)
    
    # Индекс готовности (RAG)
    pdf.set_fill_color(240, 240, 240)
    if score >= 80: fill = (100, 200, 100); text = "Отличный результат"
    elif score >= 50: fill = (230, 200, 100); text = "Требует оптимизации"
    else: fill = (200, 100, 100); text = "Критический уровень риска"
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(80, 15, 'Индекс репутационного капитала PIN100:', 0, 0, 'L', True)
    pdf.set_text_color(255)
    pdf.set_fill_color(*fill)
    pdf.cell(40, 15, f'{round(score, 1)} / 100', 0, 0, 'C', True)
    pdf.set_text_color(100)
    pdf.cell(0, 15, f' ({text})', 0, 1, 'L')
    pdf.ln(10)
    
    # Потери
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(160, 30, 30)
    pdf.cell(0, 10, 'ФИНАНСОВЫЙ АУДИТ ПОТЕРЬ (Tracking Error)', 0, 1, 'L')
    pdf.set_font('Arial', '', 11)
    pdf.set_text_color(40, 40, 40)
    msg = f"При текущей экспертной оценке ({round(score, 1)}/100) вы теряете около {round(100 - score, 1)}% целевых запросов. Упущенная выручка (Lost Revenue) оценивается в горячем трафике на сумму около {revenue_loss:,} руб. ежемесячно."
    pdf.multi_cell(0, 7, msg.replace(',', ' '))
    pdf.ln(10)
    
    # 2. Матрица PIN100
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 10, 'МАТРИЦА ОЦЕНКИ РЕПУТАЦИОННЫХ АКТИВОВ', 0, 1, 'L')
    pdf.set_font('Arial', 'B', 8)
    
    # Заголовки таблицы
    pdf.set_fill_color(220)
    pdf.cell(20, 8, 'Код', 1, 0, 'C', True)
    pdf.cell(100, 8, 'Критерий', 1, 0, 'L', True)
    pdf.cell(30, 8, 'Результат', 1, 0, 'C', True)
    pdf.cell(40, 8, 'Макс', 1, 1, 'C', True)
    
    pdf.set_font('Arial', '', 7)
    pdf.set_text_color(80)
    
    for row in data_matrix:
        code = row['Код']
        name = row['Критерий'][:60]
        earned = row['Балл']
        max_s = row['Макс']
        status = "✅" if earned > 0 else "❌"
        
        pdf.cell(20, 7, code, 1, 0, 'C')
        pdf.cell(100, 7, name, 1, 0, 'L')
        pdf.cell(30, 7, status, 1, 0, 'C')
        pdf.cell(40, 7, f'{earned}/{max_s}', 1, 1, 'C')
        
    pdf.ln(15)
    
    # 3. Call to Action
    pdf.set_font('Arial', 'I', 9)
    pdf.set_text_color(100)
    pdf.multi_cell(0, 6, "По результатам экспертного PIN100 аудита, ваша компания недополучает значительную долю прибыли из-за отклонения от эталона рынка. Рекомендуется внедрение Roadmap-политики для оптимизации репутационного капитала. Свяжитесь с нами для обсуждения стратегии.")
    
    return pdf.output(dest='S')

# ==========================================
# 4. СБОРКА И ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title=f"{PROJECT_NAME} | Экспертный Аудит", layout="wide", page_icon="📍")

rules_data, prompts_data, doc = get_database_from_sheets()

with st.sidebar: 
    st.markdown(f"## 📍 {PROJECT_NAME}")
    st.write("✅ База бенчмарков подключена.")
    st.caption("Управление весами и Roadmap осуществляется в Google Sheets.")

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
            
        with st.spinner("Анализ данных, экспертная оценка и расчет экономики..."):
            # БЛОК 1: Проверка ниши с Kill-Switch и экспертной оценкой
            try:
                niche_key = determine_niche_by_expert(title, cat)
            except Exception as e:
                send_telegram_alert(str(e), url)
                st.error(f"🚨 РАСШИФРОВКА ЭКСПЕРТНОГО СБОЯ (Ниша): {e}")
                st.stop()
            
            # БЛОК 2: Базовый парсинг
            raw_scores = {}
            for f in [calculate_prof_rules, calculate_rep_rules]:
                sc = f(data)
                raw_scores.update(sc)
            
            # БЛОК 3: Продвинутый аудит экспертным модулем
            try:
                exp_sc, exp_reasons = calculate_dynamic_expert_rules(data, prompts_data)
                raw_scores.update(exp_sc)
            except Exception as e:
                send_telegram_alert(str(e), url)
                st.error(f"🚨 РАСШИФРОВКА ЭКСПЕРТНОГО СБОЯ (Аудит): {e}")
                st.stop()
            
            results = []
            final_total_score = 0.0
            matrix_data = [] # Для PDF
            
            # PIN100 в B2B нише использует столбец 'B2B' в Google Таблице
            target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                roadmap = str(r.get('Этап внедрения (Roadmap)', 'Прочее'))
                priority = str(r.get('Приоритет', '2 - Средний'))
                
                try: max_s = float(str(r.get(target_column, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
                except: max_s = float(r.get('Балл', 0.0))
                
                if max_s > 0.0:
                    val = max_s if raw_scores.get(code) else 0.0
                    final_total_score += val
                    comm = "✅ Выполнено" if val > 0 else "❌ Требует внедрения"
                    # reasons (для дебага) мы берем из экспертного модуля
                    exp_reason = exp_reasons.get(code, "Автоматическое правило")
                    
                    results.append({"Этап": roadmap, "Приоритет": priority, "Критерий": name, "Результат": comm, "Балл": val, "Макс": max_s})
                    matrix_data.append({"Код": code, "Критерий": name, "Балл": val, "Макс": max_s})

            # Подключаем интерактивный B2B калькулятор экономики
            eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
            niche_label = eco.get("label", "Прочее")
            
            with st.sidebar:
                st.divider()
                st.markdown(f"### 🧮 Калькулятор сегмента: {niche_key}")
                st.caption("Подстройте показатели под реалии клиента")
                client_leads = st.number_input("Потенциал лидов/мес", value=eco["leads"], step=10)
                client_check = st.number_input("Средний чек (₽)", value=eco["check"], step=5000)

            lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
            lost_revenue = int(client_leads * lost_percentage * client_check)
            
            # --- ОТОБРАЖЕНИЕ PIN100 ОТЧЕТА ---
            st.divider()
            col1, col2 = st.columns([2, 1])
            with col1: 
                st.subheader(f"🏢 {title}")
                st.caption(f"🧠 Сегмент: **{niche_label}** | 📍 Фактических отзывов: {client_reviews}")
            with col2: 
                if final_total_score >= 80: delta = "Отличный результат"
                elif final_total_score >= 50: delta = "Требует оптимизации"
                else: delta = "Критический уровень риска"
                color = "normal" if final_total_score >= 80 else ("off" if final_total_score >= 50 else "inverse")
                st.metric(f"Индекс готовности {PROJECT_NAME}", f"{round(final_total_score, 1)} / 100", delta=delta, delta_color=color)

            st.markdown("### 💸 Цена ошибок (Lost Revenue / Tracking Error)")
            st.error(f"На основе бенчмарков {niche_label}, при вашей экспертной оценке ({round(final_total_score, 1)}/100) и среднем чеке в {client_check:,} ₽, вы ежемесячно недополучаете горячего трафика на сумму около **{lost_revenue:,} ₽**.".replace(',', ' '))
            
            st.divider()
            st.markdown("### 🗺 Пошаговый план внедрения (Roadmap)")
            
            df_results = pd.DataFrame(results)
            stages = df_results['Этап'].unique()
            stages = sorted(stages, key=lambda x: ("Этап 1" not in x, "Этап 2" not in x, "Этап 3" not in x, "Этап 4" not in x, x))
            
            for stage in stages:
                stage_data = df_results[df_results['Этап'] == stage]
                stage_earned = stage_data['Балл'].sum()
                stage_max = stage_data['Макс'].sum()
                stage_progress = int((stage_earned / stage_max) * 100) if stage_max > 0 else 0
                
                with st.expander(f"{stage} — Готовность: {stage_progress}%", expanded=(stage_progress < 100)):
                    st.progress(stage_progress / 100)
                    display_df = stage_data[['Приоритет', 'Критерий', 'Результат', 'Балл', 'Макс']].sort_values(by=['Приоритет'], ascending=True)
                    st.dataframe(display_df, hide_index=True, use_container_width=True)

            try:
                leads_sheet = doc.worksheet("Leads")
                leads_sheet.append_row([time.strftime("%d.%m.%Y %H:%M:%S"), url, title, niche_key, final_total_score, lost_revenue])
            except Exception:
                pass

            # --- ПАНЕЛЬ РАЗРАБОТЧИКА (БЕЗ УПОМИНАНИЯ ИИ) ---
            st.divider()
            with st.expander("🛠 Экспертная панель (Детальная аналитика)"):
                st.markdown("### 1. Как мыслит экспертный модуль")
                
                ai_debug_info = []
                for r in rules_data:
                    code = str(r.get('Код', '')).strip()
                    if code in exp_reasons:
                        name = str(r.get('Критерий', '')).strip()
                        status = "✅ Сдал" if exp_sc.get(code) else "❌ Не сдал"
                        ai_debug_info.append({
                            "Критерий": name,
                            "Результат": status,
                            "Экспертное обоснование": exp_reasons[code]
                        })
                
                if ai_debug_info:
                    st.dataframe(pd.DataFrame(ai_debug_info), use_container_width=True, hide_index=True)
                
                st.markdown("### 2. Сырые фактические данные")
                debug_data = {
                    "Название": data.get('title'),
                    "Рейтинг": data.get('rating'),
                    "Кол-во отзывов": data.get('reviewsCount'),
                    "Сайт / Ссылка": data.get('url') or data.get('website'),
                    "График работы": data.get('workingHours'),
                    "Сырой отзыв целиком (ДЛЯ ПОИСКА ОТВЕТА)": data.get('reviews', [{}])[0] if data.get('reviews') else "Пусто"
                }
                st.json(debug_data)
            
            # --- КНОПКА ГЕНЕРАЦИИ PDF PIN100 ---
            st.divider()
            pdf_bytes = create_pdf_report(title, niche_label, final_total_score, lost_revenue, matrix_data)
            st.download_button(
                label="📄 Скачать экспертный отчет PIN100 (PDF)",
                data=pdf_bytes,
                file_name=f"PIN100_Report_{title.replace(' ', '_')}.pdf",
                mime="application/pdf",
                type="secondary"
            )
