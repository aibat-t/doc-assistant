# HTML-фикстуры повторяют вёрстку adilet, переносить их строки нельзя
# ruff: noqa: E501

import pytest

from docs_assistant.ingestion.parsers.html_adilet import (
    Level,
    classify,
    extract_lines,
    parse_document,
)
from docs_assistant.ingestion.text import MainContentNotFoundError

# Фрагмент в духе настоящей страницы old.adilet.zan.kz: заголовки в <h3> через <br>,
# статьи в <p><b>, сноски в span.note и p.note, примечание красным шрифтом.
RU_PAGE = """<html><body>
<div class="menu">Главная | Поиск</div>
<article>
<font color="#FF0000">Примечание ИЗПИ!<br/>Для удобства пользования ИЗПИ создано Содержание</font><br/>
<p><a href="#">СОДЕРЖАНИЕ</a></p>
<p class="note">Сноска. По всему тексту слова заменены Законом РК от 11.06.2026 № 306-VIII.</p>
<h3>ОБЩАЯ ЧАСТЬ<br/>РАЗДЕЛ 1. ОБЩИЕ ПОЛОЖЕНИЯ<br/>Глава 1. ОСНОВНЫЕ ПОЛОЖЕНИЯ В ОБЛАСТИ ТРУДОВЫХ<br/>ОТНОШЕНИЙ</h3>
<p><b><a name="z1"></a>Статья 1 . Основные понятия</b></p>
<p>1. В настоящем Кодексе используются следующие понятия:</p>
<p>1) отпуск – освобождение работника от работы;</p>
<span class="note">2) исключен Законом РК от 08.07.2024 </span><a href="#">№ 116-VIII</a><span class="note"> (вводится в действие).</span><br/>
<p>3) труд – деятельность человека.</p>
<p>2. Статья 87 настоящего Кодекса применяется к работникам.</p>
<p>3. Исключен Законом РК от 24.12.2012 № 60-V (вводится в действие).</p>
<span class="note">Сноска. Статья 1 с изменениями, внесенными Законом РК от 23.12.2023 </span><a href="#">№ 51-VIII</a><br/>
<h3>Глава 2. ТРУДОВОЙ ДОГОВОР Статья 87. Расторжение трудового договора</h3>
<p>Трудовой договор расторгается по <u>соглашению</u> сторон.</p>
<p><b>Статья 88. Утратившая силу статья</b></p>
<p class="note">Сноска. Статья 88 исключена Законом РК от 09.01.2026 № 256-VIII.</p>
<p><b>Статья 89. Ставки</b></p>
<table><tr><td><p>Вид</p></td><td><p>Ставка</p></td></tr><tr><td>Отпуск</td><td>24 дня</td></tr></table>
</article></body></html>"""

KK_PAGE = """<html><body><article>
<p><font color="#FF0000">ЗҚАИ-ның ескертпесі!</font><br/>
<font color="#FF0000">Осы Кодекстің қолданысқа енгізілу тәртібін 204-баптан қараңыз.</font></p>
<span class="note">Ескерту. Мазмұны алып тасталды – ҚР 01.07.2021 Заңымен.</span><br/>
<h3>ЖАЛПЫ БӨЛІК<br/>1-БӨЛІМ. ЖАЛПЫ ЕРЕЖЕЛЕР<br/>1-тарау. НЕГІЗГІ ЕРЕЖЕЛЕР</h3>
<p><b>1-бап. Осы Кодексте пайдаланылатын негізгі ұғымдар</b></p>
<p>1. Осы Кодексте мынадай негізгі ұғымдар пайдаланылады:</p>
<p>1) еңбек – адамның қызметі;</p>
<p>2) алып тасталды – ҚР 08.07.2024 № 116-VIII Заңымен.</p>
<h3>2-тарау. ЕҢБЕК ШАРТЫ</h3>
<p><b>87-бап. Еңбек шартын бұзу</b></p>
<p>Еңбек шарты тараптардың келісімі бойынша бұзылады.</p>
</article></body></html>"""


def _articles(blocks):
    return [b for b in blocks if b.level is Level.article]


def test_ru_structure_and_articles():
    blocks = parse_document(RU_PAGE)
    headings = [(b.level, b.heading) for b in blocks if b.level < Level.article]
    assert headings == [
        (Level.part, "ОБЩАЯ ЧАСТЬ"),
        (Level.section, "РАЗДЕЛ 1. ОБЩИЕ ПОЛОЖЕНИЯ"),
        # Перенос через <br> внутри <h3> склеен в один заголовок
        (Level.chapter, "Глава 1. ОСНОВНЫЕ ПОЛОЖЕНИЯ В ОБЛАСТИ ТРУДОВЫХ ОТНОШЕНИЙ"),
        # «Глава 2 … Статья 87 …» в одном <h3> разрезано на главу и статью
        (Level.chapter, "Глава 2. ТРУДОВОЙ ДОГОВОР"),
    ]
    articles = _articles(blocks)
    assert [a.number for a in articles] == ["1", "87", "88", "89"]
    assert articles[0].heading == "Статья 1 . Основные понятия"
    assert articles[1].heading == "Статья 87. Расторжение трудового договора"
    # <u> внутри абзаца не рвёт строку
    assert articles[1].text == "Трудовой договор расторгается по соглашению сторон."


def test_ru_notes_and_excluded_points_are_dropped():
    first = _articles(parse_document(RU_PAGE))[0]
    assert first.text.split("\n") == [
        "1. В настоящем Кодексе используются следующие понятия:",
        "1) отпуск – освобождение работника от работы;",
        "3) труд – деятельность человека.",
        # Ссылка на статью в тексте — не заголовок: после номера нет точки
        "2. Статья 87 настоящего Кодекса применяется к работникам.",
    ]
    all_text = "\n".join(extract_lines(RU_PAGE))
    for noise in ("Сноска", "ИЗПИ", "СОДЕРЖАНИЕ", "116-VIII", "51-VIII", "Исключен", "Главная"):
        assert noise not in all_text


def test_excluded_article_has_empty_text():
    art88 = next(a for a in _articles(parse_document(RU_PAGE)) if a.number == "88")
    assert art88.text == ""


def test_table_row_is_one_line():
    art89 = next(a for a in _articles(parse_document(RU_PAGE)) if a.number == "89")
    assert art89.text.split("\n") == ["Вид | Ставка", "Отпуск | 24 дня"]


def test_kk_structure_and_articles():
    blocks = parse_document(KK_PAGE)
    headings = [(b.level, b.heading) for b in blocks if b.level < Level.article]
    assert headings == [
        (Level.part, "ЖАЛПЫ БӨЛІК"),
        (Level.section, "1-БӨЛІМ. ЖАЛПЫ ЕРЕЖЕЛЕР"),
        (Level.chapter, "1-тарау. НЕГІЗГІ ЕРЕЖЕЛЕР"),
        (Level.chapter, "2-тарау. ЕҢБЕК ШАРТЫ"),
    ]
    articles = _articles(blocks)
    assert [a.number for a in articles] == ["1", "87"]
    assert articles[0].text.split("\n") == [
        "1. Осы Кодексте мынадай негізгі ұғымдар пайдаланылады:",
        "1) еңбек – адамның қызметі;",
    ]
    all_text = "\n".join(extract_lines(KK_PAGE))
    assert "ескертпесі" not in all_text
    assert "Ескерту" not in all_text


def test_preamble_before_first_article():
    page = (
        "<article><p>Настоящий Закон регулирует отношения в области связи.</p>"
        "<h3>Глава 1. Общие положения</h3><p><b>Статья 1. Понятия</b></p><p>Текст.</p></article>"
    )
    blocks = parse_document(page)
    assert blocks[0].level is Level.preamble
    assert blocks[0].heading == "Преамбула"
    assert blocks[0].text == "Настоящий Закон регулирует отношения в области связи."


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Статья 20-1. Восстановление платежеспособности", (Level.article, "20-1")),
        ("338-5-бап. Қамтамасыз ету ақысы ұғымы", (Level.article, "338-5")),
        ("Глава II. СОЗДАНИЕ ТОВАРИЩЕСТВА", (Level.chapter, "II")),
        ("Раздел 4 Отдельные виды обязательств", (Level.section, "4")),
        ("4 бөлім Міндеттемелердің жекелеген түрлері", (Level.section, "4")),
        ("Параграф 1. Общие положения о купле-продаже", (Level.paragraph, "1")),
        ("2-параграф. Деңгейлес мониторинг", (Level.paragraph, "2")),
        ("Жалпы бөлім", (Level.part, None)),
        ("Статья 87 настоящего Кодекса применяется", None),
        ("87-бапта көзделген жағдайларда", None),
        ("1. Работник имеет право:", None),
    ],
)
def test_classify(line, expected):
    assert classify(line) == expected


def test_roman_group_only_in_headings():
    assert classify("VII. Некоммерческие организации", in_heading=True) == (Level.paragraph, "VII")
    assert classify("VII. Некоммерческие организации") is None


def test_page_without_article_raises():
    with pytest.raises(MainContentNotFoundError):
        parse_document("<html><body><div>нет текста</div></body></html>")


def test_article_without_dot_only_in_headings():
    # «663-бап Жұмыс…» в <h3> — заголовок; та же строка в тексте была бы ссылкой
    assert classify("663-бап Жұмыс нәтижелерін тапсыру", in_heading=True) == (Level.article, "663")
    assert classify("Статья 5 Общие положения", in_heading=True) == (Level.article, "5")
    assert classify("663-бап Жұмыс нәтижелерін тапсыру") is None
