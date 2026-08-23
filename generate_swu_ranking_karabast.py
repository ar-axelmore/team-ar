#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_swu_ranking.py

Genere un classement HTML des archetypes (Leader + Base) Star Wars: Unlimited,
a partir des statistiques de parties Karabast agregees par SWU Stats
(https://www.swustats.net), enrichi avec les couleurs d'aspect des bases et
les icones/editions des leaders via l'API publique swu-db.com
(https://www.swu-db.com/api).

Sources utilisees :
  - Deck Statistics API   : https://www.swustats.net/TCGEngine/Stats/APIs.php
  - Card Search API       : https://www.swu-db.com/api

Utilisation :
    python3 generate_swu_ranking.py
    python3 generate_swu_ranking.py --min-plays 100 --weeks-back 4
    python3 generate_swu_ranking.py --end-week 43 --output swu_ranking.html

IMPORTANT - a propos des numeros de semaine :
    L'API SWU Stats utilise des numeros de semaine absolus (pas des dates).
    Ce script calcule automatiquement la semaine courante a partir d'un point
    d'ancrage verifie manuellement le 19/07/2026 sur la page
    https://www.swustats.net/TCGEngine/Stats/DeckMetaStats.php
    (Wk 43 correspondait alors a la semaine se terminant le 18/07/2026).

    Si le classement produit semble decale (trop de vieux leaders, pas assez
    de decks recents), va verifier les valeurs "Start week" / "End week"
    affichees sur la page ci-dessus et force la bonne semaine avec
    --end-week, puis mets a jour ANCHOR_DATE / ANCHOR_WEEK dans ce fichier
    pour que le calcul automatique reste juste a l'avenir.
"""

import argparse
import csv
import datetime
import html
import io
import json
import sys
import urllib.parse
import urllib.request

DECK_STATS_URL = "https://www.swustats.net/TCGEngine/Stats/DeckMetaStatsAPI.php"
CARD_SEARCH_URL = "https://api.swu-db.com/cards/search"

# Point d'ancrage pour calculer automatiquement la semaine "courante".
# Verifie le 19/07/2026 : Wk 43 = semaine se terminant le 18/07/2026.
ANCHOR_DATE = datetime.date(2026, 7, 18)
ANCHOR_WEEK = 43

ASPECT_COLOR = {
    "Vigilance": "blue",
    "Command": "green",
    "Aggression": "red",
    "Cunning": "yellow",
}
DEFAULT_COLOR = "gray"

COLOR_HEX = {
    "blue": "#3b82c4",
    "red": "#c1443f",
    "yellow": "#d4b23c",
    "green": "#4c9a5b",
    "gray": "#8a8f98",
}

COLOR_LABEL_FR = {
    "blue": "Bleu (Vigilance)",
    "red": "Rouge (Aggression)",
    "yellow": "Jaune (Cunning)",
    "green": "Vert (Command)",
    "gray": "Gris (Neutre / multi-aspect)",
}


# ---------------------------------------------------------------------------
# Recuperation des donnees
# ---------------------------------------------------------------------------

def _http_get(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "swu-ranking-script/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def current_end_week(override=None):
    """Determine le numero de semaine 'courant' (fin de fenetre)."""
    if override is not None:
        return override
    today = datetime.date.today()
    delta_weeks = (today - ANCHOR_DATE).days // 7
    return ANCHOR_WEEK + delta_weeks


def fetch_deck_stats(start_week, end_week, fmt="premier"):
    """Recupere les stats d'archetypes (Leader+Base) depuis SWU Stats."""
    raw = _http_get(DECK_STATS_URL, {
        "format": fmt,
        "consolidate": 1,
        "startWeek": start_week,
        "endWeek": end_week,
    })
    return json.loads(raw)


def fetch_base_colors():
    """Retourne {nom de base: couleur} en interrogeant swu-db.com."""
    try:
        raw = _http_get(CARD_SEARCH_URL, {"q": "type:Base", "format": "json"})
        payload = json.loads(raw)
        cards = payload.get("data", [])
    except Exception as exc:  # reseau indisponible, API en panne, etc.
        print(f"Attention: impossible de recuperer les couleurs de base ({exc}). "
              f"Toutes les bases seront affichees en gris.", file=sys.stderr)
        return {}

    colors = {}
    for card in cards:
        name = card.get("Name")
        aspects = card.get("Aspects") or []
        if not name:
            continue
        if len(aspects) == 1:
            colors[name] = ASPECT_COLOR.get(aspects[0], DEFAULT_COLOR)
        else:
            colors[name] = DEFAULT_COLOR
    return colors


def fetch_leader_info():
    """Retourne {(Name, Subtitle): {"set": ..., "art": ...}} depuis swu-db.com.

    Utilise le format CSV (plus compact que le JSON pretty-print pour ~150+
    leaders) puis le parse avec le module csv standard.
    """
    try:
        raw = _http_get(CARD_SEARCH_URL, {"q": "type:Leader", "format": "csv"})
    except Exception as exc:
        print(f"Attention: impossible de recuperer les infos leaders ({exc}). "
              f"Les icones/editions seront omises.", file=sys.stderr)
        return {}

    info = {}
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        name = row.get("Name")
        subtitle = row.get("Subtitle")
        if not name:
            continue
        info[(name, subtitle or "")] = {
            "set": row.get("Set", ""),
            "art": row.get("FrontArt", ""),
        }
    return info


# ---------------------------------------------------------------------------
# Construction du classement
# ---------------------------------------------------------------------------

def build_ranking(decks, base_colors, leader_info, min_plays=100):
    rows = []
    for d in decks:
        try:
            num_plays = int(d.get("numPlays", 0))
            win_rate = float(d.get("winRate", 0))
        except (TypeError, ValueError):
            continue
        if num_plays <= min_plays:
            continue

        leader = d.get("leaderTitle", "") or ""
        leader_sub = d.get("leaderSubtitle", "") or ""
        base = d.get("baseTitle", "") or ""
        base_sub = d.get("baseSubtitle", "") or ""

        linfo = leader_info.get((leader, leader_sub), {})

        rows.append({
            "leader": leader,
            "leader_sub": leader_sub,
            "leader_set": linfo.get("set", ""),
            "leader_art": linfo.get("art", ""),
            "base": base,
            "base_sub": base_sub,
            "color": base_colors.get(base, DEFAULT_COLOR),
            "num_plays": num_plays,
            "win_rate": win_rate,
        })

    rows.sort(key=lambda r: r["win_rate"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Rendu HTML
# ---------------------------------------------------------------------------

def render_html(rows, start_week, end_week, min_plays, generated_at, fmt="premier"):
    def esc(s):
        return html.escape(str(s))

    table_rows = []
    for i, r in enumerate(rows, start=1):
        base_label = esc(r["base"])
        if r["base_sub"]:
            base_label += f" <span class='sub'>({esc(r['base_sub'])})</span>"

        if r["leader_art"]:
            icon_html = f'<span class="icon" style="background-image:url(\'{esc(r["leader_art"])}\')"></span>'
        else:
            icon_html = '<span class="icon icon-empty"></span>'

        set_label = esc(r["leader_set"]) if r["leader_set"] else "?"

        table_rows.append(f"""
        <tr>
          <td class="rank">{i}</td>
          <td class="leader">
            {icon_html}
            <span class="leader-text">{esc(r['leader'])} <span class="sub">— {esc(r['leader_sub'])}</span></span>
          </td>
          <td class="set"><span class="set-badge">{set_label}</span></td>
          <td class="base">
            <span class="dot" style="background:{COLOR_HEX[r['color']]}" title="{esc(COLOR_LABEL_FR[r['color']])}"></span>
            {base_label}
          </td>
          <td class="num">{r['num_plays']}</td>
          <td class="num winrate">{r['win_rate']:.2f}%</td>
        </tr>""")

    legend_items = "".join(
        f'<span class="legend-item"><span class="dot" style="background:{COLOR_HEX[c]}"></span>{COLOR_LABEL_FR[c]}</span>'
        for c in ["blue", "green", "red", "yellow", "gray"]
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Classement SWU — Karabast {fmt.capitalize()} (semaines {start_week}-{end_week})</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    background: #0f1216;
    color: #e6e8eb;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 32px;
  }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .meta {{ color: #9aa1ab; font-size: 13px; margin-bottom: 20px; }}
  .meta a {{ color: #7fa8d3; }}
  .legend {{
    display: flex; gap: 16px; flex-wrap: wrap;
    margin-bottom: 20px; font-size: 13px; color: #c3c8cf;
  }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
  .dot {{
    display: inline-block; width: 10px; height: 10px;
    border-radius: 50%; flex-shrink: 0;
  }}
  table {{ border-collapse: collapse; width: 100%; max-width: 1080px; }}
  th, td {{
    text-align: left; padding: 8px 12px;
    border-bottom: 1px solid #24282f; font-size: 14px; vertical-align: middle;
  }}
  th {{
    color: #9aa1ab; font-weight: 600; text-transform: uppercase;
    font-size: 11px; letter-spacing: 0.04em;
  }}
  td.rank {{ color: #6b7280; width: 32px; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.winrate {{ font-weight: 600; color: #7fd39a; }}
  td.leader {{ display: flex; align-items: center; gap: 10px; }}
  .leader-text {{ display: inline-block; }}
  .icon {{
    display: inline-block; width: 28px; height: 28px; border-radius: 50%;
    background-size: cover; background-position: center top;
    background-color: #1c2027; border: 1px solid #2c313a; flex-shrink: 0;
  }}
  .icon-empty {{ background: #1c2027; }}
  .set-badge {{
    display: inline-block; padding: 2px 7px; border-radius: 4px;
    background: #1c2027; border: 1px solid #2c313a;
    font-size: 11px; font-weight: 600; letter-spacing: 0.03em; color: #c3c8cf;
  }}
  .sub {{ color: #8a8f98; font-size: 12px; }}
  tr:hover {{ background: #171b21; }}
</style>
</head>
<body>
  <h1>Classement Star Wars: Unlimited — {fmt.capitalize()} (Karabast)</h1>
  <div class="meta">
    Semaines {start_week} à {end_week} (SWU Stats) · Decks avec plus de {min_plays} parties ·
    Généré le {esc(generated_at)} ·
    Source : <a href="https://www.swustats.net/TCGEngine/Stats/DeckMetaStats.php">swustats.net</a> +
    <a href="https://www.swu-db.com/">swu-db.com</a>
  </div>
  <div class="legend">{legend_items}</div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Leader</th><th>Édition</th><th>Base</th>
        <th style="text-align:right">Parties</th><th style="text-align:right">Win rate</th>
      </tr>
    </thead>
    <tbody>
      {"".join(table_rows)}
    </tbody>
  </table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Classement SWU par win rate (SWU Stats / Karabast, format Premier par defaut)."
    )
    parser.add_argument("--min-plays", type=int, default=100,
                         help="Seuil minimum de parties jouees, strictement superieur. Defaut: 100.")
    parser.add_argument("--weeks-back", type=int, default=4,
                         help="Nombre de semaines a inclure (fenetre glissante). Defaut: 4.")
    parser.add_argument("--end-week", type=int, default=None,
                         help="Force le numero de semaine final (a verifier sur DeckMetaStats.php). "
                              "Par defaut, calcule automatiquement depuis ANCHOR_DATE/ANCHOR_WEEK.")
    parser.add_argument("--format", default="premier", choices=["premier", "eternal", "twinsuns"],
                         help="Format de jeu. Defaut: premier.")
    parser.add_argument("--output", default="swu_ranking.html",
                         help="Nom du fichier HTML de sortie.")
    args = parser.parse_args()

    end_week = current_end_week(args.end_week)
    start_week = end_week - (args.weeks_back - 1)

    print(f"Recuperation des donnees SWU Stats (semaines {start_week} a {end_week}, "
          f"format={args.format})...")
    decks = fetch_deck_stats(start_week, end_week, args.format)

    print("Recuperation des couleurs de base (swu-db.com)...")
    base_colors = fetch_base_colors()

    print("Recuperation des icones/editions de leaders (swu-db.com)...")
    leader_info = fetch_leader_info()

    rows = build_ranking(decks, base_colors, leader_info, min_plays=args.min_plays)
    print(f"{len(rows)} archetypes retenus (>{args.min_plays} parties) sur {len(decks)} au total.")

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    output_html = render_html(rows, start_week, end_week, args.min_plays, generated_at, args.format)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output_html)
    print(f"Fichier genere : {args.output}")


if __name__ == "__main__":
    main()
