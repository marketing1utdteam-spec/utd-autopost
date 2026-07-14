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
    print("❌", msg, json.dumps(r, ensure_ascii=False)[:400]); sys.exit(1)

def to_jpg(png):
    out = os.path.join(TMP, os.path.basename(png).replace('.png','.jpg'))
    Image.open(png).convert('RGB').save(out, 'JPEG', quality=90); return out

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
        print("  carousel container:", cont["id"])
        if dry:
            print("  [dry-run] публикацию не вызываю"); return None
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
        print("  container:", cont["id"])
        if dry: print("  [dry-run] публикацию не вызываю"); return None
        pub = graph(f"{IG}/media_publish", {"creation_id": cont["id"]})
        if "id" not in pub: die("publish fail", pub)
        print("  ✅ IG published:", pub["id"]); return pub["id"]
    finally:
        gh_delete(rp, sha); print("  🧹 медиа удалено")

def ig_reel(mp4, caption, dry):
    stamp = int(time.time()); rp = f"q/{stamp}_reel.mp4"; url, sha = gh_upload(mp4, rp)
    try:
        cont = graph(f"{IG}/media", {"media_type":"REELS","video_url":url,"caption":caption,"share_to_feed":"true"})
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
        gh_delete(rp, sha); print("  🧹 видео удалено с хостинга")

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
