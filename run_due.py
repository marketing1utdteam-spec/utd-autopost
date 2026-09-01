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

def env_int(name, default):
    """Ціле з оточення, де ПОРОЖНІЙ рядок теж означає «не задано».

    🔴 Заміряно 01.09.2026: воркфлоу передає MAX_PER_RUN: ${{ inputs.max_per_run }}, і на
    прогоні ЗА РОЗКЛАДОМ inputs порожні. Тобто змінна існує й дорівнює ''. А
    os.environ.get(name, default) віддає саме '' — типове значення застосовується лише коли
    ключа НЕМА взагалі. Через це int('') валив кожен розкладний прогін, і пости не виходили,
    хоча ручні запуски працювали.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"   🟡 {name}={raw!r} не число, беру {default}")
        return default

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
    MAX_ATTEMPTS = env_int("MAX_ATTEMPTS", 5)

    # ── Суточные нормы ПО ПЛАТФОРМАМ ──────────────────────────────────────
    # Одного общего числа мало: у площадок разные пределы и разная терпимость.
    # Instagram у нас 105 постов за всё время и 1116 подписчиков — четыре-восемь
    # публикаций в сутки на таком аккаунте читаются как спам, хотя API их примет
    # (лимит Graph API — 25 за 24 часа). YouTube Shorts переносит больше: квота
    # 10000 единиц, videos.insert ~1600, то есть около 6 загрузок в сутки.
    # Facebook посередине.
    #
    # Считаем по ФАКТИЧЕСКОЙ дате публикации, а не по дате из плана: id записи
    # содержит дату расписания, и при сливе долга за 12 дней все они «июльские».
    # Поэтому ведём отдельный журнал posted_at.json.
    DAILY = {"instagram": env_int("DAILY_IG", 2),
             "youtube":   env_int("DAILY_YT", 4),
             "facebook":  env_int("DAILY_FB", 3)}
    PLATFORM = {"ig_post": "instagram", "ig_reel": "instagram",
                "yt_short": "youtube", "fb_post": "facebook"}

    at_path = os.path.join(HERE, "posted_at.json")
    posted_at = load("posted_at.json", {})
    used = {k: 0 for k in DAILY}
    for pid, day in posted_at.items():
        if day != today:
            continue
        kind = next((e["kind"] for e in sched if e["id"] == pid), None)
        plat = PLATFORM.get(kind)
        if plat:
            used[plat] += 1
    print(f"   сегодня уже опубликовано: " +
          ", ".join(f"{k} {used[k]}/{DAILY[k]}" for k in DAILY))

    # Норма на один прогон. Без неё накопившаяся очередь выкладывается целиком:
    # на 2026-08-31 просрочено 98 записей с 25 июля, и включение флоу без лимита
    # означало бы 98 публикаций подряд — верный способ получить блокировку.
    # Прогонов 4 в сутки, поэтому 2 за прогон = до 8 в сутки.
    MAX_PER_RUN = env_int("MAX_PER_RUN", 2)
    # YouTube: квота 10000 единиц в сутки, videos.insert стоит ~1600, то есть
    # около 6 загрузок. Держим 1 за прогон = максимум 4 в сутки, с запасом.
    MAX_YT_PER_RUN = env_int("MAX_YT_PER_RUN", 1)

    # Очередь сливаем ПО ДАТЕ, от самых старых. Порядок в schedule.json не
    # гарантирован, а долг должен уходить хронологически, иначе июльские записи
    # будут вечно ждать за августовскими.
    queue = sorted((e for e in sched if e["date"] <= today and e["id"] not in posted),
                   key=lambda e: (e["date"], e["id"]))

    did, failed_now, quarantined = [], [], []
    done_run, done_yt, tried = 0, 0, 0
    skipped_by_cap = skipped_by_day = 0
    for e in queue:
        if fails.get(e["id"], 0) >= MAX_ATTEMPTS:
            quarantined.append(e["id"])
            continue
        # 🔴 Норма считает ПОПЫТКИ, а не успехи. Иначе прогон, в котором всё падает
        # (сломанные креды, пропавший файл), проходит всю очередь целиком и жжёт
        # счётчики попыток на всех записях сразу — пять таких прогонов, и вся
        # очередь уходит в карантин. Найдено тестом 31.08.2026, где из-за
        # отсутствия media/ упали все 98 записей за один прогон.
        if tried >= MAX_PER_RUN:
            skipped_by_cap += 1
            continue
        if e["kind"] == "yt_short" and done_yt >= MAX_YT_PER_RUN:
            skipped_by_cap += 1
            continue
        plat = PLATFORM.get(e["kind"])
        if plat and used[plat] >= DAILY[plat]:
            skipped_by_day += 1
            continue
        tried += 1
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
            failed_now.append((e["id"], kind, str(ex)[:300]))
            left = MAX_ATTEMPTS - n
            tail = (f"попытка {n}/{MAX_ATTEMPTS}, осталось {left}" if left > 0
                    else f"попытка {n}/{MAX_ATTEMPTS} — УХОДИТ В КАРАНТИН, чинить руками")
            print(f"  ❌ ОШИБКА на {e['id']}: {ex}  — {tail}")
            continue
        if not a.dry_run:
            did.append(e["id"])
            done_run += 1
            if e["kind"] == "yt_short":
                done_yt += 1
            plat = PLATFORM.get(e["kind"])
            if plat:
                used[plat] += 1
            posted_at[e["id"]] = today
            json.dump(posted_at, open(at_path, "w"), ensure_ascii=False, indent=1)
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

    if skipped_by_day:
        print(f"\n📅 отложено СУТОЧНОЙ нормой площадки: {skipped_by_day} " +
              "(" + ", ".join(f"{k} {used[k]}/{DAILY[k]}" for k in DAILY) + ")")
    if skipped_by_cap:
        print(f"\n⏸ отложено нормой на этот прогон: {skipped_by_cap} "
              f"(MAX_PER_RUN={MAX_PER_RUN}, MAX_YT_PER_RUN={MAX_YT_PER_RUN})")
    print(f"== done · опубликовано {len(did)} · упало {len(failed_now)} · "
          f"в карантине {len(quarantined)} · отложено {skipped_by_cap}")

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
    git("add", "posted.json", "posted_at.json", "failed.json")
    if not git("diff", "--cached", "--quiet").returncode:
        print("[state] нечего коммитить")
        return
    git("commit", "-m", "autopost state (failures)")
    # Пуш без перебазирования отвергается каждый раз, когда main ушёл вперёд
    # (соседний прогон, коммит стейта прошлого запуска, ручная правка), а тогда
    # счётчик попыток в failed.json не сохраняется и карантин не срабатывает
    # никогда: именно так пять записей yt_short четверо суток печатали
    # «попытка 5/5 — уходит в карантин» и оставались в очереди.
    for attempt in range(1, 4):
        r = git("push")
        if r.returncode == 0:
            print("[state] состояние сохранено")
            return
        if attempt == 3:
            break
        git("fetch", "origin", "main")
        rb = git("rebase", "origin/main")
        if rb.returncode != 0:
            git("rebase", "--abort")
            print(f"[state] rebase не прошёл: {rb.stderr.strip()[:160]}")
            break
        print(f"[state] push отвергнут, перебазировался на origin/main, попытка {attempt + 1} из 3")
    print(f"[state] push не прошёл: {r.stderr.strip()[:160]}")

if __name__ == "__main__":
    main()
