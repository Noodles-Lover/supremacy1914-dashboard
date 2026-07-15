# -*- coding: utf-8 -*-
"""Supremacy 1914 — 多對局 / 多日戰況面板 (v9.5, 繁體中文, 作戰指揮室風格).

讀取 games/{gameID}/data/day_{N}.json（按「對局」分資料夾、按「遊戲日」儲存，非真實日），
將所有對局與天數內嵌進 JS，提供「對局切換器」+「遊戲日切換器」。
"""
import json
import os
import sys
import glob
import re

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
GAMES_DIR = os.path.join(BASE, "games")
MY_ID = int(os.environ.get("MY_ID", 22))
TOP = 15
TOP_KDA = 10


def fix_alpha(c, a):
    if not c:
        return "rgba(150,150,150,1)"
    if "255)" in c:
        return c.replace("255)", f"{a})")
    if c.startswith("rgb(") and not c.startswith("rgba("):
        return c[:-1] + f",{a})"
    return c


def load_day(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_meta(gid):
    p = os.path.join(GAMES_DIR, gid, "meta.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def pid_nationname(player_lookup, pid):
    p = player_lookup.get(pid)
    if p:
        return f'{p["nation"]} ({p["name"]})'
    return f"玩家 {pid}"


def get_province_counts(day_data):
    """回傳 {str(playerID): 領地數}。被消滅（領地=0）的玩家不會出現在鍵中。"""
    return {str(k): v for k, v in day_data.get("provinceCounts", {}).items()}


def build_payload(day_data, my_id=None, prev_provinces=None, prev_relations=None):
    my_id = my_id if my_id is not None else MY_ID
    players = day_data.get("players", [])
    player_lookup = {p["id"]: p for p in players}
    stats_src = day_data.get("playerStats", {})
    relations = day_data.get("relations", {})
    coalitions = day_data.get("coalitions", [])
    scores = {str(k): v for k, v in day_data.get("scores", {}).items()}
    province_counts = get_province_counts(day_data)
    # 存活判斷：前一天領地數 > 0 才續留資料列表。
    # 無前一天（首份快照）時改以當日領地判斷。被消滅（領地=0）玩家直接剔除，
    # 不進任何統計（戰力排行、領土、趨勢、聯盟增幅、全部玩家表皆忽略該國）。
    prev_pc = prev_provinces if prev_provinces is not None else province_counts
    def is_alive(pid):
        return prev_pc.get(str(pid), 0) > 0

    team_to_name = {c["teamID"]: c["name"] for c in coalitions}
    team_to_score = {c["teamID"]: c["score"] for c in coalitions}
    team_to_members = {c["teamID"]: c["memberIDs"] for c in coalitions}
    team_to_color = {c["teamID"]: c["primaryColor"] for c in coalitions}

    def team_label(tid):
        if not tid:
            return None
        return team_to_name.get(tid, f"聯盟 #{tid}")

    def get_stats(pid):
        s = stats_src.get(str(pid), {})
        return {
            "kills": s.get("unit2killed", 0),
            "losses": s.get("unit2lost", 0),
            "captured": s.get("provincesCaptured", 0),
            "lost": s.get("provincesLost", 0),
        }

    def kda_val(pid):
        s = get_stats(pid)
        return round(s["kills"] / max(s["losses"], 1), 2)

    def get_provinces(pid):
        return province_counts.get(str(pid), 0)

    def get_score(pid):
        return scores.get(str(pid), 0)

    def player_row(p):
        s = get_stats(p["id"])
        allies, enemies = [], []
        rels = relations.get("neighborRelations", {}).get(str(p["id"]), {})
        # 前一天外交關係：用於標註「本日新成為敵對」的玩家（上一天非敵對、本日敵對 → 粗體）
        prev_rels = {}
        if prev_relations:
            prev_rels = prev_relations.get("neighborRelations", {}).get(str(p["id"]), {})
        for trg, rt in rels.items():
            t = player_lookup.get(int(trg))
            if not t or int(trg) == p["id"]:
                continue
            if t.get("ai"):   # 跳過非人類（AI）玩家，外交關係只列人類
                continue
            # 去除已亡國玩家：當日領地數為 0 者不列於任何外交關係
            if province_counts.get(str(int(trg)), 0) <= 0:
                continue
            if rt == 4:
                allies.append({"id": t["id"], "nation": t["nation"], "name": t["name"]})
            elif rt == -2:
                was_enemy = prev_rels.get(str(trg)) == -2
                enemies.append({"id": t["id"], "nation": t["nation"], "name": t["name"], "isNew": not was_enemy})
        return {
            "id": p["id"], "name": p["name"], "nation": p["nation"], "team": p["team"],
            "score": get_score(p["id"]),
            "kills": s["kills"], "losses": s["losses"], "kda": kda_val(p["id"]),
            "captured": s["captured"], "lost": s["lost"], "provinces": get_provinces(p["id"]),
            "allies": allies, "enemies": enemies,
        }

    all_human = [player_row(p) for p in players if not p["ai"] and p["id"] != 0 and is_alive(p["id"])]
    all_human.sort(key=lambda r: r["score"], reverse=True)
    me = player_lookup.get(my_id)
    me = player_row(me) if me else player_row(all_human[0])

    my_ally_ids = {a["id"] for a in me["allies"]}
    my_allies = [r for r in all_human if r["id"] in my_ally_ids]
    my_allies.sort(key=lambda r: r["score"], reverse=True)
    for a in my_allies:
        a["enemy_display"] = [{"nation": x["nation"], "name": x["name"], "isNew": x.get("isNew", False)} for x in a["enemies"]]

    # ── charts data ──
    by_kda = sorted(all_human, key=lambda r: r["kda"], reverse=True)[:TOP_KDA]
    kda_labels = [f"{r['nation']} ({r['name']})" for r in by_kda]

    top5_kills = sorted(all_human, key=lambda r: r["kills"], reverse=True)[:5]
    top5_losses = sorted(all_human, key=lambda r: r["losses"], reverse=True)[:5]

    by_provinces = sorted([r for r in all_human if r["provinces"] > 0], key=lambda r: r["provinces"], reverse=True)[:TOP]
    prov_labels = [f"{r['nation']} ({r['name']})" for r in by_provinces]
    prov_vals = [r["provinces"] for r in by_provinces]

    coal_sorted = sorted(coalitions, key=lambda c: c["score"], reverse=True)
    coal_labels = [c["name"] for c in coal_sorted]
    coal_scores = [c["score"] for c in coal_sorted]
    coal_colors = [fix_alpha(c["primaryColor"], 0.82) for c in coal_sorted]
    coal_solid = [fix_alpha(c["primaryColor"], 1) for c in coal_sorted]

    by_score = sorted(all_human, key=lambda r: r["score"], reverse=True)[:TOP]
    score_labels = [f"{r['nation']} ({r['name']})" for r in by_score]
    score_vals = [r["score"] for r in by_score]

    # ── coalition detail (for JS) ──
    coal_detail = []
    for c in coal_sorted:
        is_mine = c["teamID"] == me["team"]
        members_s = ", ".join([pid_nationname(player_lookup, m) for m in c["memberIDs"]]) or "—"
        coal_detail.append({
            "name": c["name"], "score": c["score"],
            "solid": fix_alpha(c["primaryColor"], 1), "isMine": is_mine,
            "memberCount": len(c["memberIDs"]), "members": members_s,
        })

    # ── full table rows (for JS sortable) ──
    def kda_cls(v):
        return "kda-g" if v >= 2 else ("kda-o" if v >= 1 else "kda-b")

    table_rows = []
    for r in all_human:
        table_rows.append({
            "id": r["id"], "name": r["name"], "nation": r["nation"],
            "teamLabel": team_label(r["team"]),
            "score": r["score"], "kills": r["kills"], "losses": r["losses"],
            "kda": r["kda"], "kdaCls": kda_cls(r["kda"]),
            "captured": r["captured"], "lost": r["lost"], "provinces": r["provinces"],
            "enemies": [{"nation": e["nation"], "name": e["name"], "isNew": e.get("isNew", False)} for e in r["enemies"]],
            "isMe": r["id"] == my_id,
        })

    # ── 亡國名單：前一天領地 > 0，本日領地歸零（或已不在領地統計中）的人類玩家 ──
    defeated = []
    if prev_provinces is not None:
        for pid, cnt in prev_provinces.items():
            if cnt > 0 and province_counts.get(str(pid), 0) <= 0:
                p = player_lookup.get(int(pid))
                if p and not p.get("ai") and p["id"] != 0:
                    defeated.append({"id": p["id"], "name": p["name"], "nation": p["nation"]})

    payload = {
        "meta": {
            "day": day_data.get("day"),
            "vp": day_data.get("victoryPoints"),
            "playerCount": len(all_human),
            "reportedAt": day_data.get("reportedAt"),
        },
        "me": {
            "id": me["id"], "name": me["name"], "nation": me["nation"],
            "coalition": team_label(me["team"]),
            "score": me["score"], "kills": me["kills"], "losses": me["losses"],
            "kda": me["kda"], "captured": me["captured"], "lost": me["lost"],
            "provinces": me["provinces"],
            "allies": [{"nation": a["nation"], "name": a["name"]} for a in me["allies"]],
            "enemies": [{"nation": e["nation"], "name": e["name"], "isNew": e.get("isNew", False)} for e in me["enemies"]],
        },
        "allies": [
            {"name": a["name"], "nation": a["nation"], "score": a["score"], "kills": a["kills"],
             "losses": a["losses"], "kda": a["kda"], "kdaCls": kda_cls(a["kda"]),
             "captured": a["captured"], "lost": a["lost"], "provinces": a["provinces"],
             "enemyDisplay": a["enemy_display"]}
            for a in my_allies
        ],
        "charts": {
            "kda": {"labels": kda_labels, "kills": [r["kills"] for r in by_kda], "losses": [r["losses"] for r in by_kda]},
            "prov": {"labels": prov_labels, "vals": prov_vals},
            "coal": {"labels": coal_labels, "scores": coal_scores, "colors": coal_colors, "solid": coal_solid},
            "score": {"labels": score_labels, "vals": score_vals},
        },
        "top5Kills": [{"name": r["name"], "nation": r["nation"], "val": r["kills"]} for r in top5_kills],
        "top5Losses": [{"name": r["name"], "nation": r["nation"], "val": r["losses"]} for r in top5_losses],
        "coalitions": coal_detail,
        "tableRows": table_rows,
        "defeated": defeated,
    }
    return payload


# ── 渲染模板（共用）──
def render_template(games, gorder, my_ids, extra_json="null"):
    games_json = json.dumps(games, ensure_ascii=False)
    gorder_json = json.dumps(gorder)
    return (TEMPLATE
            .replace("__GAMES_JSON__", games_json)
            .replace("__GAME_ORDER_JSON__", gorder_json)
            .replace("__MY_IDS_JSON__", json.dumps(my_ids, ensure_ascii=False))
            .replace("__EXTRA_JSON__", extra_json))


# ── 全量建構：讀取所有對局 / 遊戲日基準檔，產生主面板 ──
def build_all():
    GAMES = {}
    GAME_ORDER = []
    for game_dir in sorted(glob.glob(os.path.join(GAMES_DIR, "*"))):
        gid = os.path.basename(game_dir)
        # 僅納入「當日首次報告」的基準檔 day_{N}.json；
        # 同日額外報告 day_{N}_{時間戳}.json 不進趨勢/變化，故排除。
        day_files = sorted(
            f for f in glob.glob(os.path.join(game_dir, "data", "day_*.json"))
            if re.match(r"day_\d+\.json$", os.path.basename(f))
        )
        if not day_files:
            continue
        meta = load_meta(gid)
        my_id = meta.get("myID", int(os.environ.get("MY_ID", 22)))
        days = {}
        order = []
        prev_pc = None
        prev_rel = None
        for df in day_files:
            dd = load_day(df)
            day_num = dd.get("day")
            if day_num is None:
                continue
            days[str(day_num)] = build_payload(dd, my_id, prev_provinces=prev_pc, prev_relations=prev_rel)
            prev_pc = get_province_counts(dd)
            prev_rel = dd.get("relations")
            order.append(day_num)
        if not order:
            continue
        order.sort()
        GAMES[gid] = {"gameID": gid, "days": days, "order": order, "myID": my_id}

    # 對局排序：依 gameID 數值升序（穩定、可預期）
    def _gid_key(g):
        return int(g) if g.isdigit() else g
    GAME_ORDER = sorted(GAMES.keys(), key=_gid_key)
    MY_IDS = {gid: GAMES[gid].get("myID", 22) for gid in GAMES}

    out_path = os.path.join(BASE, "supremacy1914_dashboard.html")
    if not GAMES:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='UTF-8'>"
                    "<title>尚無資料</title></head><body style='background:#0c0f16;color:#e7e9ee;"
                    "font-family:sans-serif;padding:48px'><h1>尚無對局資料</h1>"
                    "<p>請先執行 <code>python extract_day.py</code> 擷取遊戲數據。</p></body></html>")
        print("[WARN] 找不到任何 games/*/data/day_*.json，僅輸出空白提示頁。")
        return

    html = render_template(GAMES, GAME_ORDER, MY_IDS, "null")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] {out_path} ({os.path.getsize(out_path)/1024:.1f} KB)")
    print(f"  Games available: {GAME_ORDER}")
    for gid in GAME_ORDER:
        g = GAMES[gid]
        print(f"   對局 {gid}: 天數={g['order']} · 最新日玩家數={g['days'][str(g['order'][-1])]['meta']['playerCount']}")


# ── 單檔建構：針對某一份快照（含額外報告）產生獨立可檢視 HTML ──
def build_single(path):
    if not os.path.exists(path):
        print(f"[ERR] 找不到資料檔：{path}")
        sys.exit(1)
    day_data = load_day(path)
    day = day_data.get("day")
    if day is None:
        print("[ERR] 資料檔缺少 day 欄位，無法渲染。")
        sys.exit(1)

    # 由路徑推導對局編號：games/<gid>/data/day_*.json
    data_dir = os.path.dirname(os.path.abspath(path))
    game_dir = os.path.dirname(data_dir)
    gid = os.path.basename(game_dir)
    meta = load_meta(gid)
    my_id = meta.get("myID", int(os.environ.get("MY_ID", 22)))
    # 單檔快照：嘗試載入同對局前一個基準日，套用「前一天領地=0 則移除」規則
    prev_pc = None
    prev_rel = None
    try:
        all_df = sorted(glob.glob(os.path.join(game_dir, "data", "day_*.json")),
                        key=lambda x: int(re.match(r"day_(\d+)", os.path.basename(x)).group(1)))
        for f in reversed(all_df):
            if not re.match(r"day_\d+\.json$", os.path.basename(f)):
                continue
            fd = load_day(f)
            if fd.get("day") == day - 1:
                prev_pc = get_province_counts(fd)
                prev_rel = fd.get("relations")
                break
    except Exception:
        prev_pc = None
        prev_rel = None
    payload = build_payload(day_data, my_id, prev_provinces=prev_pc, prev_relations=prev_rel)

    games = {gid: {"gameID": gid, "days": {str(day): payload}, "order": [day], "myID": my_id}}
    gorder = [gid]
    my_ids = {gid: my_id}

    # 額外報告（同日加時間戳者）標註資訊，改由前端 JS 依語言渲染（i18n）
    reported = day_data.get("reportedAt") or "時間未記錄"
    ts_disp = (reported.replace("T", " ").replace("+08:00", " (GMT+8)")
               if reported != "時間未記錄" else "時間未記錄")
    is_extra = re.match(r"day_\d+_\d{8}_\d{6}\.json$", os.path.basename(path)) is not None
    extra_json = json.dumps({"day": day, "ts": ts_disp}, ensure_ascii=False) if is_extra else "null"

    html = render_template(games, gorder, my_ids, extra_json)
    out_path = re.sub(r"\.json$", ".html", path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 獨立快照 {out_path} ({os.path.getsize(out_path)/1024:.1f} KB)  [對局 {gid} · 遊戲日 {day}]")


def main():
    if "--single" in sys.argv:
        idx = sys.argv.index("--single")
        if idx + 1 >= len(sys.argv):
            print("[ERR] --single 需要接一個資料檔路徑")
            sys.exit(1)
        build_single(sys.argv[idx + 1])
    else:
        build_all()


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Supremacy 1914 · 戰況面板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0c0f16;
  --surface:rgba(255,255,255,0.05);
  --surface-2:rgba(255,255,255,0.09);
  --border:rgba(255,255,255,0.15);
  --border-strong:rgba(255,255,255,0.26);
  --text:#f1f3f8;
  --dim:#9aa3b6;
  --accent:#e6ad5e;
  --accent-soft:rgba(230,173,94,0.16);
  --green:#46c477;
  --red:#f2605d;
  --gold:#edc96f;
  --shadow:0 18px 48px -24px rgba(0,0,0,0.85);
}
*{margin:0;padding:0;box-sizing:border-box;}
html{-webkit-font-smoothing:antialiased;scroll-behavior:smooth;}
body{
  font-family:"Noto Sans TC","Sora",system-ui,sans-serif;
  background:var(--bg); color:var(--text); min-height:100vh;
  background-image:
    radial-gradient(120% 80% at 50% -12%, rgba(224,168,90,0.06), transparent 60%),
    radial-gradient(90% 50% at 100% 110%, rgba(63,185,104,0.025), transparent 55%);
  background-attachment:fixed;
}
.container{max-width:1280px;margin:0 auto;padding:34px 26px 60px;}
h1,h2,h3{font-family:"Sora",sans-serif;}

/* header */
header{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:16px 24px;margin-bottom:14px;}
.brand{flex:1 1 340px;min-width:0;}
.brand h1{font-size:1.85rem;font-weight:800;letter-spacing:-0.5px;}
.brand h1 span{color:var(--accent);}
.brand .sub{color:var(--dim);font-size:0.85rem;margin-top:6px;letter-spacing:0.3px;max-width:100%;overflow-wrap:anywhere;}
.day-control{display:flex;align-items:center;gap:12px;min-width:0;}
.controls{display:flex;flex-direction:column;gap:11px;align-items:flex-end;flex:0 0 auto;min-width:0;}
.day-label{font-size:0.78rem;color:var(--dim);letter-spacing:2px;text-transform:uppercase;}
.day-pills{display:flex;gap:6px;flex-wrap:nowrap;overflow-x:auto;max-width:min(60vw,600px);min-width:0;padding-bottom:6px;scrollbar-width:thin;scrollbar-color:var(--border-strong) transparent;}
.day-pills::-webkit-scrollbar{height:6px;}
.day-pills::-webkit-scrollbar-track{background:transparent;}
.day-pills::-webkit-scrollbar-thumb{background:var(--border-strong);border-radius:3px;}
.day-pill{
  padding:9px 17px;border-radius:12px;border:1px solid var(--border);
  background:var(--surface);color:var(--dim);font-family:"Sora";font-weight:700;
  font-size:0.95rem;cursor:pointer;font-variant-numeric:tabular-nums;
  transition:all .35s cubic-bezier(.16,1,.3,1);
}
.day-pill:hover{color:var(--text);border-color:var(--border-strong);}
.day-pill.active{background:var(--accent);color:#1a1206;border-color:var(--accent);box-shadow:0 8px 22px -8px var(--accent);}

/* language switch */
.lang-switch{display:flex;align-items:stretch;border:1px solid var(--border);border-radius:11px;overflow:hidden;background:var(--surface);}
.lang-switch button{background:none;border:none;color:var(--dim);font-family:"Sora";font-weight:700;font-size:0.8rem;padding:8px 15px;cursor:pointer;transition:all .3s cubic-bezier(.16,1,.3,1);white-space:nowrap;}
.lang-switch button:hover{color:var(--text);}
.lang-switch button.active{background:var(--accent);color:#1a1206;}

/* zone */
.zone{margin-top:42px;}
.zone-head{display:flex;align-items:center;gap:12px;margin-bottom:22px;padding-bottom:12px;border-bottom:1px solid var(--border);}
.zone-head h2{font-size:1.12rem;font-weight:700;letter-spacing:0.5px;}
.zone-head .dot{width:9px;height:9px;border-radius:50%;}
.zone-head .dot.self{background:var(--accent);box-shadow:0 0 12px var(--accent);}
.zone-head .dot.gold{background:var(--gold);box-shadow:0 0 12px var(--gold);}
.zone-head .meta{margin-left:auto;color:var(--dim);font-size:0.8rem;}

/* card */
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:18px;
  backdrop-filter:blur(18px) saturate(120%);box-shadow:inset 0 1px 0 rgba(255,255,255,0.05),var(--shadow);
  padding:22px;
  transition:border-color .35s,box-shadow .35s;
}
.card:hover{border-color:var(--border-strong);box-shadow:inset 0 1px 0 rgba(255,255,255,0.07),var(--shadow);}
.card h3{font-size:0.78rem;letter-spacing:1.6px;color:var(--dim);margin-bottom:18px;font-weight:600;}
.card h3::before{content:"";display:inline-block;width:3px;height:13px;border-radius:2px;background:var(--accent);margin-right:9px;vertical-align:middle;}

/* reveal */
.reveal{opacity:0;transform:translateY(18px);animation:rise .7s cubic-bezier(.16,1,.3,1) forwards;animation-delay:calc(var(--i,0)*70ms);}
@keyframes rise{to{opacity:1;transform:none;}}

/* hero */
.hero-row{display:grid;grid-template-columns:1.35fr 1fr;gap:20px;}
.hero{display:flex;gap:26px;align-items:center;flex-wrap:wrap;
  background:linear-gradient(135deg,rgba(224,168,90,0.10),rgba(20,26,40,0.5));
  border-color:rgba(224,168,90,0.18);}
.hero-avatar{width:70px;height:70px;border-radius:18px;flex-shrink:0;
  background:linear-gradient(135deg,var(--accent),#b9823c);
  display:flex;align-items:center;justify-content:center;font-family:"Sora";font-size:1.7rem;font-weight:800;color:#1a1206;
  box-shadow:0 0 34px rgba(224,168,90,0.35);}
.hero-name{font-family:"Sora";font-size:1.4rem;font-weight:700;}
.hero-nation{color:var(--dim);font-size:0.9rem;margin-top:3px;}
.hero-tags{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap;}
.hero-stats{display:flex;gap:22px;margin-top:16px;flex-wrap:wrap;}
.stat{text-align:center;}
.stat .v{font-family:"Sora";font-size:1.55rem;font-weight:800;font-variant-numeric:tabular-nums;}
.stat .l{font-size:0.7rem;color:var(--dim);letter-spacing:0.5px;margin-top:2px;}
.v.g{color:var(--green);} .v.r{color:var(--red);} .v.b{color:var(--gold);} .v.p{color:var(--accent);} .v.o{color:var(--dim);}

/* delta chip (vs 昨日) */
.delta{display:block;font-family:"Sora";font-size:0.72rem;font-weight:800;font-variant-numeric:tabular-nums;margin-top:2px;letter-spacing:0.3px;}
.delta.up{color:var(--green);} .delta.down{color:var(--red);} .delta.neu{color:var(--dim);font-weight:600;}

/* trend section */
.trend-player{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap;}
.trend-player label{font-size:0.8rem;color:var(--dim);font-weight:600;letter-spacing:0.3px;}
.trend-player select{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:8px 13px;font-family:"Sora";font-size:0.84rem;cursor:pointer;max-width:280px;}
.trend-player select option{background:#0c0f16;color:var(--text);}
.trend-player select:focus{outline:none;border-color:var(--accent);}

/* table of contents — jump nav */
.toc{position:sticky;top:12px;z-index:50;display:flex;gap:7px;flex-wrap:wrap;
  background:rgba(12,15,22,0.82);backdrop-filter:blur(14px) saturate(120%);
  border:1px solid var(--border);border-radius:14px;padding:10px 13px;margin-bottom:26px;box-shadow:var(--shadow);}
.toc a{color:var(--dim);text-decoration:none;font-size:0.8rem;font-weight:600;
  padding:6px 13px;border-radius:9px;border:1px solid transparent;white-space:nowrap;
  transition:all .3s cubic-bezier(.16,1,.3,1);}
.toc a:hover{color:var(--text);border-color:var(--border-strong);}
.toc a.active{color:var(--accent);border-color:var(--accent);background:var(--accent-soft);}
section[id],div[id].section{scroll-margin-top:96px;}
.trend-pills{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;}
.trend-pill{padding:7px 15px;border-radius:10px;border:1px solid var(--border);background:var(--surface);color:var(--dim);font-family:"Sora";font-weight:700;font-size:0.84rem;cursor:pointer;transition:all .3s cubic-bezier(.16,1,.3,1);}
.trend-pill:hover{color:var(--text);border-color:var(--border-strong);}
.trend-pill.active{background:var(--accent);color:#1a1206;border-color:var(--accent);}
.chart-wrap.trend{height:320px;}
/* leaderboard */
.lb-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;}
.lb-card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:18px;}
.lb-card h4{font-family:"Sora";font-size:0.82rem;font-weight:700;letter-spacing:0.5px;margin-bottom:14px;color:var(--text);}
.lb-card h4::before{content:"";display:inline-block;width:3px;height:13px;border-radius:2px;background:var(--accent);margin-right:9px;vertical-align:middle;}
.lb-list{list-style:none;}
.lb-list li{display:flex;align-items:center;gap:10px;padding:8px 4px;border-bottom:1px solid rgba(255,255,255,0.05);}
.lb-list li:last-child{border-bottom:none;}
.lb-rank{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-family:"Sora";font-size:0.72rem;font-weight:800;background:rgba(255,255,255,0.06);color:var(--dim);flex-shrink:0;}
.lb-rank.r1{background:rgba(232,196,104,0.25);color:var(--gold);}
.lb-rank.r2{background:rgba(190,190,190,0.18);color:#c0c0c0;}
.lb-rank.r3{background:rgba(205,127,50,0.2);color:#cd7f32;}
.lb-name{flex:1;min-width:0;}
.lb-name .nm{display:block;font-weight:600;font-size:0.84rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lb-name .nt{display:block;font-size:0.7rem;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lb-delta{font-family:"Sora";font-weight:800;font-size:0.92rem;font-variant-numeric:tabular-nums;white-space:nowrap;}
.lb-delta.up{color:var(--green);} .lb-delta.down{color:var(--red);} .lb-delta.neu{color:var(--dim);}
.lb-empty{color:var(--dim);font-size:0.82rem;text-align:center;padding:14px 0;}
@media(max-width:900px){.lb-grid{grid-template-columns:1fr;}}

/* tags */
.tag{display:inline-block;padding:4px 11px;border-radius:11px;font-size:0.76rem;font-weight:600;}
.tag-ally{background:rgba(63,185,104,0.16);color:var(--green);}
.tag-war{background:rgba(239,83,80,0.18);color:var(--red);}
.tag-war.war-new{font-weight:800;box-shadow:0 0 0 2px rgba(239,83,80,0.55), 0 0 14px rgba(239,83,80,0.35);}
.tag-self{background:var(--accent-soft);color:var(--accent);}
.tag-team{background:rgba(224,168,90,0.12);color:var(--accent);}

/* diplomacy */
.dip h3::before{background:var(--green);}
.dip-block{margin-bottom:16px;}
.dip-block:last-child{margin-bottom:0;}
.dip-label{font-size:0.78rem;font-weight:600;margin-bottom:8px;letter-spacing:0.5px;}
.dip-label.ally{color:var(--green);}
.dip-label.war{color:var(--red);}
.tag-row{display:flex;flex-wrap:wrap;gap:6px;}

/* ally intel */
.ally-intel h3::before{background:var(--green);}

/* tables */
.table-wrap{overflow-x:auto;}
table.dt{width:100%;border-collapse:collapse;font-size:0.85rem;}
.dt th,.dt td{padding:10px 14px;text-align:left;white-space:nowrap;}
.dt th{font-size:0.68rem;letter-spacing:1px;color:var(--dim);border-bottom:1px solid var(--border);cursor:pointer;user-select:none;font-weight:600;}
.dt th:hover{color:var(--text);}
.dt td{border-bottom:1px solid rgba(255,255,255,0.07);}
.dt tr:hover td{background:rgba(255,255,255,0.035);}
.dt .me{font-weight:700;background:rgba(224,168,90,0.07);}
.strong{font-weight:600;} .dim{color:var(--dim);} .accent{color:var(--accent);font-weight:700;}
.green{color:var(--green);} .red{color:var(--red);} .gold{color:var(--gold);}
.enemy{color:var(--red);font-size:0.8rem;}
.enemy.war-new{font-weight:800;color:#ff7b78;text-shadow:0 0 10px rgba(239,83,80,0.4);}
.kda-g{color:var(--green);font-weight:700;} .kda-o{color:var(--text);} .kda-b{color:var(--red);}

/* top5 */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0;}
.stats h3::before{background:var(--accent);}
.top5{list-style:none;}
.top5 li{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:11px;margin-bottom:6px;background:var(--surface-2);transition:background .2s;}
.top5 li:hover{background:rgba(255,255,255,0.08);}
.rank{display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;border-radius:50%;font-family:"Sora";font-size:0.76rem;font-weight:800;flex-shrink:0;}
.rank.r1{background:rgba(232,196,104,0.25);color:var(--gold);}
.rank.r2{background:rgba(190,190,190,0.18);color:#c0c0c0;}
.rank.r3{background:rgba(205,127,50,0.2);color:#cd7f32;}
.rank.r4,.rank.r5{background:rgba(255,255,255,0.06);color:var(--dim);}
.top5 .info{flex:1;} .top5 .info .n{display:block;color:var(--dim);font-size:0.76rem;}
.top5 .val{font-family:"Sora";font-weight:800;font-size:1.1rem;font-variant-numeric:tabular-nums;}

/* coalition chart + detail */
.chart-card h3::before{background:var(--gold);}
.chart-wrap{position:relative;width:100%;}
.chart-wrap.tall{height:460px;}
.chart-wrap.med{height:260px;}
.coal-detail h3::before{background:var(--gold);}
.coal-row{display:flex;align-items:center;gap:11px;padding:11px 4px;border-bottom:1px solid rgba(255,255,255,0.04);}
.coal-row:last-child{border-bottom:none;}
.coal-dot{width:13px;height:13px;border-radius:4px;flex-shrink:0;}
.coal-name{font-weight:600;}
.coal-meta{color:var(--dim);font-size:0.78rem;}
.coal-score{margin-left:auto;font-family:"Sora";font-weight:800;font-size:1.1rem;font-variant-numeric:tabular-nums;}
.coal-mine{background:rgba(224,168,90,0.08);border-radius:11px;padding-left:12px;padding-right:12px;}

@media(max-width:900px){.hero-row{grid-template-columns:1fr;}.grid-2{grid-template-columns:1fr;}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;}}
</style>
</head>
<body>
<div class="container">
<div id="extraBanner"></div>
<header>
  <div class="brand">
    <h1>Supremacy <span>1914</span> · <span data-i18n="brand_panel">戰況面板</span></h1>
    <p class="sub" id="subHeader"></p>
  </div>
  <div class="controls">
    <div class="day-control">
      <span class="day-label" data-i18n="lbl_lang">語言</span>
      <div class="lang-switch" id="langSwitch" role="group" aria-label="language switch">
        <button type="button" data-lang="zh">中文</button>
        <button type="button" data-lang="en">EN</button>
      </div>
    </div>
    <div class="day-control">
      <span class="day-label" data-i18n="lbl_game">對局</span>
      <div class="day-pills" id="gamePills"></div>
    </div>
    <div class="day-control">
      <span class="day-label" data-i18n="lbl_day">遊戲日</span>
      <div class="day-pills" id="dayPills"></div>
    </div>
  </div>
</header>

<nav class="toc" id="toc">
  <a href="#sec-me" data-i18n="toc_me">我的視角</a>
  <a href="#sec-power" data-i18n="toc_power">戰力排行</a>
  <a href="#sec-prov" data-i18n="toc_prov">領土控制</a>
  <a href="#sec-coal" data-i18n="toc_coal">聯盟動態</a>
  <a href="#sec-score" data-i18n="toc_score">分數排行</a>
  <a href="#sec-all" data-i18n="toc_all">全部玩家</a>
  <a href="#sec-trend" data-i18n="toc_trend">趨勢與變化</a>
</nav>

<section class="zone reveal" style="--i:0" id="sec-me">
  <div class="zone-head"><span class="dot self"></span><h2 data-i18n="sec_me">我的視角</h2><span class="meta">NoodlesLover</span></div>
  <div class="hero-row">
    <div id="heroCard"></div>
    <div id="dipCard"></div>
  </div>
  <div id="allyIntel" style="margin-top:20px;"></div>
</section>

<section class="zone reveal" style="--i:1" id="sec-power">
  <div class="zone-head"><span class="dot gold"></span><h2 data-i18n="sec_power">戰力排行</h2><span class="meta" id="globalWhen"></span></div>
  <div class="card chart-card" style="margin-bottom:20px;">
    <h3 data-i18n="h3_kda">擊殺 / 陣亡 TOP 10（按擊殺比排序）</h3>
    <div class="chart-wrap tall"><canvas id="chartKDA"></canvas></div>
  </div>
  <div class="grid-2" id="top5Grid"></div>
</section>

<section class="zone reveal" style="--i:2" id="sec-prov">
  <div class="zone-head"><span class="dot gold"></span><h2 data-i18n="sec_prov">領土控制</h2></div>
  <div class="card chart-card" style="margin-bottom:20px;">
    <h3 data-i18n="h3_prov">領地數量 TOP 15</h3>
    <div class="chart-wrap tall"><canvas id="chartProv"></canvas></div>
  </div>
</section>

<section class="zone reveal" style="--i:3" id="sec-coal">
  <div class="zone-head"><span class="dot gold"></span><h2 data-i18n="sec_coal">聯盟動態</h2></div>
  <div class="card chart-card" style="margin-bottom:20px;">
    <h3 data-i18n="h3_coal">聯盟分數排行</h3>
    <div class="chart-wrap med"><canvas id="chartCoal"></canvas></div>
  </div>
  <div id="coalDetail" style="margin-bottom:20px;"></div>
</section>

<section class="zone reveal" style="--i:4" id="sec-score">
  <div class="zone-head"><span class="dot gold"></span><h2 data-i18n="sec_score">分數排行</h2></div>
  <div class="card chart-card" style="margin-bottom:20px;">
    <h3 data-i18n="h3_score">分數排行 TOP 15</h3>
    <div class="chart-wrap tall"><canvas id="chartScore"></canvas></div>
  </div>
</section>

<section class="zone reveal" style="--i:5" id="sec-all">
  <div class="zone-head"><span class="dot gold"></span><h2 data-i18n="sec_all">全部玩家</h2></div>
  <div id="fullTable"></div>
</section>

<section class="zone reveal" style="--i:6" id="sec-trend">
  <div class="zone-head"><span class="dot gold"></span><h2 data-i18n="sec_trend">趨勢與變化</h2></div>
  <div id="leaderboard" class="lb-grid" style="margin-bottom:20px;"></div>
  <div class="card chart-card" style="margin-bottom:20px;">
    <h3 data-i18n="h3_trend">指標隨遊戲日變化</h3>
    <div class="trend-player">
      <label for="trendPlayer" data-i18n="trend_player_label">玩家</label>
      <select id="trendPlayer"></select>
    </div>
    <div class="trend-pills" id="trendPills"></div>
    <div class="chart-wrap trend"><canvas id="chartTrend"></canvas></div>
  </div>
</section>

</div>

<script>
const GAMES = __GAMES_JSON__;
const GAME_ORDER = __GAME_ORDER_JSON__;
const MY_IDS = __MY_IDS_JSON__;
const EXTRA = __EXTRA_JSON__;
let currentGame = GAME_ORDER[GAME_ORDER.length-1];
let DAYS = GAMES[currentGame].days;
let DAY_ORDER = GAMES[currentGame].order;
let currentDay = DAY_ORDER[DAY_ORDER.length-1];
let MY_ID = MY_IDS[currentGame] || 22;
let currentRows = [];
let sortCol = 4, sortAsc = false;
const charts = {};

// ── i18n：繁體中文 / English（英文術語對齊 Supremacy 1914 遊戲內用語）──
const I18N = {
  zh: {
    lbl_game:'對局', lbl_day:'遊戲日', lbl_lang:'語言',
    toc_me:'我的視角', toc_power:'戰力排行', toc_prov:'領土控制', toc_coal:'聯盟動態', toc_score:'分數排行', toc_all:'全部玩家', toc_trend:'趨勢與變化',
    sec_me:'我的視角', sec_power:'戰力排行', sec_prov:'領土控制', sec_coal:'聯盟動態', sec_score:'分數排行', sec_all:'全部玩家', sec_trend:'趨勢與變化',
    h3_kda:'擊殺 / 陣亡 TOP 10（按擊殺比排序）',
    h3_prov:'領地數量 TOP 15', h3_coal:'聯盟分數排行', h3_score:'分數排行 TOP 15', h3_trend:'指標隨遊戲日變化',
    me_tag:'我', trend_player_label:'玩家',
    dip_title:'我的外交關係', dip_ally:'盟友', dip_enemy:'敵對', dip_newenemy:'紅框為本日新敵對',
    ally_title:'盟友情報（按分數降序）',
    col_id:'ID', col_player:'玩家', col_nation:'國家', col_coal:'聯盟', col_score:'分數', col_kills:'擊殺', col_losses:'陣亡',
    col_kda:'擊殺比', col_captured:'佔領', col_lost:'被佔領', col_provinces:'領地', col_enemy:'敵對',
    top5_kills:'擊殺數 TOP 5', top5_losses:'陣亡數 TOP 5',
    coal_title:'聯盟明細（共 {n} 個）',
    hero_score:'分數', hero_kills:'擊殺', hero_losses:'陣亡', hero_kda:'擊殺比', hero_captured:'佔領省份', hero_lost:'被佔領', hero_provinces:'領地數',
    lb_score:'分數增幅排行', lb_prov:'領地增幅排行', lb_coal:'聯盟分數增幅排行',
    lb_nochange:'暫無變化', lb_needtwo:'需要至少兩個遊戲日才能比較變化',
    defeated_title:'亡國 · 本日領地歸零的玩家', defeated_none:'本日無亡國',
    sub_game:'對局 #', sub_map:'地圖：北美洲', sub_players:' 名人類玩家', sub_goal:'目標', sub_vp:'勝利點', sub_reported:'報告時間',
    chart_kills:'擊殺', chart_losses:'陣亡', chart_prov:'領地數', chart_coalscore:'聯盟分數', chart_score:'分數',
    trend_score:'分數', trend_kills:'擊殺', trend_losses:'陣亡', trend_provinces:'領地', trend_captured:'佔領', trend_lost:'被佔領',
    table_title:'全部人類玩家（按分數降序，{n} 人）',
    extra_title:'額外報告 · 即時快照',
    extra_d1:'這是遊戲日', extra_d2:'於', extra_d3:'擷取的額外報告，僅供即時查看，', extra_d4:'未納入主面板的趨勢與變化', extra_d5:'。如需歸入趨勢，請以該日首次擷取為基準。',
    unit_ppl:'人', player_x:'玩家', coal_members:'人 · ', time_unrecorded:'時間未記錄', brand_panel:'戰況面板', no_coalition:'無聯盟',
  },
  en: {
    lbl_game:'Game', lbl_day:'Game Day', lbl_lang:'Language',
    toc_me:'My View', toc_power:'Power Ranking', toc_prov:'Territory', toc_coal:'Coalitions', toc_score:'Score Ranking', toc_all:'All Players', toc_trend:'Trends & Changes',
    sec_me:'My View', sec_power:'Power Ranking', sec_prov:'Territory Control', sec_coal:'Coalition Activity', sec_score:'Score Ranking', sec_all:'All Players', sec_trend:'Trends & Changes',
    h3_kda:'Top 10 Kills / Losses (by K/D)',
    h3_prov:'Top 15 Provinces', h3_coal:'Coalition Score Ranking', h3_score:'Top 15 Score', h3_trend:'Metrics over Game Days',
    me_tag:'Me', trend_player_label:'Player',
    dip_title:'My Diplomacy', dip_ally:'Allies', dip_enemy:'Hostile', dip_newenemy:'red border = newly hostile today',
    ally_title:'Ally Intel (by score)',
    col_id:'ID', col_player:'Player', col_nation:'Nation', col_coal:'Coalition', col_score:'Score', col_kills:'Kills', col_losses:'Losses',
    col_kda:'K/D', col_captured:'Captured', col_lost:'Lost', col_provinces:'Provinces', col_enemy:'Hostile',
    top5_kills:'Top 5 Kills', top5_losses:'Top 5 Losses',
    coal_title:'Coalition Details ({n} total)',
    hero_score:'Score', hero_kills:'Kills', hero_losses:'Losses', hero_kda:'K/D', hero_captured:'Captured', hero_lost:'Lost', hero_provinces:'Provinces',
    lb_score:'Top Score Gains', lb_prov:'Top Province Gains', lb_coal:'Top Coalition Score Gains',
    lb_nochange:'No changes', lb_needtwo:'At least two game days are required to compare changes',
    defeated_title:'Eliminated · Players who lost all provinces today', defeated_none:'No eliminations today',
    sub_game:'Game #', sub_map:'Map: North America', sub_players:' human players', sub_goal:'Goal', sub_vp:'Victory Points', sub_reported:'Reported',
    chart_kills:'Kills', chart_losses:'Losses', chart_prov:'Provinces', chart_coalscore:'Coalition Score', chart_score:'Score',
    trend_score:'Score', trend_kills:'Kills', trend_losses:'Losses', trend_provinces:'Provinces', trend_captured:'Captured', trend_lost:'Lost',
    table_title:'All Human Players (by score, {n} players)',
    extra_title:'Extra Report · Live Snapshot',
    extra_d1:'This is an extra report captured on game day', extra_d2:'at', extra_d3:'for live viewing only,', extra_d4:'not included in the main dashboard trends & changes', extra_d5:'. To include it in trends, capture it as the first report of that day.',
    unit_ppl:'', player_x:'Player', coal_members:' members · ', time_unrecorded:'Time not recorded', brand_panel:'War Dashboard', no_coalition:'No Coalition',
  },
};
let lang = (function(){ try{ return localStorage.getItem('lang') || 'en'; }catch(e){ return 'en'; } })();
const t = k => (I18N[lang] && I18N[lang][k]!=null) ? I18N[lang][k] : (I18N.zh[k]!=null ? I18N.zh[k] : k);
const sep = () => lang==='en' ? ', ' : '、';
function applyStaticText(){
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const k=el.getAttribute('data-i18n');
    const v=(I18N[lang] && I18N[lang][k]!=null) ? I18N[lang][k] : I18N.zh[k];
    if(v!=null) el.textContent=v;
  });
  document.documentElement.lang = (lang==='en') ? 'en' : 'zh-Hant';
}

const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
function fmtTime(iso){
  if(!iso) return t('time_unrecorded');
  const d=new Date(iso);
  if(isNaN(d.getTime())) return iso;
  const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function HEADERS(){ return [t('col_id'),t('col_player'),t('col_nation'),t('col_coal'),t('col_score'),t('col_kills'),t('col_losses'),t('col_kda'),t('col_captured'),t('col_lost'),t('col_provinces'),t('col_enemy')]; }
const COLS = ['id','name','nation','teamLabel','score','kills','losses','kda','captured','lost','provinces','enemies'];

const baseOpts = {
  responsive:true, maintainAspectRatio:false,
  plugins:{ legend:{ labels:{ color:'#9aa3b6', font:{ size:11 } } } },
  scales:{
    x:{ ticks:{ color:'#9aa3b6' }, grid:{ color:'rgba(255,255,255,0.07)' } },
    y:{ ticks:{ color:'#9aa3b6', font:{ size:11 }, autoSkip:false }, grid:{ color:'rgba(255,255,255,0.07)' } }
  }
};

function stat(v,l,cls,delta){ return `<div class="stat"><div class="v ${cls}">${v}</div>${delta||''}<div class="l">${l}</div></div>`; }

function deltaChip(cur, prev, good){
  if(prev===null||prev===undefined) return `<span class="delta neu">—</span>`;
  const diff = cur - prev;
  if(diff===0) return `<span class="delta neu">±0</span>`;
  const up = diff>0, goodChange = good ? up : !up, cls = goodChange ? 'up' : 'down', arrow = up ? '▲' : '▼';
  const mag = Number.isInteger(diff) ? Math.abs(diff) : Math.abs(diff).toFixed(2);
  return `<span class="delta ${cls}">${arrow}${mag}</span>`;
}

function heroHtml(d, prevMe){
  const m=d.me;
  const dl = (k,g)=> deltaChip(m[k], prevMe?prevMe[k]:null, g);
  return `<div class="card hero">
    <div class="hero-avatar">${m.id}</div>
    <div>
      <div class="hero-name">${esc(m.name)}</div>
      <div class="hero-nation">${esc(m.nation)} · ${m.coalition ? esc(m.coalition) : t('no_coalition')}</div>
      <div class="hero-tags"><span class="tag tag-self">${t('me_tag')}</span><span class="tag tag-team">${m.coalition ? esc(m.coalition) : t('no_coalition')}</span></div>
      <div class="hero-stats">
        ${stat(m.score,t('hero_score'),'p',dl('score',true))}${stat(m.kills,t('hero_kills'),'g',dl('kills',true))}${stat(m.losses,t('hero_losses'),'r',dl('losses',false))}
        ${stat(m.kda,t('hero_kda'),'b',dl('kda',true))}${stat(m.captured,t('hero_captured'),'b',dl('captured',true))}${stat(m.lost,t('hero_lost'),'o',dl('lost',false))}${stat(m.provinces,t('hero_provinces'),'p',dl('provinces',true))}
      </div>
    </div></div>`;
}
function dipHtml(d){
  const m=d.me;
  const ally = m.allies.map(a=>`<span class="tag tag-ally">${esc(a.nation)} (${esc(a.name)})</span>`).join('');
  const enemy = m.enemies.map(e=>`<span class="tag tag-war${e.isNew?' war-new':''}">${esc(e.nation)} (${esc(e.name)})</span>`).join('');
  const newCount = m.enemies.filter(e=>e.isNew).length;
  return `<div class="card dip"><h3>${t('dip_title')}</h3>
    <div class="dip-block"><div class="dip-label ally">${t('dip_ally')} (${m.allies.length}${t('unit_ppl')})</div><div class="tag-row">${ally||'—'}</div></div>
    <div class="dip-block"><div class="dip-label war">${t('dip_enemy')} (${m.enemies.length}${t('unit_ppl')}${newCount?' · '+t('dip_newenemy'):''})</div><div class="tag-row">${enemy||'—'}</div></div>
  </div>`;
}
function allyHtml(d){
  const rows = d.allies.map(a=>{
    const ed = (a.enemyDisplay||[]).map(e=>`<span class="enemy${e.isNew?' war-new':''}">${esc(e.nation)} (${esc(e.name)})</span>`).join(sep());
    return `<tr><td class="strong">${esc(a.name)}</td><td class="dim">${esc(a.nation)}</td>
    <td class="accent">${a.score}</td><td class="green">${a.kills}</td><td class="red">${a.losses}</td>
    <td class="${a.kdaCls}">${a.kda}</td><td class="gold">${a.captured}</td><td class="dim">${a.lost}</td>
    <td>${a.provinces}</td><td class="enemy">${ed||'—'}</td></tr>`;
  }).join('');
  return `<div class="card ally-intel"><h3>${t('ally_title')}</h3>
    <div class="table-wrap"><table class="dt"><thead><tr>
      <th>${t('col_player')}</th><th>${t('col_nation')}</th><th>${t('col_score')}</th><th>${t('col_kills')}</th><th>${t('col_losses')}</th><th>${t('col_kda')}</th><th>${t('col_captured')}</th><th>${t('col_lost')}</th><th>${t('col_provinces')}</th><th>${t('col_enemy')}</th>
    </tr></thead><tbody>${rows}</tbody></table></div></div>`;
}
function top5Html(d){
  const k = d.top5Kills.map((r,i)=>`<li><span class="rank r${i+1}">${i+1}</span>
    <span class="info">${esc(r.name)}<span class="n">${esc(r.nation)}</span></span>
    <span class="val green">${r.val}</span></li>`).join('');
  const l = d.top5Losses.map((r,i)=>`<li><span class="rank r${i+1}">${i+1}</span>
    <span class="info">${esc(r.name)}<span class="n">${esc(r.nation)}</span></span>
    <span class="val red">${r.val}</span></li>`).join('');
  return `<div class="card stats"><h3>${t('top5_kills')}</h3><ul class="top5">${k}</ul></div>
    <div class="card stats"><h3>${t('top5_losses')}</h3><ul class="top5">${l}</ul></div>`;
}
function coalHtml(d){
  const rows = d.coalitions.map(c=>`<div class="coal-row${c.isMine?' coal-mine':''}">
    <span class="coal-dot" style="background:${c.solid}"></span>
    <span class="coal-name">${esc(c.name)}${c.isMine?' ★':''}</span>
    <span class="coal-meta">${c.memberCount}${t('coal_members')}${esc(c.members)}</span>
    <span class="coal-score" style="color:${c.solid}">${c.score}</span></div>`).join('');
  return `<div class="card coal-detail"><h3>${t('coal_title').replace('{n}', d.coalitions.length)}</h3>${rows}</div>`;
}
function enemyTags(arr){
  if(!arr || !arr.length) return '—';
  return arr.map(e=>`<span class="enemy${e.isNew?' war-new':''}">${esc(e.nation)} (${esc(e.name)})</span>`).join(sep());
}
function buildTable(rows){
  const head = HEADERS().map((h,i)=>`<th onclick="sortTable(${i})">${h}${i===sortCol?' '+(sortAsc?'▲':'▼'):''}</th>`).join('');
  const body = rows.map(r=>`<tr class="${r.isMe?'me':''}"><td>${r.id}</td><td>${esc(r.name)}</td>
    <td class="dim">${esc(r.nation)}</td><td>${r.teamLabel ? esc(r.teamLabel) : t('no_coalition')}</td><td class="accent">${r.score}</td>
    <td>${r.kills}</td><td>${r.losses}</td><td class="${r.kdaCls}">${r.kda}</td>
    <td>${r.captured}</td><td class="dim">${r.lost}</td><td>${r.provinces}</td>
    <td class="enemy">${enemyTags(r.enemies)}</td></tr>`).join('');
  document.getElementById('fullTable').innerHTML =
    `<div class="card"><h3>${t('table_title').replace('{n}', rows.length)}</h3>
     <div class="table-wrap"><table class="dt"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></div>`;
}
function sortTable(col){
  sortCol=col; sortAsc=!sortAsc;
  const f=COLS[col];
  currentRows.sort((a,b)=>{ let va=a[f],vb=b[f];
    if(typeof va==='number') return sortAsc? va-vb : vb-va;
    return sortAsc? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va)); });
  buildTable(currentRows);
}
function buildCharts(d){
  Object.values(charts).forEach(c=>c.destroy());
  const cl=id=>document.getElementById(id).getContext('2d');
  const c=d.charts;
  charts.kda=new Chart(cl('chartKDA'),{type:'bar',data:{labels:c.kda.labels,datasets:[
    {label:t('chart_kills'),data:c.kda.kills,backgroundColor:'rgba(63,185,104,0.78)',borderRadius:3,barThickness:11},
    {label:t('chart_losses'),data:c.kda.losses,backgroundColor:'rgba(239,83,80,0.55)',borderRadius:3,barThickness:11}
  ]},options:{...baseOpts,indexAxis:'y',plugins:{...baseOpts.plugins,tooltip:{mode:'index'}}}});
  charts.prov=new Chart(cl('chartProv'),{type:'bar',data:{labels:c.prov.labels,datasets:[
    {label:t('chart_prov'),data:c.prov.vals,backgroundColor:'rgba(224,168,90,0.68)',borderRadius:3,barThickness:14}
  ]},options:{...baseOpts,indexAxis:'y',plugins:{legend:{display:false}}}});
  charts.coal=new Chart(cl('chartCoal'),{type:'bar',data:{labels:c.coal.labels,datasets:[
    {label:t('chart_coalscore'),data:c.coal.scores,backgroundColor:c.coal.colors,borderRadius:4,barThickness:30}
  ]},options:{...baseOpts,indexAxis:'y',plugins:{legend:{display:false}}}});
  charts.score=new Chart(cl('chartScore'),{type:'bar',data:{labels:c.score.labels,datasets:[
    {label:t('chart_score'),data:c.score.vals,backgroundColor:'rgba(232,196,104,0.68)',borderRadius:3,barThickness:14}
  ]},options:{...baseOpts,indexAxis:'y',plugins:{legend:{display:false}}}});
}
function prevDayNum(day){
  let best=null;
  DAY_ORDER.forEach(o=>{ if(o<day && (best===null||o>best)) best=o; });
  return best;
}
function render(day){
  const d=DAYS[day];
  const pDay=prevDayNum(day);
  const prevMe = pDay!==null ? DAYS[pDay].me : null;
  const gid = GAMES[currentGame].gameID;
  document.getElementById('subHeader').textContent=`${t('sub_game')}${gid} · ${t('sub_map')} · ${d.meta.playerCount}${t('sub_players')} · ${t('sub_goal')} ${d.meta.vp} ${t('sub_vp')} · ${t('sub_reported')} ${fmtTime(d.meta.reportedAt)}`;
  document.getElementById('globalWhen').textContent=`${t('sub_game')}${gid} · ${t('lbl_day')} ${d.meta.day} · ${t('sub_reported')} ${fmtTime(d.meta.reportedAt)}`;
  document.getElementById('heroCard').innerHTML=heroHtml(d, prevMe);
  document.getElementById('dipCard').innerHTML=dipHtml(d);
  document.getElementById('allyIntel').innerHTML=allyHtml(d);
  document.getElementById('top5Grid').innerHTML=top5Html(d);
  document.getElementById('coalDetail').innerHTML=coalHtml(d);
  buildLeaderboard(d, pDay);
  currentRows=d.tableRows.slice();
  buildTable(currentRows);
  buildCharts(d);
  document.querySelectorAll('.day-pill').forEach(b=>b.classList.toggle('active',+b.textContent===day));
  const ap=[...document.querySelectorAll('#dayPills .day-pill')].find(b=>+b.textContent===day);
  if(ap) ap.scrollIntoView({behavior:'smooth',inline:'center',block:'nearest'});
}

function renderExtraBanner(){
  const el=document.getElementById('extraBanner');
  if(!EXTRA){ el.innerHTML=''; return; }
  el.innerHTML=`<div class="card" style="border-color:rgba(224,168,90,0.4);background:linear-gradient(135deg,rgba(224,168,90,0.12),rgba(20,26,40,0.5));margin-bottom:26px;">
    <h3>${t('extra_title')}</h3>
    <p style="color:var(--dim);font-size:0.86rem;line-height:1.65;">${t('extra_d1')} <b style="color:var(--text)">${EXTRA.day}</b> ${t('extra_d2')} <b style="color:var(--text)">${EXTRA.ts}</b> ${t('extra_d3')}<b style="color:var(--text)">${t('extra_d4')}</b>。${t('extra_d5')}</p></div>`;
}

function buildLeaderboard(d, pDay){
  const lb=document.getElementById('leaderboard');
  if(pDay===null){
    lb.innerHTML=`<div class="card" style="grid-column:1/-1;text-align:center;color:var(--dim);padding:34px;">${t('lb_needtwo')}</div>`;
    return;
  }
  const prevRows={}; DAYS[pDay].tableRows.forEach(r=>prevRows[r.id]=r);
  const cur=d.tableRows;
  const scoreMoves=cur.map(r=>{ const p=prevRows[r.id]; return {name:r.name,nation:r.nation,dv:p?r.score-p.score:0}; })
    .filter(x=>x.dv>0).sort((a,b)=>b.dv-a.dv).slice(0,8);
  const provMoves=cur.map(r=>{ const p=prevRows[r.id]; return {name:r.name,nation:r.nation,dv:p?r.provinces-p.provinces:0}; })
    .filter(x=>x.dv>0).sort((a,b)=>b.dv-a.dv).slice(0,8);
  const prevCoal={}; DAYS[pDay].coalitions.forEach(c=>prevCoal[c.name]=c.score);
  const coalMoves=d.coalitions.map(c=>({name:c.name,dv:c.score-(prevCoal[c.name]!=null?prevCoal[c.name]:0)}))
    .filter(x=>x.dv>0).sort((a,b)=>b.dv-a.dv);
  const card=(title,list)=>`<div class="lb-card"><h4>${title}</h4>${list}</div>`;
  const listHtml=(moves)=>{
    if(!moves.length) return `<div class="lb-empty">${t('lb_nochange')}</div>`;
    return `<ul class="lb-list">`+moves.map((m,i)=>`<li>
      <span class="lb-rank ${i<3?'r'+(i+1):''}">${i+1}</span>
      <span class="lb-name"><span class="nm">${esc(m.name)}</span><span class="nt">${esc(m.nation||'')}</span></span>
      <span class="lb-delta up">▲${m.dv}</span></li>`).join('')+`</ul>`;
  };
  const defeated=(d.defeated||[]);
  const defeatedCard=`<div class="lb-card" style="grid-column:1/-1;border-color:rgba(239,83,80,0.35);background:linear-gradient(135deg,rgba(239,83,80,0.10),rgba(20,26,40,0.5));"><h4 style="color:var(--red)">${t('defeated_title')}</h4>${defeated.length
    ? `<ul class="lb-list">`+defeated.map(m=>`<li>
        <span class="lb-rank" style="background:rgba(239,83,80,0.2);color:var(--red)">✕</span>
        <span class="lb-name"><span class="nm">${esc(m.name)}</span><span class="nt">${esc(m.nation||'')}</span></span>
      </li>`).join('')+`</ul>`
    : `<div class="lb-empty">${t('defeated_none')}</div>`}</div>`;
  lb.innerHTML=card(t('lb_score'),listHtml(scoreMoves))+card(t('lb_prov'),listHtml(provMoves))+card(t('lb_coal'),listHtml(coalMoves))+defeatedCard;
}

const TREND_METRICS=[
  {key:'score',tk:'trend_score',color:'rgba(224,168,90,0.95)',fill:'rgba(224,168,90,0.12)'},
  {key:'kills',tk:'trend_kills',color:'rgba(63,185,104,0.95)',fill:'rgba(63,185,104,0.12)'},
  {key:'losses',tk:'trend_losses',color:'rgba(239,83,80,0.95)',fill:'rgba(239,83,80,0.12)'},
  {key:'provinces',tk:'trend_provinces',color:'rgba(120,170,255,0.95)',fill:'rgba(120,170,255,0.12)'},
  {key:'captured',tk:'trend_captured',color:'rgba(232,196,104,0.95)',fill:'rgba(232,196,104,0.12)'},
  {key:'lost',tk:'trend_lost',color:'rgba(255,140,80,0.95)',fill:'rgba(255,140,80,0.12)'},
];
let trendMetric='score';
let trendChart=null;
let trendPid=MY_ID;
function playerName(pid){
  const rows=DAYS[DAY_ORDER[DAY_ORDER.length-1]].tableRows;
  const r=rows.find(x=>x.id===pid);
  return r ? `${r.name} (${r.nation})` : `${t('player_x')} ${pid}`;
}
function trendSeries(key, pid){
  return DAY_ORDER.map(day=>{
    const row=DAYS[day].tableRows.find(r=>r.id===pid);
    return row ? row[key] : null;
  });
}
function buildTrendChart(){
  if(trendChart) trendChart.destroy();
  const m=TREND_METRICS.find(x=>x.key===trendMetric);
  const pid=+document.getElementById('trendPlayer').value;
  trendChart=new Chart(document.getElementById('chartTrend').getContext('2d'),{
    type:'line',
    data:{labels:DAY_ORDER,datasets:[{label:`${t(m.tk)} · ${playerName(pid)}`,data:trendSeries(m.key,pid),borderColor:m.color,backgroundColor:m.fill,
      borderWidth:2.5,tension:0.35,fill:true,pointRadius:4,pointBackgroundColor:m.color,pointBorderColor:'#0c0f16',pointBorderWidth:2}]},
    options:{...baseOpts,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},
      scales:{x:{ticks:{color:'#9aa3b6'},grid:{color:'rgba(255,255,255,0.07)'}},
             y:{ticks:{color:'#9aa3b6',font:{size:11}},grid:{color:'rgba(255,255,255,0.07)'}}}}
  });
  const pc=document.getElementById('trendPills');
  pc.innerHTML=TREND_METRICS.map(m=>`<button class="trend-pill${m.key===trendMetric?' active':''}" data-k="${m.key}">${t(m.tk)}</button>`).join('');
  pc.querySelectorAll('.trend-pill').forEach(b=>b.onclick=()=>{
    trendMetric=b.dataset.k;
    pc.querySelectorAll('.trend-pill').forEach(x=>x.classList.toggle('active',x.dataset.k===trendMetric));
    const mm=TREND_METRICS.find(x=>x.key===trendMetric);
    const pid=+document.getElementById('trendPlayer').value;
    const ds=trendChart.data.datasets[0];
    ds.label=`${t(mm.tk)} · ${playerName(pid)}`; ds.data=trendSeries(mm.key,pid); ds.borderColor=mm.color; ds.backgroundColor=mm.fill; ds.pointBackgroundColor=mm.color;
    trendChart.update();
  });
}

// ── 對局切換 ──
function rebuildDayPills(){
  const pills=document.getElementById('dayPills');
  pills.innerHTML='';
  DAY_ORDER.forEach(day=>{
    const b=document.createElement('button');
    b.className='day-pill'; b.textContent=day;
    b.onclick=()=>{ currentDay=day; render(day); };
    pills.appendChild(b);
  });
}
function rebuildTrendPlayer(){
  const sel=document.getElementById('trendPlayer');
  sel.innerHTML='';
  const latestRows=DAYS[DAY_ORDER[DAY_ORDER.length-1]].tableRows.slice().sort((a,b)=>b.score-a.score);
  latestRows.forEach(r=>{ const o=document.createElement('option'); o.value=r.id; o.textContent=`${r.name} (${r.nation})`; sel.appendChild(o); });
  sel.value=String(MY_ID);
}
function setGame(gid){
  currentGame=String(gid);
  MY_ID = MY_IDS[currentGame] || 22;
  DAYS=GAMES[currentGame].days;
  DAY_ORDER=GAMES[currentGame].order;
  currentDay=DAY_ORDER[DAY_ORDER.length-1];
  rebuildDayPills();
  rebuildTrendPlayer();
  render(currentDay);
  buildTrendChart();
  document.querySelectorAll('.game-pill').forEach(b=>b.classList.toggle('active', b.textContent===String(gid)));
}

// 建立對局選擇器
const gp=document.getElementById('gamePills');
GAME_ORDER.forEach(gid=>{
  const b=document.createElement('button');
  b.className='day-pill game-pill'; b.textContent=gid;
  b.onclick=()=>{ setGame(gid); };
  gp.appendChild(b);
});
// 建立日選擇器（初始對局）+ 趨勢玩家下拉
rebuildDayPills();
const sel=document.getElementById('trendPlayer');
rebuildTrendPlayer();
sel.onchange=()=>{ buildTrendChart(); };

// 目錄跳轉：捲動時高亮當前章節
const tocLinks=[...document.querySelectorAll('.toc a')];
const spy=new IntersectionObserver(entries=>{
  entries.forEach(e=>{
    if(e.isIntersecting){
      const id=e.target.id;
      tocLinks.forEach(a=>a.classList.toggle('active', a.getAttribute('href')==='#'+id));
    }
  });
},{rootMargin:'-45% 0px -50% 0px',threshold:0});
document.querySelectorAll('section[id]').forEach(s=>spy.observe(s));

// ── 語言切換：切換後重新渲染所有動態區塊（靜態文字經 data-i18n 同步）──
const langBtns=[...document.querySelectorAll('#langSwitch button')];
function setLang(l){
  lang=l;
  try{ localStorage.setItem('lang', l); }catch(e){}
  langBtns.forEach(b=>b.classList.toggle('active', b.dataset.lang===l));
  applyStaticText();
  renderExtraBanner();
  render(currentDay);
  buildTrendChart();
}
langBtns.forEach(b=>b.onclick=()=>setLang(b.dataset.lang));
langBtns.forEach(b=>b.classList.toggle('active', b.dataset.lang===lang));
applyStaticText();
renderExtraBanner();
render(currentDay);
buildTrendChart();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()

