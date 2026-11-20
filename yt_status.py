"""Тільки читання: стан відео на YouTube (status, обмеження за регіонами, заявки).
  python yt_status.py ID [ID ...]
Креди з YT_CONFIG, як у yt_thumb.py. Нічого не змінює.
"""
import json, os, sys, urllib.parse, urllib.request
cfg = json.loads(os.environ["YT_CONFIG"])
body = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                               "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
at = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body))["access_token"]
q = urllib.parse.urlencode({"part": "status,contentDetails,snippet", "id": ",".join(sys.argv[1:])})
r = json.load(urllib.request.urlopen(urllib.request.Request(
    f"https://www.googleapis.com/youtube/v3/videos?{q}", headers={"Authorization": f"Bearer {at}"})))
found = {i["id"] for i in r.get("items", [])}
for i in r.get("items", []):
    st, cd = i["status"], i["contentDetails"]
    print(i["id"], "|", i["snippet"]["title"][:50], "| upload:", st.get("uploadStatus"),
          "| privacy:", st.get("privacyStatus"), "| reject:", st.get("rejectionReason"),
          "| failure:", st.get("failureReason"), "| licensed:", cd.get("licensedContent"),
          "| regionRestriction:", json.dumps(cd.get("regionRestriction"))[:200])
for v in sys.argv[1:]:
    if v not in found: print(v, "| НЕ ПОВЕРНУТО API (видалено або чужий канал)")
