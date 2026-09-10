#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Публікація в Threads, LinkedIn і TikTok — відео й картинки.

## Навіщо цей файл окремо від meta_post.py

Дозвіл власника 04.09.2026: «я дозволяю там постити не лише банери а і відео… підтримуй
всі необхідні розміри і доступи і описи і все що потрібно для якісного постінгу відео не
тільки де воно було раніше а і в інших флоу». 🔴 SEO-мережа сайтів у це НЕ входить.

`meta_post.py` тримає Meta (Instagram, Facebook) і YouTube. Тут три інші мережі, у кожної
свій хост і своя схема авторизації. Окремий файл ще й тому, що над autopost тепер працюють
ДВА чати: чим менше спільних файлів, тим менше конфліктів у git.

## Стан доступів, заміряно живими читаннями 04.09.2026

| мережа | токен | чим перевірено |
|---|---|---|
| Threads | 🟢 живий | `GET /v1.0/me` → `@utd_web_team`, id збігається з конфігом |
| LinkedIn | 🟢 живий | читання своєї організації через `/rest/organizations/{id}` → 200, версія API з конфігу |
| TikTok | 🔴 немає | застосунок у Draft, `access_token` порожній, бракує 9 полів заявки |

🔴 **Про LinkedIn і 403.** `GET /v2/userinfo` віддає 403 `ACCESS_DENIED` — і це НЕ мертвий
токен. Наші дозволи організаційні (`w_organization_social`), а не профільні (`openid`).
Дискримінатор для «токен живий» тут — читання самої організації, а не профілю. Так само
`LinkedIn-Version` треба брати **з конфігу** (`api_version`), а не вгадувати: усі мої
здогадки віддали 426 `NONEXISTENT_VERSION`, а значення з конфігу спрацювало з першого разу.

## Що НЕ перевірено викликом

Жодна публікація тут не запускалась живою — це б означало реальний пост у мережі без
затвердженого креативу. Перевірені: читання токенів, збірка тіл запитів, `--dry-run`
наскрізь. Перший справжній пост у кожній мережі треба зробити ОДИН і подивитись очима.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CFGD = os.path.expanduser("~/.config/utd")


def _cfg(name, env_key):
    """Конфіг із оточення (так його бачить GitHub Actions) або з файла (локально)."""
    raw = os.environ.get(env_key)
    if raw:
        return json.loads(raw)
    p = os.path.join(CFGD, f"{name}.json")
    if not os.path.exists(p):
        raise RuntimeError(f"немає конфігу {name}: ні змінної {env_key}, ні файла {p}")
    return json.load(open(p))


def _req(url, data=None, headers=None, method=None, timeout=180):
    body = None
    if isinstance(data, (dict, list)):
        body = json.dumps(data).encode()
        headers = {**(headers or {}), "Content-Type": "application/json"}
    elif isinstance(data, bytes):
        body = data
        # 🔴 ТИП ВМІСТУ ДЛЯ ДВІЙКОВОГО ТІЛА ОБОВʼЯЗКОВИЙ.
        #
        # `urllib.request` САМ підставляє `Content-Type: application/x-www-form-urlencoded`,
        # коли тіло задане, а тип не вказаний. Тобто LinkedIn отримував байти JPEG,
        # підписані як веб-форма, і відповідав `400` HTML-сторінкою замість помилки API.
        # Заміряно 08.09.2026 на першій живій публікації, і доведено прямим дослідом:
        #   тільки Authorization        → 400
        #   Authorization + octet-stream → 201
        #   Authorization + image/jpeg   → 201
        # Саме через це в LinkedIn не було постів «через код»: гілка існувала, підпис
        # читався, автор виправлявся — і все впиралось у заголовок, якого ніхто не ставив.
        if not (headers or {}).get("Content-Type"):
            headers = {**(headers or {}), "Content-Type": "application/octet-stream"}
    r = urllib.request.Request(url, data=body, headers=headers or {},
                               method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(txt) if txt.strip().startswith(("{", "[")) else txt), resp.headers
    except urllib.error.HTTPError as e:
        # 🔴 Тіло помилки обовʼязково: без нього в логах лишається «HTTP Error 400» без
        # причини. Це вже коштувало нам часу на YouTube (див. meta_post.yt_short).
        raise RuntimeError(f"{method or 'POST'} {url.split('?')[0]} → {e.code}: "
                           f"{e.read().decode('utf-8', 'replace')[:400]}")


# ═══════════════════════════════════════════════════════════════════════════════
# THREADS
# ═══════════════════════════════════════════════════════════════════════════════
TH_API = "https://graph.threads.net/v1.0"


def th_publish(text, dry=False, video_url=None, image_url=None):
    """Пост у Threads: текст, або текст + відео, або текст + картинка.

    Схема Threads така сама, як у Instagram: спершу контейнер, потім очікування, потім
    публікація. Відео обробляється не миттєво, тому опитуємо статус.
    """
    cfg = _cfg("threads", "THREADS_CONFIG")
    tok, uid = cfg["access_token"], cfg["threads_user_id"]
    kind = "VIDEO" if video_url else ("IMAGE" if image_url else "TEXT")
    params = {"media_type": kind, "text": text[:500], "access_token": tok}
    if video_url:
        params["video_url"] = video_url
    if image_url:
        params["image_url"] = image_url
    if dry:
        print(f"  [dry-run] Threads {kind}: {text[:60]!r}")
        return None
    st, d, _ = _req(f"{TH_API}/{uid}/threads",
                    data=urllib.parse.urlencode(params).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    cid = d.get("id")
    if not cid:
        raise RuntimeError(f"Threads: контейнер не створений: {str(d)[:200]}")
    print(f"  Threads container: {cid}")
    if kind != "TEXT":
        for _ in range(40):
            time.sleep(6)
            _s, s, _h = _req(f"{TH_API}/{cid}?fields=status,error_message"
                             f"&access_token={urllib.parse.quote(tok)}", method="GET")
            code = (s or {}).get("status")
            print(f"    status: {code}")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError(f"Threads обробка впала: {str(s)[:200]}")
        else:
            raise RuntimeError("Threads: обробка не завершилась за 4 хвилини")
    st, pub, _ = _req(f"{TH_API}/{uid}/threads_publish",
                      data=urllib.parse.urlencode(
                          {"creation_id": cid, "access_token": tok}).encode(),
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    pid = pub.get("id")
    if not pid:
        raise RuntimeError(f"Threads: публікація не вдалась: {str(pub)[:200]}")
    print(f"  ✅ Threads published: {pid}")
    return pid


# ═══════════════════════════════════════════════════════════════════════════════
# LINKEDIN
# ═══════════════════════════════════════════════════════════════════════════════
LI_API = "https://api.linkedin.com/rest"


def _li_headers(cfg):
    return {"Authorization": f"Bearer {cfg['access_token']}",
            "X-Restli-Protocol-Version": "2.0.0",
            # 🔴 Версію беремо З КОНФІГУ. Мої здогадки (202508, 202507, 202506, 202505,
            # 202411) усі віддали 426 NONEXISTENT_VERSION, а значення з конфігу — 200.
            "LinkedIn-Version": str(cfg.get("api_version") or "202608")}


def _li_author(cfg):
    """Сторінка, НА ЯКУ публікуємо. Береться за назвою з конфігу, а не за порядком у списку.

    🔴 БУЛО `organizations[0]`, І ЦЕ ПУБЛІКУВАЛО НЕ ТУДИ. У конфігу два URN:
    `49102903` — «UTD development» (останній пост 2021 року, підписників майже немає) і
    `18514299` — «UTD eCommerce» (`/company/the-united-team-of-developers/`), жива
    сторінка агентства. У списку перша — мертва.

    Заміряно 08.09.2026: та сама помилка вже знайшлась у `linkedin_refresh.py`, де вона
    лише брехала в метриці («0 постів за 30 днів» замість 1). Тут вона дорожча: пости
    поїхали б на сторінку, якої ніхто не читає, і виглядало б це як успішна публікація.
    Помилка, що не падає, а тихо робить не те, — найдорожча.

    Поле `page` у конфігу весь час містило «UTD eCommerce». Правильна відповідь лежала в
    тому самому файлі, який код уже читав.
    """
    orgs = cfg.get("organizations") or []
    if not orgs:
        raise RuntimeError("LinkedIn: у конфігу немає organizations")
    want = str(cfg.get("page") or "").strip().lower()
    if want:
        for urn in orgs:
            oid = str(urn).split(":")[-1]
            try:
                _s, d, _h = _req(f"{LI_API}/organizations/{oid}", headers=_li_headers(cfg))
                if str(d.get("localizedName") or "").strip().lower() == want:
                    return urn
            except Exception:
                continue
        # Назву не підтвердили — краще впасти, ніж опублікувати на випадкову сторінку.
        raise RuntimeError(
            f"LinkedIn: сторінку «{cfg.get('page')}» не знайдено серед {orgs}. "
            f"Публікацію НЕ роблю: пост на чужу сторінку гірший за відсутній.")
    return orgs[0]


def li_publish(text, dry=False, video_path=None, image_path=None, title=None):
    """Пост на сторінку компанії LinkedIn: текст, відео або картинка.

    Відео в LinkedIn — три кроки: initializeUpload (дає адреси частин), PUT кожної
    частини, finalizeUpload (склеює за ETag). Тільки потім /posts.
    """
    cfg = _cfg("linkedin", "LINKEDIN_CONFIG")
    author = _li_author(cfg)
    hdr = _li_headers(cfg)

    media_urn = None
    if video_path or image_path:
        path = video_path or image_path
        what = "videos" if video_path else "images"
        size = os.path.getsize(path)
        if dry:
            print(f"  [dry-run] LinkedIn {what}: {os.path.basename(path)} {size/1e6:.2f} МБ")
        else:
            init_body = {"initializeUploadRequest": {"owner": author}}
            if video_path:
                init_body["initializeUploadRequest"].update(
                    {"fileSizeBytes": size, "uploadCaptions": False, "uploadThumbnail": False})
            _s, d, _h = _req(f"{LI_API}/{what}?action=initializeUpload",
                             data=init_body, headers=hdr)
            val = d.get("value") or {}
            media_urn = val.get("video") or val.get("image")
            token = val.get("uploadToken", "")
            parts = val.get("uploadInstructions") or (
                [{"uploadUrl": val["uploadUrl"], "firstByte": 0, "lastByte": size - 1}]
                if val.get("uploadUrl") else [])
            if not media_urn or not parts:
                raise RuntimeError(f"LinkedIn init без urn або адрес: {str(d)[:250]}")
            blob = open(path, "rb").read()
            etags = []
            for i, part in enumerate(parts, 1):
                lo = int(part.get("firstByte", 0)); hi = int(part.get("lastByte", size - 1))
                # Тип саме за розширенням: DMS LinkedIn перевіряє його на завантаженні.
                _ct = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                       ".mp4": "video/mp4"}.get(os.path.splitext(path)[1].lower(),
                                                "application/octet-stream")
                _s2, _b, h2 = _req(part["uploadUrl"], data=blob[lo:hi + 1],
                                   headers={"Authorization": hdr["Authorization"],
                                            "Content-Type": _ct},
                                   method="PUT")
                et = (h2.get("ETag") or h2.get("etag") or "").strip('"')
                etags.append(et)
                print(f"    частина {i}/{len(parts)}: {(hi-lo+1)/1e6:.2f} МБ, ETag {et[:12]}")
            if video_path:
                _req(f"{LI_API}/videos?action=finalizeUpload",
                     data={"finalizeUploadRequest": {"video": media_urn,
                                                     "uploadToken": token,
                                                     "uploadedPartIds": etags}},
                     headers=hdr)
                print(f"  LinkedIn відео склеєне: {media_urn}")

    post = {"author": author, "commentary": text, "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED",
                             "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    if media_urn:
        post["content"] = {"media": {"id": media_urn,
                                     "title": (title or text)[:200]}}
    if dry:
        print(f"  [dry-run] LinkedIn пост від {author}: {text[:60]!r}")
        return None
    _s, _d, h = _req(f"{LI_API}/posts", data=post, headers=hdr)
    pid = h.get("x-restli-id") or h.get("X-RestLi-Id")
    if not pid:
        raise RuntimeError("LinkedIn: у відповіді немає x-restli-id")
    print(f"  ✅ LinkedIn published: {pid}")
    return pid


# ═══════════════════════════════════════════════════════════════════════════════
# TIKTOK
# ═══════════════════════════════════════════════════════════════════════════════
TT_API = "https://open.tiktokapis.com/v2"


def _tt_creator_info(tok):
    """Що TikTok дозволяє ЦЬОМУ клієнту й цьому акаунту прямо зараз.

    Повертає (список рівнів приватності, нікнейм, {comment/duet/stitch: вимкнено}).
    При невдачі — (None, None, None): «не знаю» це не «можна все».
    """
    try:
        _s, d, _h = _req(f"{TT_API}/post/publish/creator_info/query/", data={},
                         headers={"Authorization": f"Bearer {tok}"})
        x = (d or {}).get("data") or {}
        return (x.get("privacy_level_options"), x.get("creator_nickname"),
                {"comment": x.get("comment_disabled"), "duet": x.get("duet_disabled"),
                 "stitch": x.get("stitch_disabled")})
    except Exception as e:
        print(f"  🟡 creator_info не відповів ({type(e).__name__}) — іду чернеткою, "
              f"бо «не знаю» це не «можна публічно»")
        return None, None, None


def tt_publish(video_path, caption, dry=False):
    """Відео в TikTok. Шлях FILE_UPLOAD: init → PUT байтів → опитування статусу.

    🔴 ЧОМУ НЕ PULL_FROM_URL, хоч у документації він є. Перша версія цієї функції тягла
    відео за URL з ефемерного хостингу — і це був МІЙ винахід, тоді як у
    `~/utd-runner/scripts/tiktok_publisher.py` уже лежав інший шлях, **доведений живим
    прогоном 02.09.2026**: init → PUT байтів (HTTP 201) → `PUBLISH_COMPLETE` за 10 секунд,
    справжній `publish_id`, файл reel85.mp4.

    Тобто я написав другу реалізацію того самого, неперевірену, замість того щоб узяти
    заміряну. `PULL_FROM_URL` ще й вимагає підтвердженого домену в застосунку — зайва
    залежність там, де байти можна віддати напряму.

    🔴 ДВА ФІНАЛЬНІ СТАТУСИ, і це не деталь. Пряма публікація завершується
    `PUBLISH_COMPLETE`, чернетка — `SEND_TO_USER_INBOX`. 02.09.2026 чекання
    `PUBLISH_COMPLETE` для чернетки дало 60 секунд `PROCESSING_UPLOAD` і хибний висновок
    «не завершилось», хоч усе було доставлено.

    🔴 ПРО ТОКЕН. Заявку подано на розгляд 04.09.2026. Поки продакшн-токена немає,
    працює лише `sandbox_token`, а в Sandbox приватність **тільки SELF_ONLY** — відео
    видно лише нам. Це НЕ публікація, і функція каже це вголос: інакше «успішно
    опубліковано» означало б «ніхто не побачив».
    """
    cfg = _cfg("tiktok", "TIKTOK_CONFIG")
    prod = cfg.get("access_token")
    sand = cfg.get("sandbox_token") if isinstance(cfg.get("sandbox_token"), dict) else {}
    tok = prod or (sand or {}).get("access_token")
    if not tok:
        raise RuntimeError(
            "TikTok: немає ні продакшн-токена, ні sandbox. Стан застосунку: "
            f"«{cfg.get('status', '?')}». Це дія власника в порталі TikTok.")
    sandbox_only = not prod
    # 🔴 СХВАЛЕННЯ ЗАСТОСУНКУ ≠ ПРАВО ПУБЛІКУВАТИ ПУБЛІЧНО.
    #
    # 10.09.2026 TikTok схвалив «UTD Publisher» (live з 09:01). Перша реакція — поставити
    # PUBLIC_TO_EVERYONE, бо продакшн-токен нарешті є. Це було б помилкою, і дорогою:
    # у правилах Direct Post дослівно «Unaudited API Clients can only post contents in
    # SELF_ONLY viewership», плюс не більше 5 користувачів за 24 години. Тобто до
    # окремого АУДИТУ Direct Post кожен «успішно опублікований» ролик побачили б лише ми.
    #
    # Найгірше тут не обмеження, а те, як воно виглядало б у логах: `PUBLISH_COMPLETE`,
    # зелена галочка, справжній publish_id — і нуль глядачів. Той самий клас, що з
    # «розсилка йде, але листів немає».
    #
    # Тому маршрут вибирається за прапорцем `direct_post_audited` у конфізі, і поки він
    # не стоїть — ідемо ЧЕРНЕТКАМИ: відео падає в інбокс акаунта, людина відкриває TikTok
    # і публікує звичайним способом, тобто з нормальною видимістю. Один тап замість
    # аудиту. `post_info` у цьому маршруті не передається взагалі — приватність вибирає
    # людина в застосунку.
    # 🔴 ПИТАЄМО TIKTOK, А НЕ ДОКУМЕНТАЦІЮ. Уранці 10.09.2026 я прочитав у правилах
    # «Unaudited API Clients can only post contents in SELF_ONLY viewership» і поставив
    # прапорець `direct_post_audited` вручну. Потім спитав їхній же endpoint
    # `creator_info/query` — і він відповів, що нашому клієнту доступні
    # `['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY']`.
    #
    # Ті самі правила прямо кажуть: «The options listed in the UX must follow the
    # privacy_level_options returned in the creator_info API». Тобто авторитет — API,
    # а не абзац у документі. Я взяв документ за замір, і це той самий клас, за який я
    # платив цього тижня зі сторінками сайта: інструмент не спитав, а висновок написав.
    #
    # Тепер маршрут вибирає САМ TikTok: якщо в дозволених рівнях є публічний — ідемо
    # прямою публікацією; якщо ні — чернеткою. Прапорець у конфізі лишається лише як
    # ручне «завжди чернеткою», якщо власник так вирішить.
    allowed, nickname, gates = _tt_creator_info(tok)
    force_draft = bool(cfg.get("force_draft"))
    can_public = "PUBLIC_TO_EVERYONE" in (allowed or [])
    draft_mode = sandbox_only or force_draft or not can_public
    if allowed is not None:
        print(f"  TikTok дозволяє рівні: {allowed} · акаунт: {nickname!r}")
    size = os.path.getsize(video_path)
    if draft_mode:
        why = ("Sandbox" if sandbox_only else
               "власник поставив force_draft" if force_draft else
               f"TikTok не дає публічного рівня, дозволено лише {allowed}")
        print(f"  🟡 TikTok: іду ЧЕРНЕТКОЮ ({why}). Відео зʼявиться в інбоксі акаунта "
              f"UTD — щоб воно вийшло публічно, треба відкрити TikTok і натиснути "
              f"«Post». Пряма публікація без аудиту дала б SELF_ONLY, тобто нуль "
              f"глядачів при зеленому статусі.")
        endpoint = f"{TT_API}/post/publish/inbox/video/init/"
        body = {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": size, "total_chunk_count": 1}}
        privacy = "чернетка (приватність вибирає людина)"
    else:
        endpoint = f"{TT_API}/post/publish/video/init/"
        privacy = "PUBLIC_TO_EVERYONE"
        # 🔴 Галочки взаємодій беремо з creator_info, а не ставимо False наосліп. Їхнє
        # правило: «Disable checkboxes for interactions the creator has disabled in
        # their settings». Якщо творець вимкнув дуети в себе, а ми пришлемо
        # disable_duet=False, ми перевизначаємо його власне налаштування.
        body = {"post_info": {"title": caption[:2200], "privacy_level": privacy,
                              "disable_comment": bool((gates or {}).get("comment")),
                              "disable_duet": bool((gates or {}).get("duet")),
                              "disable_stitch": bool((gates or {}).get("stitch"))},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": size, "total_chunk_count": 1}}
        print("  🟢 TikTok: пряма ПУБЛІЧНА публікація — TikTok підтвердив, що рівень "
              "PUBLIC_TO_EVERYONE нам доступний")
    if dry:
        print(f"  [dry-run] TikTok {privacy}: {os.path.basename(video_path)} "
              f"{size/1e6:.2f} МБ, {caption[:50]!r}")
        return None

    _s, d, _h = _req(endpoint, data=body,
                     headers={"Authorization": f"Bearer {tok}"})
    data = (d or {}).get("data") or {}
    pid, up = data.get("publish_id"), data.get("upload_url")
    if not (pid and up):
        raise RuntimeError(f"TikTok init без publish_id/upload_url: {str(d)[:250]}")
    print(f"  TikTok publish_id: {pid}")

    blob = open(video_path, "rb").read()
    _req(up, data=blob, method="PUT",
         headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                  "Content-Range": f"bytes 0-{size - 1}/{size}"}, timeout=600)
    print(f"  байти прийняті: {size/1e6:.2f} МБ")

    GOOD = ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX")
    code = None
    for _ in range(32):
        time.sleep(2.5)
        _s3, st, _h3 = _req(f"{TT_API}/post/publish/status/fetch/",
                            data={"publish_id": pid},
                            headers={"Authorization": f"Bearer {tok}"})
        code = ((st or {}).get("data") or {}).get("status")
        print(f"    status: {code}")
        if code in GOOD:
            print(f"  ✅ TikTok {code}: {pid}")
            if code == "SEND_TO_USER_INBOX":
                print("  🔴 ЦЕ ЩЕ НЕ ПУБЛІКАЦІЯ: відео лежить у чернетках акаунта. "
                      "Публікує людина в застосунку TikTok.")
            return pid
        if code and "FAIL" in str(code):
            raise RuntimeError(f"TikTok статус {code}: {str(st)[:250]}")
    raise RuntimeError(f"TikTok: статус не став остаточним за 80 с, останній {code}")


# ═══════════════════════════════════════════════════════════════════════════════
def _classify(e):
    """«Токен відмовили» і «не додзвонився» — РІЗНІ відповіді.

    🔴 Заміряно на собі 04.09.2026: два прогони самоперевірки підряд дали різний
    результат — спершу 🔴, за хвилину 🟢, при незмінному коді. Причина була в мережі, а
    не в токені. Червоний колір за таймаут навчає не вірити червоному, тому мережева
    невдача це 🟡 «не доперевірив», а не «мертвий».
    """
    txt = str(e)
    has_http_code = any(f"→ {c}" in txt for c in (400, 401, 403, 404, 426, 429, 500))
    return ("🔴" if has_http_code else "🟡"), txt[:110]


def token_health():
    """Читання без побічних дій: чи живий токен кожної мережі. Для post_selftest."""
    out = {}
    try:
        cfg = _cfg("threads", "THREADS_CONFIG")
        _s, d, _h = _req(f"{TH_API}/me?fields=id,username"
                         f"&access_token={urllib.parse.quote(cfg['access_token'])}",
                         method="GET", timeout=30)
        out["threads"] = f"🟢 @{d.get('username')}"
    except Exception as e:
        mark, txt = _classify(e)
        out["threads"] = f"{mark} {txt}"
    try:
        cfg = _cfg("linkedin", "LINKEDIN_CONFIG")
        # 🔴 ТРЕТІЙ ВИПАДОК ТОГО САМОГО БАГА за одну добу: `organizations[0]` — це
        # «UTD development», сторінка з останнім постом 2021 року. Перший випадок брехав
        # у метриці («0 постів за 30 днів»), другий публікував НА МЕРТВУ сторінку, третій
        # — цей — казав «🟢 linkedin: UTD development», тобто підтверджував здоровʼя не
        # тієї сторінки. Беремо ту саму функцію, що й публікація: один власник на факт.
        org = _li_author(cfg).split(":")[-1]
        _s, d, _h = _req(f"{LI_API}/organizations/{org}",
                         headers=_li_headers(cfg), method="GET", timeout=30)
        out["linkedin"] = f"🟢 {d.get('localizedName')}" if str(d.get("localizedName") or "").strip().lower() == str(cfg.get("page") or "").strip().lower() else f"🔴 перевіряє НЕ ТУ сторінку: {d.get('localizedName')}, а в конфігу page={cfg.get('page')}"
    except Exception as e:
        mark, txt = _classify(e)
        out["linkedin"] = f"{mark} {txt}"
    try:
        cfg = _cfg("tiktok", "TIKTOK_CONFIG")
        out["tiktok"] = ("🟢 токен є" if cfg.get("access_token")
                         else f"🔴 немає токена, застосунок «{cfg.get('status', '?')}»")
    except Exception as e:
        out["tiktok"] = f"🔴 {str(e)[:110]}"
    return out


if __name__ == "__main__":
    import sys
    if "--health" in sys.argv:
        for k, v in token_health().items():
            print(f"   {k:10} {v}")
        sys.exit(0)
    print(__doc__)
