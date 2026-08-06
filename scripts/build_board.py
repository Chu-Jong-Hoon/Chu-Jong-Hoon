#!/usr/bin/env python3
"""plans/YYYY-MM.md 를 읽어 README.md, 월간/연간 아카이브, 달력 SVG 를 생성한다.

사용법:
    python scripts/build_board.py            # 오늘(KST) 기준
    python scripts/build_board.py 2026-09    # 특정 월 기준
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PLANS_DIR = ROOT / "plans"
ASSETS_DIR = ROOT / "assets"
ARCHIVE_DIR = ROOT / "archive"
KST = ZoneInfo("Asia/Seoul")

WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]
USER = "Chu-Jong-Hoon"


# --------------------------------------------------------------------------
# 파싱
# --------------------------------------------------------------------------
@dataclass
class Item:
    text: str
    done: bool | None = None      # None = 체크박스가 아닌 메모/일정
    important: bool = False
    time: str | None = None

    @property
    def is_task(self) -> bool:
        return self.done is not None


@dataclass
class Month:
    year: int
    month: int
    goals: list[Item] = field(default_factory=list)
    days: dict[int, list[Item]] = field(default_factory=dict)
    extras: list[tuple[str, list[Item]]] = field(default_factory=list)


ITEM_RE = re.compile(r"^\s*[-*]\s+(.*)$")
CHECK_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
FLAG_RE = re.compile(r"^(!+|📌|⭐|🔥|❗)\s*(.*)$")
TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s+(.*)$")
HEAD_RE = re.compile(r"^##\s+(.*)$")
DAY_RE = re.compile(r"^(\d{1,4})(?:[-./](\d{1,2}))?(?:[-./](\d{1,2}))?")
MONTH_FILE_RE = re.compile(r"^(\d{4})-(\d{2})\.md$")


def day_from_title(title: str) -> int | None:
    """'2026-08-06 (목)', '08-06', '6 (목)' 등에서 '일' 숫자만 뽑는다."""
    m = DAY_RE.match(title)
    if not m:
        return None
    nums = [int(g) for g in m.groups() if g is not None]
    day = nums[-1]
    return day if 1 <= day <= 31 else None


def parse_item(line: str) -> Item | None:
    m = ITEM_RE.match(line)
    if not m:
        return None
    text = m.group(1).strip()
    done: bool | None = None
    if cb := CHECK_RE.match(text):
        done = cb.group(1).lower() == "x"
        text = cb.group(2).strip()
    important = False
    if fl := FLAG_RE.match(text):
        important = True
        text = fl.group(2).strip()
    time = None
    if tm := TIME_RE.match(text):
        time = tm.group(1)
        text = tm.group(2).strip()
    if not text:
        return None
    return Item(text=text, done=done, important=important, time=time)


def parse_month(path: Path, year: int, month: int) -> Month:
    mo = Month(year=year, month=month)
    bucket: list[Item] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if h := HEAD_RE.match(raw.rstrip()):
            title = h.group(1).strip()
            day = day_from_title(title)
            if day is not None:
                bucket = mo.days.setdefault(day, [])
            elif "목표" in title or "goal" in title.lower():
                bucket = mo.goals
            else:
                bucket = []
                mo.extras.append((title, bucket))
            continue
        if bucket is not None and (item := parse_item(raw)):
            bucket.append(item)
    return mo


# --------------------------------------------------------------------------
# 여러 달 / 연도 스캔
# --------------------------------------------------------------------------
def discover_months() -> list[tuple[int, int]]:
    """plans/ 아래 YYYY-MM.md 파일을 전부 찾아 (year, month) 리스트로 반환한다."""
    if not PLANS_DIR.exists():
        return []
    out = []
    for p in PLANS_DIR.iterdir():
        if m := MONTH_FILE_RE.match(p.name):
            out.append((int(m.group(1)), int(m.group(2))))
    return sorted(out)


def discover_years(months: list[tuple[int, int]]) -> list[int]:
    return sorted({y for y, _ in months})


def adjacent_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


# --------------------------------------------------------------------------
# 달력 SVG (월간)
# --------------------------------------------------------------------------
THEMES = {
    "light": dict(bg="#ffffff", cell="#f6f8fa", grid="#d1d9e0", fg="#1f2328",
                  muted="#8b949e", accent="#0969da", tint="#ddf4ff",
                  red="#cf222e", blue="#0969da", green="#1a7f37"),
    "dark": dict(bg="#0d1117", cell="#161b22", grid="#30363d", fg="#e6edf3",
                 muted="#7d8590", accent="#4493f8", tint="#0c2d4d",
                 red="#ff7b72", blue="#79c0ff", green="#3fb950"),
}

PAD, CW, CH = 16, 104, 78
TITLE_H, WD_H, LEGEND_H = 44, 28, 34
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Malgun Gothic', Roboto, sans-serif"

# 연간 잔디밭 뷰용 색상 단계 (0 = 활동 없음 -> 4 = 완료율 100%)
DAY_LEVEL_COLORS = {
    "light": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    "dark": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
}

# 연간 미니 달력 레이아웃
Y_PAD, Y_CW, Y_CH = 20, 16, 16
Y_GAP_X, Y_GAP_Y = 26, 30
Y_TITLE_H, Y_HEADER_H, Y_LEGEND_H = 20, 44, 34
Y_COLS, Y_ROWS = 4, 3


def svg_calendar(mo: Month, today: dt.date, theme: str) -> str:
    t = THEMES[theme]
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(mo.year, mo.month)
    width = PAD * 2 + CW * 7
    top = PAD + TITLE_H + WD_H
    height = top + len(weeks) * CH + LEGEND_H + PAD

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{mo.year}년 {mo.month}월 계획 달력">',
        f"<style>text{{font-family:{FONT};}}</style>",
        f'<rect width="{width}" height="{height}" rx="12" fill="{t["bg"]}"/>',
    ]

    # 제목 + 요약
    total = sum(1 for its in mo.days.values() for i in its if i.is_task)
    done = sum(1 for its in mo.days.values() for i in its if i.done)
    out.append(f'<text x="{PAD + 4}" y="{PAD + 26}" font-size="20" font-weight="700" '
               f'fill="{t["fg"]}">{mo.year}. {mo.month:02d}</text>')
    summary = f"{done}/{total} 완료" if total else "계획 없음"
    out.append(f'<text x="{width - PAD - 4}" y="{PAD + 25}" font-size="13" text-anchor="end" '
               f'fill="{t["muted"]}">{summary}</text>')

    # 요일 헤더
    for col, wd in enumerate(WEEKDAYS):
        color = t["red"] if col == 0 else t["blue"] if col == 6 else t["muted"]
        cx = PAD + col * CW + (CW - 6) / 2
        out.append(f'<text x="{cx:.1f}" y="{PAD + TITLE_H + 18}" font-size="12" '
                   f'font-weight="600" text-anchor="middle" fill="{color}">{wd}</text>')

    cw, ch = CW - 6, CH - 6
    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            if day == 0:
                continue
            x = PAD + col * CW
            y = top + row * CH
            date = dt.date(mo.year, mo.month, day)
            items = mo.days.get(day, [])
            tasks = [i for i in items if i.is_task]
            is_today = date == today
            is_past = date < today
            has_important = any(i.important for i in items)

            group = f'<g{" opacity=\"0.45\"" if is_past and not is_today else ""}>'
            out.append(group)

            fill = t["tint"] if is_today else t["cell"]
            stroke = t["accent"] if is_today else t["grid"]
            sw = 2 if is_today else 1
            out.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="8" '
                       f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

            num_color = (t["accent"] if is_today
                         else t["red"] if col == 0
                         else t["blue"] if col == 6
                         else t["fg"])
            out.append(f'<text x="{x + 11}" y="{y + 24}" font-size="16" font-weight="700" '
                       f'fill="{num_color}">{day}</text>')

            if is_today:
                out.append(f'<text x="{x + cw - 10}" y="{y + 21}" font-size="10" '
                           f'font-weight="700" text-anchor="end" fill="{t["accent"]}">TODAY</text>')
            elif has_important:
                out.append(f'<circle cx="{x + cw - 13}" cy="{y + 17}" r="4.5" fill="{t["red"]}"/>')

            # 할 일 점 (최대 6개)
            for idx, task in enumerate(tasks[:6]):
                cx = x + 13 + idx * 13
                cy = y + ch - 25
                if task.done:
                    out.append(f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{t["green"]}"/>')
                else:
                    color = t["red"] if task.important else t["accent"]
                    out.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="none" '
                               f'stroke="{color}" stroke-width="1.8"/>')
            if len(tasks) > 6:
                out.append(f'<text x="{x + 13 + 6 * 13}" y="{y + ch - 21}" font-size="10" '
                           f'fill="{t["muted"]}">+{len(tasks) - 6}</text>')

            label = ""
            if tasks:
                nd = sum(1 for i in tasks if i.done)
                label = "완료" if nd == len(tasks) else f"{nd}/{len(tasks)}"
            elif items:
                label = "일정"
            if label:
                color = t["green"] if label == "완료" else t["muted"]
                out.append(f'<text x="{x + 11}" y="{y + ch - 8}" font-size="10" '
                           f'fill="{color}">{label}</text>')
            out.append("</g>")

    # 범례
    ly = top + len(weeks) * CH + 16
    lx = PAD + 6
    legend = [("circle-open", "할 일"), ("circle-fill", "완료"),
              ("dot-red", "중요"), ("box", "오늘")]
    for kind, text in legend:
        if kind == "circle-open":
            out.append(f'<circle cx="{lx + 5}" cy="{ly}" r="4" fill="none" '
                       f'stroke="{t["accent"]}" stroke-width="1.8"/>')
        elif kind == "circle-fill":
            out.append(f'<circle cx="{lx + 5}" cy="{ly}" r="4.5" fill="{t["green"]}"/>')
        elif kind == "dot-red":
            out.append(f'<circle cx="{lx + 5}" cy="{ly}" r="4.5" fill="{t["red"]}"/>')
        else:
            out.append(f'<rect x="{lx}" y="{ly - 6}" width="12" height="12" rx="3" '
                       f'fill="{t["tint"]}" stroke="{t["accent"]}" stroke-width="1.5"/>')
        out.append(f'<text x="{lx + 18}" y="{ly + 4}" font-size="11" '
                   f'fill="{t["muted"]}">{text}</text>')
        lx += 18 + len(text) * 12 + 18

    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# 달력 SVG (연간 - 잔디밭 스타일)
# --------------------------------------------------------------------------
def day_level(items: list[Item]) -> int:
    """그 날의 활동량/완료율을 0~4 단계로 압축한다."""
    if not items:
        return 0
    tasks = [i for i in items if i.is_task]
    if not tasks:
        return 1
    ratio = sum(1 for i in tasks if i.done) / len(tasks)
    if ratio >= 1:
        return 4
    if ratio >= 0.66:
        return 3
    if ratio >= 0.33:
        return 2
    return 1


def svg_year(year: int, months: dict[int, Month], today: dt.date, theme: str) -> str:
    t = THEMES[theme]
    levels = DAY_LEVEL_COLORS[theme]
    block_w = Y_CW * 7
    block_h = Y_TITLE_H + Y_CH * 6
    width = Y_PAD * 2 + Y_COLS * block_w + (Y_COLS - 1) * Y_GAP_X
    grid_top = Y_PAD + Y_HEADER_H
    height = grid_top + Y_ROWS * block_h + (Y_ROWS - 1) * Y_GAP_Y + Y_LEGEND_H + Y_PAD

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{year}년 전체 계획 달력">',
        f"<style>text{{font-family:{FONT};}}</style>",
        f'<rect width="{width}" height="{height}" rx="12" fill="{t["bg"]}"/>',
        f'<text x="{Y_PAD + 4}" y="{Y_PAD + 26}" font-size="20" font-weight="700" '
        f'fill="{t["fg"]}">{year}</text>',
    ]

    cal = calendar.Calendar(firstweekday=6)
    for idx in range(12):
        month = idx + 1
        col, row = idx % Y_COLS, idx // Y_COLS
        bx = Y_PAD + col * (block_w + Y_GAP_X)
        by = grid_top + row * (block_h + Y_GAP_Y)
        mo = months.get(month) or Month(year=year, month=month)
        is_cur_month = (year, month) == (today.year, today.month)
        title_color = t["accent"] if is_cur_month else t["fg"]
        out.append(f'<text x="{bx}" y="{by + 14}" font-size="12" font-weight="700" '
                   f'fill="{title_color}">{month}월</text>')
        cell_top = by + Y_TITLE_H
        for wi, week in enumerate(cal.monthdayscalendar(year, month)):
            for ci, day in enumerate(week):
                if day == 0:
                    continue
                x = bx + ci * Y_CW
                y = cell_top + wi * Y_CH
                items = mo.days.get(day, [])
                level = day_level(items)
                is_today = (year, month, day) == (today.year, today.month, today.day)
                fill = t["cell"] if level == 0 else levels[level]
                stroke = t["accent"] if is_today else t["grid"]
                sw = 2 if is_today else 0.75
                out.append(f'<rect x="{x}" y="{y}" width="{Y_CW - 3}" height="{Y_CH - 3}" rx="3" '
                           f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
                if any(i.important for i in items):
                    out.append(f'<circle cx="{x + Y_CW - 5}" cy="{y + 3}" r="2.2" '
                               f'fill="{t["red"]}"/>')

    # 범례
    ly = grid_top + Y_ROWS * block_h + (Y_ROWS - 1) * Y_GAP_Y + 20
    lx = Y_PAD + 4
    out.append(f'<text x="{lx}" y="{ly + 4}" font-size="11" fill="{t["muted"]}">적음</text>')
    lx += 34
    for lvl in range(5):
        color = t["cell"] if lvl == 0 else levels[lvl]
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="12" height="12" rx="3" fill="{color}" '
                   f'stroke="{t["grid"]}" stroke-width="0.75"/>')
        lx += 16
    lx += 6
    out.append(f'<text x="{lx}" y="{ly + 4}" font-size="11" fill="{t["muted"]}">많음</text>')
    lx += 34
    out.append(f'<circle cx="{lx + 5}" cy="{ly}" r="4" fill="{t["red"]}"/>')
    out.append(f'<text x="{lx + 16}" y="{ly + 4}" font-size="11" fill="{t["muted"]}">중요</text>')

    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# 네비게이션
# --------------------------------------------------------------------------
def archive_month_nav(y: int, m: int, months: set[tuple[int, int]]) -> str:
    py, pm = adjacent_month(y, m, -1)
    ny, nm = adjacent_month(y, m, 1)
    segs = []
    if (py, pm) in months:
        segs.append(f"[◀ {py}-{pm:02d}]({py}-{pm:02d}.md)")
    segs.append("[🏠 홈](../README.md)")
    segs.append(f"[📆 {y} 연간]({y}.md)")
    if (ny, nm) in months:
        segs.append(f"[{ny}-{nm:02d} ▶]({ny}-{nm:02d}.md)")
    return " | ".join(segs)


def readme_month_nav(y: int, m: int, months: set[tuple[int, int]]) -> str:
    py, pm = adjacent_month(y, m, -1)
    ny, nm = adjacent_month(y, m, 1)
    segs = []
    if (py, pm) in months:
        segs.append(f"[◀ {py}-{pm:02d}](archive/{py}-{pm:02d}.md)")
    segs.append(f"[📆 {y} 연간](archive/{y}.md)")
    if (ny, nm) in months:
        segs.append(f"[{ny}-{nm:02d} ▶](archive/{ny}-{nm:02d}.md)")
    return " | ".join(segs)


def year_nav(y: int, years: list[int]) -> str:
    segs = []
    if (y - 1) in years:
        segs.append(f"[◀ {y - 1}]({y - 1}.md)")
    segs.append("[🏠 홈](../README.md)")
    if (y + 1) in years:
        segs.append(f"[{y + 1} ▶]({y + 1}.md)")
    return " | ".join(segs)


def calendar_picture_lines(rel: str, y: int, m: int, alt: str) -> list[str]:
    return [
        "<picture>",
        f'  <source media="(prefers-color-scheme: dark)" srcset="{rel}assets/calendar-{y}-{m:02d}-dark.svg">',
        f'  <img alt="{alt}" src="{rel}assets/calendar-{y}-{m:02d}-light.svg" width="100%">',
        "</picture>",
    ]


# --------------------------------------------------------------------------
# 공용 렌더링 조각 (README / 아카이브 공용)
# --------------------------------------------------------------------------
def bar(done: int, total: int, width: int = 22) -> str:
    if total == 0:
        return "`계획 없음`"
    filled = round(width * done / total)
    return f"`{'█' * filled}{'░' * (width - filled)}` **{done}/{total}** ({done * 100 // total}%)"


def fmt(item: Item) -> str:
    mark = "**🔴 " if item.important else ""
    tail = "**" if item.important else ""
    time = f"`{item.time}` " if item.time else ""
    if item.done is None:
        return f"- {time}{mark}{item.text}{tail}"
    box = "[x]" if item.done else "[ ]"
    return f"- {box} {time}{mark}{item.text}{tail}"


def time_sort_key(time: str) -> tuple[int, int]:
    """자정 넘어가는 항목(00~04시)은 그날의 연장(24~28시)으로 취급해 정렬한다."""
    h, mi = (int(x) for x in time.split(":"))
    if h < 5:
        h += 24
    return h, mi


def schedule_row(item: Item) -> str:
    icon = "✅" if item.done else "⬜" if item.is_task else "🔴" if item.important else "📝"
    text = item.text.replace("|", "\\|")
    if item.important:
        text = f"**{text}**"
    return f"| `{item.time}` | {icon} {text} |"


def goals_lines(mo: Month) -> list[str]:
    if not mo.goals:
        return []
    gt = [i for i in mo.goals if i.is_task]
    L = ["## 🎯 이번 달 목표", "", bar(sum(1 for i in gt if i.done), len(gt)), ""]
    for i in mo.goals:
        L.append(fmt(i))
    L.append("")
    return L


def day_detail_lines(mo: Month, today: dt.date) -> list[str]:
    L: list[str] = []
    for day in sorted(mo.days):
        items = mo.days[day]
        if not items:
            continue
        try:
            d = dt.date(mo.year, mo.month, day)
        except ValueError:
            continue
        mark = " ← **오늘**" if d == today else ""
        L.append(f"#### {mo.month:02d}/{day:02d} ({WEEKDAYS[(d.weekday() + 1) % 7]}){mark}")
        L.append("")
        ordered = sorted(items, key=lambda i: time_sort_key(i.time) if i.time else (99, 99))
        for i in ordered:
            L.append(fmt(i))
        L.append("")
    return L


def extras_lines(mo: Month) -> list[str]:
    L: list[str] = []
    for title, items in mo.extras:
        if not items:
            continue
        L.append(f"## {title}")
        L.append("")
        for i in items:
            L.append(fmt(i))
        L.append("")
    return L


# --------------------------------------------------------------------------
# README
# --------------------------------------------------------------------------
def build_readme(mo: Month, today: dt.date, months: set[tuple[int, int]], years: list[int]) -> str:
    wd = WEEKDAYS[(today.weekday() + 1) % 7]
    L: list[str] = []

    L.append('<div align="center">')
    L.append("")
    L.append(f"# 📅 {USER}'s Daily Board")
    L.append("")
    L.append(f"### {today.year}년 {today.month}월 {today.day}일 ({wd})")
    L.append("")
    L.append("</div>")
    L.append("")
    L.append("---")
    L.append("")

    # 오늘 시간표
    todays = mo.days.get(today.day, []) if (mo.year, mo.month) == (today.year, today.month) else []
    tasks = [i for i in todays if i.is_task]
    L.append("## 🔥 오늘 시간표")
    L.append("")
    if todays:
        L.append(bar(sum(1 for i in tasks if i.done), len(tasks)))
        L.append("")
        timed = sorted((i for i in todays if i.time), key=lambda i: time_sort_key(i.time))
        untimed = [i for i in todays if not i.time]
        if timed:
            L.append("| 시간 | 내용 |")
            L.append("| :---: | --- |")
            for i in timed:
                L.append(schedule_row(i))
            L.append("")
        if untimed:
            L.append("**⏰ 시간 미정**")
            L.append("")
            for i in sorted(untimed, key=lambda i: (i.done is True, not i.important)):
                L.append(fmt(i))
            L.append("")
    else:
        L.append(f"> 오늘 등록된 계획이 없어요. [`plans/{mo.year}-{mo.month:02d}.md`]"
                 f"(plans/{mo.year}-{mo.month:02d}.md) 에 `## {today.day:02d} ({wd})` 를 추가하세요.")
        L.append("")

    # 달력
    L.append(f"## 🗓️ {mo.month}월 달력")
    L.append("")
    L += calendar_picture_lines("", mo.year, mo.month, f"{mo.year}년 {mo.month}월 달력")
    L.append("")

    # 이번 달 목표
    L += goals_lines(mo)

    # 다가오는 일정
    upcoming: list[tuple[int, Item]] = []
    for day, items in mo.days.items():
        try:
            date = dt.date(mo.year, mo.month, day)
        except ValueError:
            continue
        dd = (date - today).days
        if 1 <= dd <= 14:  # 오늘(dd=0)은 위 시간표에 이미 다 나오므로 제외
            for i in items:
                if i.important or i.time:
                    if not i.done:
                        upcoming.append((dd, i))
    if upcoming:
        L.append("## ⏳ 다가오는 중요 일정")
        L.append("")
        L.append("| D-day | 날짜 | 내용 |")
        L.append("| :---: | :---: | --- |")
        for dd, i in sorted(upcoming, key=lambda x: (x[0], x[1].time or "zz"))[:8]:
            d = today + dt.timedelta(days=dd)
            label = "**D-DAY**" if dd == 0 else f"D-{dd}"
            when = f"{d.month:02d}/{d.day:02d} ({WEEKDAYS[(d.weekday() + 1) % 7]})"
            body = (f"`{i.time}` " if i.time else "") + i.text
            L.append(f"| {label} | {when} | {'🔴 ' if i.important else ''}{body} |")
        L.append("")

    # 전체 월 상세
    if mo.days:
        L.append("<details>")
        L.append(f"<summary><b>📖 {mo.month}월 전체 계획 펼쳐보기</b></summary>")
        L.append("")
        L += day_detail_lines(mo, today)
        L.append("</details>")
        L.append("")

    # 기타 섹션
    L += extras_lines(mo)

    # 네비게이션
    L.append("---")
    L.append("")
    L.append(readme_month_nav(mo.year, mo.month, months))
    L.append("")
    if years:
        archive_line = " · ".join(f"[{yr}](archive/{yr}.md)" for yr in years)
        L.append(f"**연도별 아카이브:** {archive_line}")
        L.append("")

    L.append(f'<sub>이 README 는 자동 생성됩니다. 수정은 <a href="plans/{mo.year}-{mo.month:02d}.md">'
             f'plans/{mo.year}-{mo.month:02d}.md</a> 에서 하세요. '
             f'마지막 갱신: {dt.datetime.now(KST):%Y-%m-%d %H:%M} KST</sub>')
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# 아카이브 (월간 / 연간)
# --------------------------------------------------------------------------
def build_archive_month(mo: Month, today: dt.date, months: set[tuple[int, int]],
                         years: list[int]) -> str:
    L: list[str] = []
    L.append(f"# 📅 {mo.year}-{mo.month:02d}")
    L.append("")
    L.append(archive_month_nav(mo.year, mo.month, months))
    L.append("")
    L.append("---")
    L.append("")
    L += calendar_picture_lines("../", mo.year, mo.month, f"{mo.year}년 {mo.month}월 달력")
    L.append("")
    L += goals_lines(mo)

    if mo.days:
        L.append(f"## 📖 {mo.month}월 전체 계획")
        L.append("")
        L += day_detail_lines(mo, today)

    L += extras_lines(mo)

    L.append("---")
    L.append("")
    L.append(archive_month_nav(mo.year, mo.month, months))
    L.append("")
    L.append(f'<sub>수정은 <a href="../plans/{mo.year}-{mo.month:02d}.md">'
             f'plans/{mo.year}-{mo.month:02d}.md</a> 에서 하세요.</sub>')
    L.append("")
    return "\n".join(L)


def build_archive_year(year: int, all_months: dict[tuple[int, int], Month],
                        today: dt.date, years: list[int]) -> str:
    L: list[str] = []
    L.append(f"# 📆 {year}년 아카이브")
    L.append("")
    L.append(year_nav(year, years))
    L.append("")
    L.append("---")
    L.append("")
    L.append("<picture>")
    L.append(f'  <source media="(prefers-color-scheme: dark)" srcset="../assets/year-{year}-dark.svg">')
    L.append(f'  <img alt="{year}년 전체 달력" src="../assets/year-{year}-light.svg" width="100%">')
    L.append("</picture>")
    L.append("")
    L.append("| 월 | 목표 진행률 | 링크 |")
    L.append("| :---: | --- | :---: |")
    for m in range(1, 13):
        mo = all_months.get((year, m))
        if mo is None:
            L.append(f"| {m}월 | — | — |")
            continue
        gt = [i for i in mo.goals if i.is_task]
        if gt:
            prog = bar(sum(1 for i in gt if i.done), len(gt))
        elif mo.goals or mo.days:
            prog = "기록 있음"
        else:
            prog = "—"
        L.append(f"| {m}월 | {prog} | [보기]({year}-{m:02d}.md) |")
    L.append("")
    L.append(year_nav(year, years))
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
TEMPLATE = """# {y}-{m:02d}

## 이번 달 목표
- [ ] 목표를 적어보세요

## {d:02d} ({wd})
- [ ] 오늘 할 일
"""


def main() -> None:
    now = dt.datetime.now(KST)
    today = now.date()
    if len(sys.argv) > 1:
        y, m = (int(x) for x in sys.argv[1].split("-"))
    else:
        y, m = today.year, today.month

    PLANS_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(exist_ok=True)
    ARCHIVE_DIR.mkdir(exist_ok=True)

    path = PLANS_DIR / f"{y}-{m:02d}.md"
    if not path.exists():
        wd = WEEKDAYS[(dt.date(y, m, 1).weekday() + 1) % 7] if today.month != m else \
            WEEKDAYS[(today.weekday() + 1) % 7]
        day = today.day if (y, m) == (today.year, today.month) else 1
        path.write_text(TEMPLATE.format(y=y, m=m, d=day, wd=wd), encoding="utf-8")
        print(f"created {path}")

    month_keys = discover_months()
    months_set = set(month_keys)
    all_months: dict[tuple[int, int], Month] = {
        (yy, mm): parse_month(PLANS_DIR / f"{yy}-{mm:02d}.md", yy, mm)
        for yy, mm in month_keys
    }
    years = discover_years(month_keys)

    for (yy, mm), mo in all_months.items():
        (ASSETS_DIR / f"calendar-{yy}-{mm:02d}-light.svg").write_text(
            svg_calendar(mo, today, "light"), encoding="utf-8")
        (ASSETS_DIR / f"calendar-{yy}-{mm:02d}-dark.svg").write_text(
            svg_calendar(mo, today, "dark"), encoding="utf-8")
        (ARCHIVE_DIR / f"{yy}-{mm:02d}.md").write_text(
            build_archive_month(mo, today, months_set, years), encoding="utf-8")

    for yy in years:
        months_of_year = {mm: mo for (y2, mm), mo in all_months.items() if y2 == yy}
        (ASSETS_DIR / f"year-{yy}-light.svg").write_text(
            svg_year(yy, months_of_year, today, "light"), encoding="utf-8")
        (ASSETS_DIR / f"year-{yy}-dark.svg").write_text(
            svg_year(yy, months_of_year, today, "dark"), encoding="utf-8")
        (ARCHIVE_DIR / f"{yy}.md").write_text(
            build_archive_year(yy, all_months, today, years), encoding="utf-8")

    mo_current = all_months[(y, m)]
    (ROOT / "README.md").write_text(
        build_readme(mo_current, today, months_set, years), encoding="utf-8")
    print(f"built README.md, {len(all_months)} month page(s), {len(years)} year page(s) "
          f"for {y}-{m:02d} (today={today})")


if __name__ == "__main__":
    main()
