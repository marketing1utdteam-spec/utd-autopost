"""Поставити власну обкладинку на вже опубліковане YouTube-відео (thumbnails.set).

Креди беруться з YT_CONFIG (секрет GitHub), як у meta_post.py: локальний
~/.config/utd/youtube.json застарів і дає invalid_client.
  python yt_thumb.py VIDEO_ID path/to/thumb.png
"""
import json, os, sys, urllib.parse, urllib.request, urllib.error

vid, path = sys.argv[1], sys.argv[2]
cfg = json.loads(os.environ["YT_CONFIG"])
body = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                               "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
at = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body))["access_token"]
ctype = "image/png" if path.endswith(".png") else "image/jpeg"
req = urllib.request.Request(
    f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
    data=open(path, "rb").read(), headers={"Authorization": f"Bearer {at}", "Content-Type": ctype}, method="POST")
try:
    resp = json.load(urllib.request.urlopen(req))
except urllib.error.HTTPError as e:
    sys.exit(f"🔴 thumbnails.set {e.code}: {e.read().decode()[:400]}")
print("✅ обкладинку поставлено:", vid, resp.get("items", [{}])[0].get("maxres", resp.get("items", [{}])[0].get("default", {})).get("url", ""))
