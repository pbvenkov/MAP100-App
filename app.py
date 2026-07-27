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

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets.get("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# Инициализация ИИ (используем последнюю версию Flash)
try:
    genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))
    ai_model = genai.GenerativeModel('gemini-3.6-flash') 
except Exception as e:
    ai_model = None

# Функция для отправки алертов в Telegram (С ОТЛАДКОЙ В ТЕРМИНАЛ)
def send_telegram_alert(error_msg, target_url="Неизвестно"):
    tg_token = st.secrets.get("TG_BOT_TOKEN")
    tg_admin_id = st.secrets.get("TG_ADMIN_ID")
    
    if tg_token and tg_admin_id:
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        text = f"🚨 *MAP100: Критический сбой ИИ*\n\n*Аудит:* {target_url}\n*Ошибка:* {error_msg}\n\n🛑 *Действие:* Генерация отчета остановлена."
        try:
            response = requests.post(tg_url, json={"chat_id": tg_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=5)
            print(f"Ответ от Telegram: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Ошибка сети при отправке в Telegram: {e}")
    else:
        print("ВНИМАНИЕ: Ключи TG_BOT_TOKEN или TG_ADMIN_ID не найдены в secrets.toml")

# ==========================================
# 1.5. БАЗА ДАННЫХ НИШ И РЕГЛАМЕНТОВ
# ==========================================
NICHE_ECONOMICS = {
    "HORECA": {"leads": 300, "check": 2500},
    "B2B_PRODUCTION": {"leads": 20, "check": 100000},
    "RETAIL": {"leads": 400, "check": 1500},
    "AUTO": {"leads": 150, "check": 8000},
    "SERVICES": {"leads": 100, "check": 5000},
    "BEAUTY_MEDICAL": {"leads": 150, "check": 4000},
    "OTHER": {"leads": 100, "check": 3000}
}

def determine_niche(title, category):
    if not ai_model: 
        raise Exception("Модуль ИИ не инициализирован (отсутствует или неверен GEMINI_API_KEY).")
        
    prompt = f"""
    Определи бизнес по названию "{title}" и категории "{category}".
    ВНИМАНИЕ: Если в категории есть слова "стоматология", "клиника", "медицина", "красота", "салон" - это СТРОГО BEAUTY_MEDICAL.
    Выбери ОДИН наиболее подходящий ключ из списка:
    - HORECA 
    - B2B_PRODUCTION 
    - RETAIL 
    - AUTO 
    - SERVICES 
    - BEAUTY_MEDICAL 
    - OTHER 
    Верни ТОЛЬКО ОДНО СЛОВО - ключ на английском.
    """
    try:
        response = ai_model.generate_content(prompt)
        key = response.text.strip().upper()
        valid_keys = ["BEAUTY_MEDICAL", "HORECA", "B2B_PRODUCTION", "RETAIL", "AUTO", "SERVICES", "OTHER"]
        for v in valid_keys:
            if v in key: return v
        return "OTHER"
    except Exception as e:
        raise Exception(f"Сбой API (Ниша): {str(e)}")

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
# 3. АЛГОРИТМЫ ОЦЕНКИ MAP100
# ==========================================
def get_safe_list(data, keys):
    res = []
    for k in keys:
        if isinstance(data.get(k), list): res.extend(data[k])
        elif isinstance(data.get(k), dict): res.append(data[k])
    return res

def calculate_prof_rules(data):
    scores, logs = {}, []
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

    phones = data.get('phones')
    if isinstance(phones, list):
        for p in phones:
            p_str = str(p).lower()
            if "доб" not in p_str and len(re.sub(r'\D', '', p_str)) >= 10:
                scores['PROF-05.2'] = True
                break
                
    feat = data.get('features')
    if isinstance(feat, list):
        if len(feat) > 0: scores['PROF-08.1'] = True
        if len(feat) >= 5: scores['PROF-08.2'] = True
    else: feat = []

    if len(description) > 1500: scores['PROF-09.1'] = True
    
    url = str(data.get('url') or data.get('website') or '').lower()
    if url: 
        scores['PROF-04.1'] = True
        if "utm_" in url: scores['PROF-04.2'] = True
            
    if data.get('requisites') or data.get('legalInfo'): scores['PROF-15.1'] = True
    working_hours_str = str(data.get('workingHours') or '').lower()
    if 'перерыв' in working_hours_str or 'special' in working_hours_str: scores['PROF-07.2'] = True
        
    search_text = f"{description} {' '.join(str(f) for f in feat)}".lower()
    if re.search(r'(в 19\d{2}|в 20\d{2}|с 19\d{2}|с 20\d{2}|since)', search_text): scores['PROF-14.1'] = True

    prods = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    valid_prods = [p for p in prods if isinstance(p, dict)]
    if len(valid_prods) >= 10:
        scores['PROF-11.1'] = True
        if sum(1 for p in valid_prods if p.get('photoUrl') or p.get('imageUrl') or p.get('image')) / len(valid_prods) >= 0.8: scores['PROF-11.2'] = True
        if sum(1 for p in valid_prods if p.get('price')) / len(valid_prods) >= 0.8: scores['PROF-11.3'] = True
        if sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 50) / len(valid_prods) >= 0.8: scores['PROF-11.4'] = True
        c_set = set()
        for p in valid_prods:
            cat = p.get('category')
            if isinstance(cat, dict): c_set.add(str(cat.get('name') or ''))
            elif isinstance(cat, list): c_set.add(str(cat[0] if cat else ''))
            else: c_set.add(str(cat or ''))
        if len([c for c in c_set if c]) >= 2: scores['PROF-11.5'] = True
            
    owner_links = url + " " + description + " "
    links_data = data.get('links') or data.get('socialLinks') or data.get('socials') or []
    if isinstance(links_data, list): owner_links += " ".join(str(l) for l in links_data)
    elif isinstance(links_data, dict): owner_links += " ".join(str(v) for v in links_data.values())
    owner_links = owner_links.lower()

    if any(s in owner_links for s in ["t.me", "wa.me", "whatsapp", "viber", "tg://"]): scores['PROF-13.1'] = True
    if any(s in owner_links for s in ["vk.com", "youtube", "dzen", "instagram", "inst:"]): scores['PROF-13.2'] = True
    if data.get('feeds') or 'xml' in owner_links or 'yml' in owner_links: scores['TECH-83.1'] = True
    return scores, logs

def calculate_rep_rules(data):
    scores, logs = {}, []
    try: rating = float(data.get('rating') or 0.0)
    except: rating = 0.0
        
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    
    try: rev_count = int(data.get('reviewsCount') or data.get('ratingsCount') or 0)
    except: rev_count = 0
    if rev_count >= 50: scores['REP-28.1'] = True

    reviews_raw = data.get('reviews')
    if not isinstance(reviews_raw, list): return scores, logs
    reviews = [r for r in reviews_raw if isinstance(r, dict)]
    if not reviews: return scores, logs

    l20 = reviews[:20]
    dates = []
    for r in l20:
        raw_date = r.get('date') or r.get('createdAt')
        if raw_date:
            try: dates.append(datetime.fromisoformat(str(raw_date).replace('Z', '+00:00')))
            except: pass
                
    dates.sort(reverse=True)
    if dates and (datetime.now(timezone.utc) - dates[0]).days < 14: scores['REP-29.1'] = True
    if len(dates) >= 3:
        diffs = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
        if diffs and len(diffs) > 0 and (sum(d == 0 for d in diffs) / len(diffs)) < 0.3: scores['REP-29.2'] = True

    photos_count = sum(1 for r in l20 if isinstance(r.get('photos'), list) and len(r.get('photos')) > 0)
    if l20 and (photos_count / len(l20)) >= 0.1: scores['REP-35.1'] = True

    replied, td, vt, unans_neg, ans_pos = 0, 0, 0, 0, 0
    ow_txt = []
    
    for r in l20:
        try: rate = float(r.get('rating') or 0.0)
        except: rate = 0.0
        rep = r.get('reply') or r.get('ownerAnswer')
        
        if isinstance(rep, dict):
            replied += 1
            rep_text = str(rep.get('text') or '').strip()
            if rep_text: ow_txt.append(rep_text.lower())
            r_date = r.get('date') or r.get('createdAt')
            a_date = rep.get('date') or rep.get('createdAt') or rep.get('updatedAt')
            if r_date and a_date:
                try:
                    rd = datetime.fromisoformat(str(r_date).replace('Z', '+00:00'))
                    ad = datetime.fromisoformat(str(a_date).replace('Z', '+00:00'))
                    days_diff = (ad - rd).days
                    if days_diff >= 0: td += days_diff; vt += 1
                except: pass
        if rate > 0: 
            if rate <= 3 and not isinstance(rep, dict): unans_neg += 1
            if rate >= 4 and isinstance(rep, dict): ans_pos += 1

    if l20 and (replied / len(l20)) >= 0.9: scores['REP-30.1'] = True
    if vt > 0 and (td / vt) <= 3: scores['REP-30.2'] = True
    if unans_neg == 0 and l20: scores['REP-32.1'] = True
    if ans_pos > 0: scores['REP-30.3'] = True

    if len(ow_txt) >= 2:
        templ = False
        for t1, t2 in itertools.combinations(ow_txt[:10], 2):
            w1, w2 = set(re.findall(r'\w+', t1)), set(re.findall(r'\w+', t2))
            union_len = len(w1 | w2)
            if union_len > 0 and (len(w1 & w2) / union_len) > 0.8: templ = True; break
        if not templ: scores['REP-31.1'] = True
    elif len(ow_txt) == 1: scores['REP-31.1'] = True

    if ow_txt:
        stop_words = ['не были', 'не находим', 'уточните', 'нет в базе', 'какой номер']
        if any(w in t for t in ow_txt for w in stop_words): scores['REP-33.1'] = True

    return scores, logs

def calculate_dynamic_ai_rules(data, prompts_data):
    scores, ai_reasons = {}, {}
    if not ai_model or not prompts_data: 
        raise Exception("Модуль ИИ не инициализирован (отсутствует или неверен GEMINI_API_KEY).")

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
                rep = r.get('reply') or r.get('ownerAnswer')
                rep_txt = str(rep.get('text') or '').strip() if isinstance(rep, dict) else ""
                if txt: reviews_text.append(f"Отзыв: {txt} | Ответ владельца: {rep_txt if rep_txt else 'НЕТ ОТВЕТА'}")

    context = f"Название: {title}\nОписание: {desc}\nОсобенности/Услуги: {feat_str}\n"
    if reviews_text: context += "Последние отзывы и ответы:\n" + "\n".join(reviews_text)

    rules_list = []
    for p in prompts_data:
        code = str(p.get('Код', '')).strip()
        prompt_text = str(p.get('Промпт для ИИ', '')).strip()
        if code and prompt_text: rules_list.append(f'"{code}": {prompt_text}')

    if not rules_list: return scores, ai_reasons

    batch_prompt = f"""
Ты — строгий AI-аудитор геосервисов. Проанализируй контекст карточки компании и оцени ее сразу по всем перечисленным критериям.

Контекст карточки:
{context}

Критерии для оценки (Код: Правило):
{chr(10).join(rules_list)}

ТВОЯ ЗАДАЧА:
Верни СТРОГО один JSON-объект, где ключи — это коды критериев, а значения — объекты с полями "score" (boolean: true если выполнено, false если нет) и "reason" (строка: краткое обоснование на 1 предложение).
Никакого лишнего текста.

Пример ответа:
{{
  "AI-01": {{"score": true, "reason": "В описании четко указано УТП компании."}},
  "AI-02": {{"score": false, "reason": "Владелец игнорирует негативные отзывы."}}
}}
"""
    try:
        response = ai_model.generate_content(batch_prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
            for code, result in res_json.items():
                if isinstance(result, dict):
                    is_passed = result.get('score') in [1, True, "1", "true"]
                    if is_passed: scores[code] = True
                    ai_reasons[code] = result.get('reason', 'Нет объяснения')
        else:
            raise Exception("ИИ вернул неверный формат (отсутствует JSON).")
    except Exception as e:
        raise Exception(f"Сбой при запросе к Gemini API (Аудит): {str(e)}")
        
    return scores, ai_reasons

# ==========================================
# 4. СБОРКА И ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title="MAP100 | B2B CRM", layout="wide", page_icon="📈")

rules_data, prompts_data, doc = get_database_from_sheets()

with st.sidebar: 
    st.write("✅ База данных подключена.")
    st.caption("Управление весами и Roadmap осуществляется в Google Sheets.")

st.title("📍 MAP100: AI-Аудитор (Roadmap Edition)")

url = st.text_input("Ссылка на карточку Яндекс.Бизнес")

if st.button("🚀 Запустить глубокий аудит", type="primary"):
    if "yandex" not in url.lower(): 
        st.error("❌ Неверная ссылка.")
    else:
        with st.spinner("Сбор свежих данных клиента..."):
            try:
                data = fetch_apify_data(url)
            except Exception as e:
                st.error(str(e))
                st.stop()
                
            title = data.get('title', 'Без названия')
            c_list = data.get('categories', [])
            cat = c_list[0].get('name', '') if c_list and isinstance(c_list[0], dict) else (str(c_list[0]) if c_list else '')
            client_reviews = int(data.get('reviewsCount') or data.get('ratingsCount') or len(data.get('reviews') or []) or 0)
            
        with st.spinner("Анализ данных, маршрутизация и расчет экономики..."):
            # БЛОК 1: Проверка ниши с Kill-Switch и прямым выводом ошибки
            try:
                niche_key = determine_niche(title, cat)
            except Exception as e:
                send_telegram_alert(str(e), url)
                st.error(f"🚨 РАСШИФРОВКА ОШИБКИ ИИ (Ниша): {e}")
                st.stop()
            
            # БЛОК 2: Базовый парсинг
            raw_scores = {}
            for f in [calculate_prof_rules, calculate_rep_rules]:
                sc, _ = f(data)
                raw_scores.update(sc)
            
            # БЛОК 3: Продвинутый AI-аудит с Kill-Switch и прямым выводом ошибки
            try:
                ai_sc, ai_reasons = calculate_dynamic_ai_rules(data, prompts_data)
                raw_scores.update(ai_sc)
            except Exception as e:
                send_telegram_alert(str(e), url)
                st.error(f"🚨 РАСШИФРОВКА ОШИБКИ ИИ (Аудит): {e}")
                st.stop()
            
            results = []
            final_total_score = 0.0
            
            target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
            if niche_key in ['BEAUTY_MEDICAL', 'OTHER']: target_column = 'Балл'
            
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
                    results.append({"Этап": roadmap, "Приоритет": priority, "Критерий": name, "Балл": val, "Макс": max_s, "Статус": comm})

            eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
            lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
            lost_revenue = int(eco["leads"] * lost_percentage * eco["check"])
            
            st.divider()
            col1, col2 = st.columns([2, 1])
            with col1: 
                st.subheader(f"🏢 {title}")
                st.caption(f"🧠 Ниша: **{niche_key}** | 📍 Текущих отзывов: {client_reviews}")
            with col2: 
                color = "normal" if final_total_score >= 80 else ("off" if final_total_score >= 50 else "inverse")
                st.metric("Общий рейтинг MAP100", f"{round(final_total_score, 1)} / 100", delta="Требует оптимизации" if final_total_score < 80 else "Отличный результат", delta_color=color)

            st.markdown("### 💸 Цена ошибок (Lost Revenue)")
            st.error(f"При вашей оценке ({round(final_total_score, 1)}/100) и среднем чеке в {eco['check']:,} ₽, вы ежемесячно недополучаете горячего трафика на сумму около **{lost_revenue:,} ₽**.".replace(',', ' '))
            
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
                    display_df = stage_data[['Приоритет', 'Критерий', 'Статус', 'Балл', 'Макс']].sort_values(by=['Приоритет'], ascending=True)
                    st.dataframe(display_df, hide_index=True, use_container_width=True)

            try:
                leads_sheet = doc.worksheet("Leads")
                headers = leads_sheet.row_values(1)
                if not headers: 
                    headers = ["Дата", "Ссылка", "Компания", "Ниша", "Балл", "Упущенная выручка"]
                    leads_sheet.append_row(headers)
                row_data = [time.strftime("%d.%m.%Y %H:%M:%S"), url, title, niche_key, final_total_score, lost_revenue]
                leads_sheet.append_row(row_data)
            except Exception:
                pass

            # --- ПАНЕЛЬ РАЗРАБОТЧИКА ---
            st.divider()
            with st.expander("🛠 Режим разработчика (Доказательство реальности данных)"):
                st.markdown("### 1. Как мыслит ИИ (Детальный разбор)")
                st.info("Здесь видно, какое решение принял Gemini по каждому критерию и как он его обосновал.")
                
                ai_debug_info = []
                for r in rules_data:
                    code = str(r.get('Код', '')).strip()
                    if code in ai_reasons:
                        name = str(r.get('Критерий', '')).strip()
                        status = "✅ Сдал" if ai_sc.get(code) else "❌ Не сдал"
                        ai_debug_info.append({
                            "Критерий": name,
                            "Статус": status,
                            "Обоснование ИИ": ai_reasons[code]
                        })
                
                if ai_debug_info:
                    st.dataframe(pd.DataFrame(ai_debug_info), use_container_width=True, hide_index=True)
                else:
                    st.write("ИИ-правила не применялись или API недоступно.")
                
                st.markdown("### 2. Что мы спарсили с Яндекса (Сырые данные)")
                st.info("Это реальные фактические данные, которые отдал API Яндекса в момент проверки.")
                debug_data = {
                    "Название": data.get('title'),
                    "Рейтинг": data.get('rating'),
                    "Кол-во отзывов": data.get('reviewsCount'),
                    "Сайт / Ссылка": data.get('url') or data.get('website'),
                    "График работы": data.get('workingHours'),
                    "Первые 3 отзыва (фрагмент)": [str(r.get('text'))[:100] + "..." for r in data.get('reviews', []) if isinstance(r, dict)][:3]
                }
                st.json(debug_data)
