import argparse
import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ==========================================================
# ЭКОНОМИЧЕСКИЕ ПАРАМЕТРЫ НИШ
# ==========================================================

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,  # медиана обращений ТОП-3 района
        "base_check": 5500,     # консервативный порог первого визита
        "ltv_months": 12,       # горизонт прикрепления
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4500,
        "ltv_months": 10,
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3800,
        "ltv_months": 12,
    },
}


# ==========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И СКЛОНЕНИЯ
# ==========================================================

def format_currency(value: float | int) -> str:
    """Форматирует число с разделением тысяч неразрывным пробелом."""
    return f"{int(round(value)):,}".replace(",", " ")


def get_declension(number: int, word_type: str = "пациент") -> str:
    """Возвращает корректную форму существительного в зависимости от числа."""
    n = abs(int(number)) % 100
    n1 = n % 10

    if word_type == "пациент":
        if 11 <= n <= 19:
            return "пациентов"
        if n1 == 1:
            return "пациент"
        if 2 <= n1 <= 4:
            return "пациента"
        return "пациентов"

    if word_type == "клиент":
        if 11 <= n <= 19:
            return "клиентов"
        if n1 == 1:
            return "клиент"
        if 2 <= n1 <= 4:
            return "клиента"
        return "клиентов"

    return "обращений"


def get_score_color(score: float) -> str:
    """Цветовая индикация общего балла готовности."""
    if score >= 80:
        return "16a34a"  # Зеленый
    if score >= 60:
        return "d97706"  # Янтарный / Оранжевый
    return "dc2626"      # Красный


def sanitize_filename(name: str) -> str:
    """Очищает строку для безопасного использования в именах файлов."""
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")


# ==========================================================
# ГЕНЕРАТОР ПЕРВОГО СООБЩЕНИЯ (ICEBREAKER)
# ==========================================================

def generate_icebreaker(
    title: str,
    rating: float | str,
    competitors: List[str],
    lost_leads: int,
    niche_genitive: str = "стоматологий",
) -> str:
    """Генерирует согласованное первое сообщение руководителю (ЛПР)"""
    if competitors and len(competitors) >= 2:
        comp_str = f"«{competitors[0]}» и «{competitors[1]}»"
    elif competitors and len(competitors) == 1:
        comp_str = f"«{competitors[0]}»"
    else:
        comp_str = "прямые конкуренты"

    low_range = max(1, lost_leads - 2)
    high_range = lost_leads + 3
    leads_range_str = f"{low_range}–{high_range}"

    return (
        f"Добрый день!\n\n"
        f"Анализировали выдачу {niche_genitive} в вашем районе на Яндекс Картах "
        f"и обратили внимание на карточку «{title}». При сильной репутации ({rating}) "
        f"первичный поток прямо сейчас перехватывают {comp_str}.\n\n"
        f"На поверхности лежит отсутствие кнопки быстрой записи (пациенты вечером не хотят звонить "
        f"и уходят к соседям), но алгоритмы пессимизируют карточку еще по нескольким (иногда не очевидным) "
        f"параметрам. По емкости района это отток около {leads_range_str} пациентов в месяц.\n\n"
        f"Собрали наглядный разбор карточки и расчет потерь в короткий PDF на 4 страницы. "
        f"Скинуть файл сюда для ознакомления?"
    )


# ==========================================================
# РАСЧЕТ ЮНИТ-ЭКОНОМИКИ И ПОДГОТОВКА ДАННЫХ
# ==========================================================

def calculate_report_metrics(audit_data: Dict[str, Any]) -> Dict[str, str]:
    """Производит расчет финансовых показателей и готовит маппинг под Typst."""
    niche_key = audit_data.get("niche", "DENTISTRY")
    niche_info = NICHE_CONFIG.get(niche_key, NICHE_CONFIG["DENTISTRY"])

    title = audit_data.get("title", "Организация")
    rating = audit_data.get("rating", 4.7)
    score = float(audit_data.get("score", 66.5))

    leads_bench = audit_data.get("benchmark_leads", niche_info["benchmark_leads"])
    base_check = audit_data.get("base_check", niche_info["base_check"])
    ltv_months = audit_data.get("ltv_months", niche_info["ltv_months"])

    # Дефицит конверсии и потери
    dev = max(0.0, round(100.0 - score, 1))
    lost_leads = int(round(leads_bench * (dev / 100.0)))
    rev_loss = lost_leads * base_check
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * ltv_months

    word_type = niche_info["client_word"]
    table_declension = get_declension(lost_leads, word_type)

    # Разбор ошибок для страницы 3
    failures = audit_data.get("top_failures", [])
    fail_1 = failures[0] if len(failures) > 0 else {
        "title": "Отсутствие сквозной онлайн-записи (модуля МИС)",
        "desc": "Пациенты в вечерние часы и с мобильных устройств не могут записаться в один клик. При отсутствии кнопки прямого действия свыше 60% мобильного трафика возвращаются в поисковую выдачу к конкурентам."
    }
    fail_2 = failures[1] if len(failures) > 1 else {
        "title": "Фрагментарный прайс-лист без цен «от...»",
        "desc": "В карточке оцифровано менее 30% услуг клиники. Алгоритм гео-поиска Яндекса ранжирует профили с полной витриной цен выше при категориальных запросах пациентов района."
    }
    fail_3 = failures[2] if len(failures) > 2 else {
        "title": "Неоптимизированное описание профиля (дефицит гео-семантики)",
        "desc": "Текст карточки не содержит ключевых поисковых маркеров района и специализаций, из-за чего профиль исключается из выдачи по среднечастотным медицинским запросам."
    }

    report_date = audit_data.get(
        "date",
        datetime.date.today().strftime("%d.%m.%Y")
    )

    mapping = {
        "[[TITLE]]": title,
        "[[NICHE]]": niche_info["niche_name"],
        "[[DATE]]": report_date,
        "[[SCORE]]": f"{score:.1f}" if score % 1 != 0 else str(int(score)),
        "[[SCORE_COLOR]]": get_score_color(score),
        "[[REV_LOSS_FMT]]": format_currency(rev_loss),
        "[[CLIENT_LEADS]]": str(leads_bench),
        "[[DEV]]": f"{dev:.1f}" if dev % 1 != 0 else str(int(dev)),
        "[[LOST_LEADS]]": str(lost_leads),
        "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": format_currency(base_check),
        "[[CLIENT_LTV]]": str(ltv_months),
        "[[LTV_LOSS_FMT]]": format_currency(ltv_loss),
        "[[QUALITY_PHRASE]]": niche_info["quality_phrase"],
        "[[EXECUTIVE_SUMMARY]]": audit_data.get(
            "executive_summary",
            f"Профиль «{title}» обладает высокой клинической репутацией ({rating}), однако из-за отсутствия прямого конверсионного инструментария (онлайн-запись и открытый прейскурант) алгоритм перенаправляет до {lost_leads} готовых обращений в месяц прямым конкурентам локации."
        ),
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери пациентов",
        "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию в первичное обращение:",
        "[[FAIL_1_TITLE]]": fail_1["title"],
        "[[FAIL_1_DESC]]": fail_1["desc"],
        "[[FAIL_2_TITLE]]": fail_2["title"],
        "[[FAIL_2_DESC]]": fail_2["desc"],
        "[[FAIL_3_TITLE]]": fail_3["title"],
        "[[FAIL_3_DESC]]": fail_3["desc"],
        "[[WEEKLY_LOSS_FMT]]": format_currency(weekly_loss),
    }

    return mapping


# ==========================================================
# СБОРКА ТЕМПЛЕЙТА И КОМПИЛЯЦИЯ В TYPST
# ==========================================================

def render_typst_template(template_path: Path, mapping: Dict[str, str]) -> str:
    """Читает исходный файл .typ и заменяет все плейсхолдеры."""
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    for placeholder, val in mapping.items():
        content = content.replace(placeholder, val)

    return content


def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path) -> bool:
    """Записывает промежуточный .typ файл и вызывает CLI-компилятор Typst."""
    temp_typ_path = work_dir / f"temp_{output_pdf_path.stem}.typ"

    try:
        with open(temp_typ_path, "w", encoding="utf-8") as f:
            f.write(typst_content)

        cmd = ["typst", "compile", str(temp_typ_path), str(output_pdf_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка компиляции Typst: {e.stderr}")
        return False
    except FileNotFoundError:
        print("Ошибка: утилита 'typst' не найдена в PATH системы. Установите Typst CLI.")
        return False
    finally:
        if temp_typ_path.exists():
            try:
                temp_typ_path.unlink()
            except OSError:
                pass


# ==========================================================
# ОСНОВНОЙ ПАЙПЛАЙН ОБРАБОТКИ
# ==========================================================

def process_clinic_audit(
    audit_data: Dict[str, Any],
    template_path: Path,
    output_dir: Path
) -> Tuple[Path, Path]:
    """
    Выполняет полный цикл генерации:
    1. Расчет метрик и подготовка данных
    2. Компиляция PDF-отчета
    3. Создание текстового файла icebreaker
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    title = audit_data.get("title", "Организация")
    org_id = audit_data.get("org_id", "0000000000")
    date_str = audit_data.get("date_raw", datetime.date.today().strftime("%Y-%m-%d"))

    file_prefix = f"{sanitize_filename(title)}_{org_id}_{date_str}"
    pdf_path = output_dir / f"{file_prefix}_report.pdf"
    txt_path = output_dir / f"{file_prefix}_icebreaker.txt"

    # Расчет метрик
    mapping = calculate_report_metrics(audit_data)

    # Генерация Typst PDF
    rendered_typst = render_typst_template(template_path, mapping)
    success = compile_typst_pdf(rendered_typst, pdf_path, work_dir=output_dir)
    if success:
        print(f"[+] Сгенерирован PDF отчет: {pdf_path.resolve()}")
    else:
        print(f"[-] Не удалось собрать PDF для {title}")

    # Генерация Icebreaker
    niche_key = audit_data.get("niche", "DENTISTRY")
    niche_genitive = NICHE_CONFIG.get(niche_key, NICHE_CONFIG["DENTISTRY"])["niche_genitive"]
    lost_leads_int = int(mapping["[[LOST_LEADS]]"])

    icebreaker_text = generate_icebreaker(
        title=title,
        rating=audit_data.get("rating", 4.7),
        competitors=audit_data.get("competitors", []),
        lost_leads=lost_leads_int,
        niche_genitive=niche_genitive,
    )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(icebreaker_text)

    print(f"[+] Сохранен текст первого сообщения: {txt_path.resolve()}")
    return pdf_path, txt_path


# ==========================================================
# ТОЧКА ВХОДА CLI
# ==========================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PIN100 Analytics: Генератор PDF-отчетов и outreach-сообщений для клиник."
    )
    parser.add_argument(
        "-f", "--file", type=str, help="Путь к JSON-файлу с аудитом клиники."
    )
    parser.add_argument(
        "-t", "--template", type=str, default="report_template.typ",
        help="Путь к шаблону Typst (по умолчанию: report_template.typ)."
    )
    parser.add_argument(
        "-o", "--outdir", type=str, default="output",
        help="Директория для сохранения готовых файлов (по умолчанию: ./output)."
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Запустить демонстрационную генерацию для тестовой клиники «Айдента»."
    )

    args = parser.parse_args()

    template_file = Path(args.template)
    if not template_file.exists():
        print(f"Ошибка: Файл шаблона '{template_file}' не найден в рабочей директории.")
        return

    output_dir = Path(args.outdir)

    if args.sample or not args.file:
        sample_data = {
            "title": "Айдента",
            "org_id": "1015646715",
            "date": "11.09.2026",
            "date_raw": "2026-09-11",
            "rating": 4.7,
            "score": 66.5,
            "niche": "DENTISTRY",
            "competitors": ["РозДент", "На Приморской"],
            "benchmark_leads": 70,
            "base_check": 5500,
            "ltv_months": 12,
            "executive_summary": (
                "Профиль «Айдента» обладает высокой клинической репутацией (4.7), однако из-за отсутствия "
                "прямого конверсионного инструментария (онлайн-запись и открытый прейскурант) алгоритм "
                "перенаправляет до 23 готовых первичных обращений в месяц прямым конкурентам локации."
            ),
            "top_failures": [
                {
                    "title": "Отсутствие кнопки быстрой онлайн-записи (виджета МИС)",
                    "desc": "Пациенты в вечерние часы и при острой боли не хотят совершать звонок администратору. Карточка теряет от 60% вечернего и мобильного трафика, отдавая записи клиникам с активным модулем записи."
                },
                {
                    "title": "Фрагментарный прейскурант без цен формата «от...»",
                    "desc": "В карточке заполнено менее трети ключевых позиций (имплантация, терапия, гигиена). Поисковые алгоритмы Яндекса пессимизируют профиль по предметным запросам процедур."
                },
                {
                    "title": "Дефицит гео-семантики в описании организации",
                    "desc": "Текст профиля не содержит явных привязок к локации и ключевым направлениям работы, что снижает частоту показа в органическом радиусе 1.5 км."
                }
            ]
        }
        process_clinic_audit(sample_data, template_file, output_dir)
    else:
        audit_file = Path(args.file)
        if not audit_file.exists():
            print(f"Ошибка: Входной файл '{audit_file}' не найден.")
            return

        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            for entry in data:
                process_clinic_audit(entry, template_file, output_dir)
        else:
            process_clinic_audit(data, template_file, output_dir)


if __name__ == "__main__":
    main()
