"""Тільки читання: стан відео на YouTube (status, обмеження за регіонами, заявки).
  python yt_status.py ID [ID ...]
Креди з YT_CONFIG, як у yt_thumb.py. Нічого не змінює.
"""
import json, os, sys, urllib.parse, urllib.request
cfg = json.loads(os.environ["YT_CONFIG"])
body = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                               "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
at = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body))["access_token"]
ids = sys.argv[1:]
def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {at}"})))
if ids == ["--uploads"]:  # усі завантаження каналу
    pl = get("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true")["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], ""
    while True:
        pg = get(f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId={pl}&pageToken={tok}")
        ids += [i["contentDetails"]["videoId"] for i in pg["items"]]
        tok = pg.get("nextPageToken")
        if not tok: break
    sys.argv[1:] = ids
r = {"items": []}
for n in range(0, len(ids), 50):  # API бере до 50 ID за раз
    q = urllib.parse.urlencode({"part": "status,contentDetails,snippet,statistics", "id": ",".join(ids[n:n+50])})
    r["items"] += json.load(urllib.request.urlopen(urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3/videos?{q}", headers={"Authorization": f"Bearer {at}"}))).get("items", [])
found = {i["id"] for i in r.get("items", [])}
if os.environ.get("DUMP"):  # повні сніпети для правки описів (усе публічне)
    json.dump([{"id": i["id"], "title": i["snippet"]["title"], "description": i["snippet"].get("description", ""),
                "tags": i["snippet"].get("tags", []), "categoryId": i["snippet"].get("categoryId"),
                "defaultLanguage": i["snippet"].get("defaultLanguage"), "publishedAt": i["snippet"]["publishedAt"],
                "duration": i["contentDetails"]["duration"], "views": int(i.get("statistics", {}).get("viewCount", 0))}
               for i in r["items"]], open(os.environ["DUMP"], "w"), ensure_ascii=False, indent=1)
for i in r.get("items", []):
    st, cd = i["status"], i["contentDetails"]
    print(i["id"], "|", i["snippet"]["title"][:70], "| upload:", st.get("uploadStatus"),
          "| privacy:", st.get("privacyStatus"), "| reject:", st.get("rejectionReason"),
          "| failure:", st.get("failureReason"), "| licensed:", cd.get("licensedContent"),
          "| dur:", cd.get("duration"),
          "| blocked_countries:", len((cd.get("regionRestriction") or {}).get("blocked", [])))
for v in sys.argv[1:]:
    if v not in found: print(v, "| НЕ ПОВЕРНУТО API (видалено або чужий канал)")
