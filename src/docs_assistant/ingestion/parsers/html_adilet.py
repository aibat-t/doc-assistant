"""Разбор страницы документа old.adilet.zan.kz на структурные блоки.

Вёрстка на adilet неоднородная: заголовки глав и статей бывают в `<h3>`, в `<b>` или просто
в `<p>`, а в одном `<h3>` через `<br>` может идти «ОБЩАЯ ЧАСТЬ / РАЗДЕЛ 1 / Глава 1». Поэтому
HTML используем только для двух вещей: разбить текст на строки и выкинуть сноски. Уровень
строки (раздел, глава, статья) определяем по её тексту регулярками — на русском и казахском.

Парсер текст не режет: на выходе статья целиком. Резать на чанки — задача `chunking.py`.
"""

import enum
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from docs_assistant.ingestion.text import MAIN_CONTENT_SELECTOR, MainContentNotFoundError


class Level(enum.IntEnum):
    """Уровни структуры. Значение — глубина: заголовок закрывает все уровни не выше себя."""

    part = 0  # Общая / Особенная часть
    section = 1  # Раздел
    subsection = 2  # Подраздел
    chapter = 3  # Глава
    paragraph = 4  # Параграф (группа статей внутри главы)
    article = 5  # Статья
    preamble = 6  # текст до первой статьи (преамбула закона)


@dataclass
class Block:
    """Структурный блок документа.

    Для заголовков (раздел, глава…) `text` пустой; у статьи `heading` — строка
    «Статья 87. Расторжение…», `number` — «87», `text` — тело статьи построчно.
    """

    level: Level
    heading: str
    text: str = ""
    number: str | None = None


@dataclass
class _Line:
    text: str
    # Номер заголовочного тега (<h1>…<h6>), из которого пришла строка, иначе None.
    # Нужен, чтобы склеить заголовок, перенесённый через <br>: «Глава 2. … ТРУДОВЫХ» + «ОТНОШЕНИЙ».
    heading_group: int | None = None


@dataclass
class _Builder:
    lines: list[_Line] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    note_chars: int = 0
    text_chars: int = 0
    heading_group: int | None = None


# --- Шум ---------------------------------------------------------------------------------


# Сноски и примечания редакции: «Сноска. Статья 5 изменена Законом РК от …», «Примечание ИЗПИ!».
# Это история поправок, а не норма права: в чанки не берём.
def _is_note(tag: Tag) -> bool:
    if tag.name in ("span", "p") and "note" in (tag.get("class") or []):
        return True
    # Красным шрифтом выделены примечания «Вниманию пользователей!», «ЗҚАИ-ның ескертпесі!».
    # Другие цвета и <font face="Symbol"> встречаются внутри обычного текста — их не трогаем.
    color = str(tag.get("color", "")).lstrip("#").upper()
    return tag.name == "font" and color == "FF0000"


_NOISE_LINE = re.compile(
    r"^(Сноска|Ескерту|Примечание\s+[А-ЯЁ]+|Вниманию\s+пользователей|Қолданушылар\s+назарына"
    r"|[А-ЯӘҒҚҢӨҰҮҺІ]+-ның\s+ескертпесі|СОДЕРЖАНИЕ$|ОГЛАВЛЕНИЕ$|МАЗМҰНЫ$"
    # Исключённые пункты вёрстка оформляет обычным текстом, а не сноской:
    # «5. Исключен Законом РК от …», «2. - 6. Исключены…», «7. | Исключена…» (строка таблицы),
    # «3) алып тасталды – ҚР … Заңымен». Нормы в них нет.
    r"|(?:\d+(?:-\d+)*[.)]\s*(?:[-–]\s*\d+(?:-\d+)*[.)]\s*)?(?:\|\s*)?)?"
    r"(?:Исключен[аоы]?\b|Утратил[аио]?\s+силу|Алып\s+тасталды|Күші\s+жойылды))",
    re.IGNORECASE,
)

_BLOCK_TAGS = frozenset(
    {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "ul", "ol", "blockquote"}
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def _flush(b: _Builder) -> None:
    text = " ".join("".join(b.parts).split())
    # Строка, в которой больше половины символов из сносок, — это сноска с вкраплёнными ссылками
    # (<span class=note>исключен Законом</span><a>№ 116-VIII</a><span class=note>…</span>)
    is_note = b.note_chars > b.text_chars
    if text and not is_note and not _NOISE_LINE.match(text):
        b.lines.append(_Line(text, b.heading_group))
    b.parts.clear()
    b.note_chars = b.text_chars = 0


def _walk(node: Tag, b: _Builder, in_note: bool) -> None:
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            s = str(child)
            if in_note:
                b.note_chars += len(s.strip())
            else:
                b.parts.append(s)
                b.text_chars += len(s.strip())
            continue
        if not isinstance(child, Tag) or child.name in ("script", "style", "noscript"):
            continue
        if child.name == "br":
            _flush(b)
        elif child.name == "tr":
            # Строка таблицы (ставки налогов, перечни) — одна строка текста «ячейка | ячейка»,
            # иначе каждая ячейка становится отдельной строкой и таблица теряет смысл
            _flush(b)
            cells = [
                " ".join(cell.get_text(" ").split())
                for cell in child.find_all(["td", "th"], recursive=False)
            ]
            row = " | ".join(c for c in cells if c)
            if row and not in_note:
                b.parts.append(row)
                b.text_chars += len(row)
            _flush(b)
        elif child.name in _BLOCK_TAGS:
            _flush(b)
            saved = b.heading_group
            if child.name in _HEADING_TAGS:
                b.heading_group = id(child)
            _walk(child, b, in_note or _is_note(child))
            _flush(b)
            b.heading_group = saved
        else:
            # Строчные теги (<a>, <b>, <span>, <u>) — часть той же строки
            _walk(child, b, in_note or _is_note(child))


def extract_lines(html: str | bytes) -> list[str]:
    """Строки основного текста без сносок и служебных примечаний (для отладки и тестов)."""
    return [line.text for line in _extract(html)]


def _extract(html: str | bytes) -> list[_Line]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one(MAIN_CONTENT_SELECTOR)
    if main is None:
        raise MainContentNotFoundError(f"не найден элемент {MAIN_CONTENT_SELECTOR!r}")
    b = _Builder()
    _walk(main, b, in_note=False)
    _flush(b)
    return b.lines


# --- Структура ---------------------------------------------------------------------------

_NUM = r"(\d+(?:-\d+)*)"  # 87, 20-1, 338-5
_ROMAN_OR_NUM = r"([0-9IVXLC]+(?:-\d+)*)"
_I = "[іi]"  # в казахских текстах adilet «і» бывает и кириллической, и латинской

_PATTERNS: list[tuple[Level, re.Pattern[str]]] = [
    (Level.part, re.compile(r"^(?:ОБЩАЯ|ОСОБЕННАЯ)\s+ЧАСТЬ$", re.IGNORECASE)),
    # «Жалпы бөлік» в Трудовом кодексе, «Жалпы бөлім» — в Гражданском
    (Level.part, re.compile(rf"^(?:ЖАЛПЫ|ЕРЕКШЕ)\s+БӨЛ{_I}[КМ]$", re.IGNORECASE)),
    (Level.subsection, re.compile(rf"^ПОДРАЗДЕЛ\s+{_NUM}\b\.?\s*(.*)$", re.IGNORECASE)),
    (Level.subsection, re.compile(rf"^{_NUM}[-\s]к{_I}ш{_I}\s+бөл{_I}м\b\.?\s*(.*)$", re.I)),
    (Level.section, re.compile(rf"^РАЗДЕЛ\s+{_ROMAN_OR_NUM}\b\.?\s*(.*)$", re.IGNORECASE)),
    (Level.section, re.compile(rf"^{_NUM}[-\s]бөл{_I}м\b\.?\s*(.*)$", re.IGNORECASE)),
    (Level.chapter, re.compile(rf"^Глава\s+{_ROMAN_OR_NUM}\s*\.?\s*(.*)$", re.IGNORECASE)),
    (Level.chapter, re.compile(rf"^{_NUM}-тарау\b\.?\s*(.*)$", re.IGNORECASE)),
    (Level.paragraph, re.compile(rf"^Параграф\s+{_NUM}\b\.?\s*(.*)$", re.IGNORECASE)),
    (Level.paragraph, re.compile(rf"^{_NUM}-параграф\b\.?\s*(.*)$", re.IGNORECASE)),
    # Точка после номера обязательна: «Статья 87 настоящего Кодекса…» в тексте — это ссылка,
    # а не заголовок. «Статья 1 . Основные понятия» (пробел перед точкой) тоже встречается.
    (Level.article, re.compile(rf"^Статья\s+{_NUM}\s*\.\s*(.*)$")),
    (Level.article, re.compile(rf"^{_NUM}-бап\s*\.\s*(.*)$")),
]


# Заголовки короткие. Длинная строка, начинающаяся с «Глава 5 …», — это текст со ссылкой.
_MAX_HEADING_CHARS = {Level.article: 600}
_DEFAULT_MAX_HEADING_CHARS = 300


# Группа статей внутри главы с римским номером: «VII. Некоммерческие организации» в главе 2
# Гражданского кодекса. По глубине — как параграф: следующая глава её закрывает. Шаблон
# слишком общий для текста, поэтому проверяем его только в строках из заголовочных тегов.
_ROMAN_GROUP = re.compile(r"^([IVXLC]+)\.\s+\S")

# Внутри <h3> заголовок статьи иногда без точки: «663-бап Жұмыс нәтижелерін тапсыру».
# В тексте такая строка была бы ссылкой, а в заголовочном теге — это заголовок.
_LOOSE_ARTICLE = re.compile(rf"^(?:Статья\s+{_NUM}|{_NUM}-бап)\s+\S")

# В одном <h3> бывает «Глава 4. Сделки Статья 147. Понятие сделки» — без <br>.
# Режем перед заголовком статьи, если он начинается не в начале строки.
# Группы внутри без захвата: иначе re.split вернёт их как отдельные куски.
_EMBEDDED_ARTICLE = re.compile(r"\s+(?=Статья\s+\d+(?:-\d+)*\s*\.|\d+(?:-\d+)*-бап\s*\.)")


def classify(line: str, in_heading: bool = False) -> tuple[Level, str | None] | None:
    """Уровень строки-заголовка и номер (для статьи, главы, раздела) или None для текста."""
    for level, pattern in _PATTERNS:
        if len(line) > _MAX_HEADING_CHARS.get(level, _DEFAULT_MAX_HEADING_CHARS):
            continue
        m = pattern.match(line)
        if m:
            number = m.group(1) if m.groups() and level is not Level.part else None
            return level, number
    if in_heading and len(line) <= _DEFAULT_MAX_HEADING_CHARS:
        m = _ROMAN_GROUP.match(line)
        if m:
            return Level.paragraph, m.group(1)
        m = _LOOSE_ARTICLE.match(line)
        if m:
            return Level.article, m.group(1) or m.group(2)
    return None


def _split_heading_lines(lines: list[_Line]) -> list[_Line]:
    out: list[_Line] = []
    for line in lines:
        if line.heading_group is None:
            out.append(line)
            continue
        for part in _EMBEDDED_ARTICLE.split(line.text):
            if part:
                out.append(_Line(part, line.heading_group))
    return out


def parse_document(html: str | bytes) -> list[Block]:
    """Разобрать страницу adilet на блоки: заголовки структуры и статьи целиком."""
    blocks: list[Block] = []
    body: list[str] = []
    current: Block | None = None  # статья или преамбула, в которую сейчас пишем текст
    last_heading_group: int | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            current.text = "\n".join(body)
            if current.level is Level.article or current.text:
                blocks.append(current)
        body.clear()
        current = None

    seen_article = False
    for line in _split_heading_lines(_extract(html)):
        kind = classify(line.text, in_heading=line.heading_group is not None)
        if kind is None:
            # Продолжение заголовка, перенесённого через <br> внутри того же <h3>
            if line.heading_group is not None and line.heading_group == last_heading_group:
                target = current if current is not None and not body else None
                if target is None and current is None and blocks:
                    target = blocks[-1]
                if target is not None:
                    target.heading = f"{target.heading} {line.text}"
                    continue
            if current is None:
                # Текст вне статьи: преамбула закона или вводные положения раздела
                # («Положения настоящего раздела применяются…»). У второго своего заголовка нет.
                current = Block(Level.preamble, "" if seen_article else "Преамбула")
            body.append(line.text)
            continue

        level, number = kind
        close()
        last_heading_group = line.heading_group
        block = Block(level, line.text, number=number)
        if level is Level.article:
            seen_article = True
            current = block
        else:
            blocks.append(block)
    close()
    return blocks
