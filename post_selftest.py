#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Самоперевірка постингу. Нічого не публікує. Ганяти ПІСЛЯ будь-якої своєї зміни.

## Кому це потрібно і чому

Над autopost працюють два чати: технічна зона (норми, черга, тіла запитів до API) —
чат Юрія, доставка креативу (медіа, підписи, формати) — чат Вікторії, право видане
власником 04.09.2026. Обидва зобовʼязані прогнати цей файл після своєї зміни й вкласти
його вивід у нотатку іншому.

🔴 **Чому саме так, а не «я подивився».** Заміряно двома живими випадками:

* 31.08.2026 відсутність теки `media/` поклала **всі 98 записів** черги за один прогін,
  бо норма рахувала успіхи, а не спроби;
* 04.09.2026 у сусідній системі відправник падав 12 прогонів підряд, а звіт показував
  зелене, бо перевірка **компілювала** файл, а не **запускала** його.

Тому тут перевірка не «чи компілюється», а «чи узгоджені між собою типи, поля, підписи,
норми й посилання».

    python3 post_selftest.py           # усе
    python3 post_selftest.py --quiet   # лише вердикт, код 1 при провалі
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
N = [0]


def ok(label, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append((label, detail))
    return cond


def load(p, default):
    fp = os.path.join(HERE, p)
    return json.load(open(fp)) if os.path.exists(fp) else default


def main():
    quiet = "--quiet" in sys.argv
    say = (lambda *a: None) if quiet else print
    say("════ САМОПЕРЕВІРКА ПОСТИНГУ ════\n")

    import run_due as R                     # noqa: F401  (перевіряємо, що імпортується)
    import post_validate as V
    import social_post as S

    sched = load("schedule.json", [])
    posted = set(load("posted.json", {"posted": []}).get("posted", []))

    # ── 1. Кожен тип черги має обробник і платформу ───────────────────────────
    # 🔴 Це та перевірка, якої не було: `run_due` на невідомий kind друкував
    # «! неизвестный kind» і йшов далі — тобто запис МОВЧКИ не публікувався, і в
    # звіті це виглядало як «нічого не було в черзі».
    src = open(os.path.join(HERE, "run_due.py")).read()
    kinds = sorted({str(e.get("kind")) for e in sched})
    known = {"ig_post", "ig_reel", "yt_short", "fb_post", "th_post", "li_post", "tt_post"}
    unknown = [k for k in kinds if k not in known]
    ok("усі типи в черзі мають обробник", not unknown, str(unknown))
    say(f"   {'🟢' if not unknown else '🔴'} типів у черзі: {len(kinds)} "
        f"({', '.join(kinds)}), без обробника: {len(unknown)}")

    missing_h = [k for k in known if f'kind == "{k}"' not in src]
    ok("кожен відомий тип згадується в розгалуженні", not missing_h, str(missing_h))
    missing_p = [k for k in known if f'"{k}":' not in src]
    ok("кожен відомий тип має платформу в PLATFORM", not missing_p, str(missing_p))
    say(f"   {'🟢' if not (missing_h or missing_p) else '🔴'} обробників {len(known)-len(missing_h)}"
        f"/{len(known)}, платформ {len(known)-len(missing_p)}/{len(known)}")

    # ── 2. Норма є для кожної платформи ──────────────────────────────────────
    plats = {"instagram", "youtube", "facebook", "threads", "linkedin", "tiktok"}
    no_daily = [p for p in plats if f'"{p}":' not in src]
    ok("у кожної платформи є добова норма", not no_daily, str(no_daily))
    no_lim = sorted(plats - set(V.LIMITS))
    ok("у кожної платформи є межі у валідаторі", not no_lim, str(no_lim))
    say(f"   {'🟢' if not (no_daily or no_lim) else '🔴'} норм {len(plats)-len(no_daily)}"
        f"/{len(plats)}, меж {len(plats)-len(no_lim)}/{len(plats)}")

    # ── 3. Файли креативу на місці для НЕопублікованих записів ───────────────
    # Перевіряємо лише те, що ще має вийти: у вже опублікованих медіа свідомо прибрано.
    due = [e for e in sched if e["id"] not in posted]
    # 🔴 «Теки media немає взагалі» і «конкретного файла немає» — РІЗНІ відповіді.
    # Перше означає, що це не робоча копія репозиторію (я сам так запустив: витягнув
    # пʼять файлів через API без media/, і перевірка дала 192 «поломки», яких нема —
    # у справжньому репозиторії media/reels має 270 файлів, media/ig 47 тек).
    # Друге — справжня поломка, яка 31.08.2026 поклала всі 98 записів черги.
    # Тому: немає теки — кажу «не перевірено» і не малюю зеленим; є тека, немає файла —
    # це провал.
    has_media = os.path.isdir(os.path.join(HERE, "media"))
    if not has_media:
        say("   ⚪ медіа й підписи НЕ перевірені: теки media/ немає — це не робоча копія")
        say(f"      (незакритих записів у черзі: {len(due)})")
    lost = []
    for e in due if has_media else []:
        if e.get("video"):
            if not os.path.exists(os.path.join(HERE, e["video"])):
                lost.append(f"{e['id']}: немає {e['video']}")
        elif e.get("folder"):
            d = os.path.join(HERE, e["folder"])
            if not (glob.glob(f"{d}/slide_*.jpg") or glob.glob(f"{d}/slide_*.png")):
                lost.append(f"{e['id']}: у {e['folder']} немає слайдів")
        else:
            lost.append(f"{e['id']}: ні video, ні folder")
    if has_media:
        ok("у всіх незакритих записів є медіа", not lost, "; ".join(lost[:6]))
        say(f"   {'🟢' if not lost else '🔴'} незакритих записів: {len(due)}, "
            f"без медіа: {len(lost)}")
    for x in lost[:5]:
        say(f"      · {x}")

    # ── 4. Підпис знаходиться для кожного незакритого запису ─────────────────
    NET = {"ig_post": "caption_ig.txt", "fb_post": "caption_fb.txt",
           "th_post": "caption_th.txt", "li_post": "caption_li.txt",
           "tt_post": "caption_tt.txt", "ig_reel": "caption.txt",
           "yt_short": "caption.txt"}
    nocap = []
    for e in due if has_media else []:
        if e["kind"] == "yt_short":
            mf = os.path.join(HERE, e.get("meta_file", ""))
            if not os.path.exists(mf):
                nocap.append(f"{e['id']}: немає meta_file")
            continue
        try:
            R._caption(HERE, e, NET.get(e["kind"], "caption.txt"), "caption.txt")
        except Exception as ex:
            nocap.append(f"{e['id']}: {str(ex)[:70]}")
    if has_media:
        ok("підпис знаходиться для кожного запису", not nocap, "; ".join(nocap[:6]))
        say(f"   {'🟢' if not nocap else '🔴'} без підпису: {len(nocap)}")
    for x in nocap[:5]:
        say(f"      · {x}")

    # ── 5. Валідатор реально вміє відмовляти ─────────────────────────────────
    # Перевірка, яка не може впасти, не є перевіркою. Підсовую свідомо непридатне.
    bad_ok, bad_pr, _w = V.check_video("/nonexistent.mp4", "instagram", "текст")
    ok("валідатор відмовляє на відсутньому файлі", not bad_ok and bad_pr, str(bad_pr))
    e_ok, e_pr, _ = V.check_video(os.path.join(HERE, "run_due.py"), "instagram", "")
    ok("валідатор ловить порожній підпис", not e_ok, str(e_pr))
    n_ok, n_pr, _ = V.check_video(os.path.join(HERE, "run_due.py"), "нема-такої", "т")
    ok("валідатор відмовляє на невідомій платформі", not n_ok, str(n_pr))
    say(f"   🟢 валідатор відмовляє в трьох свідомо поганих випадках")

    # ── 6. Стандарт форматів усередині меж платформ ──────────────────────────
    bad_fmt = []
    for name, (w, h) in V.FORMATS.items():
        a = w / h
        fits = [p for p, l in V.LIMITS.items() if l["aspect"][0] <= a <= l["aspect"][1]]
        if not fits:
            bad_fmt.append(f"{name} не проходить НІКУДИ")
    ok("кожен формат комплекту приймає хоч одна мережа", not bad_fmt, str(bad_fmt))
    say(f"   🟢 форматів у стандарті: {len(V.FORMATS)}, тривалість "
        f"{V.DURATION[0]}–{V.DURATION[1]} с")

    # ── 7. Токени мереж: читання без побічних дій ────────────────────────────
    if "--no-net" not in sys.argv:
        h = S.token_health()
        for k, v in h.items():
            say(f"   {v.split()[0]} {k}: {' '.join(v.split()[1:])}")
        # 🔴 TikTok у ПАДІННЯ не зараховуємо: його застосунок у Draft, і це дія власника,
        # а не поломка коду. Але й «зеленим» не малюємо — інакше борг стане невидимим.
        dead = [k for k, v in h.items() if v.startswith("🔴") and k != "tiktok"]
        ok("токени мереж живі (крім TikTok, який чекає власника)", not dead, str(dead))

    say("\n" + "═" * 66)
    if FAILS:
        print(f"  🔴 ПРОВАЛІВ: {len(FAILS)} із {N[0]} перевірок")
        for label, detail in FAILS:
            print(f"     · {label}: {detail[:200]}")
        print("  🔴 НЕ ПУБЛІКУВАТИ, поки це не полагоджено.")
        return 1
    print(f"  🟢 усі {N[0]} перевірок пройдені")
    return 0


if __name__ == "__main__":
    sys.exit(main())
