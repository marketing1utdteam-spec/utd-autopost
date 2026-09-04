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


def li_publish(text, dry=False, video_path=None, image_path=None, title=None):
    """Пост на сторінку компанії LinkedIn: текст, відео або картинка.

    Відео в LinkedIn — три кроки: initializeUpload (дає адреси частин), PUT кожної
    частини, finalizeUpload (склеює за ETag). Тільки потім /posts.
    """
    cfg = _cfg("linkedin", "LINKEDIN_CONFIG")
    author = (cfg.get("organizations") or [None])[0]
    if not author:
        raise RuntimeError("LinkedIn: у конфігу немає organizations")
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
                _s2, _b, h2 = _req(part["uploadUrl"], data=blob[lo:hi + 1],
                                   headers={"Authorization": hdr["Authorization"]},
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


def tt_publish(video_url, caption, dry=False):
    """Відео в TikTok через Content Posting API, спосіб PULL_FROM_URL.

    🔴 Зараз це НЕ ПРАЦЮЄ, і причина не в коді. Заміряно 04.09.2026:
    `~/.config/utd/tiktok.json` має `client_key` і `client_secret`, але `access_token`
    порожній, а сам застосунок у стані **Draft**: не подані іконка, категорія, опис,
    Terms of Service URL, Privacy Policy URL, платформи, опис для рев'ю з демо-відео,
    продукт Content Posting API і дозволи.

    Функція навмисно не «тихо пропускає», а падає з поясненням: інакше запис пішов би в
    карантин із порожньою причиною, і через тиждень ніхто б не згадав, чому TikTok мовчить.
    Домен для PULL_FROM_URL мусить бути підтверджений у застосунку — у конфігу є
    `domain_verified`, і його теж треба буде звірити перед першим постом.
    """
    cfg = _cfg("tiktok", "TIKTOK_CONFIG")
    tok = cfg.get("access_token")
    if not tok:
        raise RuntimeError(
            "TikTok не налаштований: у застосунку немає access_token, стан «"
            f"{cfg.get('status', 'Draft')}». Бракує: "
            f"{', '.join(cfg.get('missing') or ['опис заявки'])}. "
            "Це дія власника в порталі TikTok, кодом не обходиться.")
    body = {"post_info": {"title": caption[:2200], "privacy_level": "PUBLIC_TO_EVERYONE",
                          "disable_duet": False, "disable_comment": False,
                          "disable_stitch": False},
            "source_info": {"source": "PULL_FROM_URL", "video_url": video_url}}
    if dry:
        print(f"  [dry-run] TikTok: {caption[:60]!r}")
        return None
    _s, d, _h = _req(f"{TT_API}/post/publish/video/init/", data=body,
                     headers={"Authorization": f"Bearer {tok}"})
    pid = ((d or {}).get("data") or {}).get("publish_id")
    if not pid:
        raise RuntimeError(f"TikTok: немає publish_id: {str(d)[:250]}")
    print(f"  ✅ TikTok publish_id: {pid}")
    return pid


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
        org = (cfg.get("organizations") or [""])[0].split(":")[-1]
        _s, d, _h = _req(f"{LI_API}/organizations/{org}",
                         headers=_li_headers(cfg), method="GET", timeout=30)
        out["linkedin"] = f"🟢 {d.get('localizedName')}"
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
