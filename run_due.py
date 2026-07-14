#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Раннер по расписанию: публикует IG-посты и рилсы, у которых наступила дата и которые ещё не опубликованы.
FB идёт через нативное отложенное планирование Meta (см. fb_bulk_schedule.py), тут — только IG (нет нативного расписания).
Запуск: python run_due.py [--date YYYY-MM-DD] [--dry-run]
"""
import json, os, glob, argparse, datetime
import meta_post as M

HERE = os.path.dirname(os.path.abspath(__file__))

def today_brussels():
    # смещение Europe/Brussels: летом +2 (CEST). Для наших целей достаточно фикс.
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=2)).date().isoformat()

def load(p, default):
    fp = os.path.join(HERE, p)
    return json.load(open(fp)) if os.path.exists(fp) else default

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = a.date or today_brussels()
    sched = load("schedule.json", [])
    posted = set(load("posted.json", {"posted": []})["posted"])
    print(f"== run_due · today={today} · dry={a.dry_run} · записей в плане={len(sched)} · уже опубликовано={len(posted)}")

    did = []
    for e in sched:
        if e["date"] > today:            # ещё не время
            continue
        if e["id"] in posted:            # уже сделано
            continue
        print(f"\n--- ДЕЛАЮ {e['id']} ({e['kind']}, дата {e['date']}) ---")
        kind = e["kind"]
        if kind == "ig_post":
            folder = os.path.join(HERE, e["folder"])
            slides = sorted(glob.glob(f"{folder}/slide_*.jpg")) or sorted(glob.glob(f"{folder}/slide_*.png"))
            cap = open(f"{folder}/caption.txt").read().strip()
            if len(slides) > 1: M.ig_carousel(slides, cap, a.dry_run)
            else: M.ig_single(slides[0], cap, a.dry_run)
        elif kind == "ig_reel":
            cap = open(os.path.join(HERE, e["caption_file"])).read().strip()
            M.ig_reel(os.path.join(HERE, e["video"]), cap, a.dry_run)
        elif kind == "fb_post":
            folder = os.path.join(HERE, e["folder"])
            cover = (sorted(glob.glob(f"{folder}/slide_*.jpg")) or sorted(glob.glob(f"{folder}/slide_*.png")))[0]
            cap = open(f"{folder}/caption_fb.txt").read().strip()
            M.fb_photo(cover, cap, None, a.dry_run)
        else:
            print("  ! неизвестный kind:", kind); continue
        if not a.dry_run:
            did.append(e["id"])

    if did and not a.dry_run:
        p = load("posted.json", {"posted": []}); p["posted"] += did
        json.dump(p, open(os.path.join(HERE, "posted.json"), "w"), indent=2)
        print(f"\n== отмечено опубликованным: {did}")
    print("== done")

if __name__ == "__main__":
    main()
