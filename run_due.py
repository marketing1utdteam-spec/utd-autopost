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

    # Счётчик неудач по каждой записи. Запись, которая падает раз за разом
    # (протухший OAuth, битый файл), после MAX_ATTEMPTS уходит в карантин и
    # больше не перебирается каждый прогон. Живой случай 2026-07-28: четыре
    # yt_short копились с 25 июля, падали на 400 и молча тянулись в каждый запуск.
    fails = load("failed.json", {})
    MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "5"))

    did, failed_now, quarantined = [], [], []
    for e in sched:
        if e["date"] > today:            # ещё не время
            continue
        if e["id"] in posted:            # уже сделано
            continue
        if fails.get(e["id"], 0) >= MAX_ATTEMPTS:
            quarantined.append(e["id"])
            continue
        print(f"\n--- ДЕЛАЮ {e['id']} ({e['kind']}, дата {e['date']}) ---")
        kind = e["kind"]
        try:
            if kind == "ig_post":
                folder = os.path.join(HERE, e["folder"])
                slides = sorted(glob.glob(f"{folder}/slide_*.jpg")) or sorted(glob.glob(f"{folder}/slide_*.png"))
                cap = open(f"{folder}/caption.txt").read().strip()
                if len(slides) > 1: M.ig_carousel(slides, cap, a.dry_run)
                else: M.ig_single(slides[0], cap, a.dry_run)
            elif kind == "ig_reel":
                cap = open(os.path.join(HERE, e["caption_file"])).read().strip()
                M.ig_reel(os.path.join(HERE, e["video"]), cap, a.dry_run)
            elif kind == "yt_short":
                m = json.load(open(os.path.join(HERE, e["meta_file"])))
                M.yt_short(os.path.join(HERE, e["video"]), m["title"], m["description"], a.dry_run)
            elif kind == "fb_post":
                folder = os.path.join(HERE, e["folder"])
                cover = (sorted(glob.glob(f"{folder}/slide_*.jpg")) or sorted(glob.glob(f"{folder}/slide_*.png")))[0]
                cap = open(f"{folder}/caption_fb.txt").read().strip()
                M.fb_photo(cover, cap, None, a.dry_run)
            else:
                print("  ! неизвестный kind:", kind); continue
        except Exception as ex:
            n = fails.get(e["id"], 0) + 1
            fails[e["id"]] = n
            failed_now.append((e["id"], kind, str(ex)[:120]))
            left = MAX_ATTEMPTS - n
            tail = (f"попытка {n}/{MAX_ATTEMPTS}, осталось {left}" if left > 0
                    else f"попытка {n}/{MAX_ATTEMPTS} — УХОДИТ В КАРАНТИН, чинить руками")
            print(f"  ❌ ОШИБКА на {e['id']}: {ex}  — {tail}")
            continue
        if not a.dry_run:
            did.append(e["id"])
            fails.pop(e["id"], None)      # успех обнуляет счётчик

    if did and not a.dry_run:
        p = load("posted.json", {"posted": []}); p["posted"] += did
        json.dump(p, open(os.path.join(HERE, "posted.json"), "w"), indent=2)
        print(f"\n== отмечено опубликованным: {did}")
    if not a.dry_run:
        json.dump(fails, open(os.path.join(HERE, "failed.json"), "w"), indent=2)

    if quarantined:
        print(f"\n⛔ В КАРАНТИНЕ (превышен лимит попыток, нужен ручной разбор): {quarantined}")
    if failed_now:
        print(f"\n❌ УПАЛО в этом прогоне: {len(failed_now)}")
        for pid, kind, err in failed_now:
            print(f"   · {pid} [{kind}] — {err}")

    print(f"== done · опубликовано {len(did)} · упало {len(failed_now)} · в карантине {len(quarantined)}")

    # Зелёный прогон при нулевых публикациях и непустой очереди — это ложь,
    # из-за которой простой YouTube-постинга не замечали четверо суток.
    # Пусть Actions краснеет: сбой должен быть виден в списке запусков.
    if failed_now or quarantined:
        # ВАЖНО: шаг воркфлоу «git add posted.json && commit» после ненулевого
        # выхода не выполнится (шаги пропускаются на упавшем job'е), а раннер
        # эфемерный — счётчик попыток обнулился бы каждый прогон и карантин
        # никогда бы не сработал. Поэтому состояние коммитим сами, до выхода.
        _persist_state_in_ci()
        raise SystemExit(1)


def _persist_state_in_ci():
    """Закоммитить posted.json/failed.json из самого скрипта (только в Actions)."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    import subprocess
    def git(*args):
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
    git("config", "user.name", "utd-autopost")
    git("config", "user.email", "actions@users.noreply.github.com")
    git("add", "posted.json", "failed.json")
    if not git("diff", "--cached", "--quiet").returncode:
        print("[state] нечего коммитить")
        return
    git("commit", "-m", "autopost state (failures)")
    r = git("push")
    print("[state] состояние сохранено" if r.returncode == 0
          else f"[state] push не прошёл: {r.stderr.strip()[:160]}")

if __name__ == "__main__":
    main()
