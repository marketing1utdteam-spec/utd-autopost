#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка креативу ПЕРЕД відправкою: співвідношення, тривалість, наявність підпису.

## Навіщо

Дозвіл власника 04.09.2026: «підтримуй всі необхідні розміри і доступи і описи і все що
потрібно для якісного постінгу відео не тільки де воно було раніше а і в інших флоу».
Виняток: SEO-мережа сайтів сюди не входить.

🔴 **Чому перевірка тут, а не в голові.** Кожна мережа має свої межі, і платформа
відмовляє вже ПІСЛЯ завантаження файла на хостинг. Заміряно 31.08.2026: відсутність теки
`media/` поклала всі 98 записів черги за один прогін, бо норма рахувала успіхи, а не
спроби. Відео дорожче за картинку: невалідний файл спалює і трафік, і спробу, і рахунок
записи в карантині.

## Хто це править

**Константи `FORMATS` і `DURATION` — зона чату Вікторії** (креативний стандарт: які
співвідношення й тривалості ми вважаємо придатними). Правити без пропозиції.

**Логіка функцій і межі платформ — зона чату Юрія**: `LIMITS` це не наш вибір, а те, що
приймає API, і взято з документації мереж.
"""
import json
import os
import shutil
import subprocess

# ── КРЕАТИВНИЙ СТАНДАРТ (зона чату Вікторії) ─────────────────────────────────
# Комплект, який збирається з одного шаблона. Імена — як у теці комплекту.
FORMATS = {
    "9:16": (1080, 1920),   # рілси, шортси, TikTok, Threads
    "4:5": (1080, 1350),    # стрічка Instagram і Facebook
    "1:1": (1080, 1080),    # квадрат, універсальний
    "16:9": (1920, 1080),   # YouTube горизонталь, LinkedIn
}
DURATION = (15, 30)         # робочий діапазон у секундах, свідомо всередині лімітів мереж

# ── МЕЖІ ПЛАТФОРМ (зона чату Юрія; це документація мереж, не наш вибір) ──────
# aspect — (мінімум, максимум) відношення ширина/висота, яке приймає API.
LIMITS = {
    "instagram": {"sec": (3, 900), "aspect": (0.01, 10.0),
                  "note": "рілс приймає 9:16; у стрічку йде через REELS + share_to_feed"},
    "facebook":  {"sec": (1, 14400), "aspect": (0.01, 10.0), "note": "/videos приймає будь-що"},
    "threads":   {"sec": (1, 300), "aspect": (0.01, 10.0), "note": "до 5 хвилин"},
    "linkedin":  {"sec": (3, 1800), "aspect": (0.417, 2.4),
                  "note": "від 1:2.4 до 2.4:1, тобто 9:16 (0.5625) проходить"},
    "tiktok":    {"sec": (3, 600), "aspect": (0.01, 10.0), "note": "рекомендовано 9:16"},
    "youtube":   {"sec": (1, 60), "aspect": (0.4, 0.6), "note": "Shorts: вертикаль до 60 с"},
}


def probe(mp4):
    """(секунди, ширина, висота) або None, якщо ffprobe недоступний.

    🔴 `None` означає «не знаю», і це НЕ те саме, що «все добре». Викликач мусить
    розрізняти: перевірка, яка не виконалась, не має права виглядати як пройдена.
    """
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", mp4],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None
        d = json.loads(r.stdout)
        st = (d.get("streams") or [{}])[0]
        sec = float((d.get("format") or {}).get("duration") or 0)
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        if not (w and h):
            return None
        return sec, w, h
    except Exception:
        return None


def aspect_name(w, h):
    """Назва співвідношення з нашого комплекту, або None якщо не з переліку."""
    for name, (fw, fh) in FORMATS.items():
        if abs((w / h) - (fw / fh)) < 0.02:
            return name
    return None


def check_video(mp4, platform, caption=None):
    """(ok, [проблеми], [попередження]).

    `ok=False` — не відправляти. Попередження не блокують: це те, про що варто знати,
    але через що не варто спиняти публікацію (наприклад, ffprobe не встановлений).
    """
    problems, warns = [], []
    if not os.path.exists(mp4):
        return False, [f"файла немає: {mp4}"], []
    size_mb = os.path.getsize(mp4) / 1e6
    if size_mb < 0.02:
        problems.append(f"файл {size_mb:.2f} МБ — це не відео")
    if caption is not None and not str(caption).strip():
        problems.append(f"підпис під {platform} порожній")

    lim = LIMITS.get(platform)
    if not lim:
        problems.append(f"невідома платформа «{platform}»")
        return not problems, problems, warns

    p = probe(mp4)
    if p is None:
        # Тиша ffprobe це «не знаю». Кажу це вголос і пускаю далі: інакше відсутність
        # ffprobe на раннері зупинила б увесь постинг, а це гірше за неперевірене відео.
        warns.append("ffprobe недоступний — тривалість і співвідношення НЕ перевірені")
        return not problems, problems, warns

    sec, w, h = p
    lo, hi = lim["sec"]
    if not (lo <= sec <= hi):
        problems.append(f"тривалість {sec:.1f} с поза межами {platform} ({lo}–{hi} с)")
    elif not (DURATION[0] - 1 <= sec <= DURATION[1] + 1):
        warns.append(f"тривалість {sec:.1f} с поза нашим стандартом "
                     f"{DURATION[0]}–{DURATION[1]} с (платформа приймає)")
    a = w / h
    alo, ahi = lim["aspect"]
    if not (alo <= a <= ahi):
        problems.append(f"співвідношення {w}×{h} ({a:.3f}) поза межами {platform} "
                        f"({alo}–{ahi}): {lim['note']}")
    name = aspect_name(w, h)
    if not name:
        warns.append(f"{w}×{h} не з нашого комплекту {sorted(FORMATS)}")
    return not problems, problems, warns


def say(mp4, platform, caption=None):
    """Друкує вердикт і вертає ok. Викликається з run_due перед публікацією."""
    ok, problems, warns = check_video(mp4, platform, caption)
    for w in warns:
        print(f"  🟡 {w}")
    for p in problems:
        print(f"  🔴 {p}")
    if ok and not warns:
        pr = probe(mp4)
        if pr:
            print(f"  🟢 відео придатне для {platform}: {pr[1]}×{pr[2]}, {pr[0]:.1f} с")
    return ok


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(__doc__)
        print(f"   формати: {FORMATS}\n   наш діапазон: {DURATION[0]}–{DURATION[1]} с")
        print(f"   платформи: {sorted(LIMITS)}")
        print("\n   python3 post_validate.py <файл.mp4> <платформа>")
        sys.exit(0)
    sys.exit(0 if say(sys.argv[1], sys.argv[2], "тест") else 1)
