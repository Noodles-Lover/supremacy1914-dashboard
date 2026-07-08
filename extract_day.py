# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 單日快照擷取器 (unified extractor).

功能：
  透過 Chrome DevTools Protocol (CDP) 連上正在遊玩的 Supremacy 1914 分頁，
  在遊戲 iframe 的執行環境內讀取 hup.gameState，一次性撈出：
    玩家 / 戰鬥統計 / 外交關係 / 聯盟(含分數) / 玩家分數 / 領地數
  並寫入 data/day_{N}.json（N = 遊戲日，非真實日），同時蓋上 reportedAt 時間戳。
  寫完後自動呼叫 build_dashboard.py 重建儀表盤。

前置條件：
  1. 遊戲已在 Chrome 中開啟並登入（網址含 supremacy1914.com/game）。
  2. Chrome 以遠端除錯啟動：
       "C:/Program Files/Google/Chrome/Application/chrome.exe"
         --remote-debugging-port=9222 --remote-allow-origins=*
         --user-data-dir="C:/Users/<user>/chrome-debug-profile"
     （Chrome 136+ 必須指定非預設 --user-data-dir，否則 9222 不生效）
  3. 本機 Python 已安裝 websockets：  pip install websockets

用法：
  python extract_day.py            # 擷取當前遊戲日並重建儀表盤
  python extract_day.py --no-build # 只擷取，不重建儀表盤

同一遊戲日重跑會直接覆寫 data/day_{N}.json（不另存時間版本）；
真實擷取時刻記錄在檔案的 reportedAt 欄位。
"""
import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
OUT_PY = os.path.join(BASE, "build_dashboard.py")

try:
    import websockets
except ImportError:
    print("[ERR] 缺少 websockets 套件，請先執行：pip install websockets")
    sys.exit(1)

# 強制 UTF-8 輸出，避免 Windows 主控台 (cp932/cp950) 印不出中文而崩潰
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── 在遊戲 iframe 內執行的擷取腳本（一次性回傳完整 day_N.json 內容）──
EXTRACT_JS = r"""
(function(){
  try {
    function st(t){
      var s = hup.gameState.states;
      if (!s) return null;
      if (s[t] !== undefined) return s[t];
      if (s[String(t)] !== undefined) return s[String(t)];
      if (Array.isArray(s)) { for (var i=0;i<s.length;i++){ if(s[i]&&s[i].type===t) return s[i]; } }
      return null;
    }

    // 遊戲日
    var day = null;
    try { day = hup.gameState.getGameInfoState().getDayOfGame(); } catch(e){}
    var gi = st(12); var gid = gi ? (gi.data || gi) : null;
    if (day == null && gid) day = (gid.day != null) ? gid.day : (gid.gameDay != null ? gid.gameDay : null);
    var vp = gid ? (gid.victoryPoints != null ? gid.victoryPoints : null) : null;

    // 玩家（state 1 的玩家物件欄位為 nationName/teamID/primaryColor/capitalID/computerPlayer）
    var s1 = st(1); var psrc = s1 ? (s1.players || s1.data || s1) : {};
    var players = [];
    for (var pid in psrc){
      var p = psrc[pid]; if (!p) continue;
      var id = (p.playerID != null) ? p.playerID : ((p.id != null) ? p.id : parseInt(pid));
      players.push({
        id: id, name: p.name || "", nation: p.nationName || "", team: p.teamID || 0,
        color: p.primaryColor, capital: p.capitalID, ai: !!p.computerPlayer, defeated: !!p.defeated
      });
    }

    // 戰鬥統計（state 30，跨日累計）
    var s30 = st(30); var stats = {};
    if (s30){
      var map = s30.playerIDToDaysStatsMap || (s30.data && s30.data.playerIDToDaysStatsMap);
      if (map){
        for (var pid in map){
          var days = map[pid]; var tot = {provincesCaptured:0, provincesLost:0, unit2killed:0, unit2lost:0};
          for (var d in days){ var dd = days[d]; for (var k in tot){ if (dd[k] != null) tot[k] += dd[k]; } }
          stats[String(pid)] = tot;
        }
      }
    }

    // 外交關係（state 5：資料位於 s5.relations 下，含 neighborRelations）
    var s5 = st(5);
    var relations = (s5 && s5.relations) ? s5.relations : (s5 ? (s5.data || s5) : {});

    // 報紙排名（拿玩家分數與聯盟分數）
    var rank = null;
    try { rank = hup.gameState.getNewspaperState().getRanking(day); } catch(e){}

    // 玩家分數
    var scores = {};
    for (var i=0;i<players.length;i++){
      var pid = players[i].id; var sc = 0;
      try { if (rank && typeof rank.getPlayerPoints === 'function') sc = rank.getPlayerPoints(pid); } catch(e){}
      scores[String(pid)] = sc || 0;
    }

    // 聯盟（含分數）
    var ctrl = hup.inGameAllianceController; var coal = [];
    if (ctrl && ctrl.alliances){
      ctrl.alliances.forEach(function(a){
        var prof = a.profile || {};
        var tid = (prof.teamID != null) ? prof.teamID : null;
        var score = 0;
        try { if (rank && typeof rank.getTeamPoints === 'function') score = rank.getTeamPoints(tid); } catch(e){}
        if (!score){ try { var gs = a.getScore(); if (typeof gs === 'number') score = gs; else if (gs && gs.points) score = gs.points; } catch(e){} }
        coal.push({
          teamID: tid, name: prof.name || null, score: score || 0,
          memberIDs: Object.keys(a.members || {}).map(function(k){ return parseInt(k); }),
          primaryColor: prof.primaryColor || null,
          leaderID: (prof.leaderID != null) ? prof.leaderID : null
        });
      });
    }

    // 領地數（state 3，僅回傳聚合後的計數，避免大狀態崩潰）
    var s3 = st(3); var pc = {};
    if (s3){
      var pMap = s3.provincesAsMap || (s3.data && s3.data.provincesAsMap);
      if (pMap){
        var entries = (pMap instanceof Map) ? pMap.entries() : Object.entries(pMap);
        for (var pair of entries){
          var prov = pair[1];
          var owner = (prov.ownerID != null) ? prov.ownerID
                    : (prov.ownerId != null) ? prov.ownerId
                    : (prov.owner != null) ? prov.owner
                    : (prov.playerID != null) ? prov.playerID : prov.playerId;
          if (owner != null){ var ok = String(owner); pc[ok] = (pc[ok] || 0) + 1; }
        }
      }
    }

    return JSON.stringify({
      day: day, victoryPoints: vp, players: players, playerStats: stats,
      relations: relations, coalitions: coal, scores: scores, provinceCounts: pc
    });
  } catch(e){
    return JSON.stringify({__error__: e.message, stack: (e.stack||'')});
  }
})()
"""


async def _run(no_build: bool):
    # 1) 找到遊戲分頁
    resp = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=10)
    targets = json.loads(resp.read())
    page = next((t for t in targets
                 if t.get("type") == "page"
                 and "supremacy1914.com/game" in t.get("url", "")), None)
    if not page:
        page = next((t for t in targets
                     if t.get("type") == "page"
                     and "supremacy1914" in t.get("url", "")), None)
    if not page:
        print("[ERR] 找不到 Supremacy 1914 遊戲分頁。請確認遊戲已開啟且 Chrome 已啟用遠端除錯。")
        return
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=80_000_000) as ws:
        mid = [0]

        async def send(method, params=None):
            mid[0] += 1
            m = {"id": mid[0], "method": method}
            if params:
                m["params"] = params
            await ws.send(json.dumps(m))
            while True:
                d = json.loads(await ws.recv())
                if d.get("id") == mid[0]:
                    return d

        await send("Runtime.enable")

        # 2) 找到 hup 所在的遊戲 iframe 執行環境
        game_ctx = None
        for cid in range(1, 50):
            r = await send("Runtime.evaluate", {
                "expression": "typeof hup !== 'undefined' ? 'yes' : 'no'",
                "contextId": cid, "returnByValue": True,
            })
            if r.get("result", {}).get("result", {}).get("value") == "yes":
                game_ctx = cid
                break
        if game_ctx is None:
            print("[ERR] 在頁面執行環境中找不到 hup（遊戲可能還在載入，請稍候重試）。")
            return

        async def eg(js):
            r = await send("Runtime.evaluate", {
                "expression": js, "contextId": game_ctx,
                "returnByValue": True, "awaitPromise": True,
            })
            res = r.get("result", {}).get("result", {})
            if res.get("subtype") == "error":
                return {"__error__": res.get("description", "JS error")}
            return res.get("value")

        print(f"[OK] 已連線遊戲執行環境 (contextId={game_ctx})，開始擷取…")
        raw = await eg(EXTRACT_JS)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict) and raw.get("__error__"):
            print("[ERR] 擷取失敗：", raw["__error__"])
            return

        # 3) 蓋時間戳並寫檔
        tz = timezone(timedelta(hours=8))
        raw["reportedAt"] = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S+08:00")

        day = raw.get("day")
        if day is None:
            print("[ERR] 無法取得遊戲日（day 為空），中止寫檔。")
            return

        os.makedirs(DATA_DIR, exist_ok=True)
        out_path = os.path.join(DATA_DIR, f"day_{day}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        pc = raw.get("provinceCounts", {})
        print(f"[OK] 寫入 {out_path}")
        print(f"  遊戲日={day} · 玩家={len(raw.get('players', []))} · "
              f"統計={len(raw.get('playerStats', {}))} · 聯盟={len(raw.get('coalitions', []))} · "
              f"領地記錄={len(pc)}")

        # 4) 重建儀表盤
        if not no_build:
            if not os.path.exists(OUT_PY):
                print("[WARN] 找不到 build_dashboard.py，跳過自動重建。")
                return
            print("[..] 重建儀表盤…")
            try:
                subprocess.run([sys.executable, OUT_PY], cwd=BASE, check=True)
            except subprocess.CalledProcessError as e:
                print(f"[WARN] 儀表盤重建失敗：{e}")


def main():
    no_build = "--no-build" in sys.argv
    try:
        asyncio.run(_run(no_build))
    except urllib.error.URLError:
        print("[ERR] 無法連線 127.0.0.1:9222。請確認 Chrome 已以 --remote-debugging-port=9222 啟動。")
    except Exception as e:
        print(f"[ERR] 未預期錯誤：{e}")


if __name__ == "__main__":
    main()
