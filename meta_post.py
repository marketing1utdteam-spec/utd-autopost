#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UTD Meta poster — IG (single/carousel/reel) + FB. Эфемерный хостинг медиа (залил→запостил→удалил).
Config: ~/.config/utd/meta-app.json  (system user + page tokens, ids).
GitHub token: env GH_TOKEN или git credential fill. Медиа-репо: marketing1utdteam-spec/utd-media (public).

Примеры:
  python3 meta_post.py --ig-post <folder> [--dry-run]
  python3 meta_post.py --fb-post <folder> [--schedule 2026-07-15T12:00] [--dry-run]
  python3 meta_post.py --ig-reel <mp4> --caption-file <f> [--dry-run]
"""
import json, os, sys, time, base64, subprocess, argparse, glob, tempfile
import urllib.parse, urllib.request, urllib.error
from PIL import Image

CFG = (json.loads(os.environ['META_CONFIG']) if os.environ.get('META_CONFIG')
       else json.load(open(os.path.expanduser('~/.config/utd/meta-app.json'))))
IG = CFG['ig_user_id']; PAGE = CFG['page_id']; PT = CFG['page_access_token']
GRAPH = "https://graph.facebook.com/v21.0/"
MEDIA_REPO = "marketing1utdteam-spec/utd-media"
TMP = os.path.join(tempfile.gettempdir(), "utd_meta_post"); os.makedirs(TMP, exist_ok=True)

# ---------- GitHub ephemeral hosting ----------
def gh_token():
    t = os.environ.get('GH_TOKEN')
    if t: return t
    out = subprocess.run(['git','credential','fill'], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith('password='): return line[9:]
    raise RuntimeError('нет GitHub токена (GH_TOKEN или git credential)')

def gh_upload(localfile, repopath):
    tok = gh_token()
    with open(localfile,'rb') as f: content = base64.b64encode(f.read()).decode()
    body = json.dumps({"message":f"add {repopath}","content":content}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{MEDIA_REPO}/contents/{repopath}",
        data=body, method='PUT', headers={"Authorization":f"token {tok}","Accept":"application/vnd.github+json"})
    r = json.load(urllib.request.urlopen(req, timeout=180))
    url = f"https://raw.githubusercontent.com/{MEDIA_REPO}/main/{repopath}"
    return url, r['content']['sha']

def gh_delete(repopath, sha):
    tok = gh_token()
    body = json.dumps({"message":f"del {repopath}","sha":sha}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{MEDIA_REPO}/contents/{repopath}",
        data=body, method='DELETE', headers={"Authorization":f"token {tok}","Accept":"application/vnd.github+json"})
    try: urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e: print("  ! delete warn:", e.read()[:120])

# ---------- Graph API ----------
def graph(path, params, method='POST'):
    params = {**params, "access_token": PT}
    try:
        if method == 'POST':
            r = urllib.request.urlopen(GRAPH+path, data=urllib.parse.urlencode(params).encode(), timeout=180)
        else:
            r = urllib.request.urlopen(GRAPH+path+"?"+urllib.parse.urlencode(params), timeout=180)
        return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": json.load(e)}

def die(msg, r):
    raise RuntimeError(f"{msg}: {json.dumps(r, ensure_ascii=False)[:400]}")

def wait_ready(cid, tries=30, delay=5):
    """Ждём, пока медиа-контейнер обработается (status_code=FINISHED) перед публикацией."""
    for _ in range(tries):
        st = graph(cid, {"fields": "status_code"}, method='GET')
        code = st.get("status_code")
        if code == "FINISHED": return
        if code == "ERROR": die("container processing error", st)
        time.sleep(delay)
    die("container not ready (timeout)", {"cid": cid})

def to_jpg(png, maxw=1440):
    im = Image.open(png).convert('RGB')
    if im.width > maxw:                       # ровно под макс. размер ленты IG — минимум перекодирования на их стороне
        im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    out = os.path.join(TMP, os.path.splitext(os.path.basename(png))[0] + '.jpg')
    im.save(out, 'JPEG', quality=95, subsampling=0); return out

def strip_caption(md_path):
    txt = open(md_path).read().strip()
    return "\n".join(l for l in txt.splitlines() if not l.startswith('## ')).strip()

# ---------- IG ----------
def ig_carousel(slides, caption, dry):
    stamp = int(time.time()); uploaded = []; children = []
    try:
        for i, png in enumerate(slides, 1):
            jpg = to_jpg(png); rp = f"q/{stamp}_s{i}.jpg"; url, sha = gh_upload(jpg, rp); uploaded.append((rp, sha))
            r = graph(f"{IG}/media", {"image_url": url, "is_carousel_item": "true"})
            if "id" not in r: die("child fail", r)
            children.append(r["id"]); print(f"  child {i}: {r['id']}")
        cont = graph(f"{IG}/media", {"media_type":"CAROUSEL","children":",".join(children),"caption":caption})
        if "id" not in cont: die("carousel container fail", cont)
        print("  carousel container:", cont["id"], "— жду готовности...")
        if dry:
            print("  [dry-run] публикацию не вызываю"); return None
        wait_ready(cont["id"])
        pub = graph(f"{IG}/media_publish", {"creation_id": cont["id"]})
        if "id" not in pub: die("publish fail", pub)
        print("  ✅ IG published:", pub["id"]); return pub["id"]
    finally:
        for rp, sha in uploaded: gh_delete(rp, sha)
        print("  🧹 медиа удалены с хостинга")

def ig_single(png, caption, dry):
    stamp = int(time.time()); jpg = to_jpg(png); rp = f"q/{stamp}_s.jpg"; url, sha = gh_upload(jpg, rp)
    try:
        cont = graph(f"{IG}/media", {"image_url": url, "caption": caption})
        if "id" not in cont: die("container fail", cont)
        print("  container:", cont["id"], "— жду готовности...")
        if dry: print("  [dry-run] публикацию не вызываю"); return None
        wait_ready(cont["id"])
        pub = graph(f"{IG}/media_publish", {"creation_id": cont["id"]})
        if "id" not in pub: die("publish fail", pub)
        print("  ✅ IG published:", pub["id"]); return pub["id"]
    finally:
        gh_delete(rp, sha); print("  🧹 медиа удалено")

def reencode_hi(mp4):
    """Перекодируем в высокий битрейт (IG меньше дожимает движение). Если ffmpeg нет — вернём как есть."""
    out = os.path.join(TMP, "hb_" + os.path.basename(mp4))
    try:
        r = subprocess.run(["ffmpeg","-y","-i",mp4,"-c:v","libx264","-preset","slow",
                            "-b:v","8M","-maxrate","10M","-bufsize","16M","-pix_fmt","yuv420p",
                            "-c:a","aac","-b:a","192k","-movflags","+faststart",out],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            print("  видео перекодировано в высокий битрейт (8 Mbps)"); return out
    except FileNotFoundError:
        pass
    print("  ! ffmpeg недоступен — гружу оригинал"); return mp4

def extract_cover(mp4, sec=None):
    """Обложка рилса = кадр, где заголовок и экран магазина полностью видны (правило Дениса: обложка показывает содержание).
    По умолчанию берём кадр на 45% длительности (скролл в разгаре, экран магазина виден)."""
    try:
        probe = subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_format",mp4],capture_output=True,text=True)
        dur = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        dur = 20.0
    ts = sec if sec is not None else round(dur*0.45, 1)
    out = os.path.join(TMP, "cover_"+os.path.splitext(os.path.basename(mp4))[0]+".jpg")
    r = subprocess.run(["ffmpeg","-y","-v","error","-ss",str(ts),"-i",mp4,"-frames:v","1","-q:v","2",out],capture_output=True,text=True)
    if r.returncode == 0 and os.path.exists(out):
        print(f"  обложка: кадр {ts}s"); return out
    print("  ! не смог извлечь обложку — рилс уйдёт без cover_url"); return None

def ig_reel(mp4, caption, dry, cover=None, cover_sec=None):
    mp4 = reencode_hi(mp4)
    cover = cover or extract_cover(mp4, cover_sec)
    stamp = int(time.time()); rp = f"q/{stamp}_reel.mp4"; url, sha = gh_upload(mp4, rp)
    cov_rp, cov_sha, cov_url = None, None, None
    if cover:
        cov_rp = f"q/{stamp}_cover.jpg"; cov_url, cov_sha = gh_upload(cover, cov_rp)
    try:
        params = {"media_type":"REELS","video_url":url,"caption":caption,"share_to_feed":"false"}
        if cov_url: params["cover_url"] = cov_url
        cont = graph(f"{IG}/media", params)
        if "id" not in cont: die("reel container fail", cont)
        cid = cont["id"]; print("  reel container:", cid, "— жду обработку видео Meta...")
        for _ in range(40):
            time.sleep(6)
            st = graph(cid, {"fields":"status_code,status"}, method='GET')
            code = st.get("status_code"); print("    status:", code)
            if code == "FINISHED": break
            if code == "ERROR": die("reel processing error", st)
        else:
            die("reel timeout", {"last": st})
        if dry: print("  [dry-run] публикацию не вызываю"); return None
        pub = graph(f"{IG}/media_publish", {"creation_id": cid})
        if "id" not in pub: die("reel publish fail", pub)
        print("  ✅ IG Reel published:", pub["id"]); return pub["id"]
    finally:
        gh_delete(rp, sha)
        if cov_rp: gh_delete(cov_rp, cov_sha)
        print("  🧹 видео и обложка удалены с хостинга")

# ---------- YouTube ----------
def yt_short(mp4, title, description, dry=False):
    """Загрузка Shorts. До аудита Google видео выходят private (ограничение платформы)."""
    ycfg = (json.loads(os.environ['YT_CONFIG']) if os.environ.get('YT_CONFIG')
            else json.load(open(os.path.expanduser('~/.config/utd/youtube.json'))))
    body = urllib.parse.urlencode({'client_id':ycfg['client_id'],'client_secret':ycfg['client_secret'],
        'refresh_token':ycfg['refresh_token'],'grant_type':'refresh_token'}).encode()
    try:
        at = json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', data=body))['access_token']
    except urllib.error.HTTPError as e:
        # без этого except run_due.py логировал только "HTTP Error 400: Bad Request"
        # без тела ответа — реальная причина (invalid_grant и т.п.) была не видна в логах.
        raise RuntimeError(f"YT token refresh {e.code}: {e.read().decode()[:300]}")
    # 🔴 containsSyntheticMedia — ОБОВʼЯЗКОВА декларація, а не ввічливість.
    # YouTube вимагає позначати реалістичний згенерований або змінений контент; поле додане в
    # Data API 30.10.2024 і ставиться саме тут, у videos.insert. Без нього відео виходить без
    # позначки «Made with AI» у розділі «How this content was made», і це порушення правил
    # платформи. Наші рілси зроблені генерацією, тому значення завжди True.
    # Друга частина того самого обовʼязку — видимий напис «AI Generated» на самому кадрі
    # (правило власника від 13.08.2026); він додається на етапі збірки відео, не тут.
    meta = {"snippet":{"title":title[:100],"description":description[:4900],"categoryId":"28"},
            "status":{"privacyStatus":"public","selfDeclaredMadeForKids":False,
                      "containsSyntheticMedia":True}}
    if dry: print("  [dry-run] YT не загружаю:", title[:60]); return None
    try:
        init = urllib.request.Request(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            data=json.dumps(meta).encode(),
            headers={"Authorization":f"Bearer {at}","Content-Type":"application/json","X-Upload-Content-Type":"video/mp4"})
        loc = urllib.request.urlopen(init).headers["Location"]
        up = urllib.request.Request(loc, data=open(mp4,'rb').read(),
            headers={"Authorization":f"Bearer {at}","Content-Type":"video/mp4"}, method='PUT')
        resp = json.load(urllib.request.urlopen(up))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"YT upload {e.code}: {e.read().decode()[:300]}")
    print("  ✅ YT Short:", resp['id'], "(private до аудита) https://youtu.be/"+resp['id']); return resp['id']

# ---------- FB ----------
def fb_photo(png, caption, schedule_iso=None, dry=False):
    stamp = int(time.time()); jpg = to_jpg(png); rp = f"q/{stamp}_fb.jpg"; url, sha = gh_upload(jpg, rp)
    try:
        params = {"url": url, "caption": caption}
        if schedule_iso:
            ts = int(time.mktime(time.strptime(schedule_iso, "%Y-%m-%dT%H:%M")))
            params.update({"published":"false","scheduled_publish_time":str(ts)})
            print(f"  FB запланирован на {schedule_iso} (ts {ts})")
        if dry: print("  [dry-run] FB пост не создаю"); return None
        r = graph(f"{PAGE}/photos", params)
        if "id" not in r: die("fb fail", r)
        print("  ✅ FB post:", r["id"]); return r["id"]
    finally:
        # для scheduled Meta забирает фото при создании — можно удалить сразу
        gh_delete(rp, sha); print("  🧹 медиа удалено")

# ---------- CLI ----------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ig-post"); ap.add_argument("--fb-post"); ap.add_argument("--ig-reel")
    ap.add_argument("--caption-file"); ap.add_argument("--schedule")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.ig_post:
        folder = a.ig_post; slides = sorted(glob.glob(f"{folder}/slide_*.png"))
        cap = strip_caption(f"{folder}/caption_instagram.md")
        print(f"IG post: {os.path.basename(folder)} ({len(slides)} слайд.)")
        (ig_carousel if len(slides) > 1 else (lambda s,c,d: ig_single(s[0],c,d)))(slides, cap, a.dry_run)
    elif a.fb_post:
        folder = a.fb_post; cover = sorted(glob.glob(f"{folder}/slide_*.png"))[0]
        cap = strip_caption(f"{folder}/caption_facebook.md")
        print(f"FB post: {os.path.basename(folder)}")
        fb_photo(cover, cap, a.schedule, a.dry_run)
    elif a.ig_reel:
        cap = open(a.caption_file).read().strip() if a.caption_file else ""
        print(f"IG Reel: {os.path.basename(a.ig_reel)}")
        ig_reel(a.ig_reel, cap, a.dry_run)
    else:
        ap.print_help()
