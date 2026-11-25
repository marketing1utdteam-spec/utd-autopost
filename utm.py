"""UTM-мітки на ВСІ наші посилання в підписах і описах — у момент публікації.

🔴 НАВІЩО (власник 25.11.2026): «нам треба відслідковувати всі данні а не діяти
наосліп». Аудит соцмереж того ж дня показав: за осінь у GA4 лістингів Theme Store
лише 2 сесії з міткою `youtube`, решта переходів з соцмереж розчиняється в
`(direct)`. Тобто ми не могли відповісти навіть на «чи продали 4 Victory через
ролики». Мітки ставились руками, у частині підписів і з різними назвами полів.

🔴 ЧОМУ ТУТ, а не в файлах підписів. Підписи пише чат Вікторії, їх сотні, і будь-яка
ручна вимога «не забудь мітку» живе до першого пропуску. Одна функція в точці
публікації ставить мітку кожному посту кожної мережі, і забути її неможливо.

🔴 ЩО ЧІПАЄМО. Лише посилання на НАШ продукт: utdweb.team (з піддоменами) і сторінки
наших тем у Theme Store (+ пошук `?q=utd`). Чужі адреси — ні: мережа вже обпеклась,
коли дописала наші мітки в цитати на dawn/horizon (`utd-seo-network/tools/utm-links.mjs`).

🔴 ВЖЕ Є `utm_source` — не перезаписуємо: автор міг поставити свою кампанію навмисно.

Схема (однакова для всіх мереж, щоб у GA4 зводилось одним запитом):
    utm_source   = instagram | facebook | threads | linkedin | youtube | tiktok
    utm_medium   = social (youtube: video)
    utm_campaign = назва теми з адреси (victory, fuse…) | all (пошук ?q=utd) | site
    utm_content  = id запису в черзі — щоб бачити, ЯКИЙ САМЕ пост привів людину
"""
import re
import urllib.parse

OUR_THEMES = {"allure", "boutique", "fuse", "gain", "impression", "ultra", "victory"}
URL_RE = re.compile(r"https?://[^\s<>()\"'«»]+")
TRAIL = ".,;:!?)]}…"


def _ours(u):
    h = (u.hostname or "").lower()
    if h == "utdweb.team" or h.endswith(".utdweb.team"):
        return "site"
    if h != "themes.shopify.com":
        return None
    q = urllib.parse.parse_qs(u.query)
    if q.get("q", [""])[0].lower() == "utd":
        return "all"
    m = re.match(r"^/themes/([a-z0-9-]+)", u.path)
    return m.group(1) if m and m.group(1) in OUR_THEMES else None


def tag_url(url, source, content, medium=None):
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    campaign = _ours(u)
    if not campaign:
        return url
    q = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
    if any(k == "utm_source" for k, _ in q):
        return url
    q += [("utm_source", source),
          ("utm_medium", medium or ("video" if source == "youtube" else "social")),
          ("utm_campaign", campaign),
          ("utm_content", re.sub(r"[^a-z0-9_-]+", "-", str(content).lower()).strip("-")[:60])]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path,
                                    urllib.parse.urlencode(q), u.fragment))


def tag(text, source, content, medium=None):
    """Повертає текст, де кожне наше посилання має UTM. Розділові знаки в кінці
    адреси (крапка після посилання) лишаються поза адресою."""
    if not text:
        return text

    def rep(m):
        url = m.group(0)
        tail = ""
        while url and url[-1] in TRAIL:
            tail = url[-1] + tail
            url = url[:-1]
        return tag_url(url, source, content, medium) + tail

    return URL_RE.sub(rep, text)


if __name__ == "__main__":
    cases = [
        ("Try it: https://themes.shopify.com/themes/victory/presets/nitro.", "instagram", "p1",
         "utm_source=instagram&utm_medium=social&utm_campaign=victory&utm_content=p1"),
        ("All: https://themes.shopify.com/themes?q=utd", "youtube", "reel 116",
         "q=utd&utm_source=youtube&utm_medium=video&utm_campaign=all&utm_content=reel-116"),
        ("Site https://utdweb.team/shopify-themes/", "threads", "x", "utm_campaign=site"),
        # не наше — не чіпаємо
        ("Dawn https://themes.shopify.com/themes/dawn", "instagram", "p", None),
        ("Docs https://example.com/a", "instagram", "p", None),
        # уже з міткою — не чіпаємо
        ("https://themes.shopify.com/themes/fuse?utm_source=x", "instagram", "p", None),
    ]
    bad = 0
    for text, src, cid, want in cases:
        got = tag(text, src, cid)
        ok = (got == text) if want is None else (want in got and got.count("utm_source") == 1)
        bad += not ok
        print("✅" if ok else "❌", got)
    # крапка в кінці лишилась поза адресою
    t = tag("See https://utdweb.team/a.", "facebook", "q")
    ok = t.endswith("utm_content=q.")
    bad += not ok
    print("✅" if ok else "❌", t)
    raise SystemExit(1 if bad else 0)
