# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 單日快照擷取器 (unified extractor).

功能：
  透過 Chrome DevTools Protocol (CDP) 連上正在遊玩的 Supremacy 1914 分頁，
  在遊戲 iframe 的執行環境內讀取 hup.gameState，一次性撈出：
    玩家 / 戰鬥統計 / 外交關係 / 聯盟(含分數) / 玩家分數 / 領地數
  並寫入 games/{gameID}/data/：同一遊戲日的首次報告為基準檔 day_{N}.json（納入趨勢/變化，並觸發儀表盤重建）；
同日後續報告加時間戳另存為 day_{N}_{YYYYMMDD_HHMMSS}.json（額外報告，不覆蓋基準、不進趨勢、不重建）。

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

同一遊戲日首次擷取寫入 day_{N}.json（基準，納入趨勢/變化）；
同日再次擷取不覆蓋，改存 day_{N}_{YYYYMMDD_HHMMSS}.json（額外報告，不進趨勢）。
真實擷取時刻記錄在檔案的 reportedAt 欄位。
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
GAMES_DIR = os.path.join(BASE, "games")
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

    // 對局開始時間（推算切日鐘點）與本地玩家 ID（自動標註「我」）
    var startInfo = {};
    if (gid) {
      ['startDate','startTime','start','startTimeStamp','createdAt','gameStartDate','matchStart'].forEach(function(k){
        if (gid[k] !== undefined && gid[k] !== null) startInfo[k] = gid[k];
      });
    }
    var myIdCandidate = null;
    for (var i=0;i<players.length;i++){ var pp=players[i]; if(pp.me===true||pp.isMe===true||pp.localPlayer===true){ myIdCandidate=pp.id; break; } }
    if (myIdCandidate==null){ try{ if(hup.localPlayerID!=null) myIdCandidate=hup.localPlayerID; }catch(e){} try{ if(hup.gameState&&hup.gameState.localPlayerID!=null) myIdCandidate=hup.gameState.localPlayerID; }catch(e){} }

    return JSON.stringify({
      day: day, victoryPoints: vp, players: players, playerStats: stats,
      relations: relations, coalitions: coal, scores: scores, provinceCounts: pc,
      startInfo: startInfo, myIdCandidate: myIdCandidate
    });
  } catch(e){
    return JSON.stringify({__error__: e.message, stack: (e.stack||'')});
  }
})()
"""


def parse_switch_clock(start_info):
    """從 GameInfo 的開始時間欄位推算每日切日的本地鐘點 (HH:MM)。失敗回傳 None。"""
    if not isinstance(start_info, dict):
        return None
    for k, v in start_info.items():
        # 數值型：視為 epoch（秒或毫秒）
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            s = v / 1000.0 if v > 1e11 else v
            try:
                dt = datetime.fromtimestamp(s)
                return f"{dt.hour:02d}:{dt.minute:02d}"
            except Exception:
                pass
        if isinstance(v, str):
            s2 = v.strip()
            # 僅當含時間成分（':' 或 'T'）才視為可推算；純日期無法取得鐘點
            if (":" in s2) or ("T" in s2):
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                            "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f%z",
                            "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        dt = datetime.strptime(s2, fmt)
                        return f"{dt.hour:02d}:{dt.minute:02d}"
                    except Exception:
                        pass
    return None


SWITCH_FALLBACK = "17:00"  # 無法自動推算時的預設切日鐘點（本對局已知約 17:00）


async def _run(no_build: bool):
    # 1) 找到遊戲分頁
    resp = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=10)
    targets = json.loads(resp.read())
    # 優先選擇網址含 gameID 的遊戲分頁
    candidates = [t for t in targets
                  if t.get("type") == "page"
                  and "supremacy1914.com/game" in t.get("url", "")]
    page = next((t for t in candidates
                 if "gameID=" in t.get("url", "")), None) or (candidates[0] if candidates else None)
    if not page:
        page = next((t for t in targets
                     if t.get("type") == "page"
                     and "supremacy1914" in t.get("url", "")), None)
    if not page:
        print("[ERR] 找不到 Supremacy 1914 遊戲分頁。請確認遊戲已開啟且 Chrome 已啟用遠端除錯。")
        return False

    # 從網址解析 gameID（對局編號）
    import re
    m = re.search(r"gameID=(\d+)", page.get("url", ""))
    if not m:
        print("[ERR] 無法從網址解析 gameID（對局編號）。請確認網址含 gameID= 參數。")
        return False
    game_id = m.group(1)
    print(f"[OK] 偵測到對局 gameID={game_id}")
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=80_000_000) as ws:
        mid = [0]
        _pending = {}
        _buffer = {}
        live_contexts = set()
        _closed = False
        reader_task = None

        async def send(method, params=None):
            mid[0] += 1
            m = {"id": mid[0], "method": method}
            if params:
                m["params"] = params
            q = asyncio.Queue()
            _pending[mid[0]] = q
            # 若該 id 的回應已先抵達（被 reader 緩衝），直接取用，不重送
            if mid[0] in _buffer:
                return _buffer.pop(mid[0])
            await ws.send(json.dumps(m))
            return await q.get()

        # 背景協程：持續接收 CDP 訊息
        #   - 帶 id 的回應 → 若 send 已註冊則立即交付；否則暫存緩衝（避免回應先到導致 send 永遠等待）
        #   - Runtime.executionContextCreated → 記錄 contextId（含背景分頁延遲建立的 iframe context）
        #   - Runtime.executionContextsCleared → 清空
        async def reader():
            while not _closed:
                try:
                    d = json.loads(await ws.recv())
                except Exception:
                    break
                rid = d.get("id")
                if rid is not None:
                    if rid in _pending:
                        await _pending.pop(rid).put(d)
                    else:
                        _buffer[rid] = d
                elif d.get("method") == "Runtime.executionContextCreated":
                    ctx = d.get("params", {}).get("context", {})
                    cid = ctx.get("id")
                    if cid is not None:
                        live_contexts.add(cid)
                elif d.get("method") == "Runtime.executionContextsCleared":
                    live_contexts.clear()

        reader_task = asyncio.ensure_future(reader())
        await send("Runtime.enable")

        # 2) 找到 hup 所在的遊戲 iframe 執行環境
        #    依 supremacy1914-monitoring 技能 §6/§7：背景/凍結分頁單次掃描會失敗，
        #    必須以事件驅動持續收集新建立的 execution contexts 並輪詢，
        #    且確認 hup.gameState.states 非空（client 已連線、資料已載入）才擷取，
        #    否則凍結/斷線分頁會吐空白資料（hup 存在但 states 被清空）。
        async def probe_hup(ctx):
            r = await send("Runtime.evaluate", {
                "expression": (
                    "typeof hup !== 'undefined' && typeof hup.gameState !== 'undefined' "
                    "&& hup.gameState.states && Object.keys(hup.gameState.states).length > 0 "
                    "? 'live' : (typeof hup !== 'undefined' ? 'dead' : 'no')"
                ),
                "contextId": ctx, "returnByValue": True,
            })
            return r.get("result", {}).get("result", {}).get("value")

        try:
            game_ctx = None
            dead_ctx = None
            seen_hup_undefined = False
            poll_deadline = time.monotonic() + 20  # 背景/凍結分頁延遲建立 context，拉長視窗
            while time.monotonic() < poll_deadline:
                # 事件收集到的 contexts；若事件尚未送達則用固定範圍備援掃描（雙保險）
                cids = set(live_contexts)
                if not cids:
                    cids = set(range(1, 60))
                for cid in cids:
                    st = await probe_hup(cid)
                    if st == "live":
                        game_ctx = cid
                        break
                    if st == "dead" and dead_ctx is None:
                        dead_ctx = cid
                    if st == "no":
                        seen_hup_undefined = True
                if game_ctx is not None:
                    break
                await asyncio.sleep(0.4)

            if game_ctx is None:
                if dead_ctx is not None:
                    print("[ERR] 找到遊戲分頁，但 hup.gameState.states 為空（分頁已凍結 / 與伺服器斷線）。"
                          "請點擊並聚焦遊戲分頁，待其重新連線後再重試。")
                elif seen_hup_undefined:
                    print("[ERR] 已掃描到分頁執行環境，但其中找不到 hup（遊戲腳本可能尚未載入完成）。"
                          "請確認遊戲已完全進入對局畫面，並讓該分頁保持前景（點進該分頁、不要被其他視窗蓋住），稍候重試。")
                else:
                    print("[ERR] 在頁面執行環境中找不到任何執行上下文（分頁可能凍結 / 未開啟 / 非遊戲分頁）。"
                          "請點擊並聚焦遊戲分頁，待其重新連線後再重試。")
                return False

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
                return False

            # 3) 蓋時間戳、標註 gameID 並寫檔（按對局分資料夾）
            tz = timezone(timedelta(hours=8))
            raw["reportedAt"] = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S+08:00")
            raw["gameID"] = game_id

            day = raw.get("day")
            if day is None:
                print("[ERR] 無法取得遊戲日（day 為空），中止寫檔。")
                return False

            game_dir = os.path.join(GAMES_DIR, game_id)
            data_dir = os.path.join(game_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            canonical_path = os.path.join(data_dir, f"day_{day}.json")
            # 當日首次報告 → 寫入 day_{N}.json（基準，納入趨勢/變化）；
            # 同日後續報告 → 加時間戳另存為額外報告，不覆蓋基準、不進趨勢。
            is_first = not os.path.exists(canonical_path)
            if is_first:
                out_path = canonical_path
                action = "當日首次報告（基準）"
            else:
                ts = datetime.now(tz).strftime("%Y%m%d_%H%M%S")
                out_path = os.path.join(data_dir, f"day_{day}_{ts}.json")
                action = "額外報告（加時間戳，不納入趨勢/變化）"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)

            pc = raw.get("provinceCounts", {})
            print(f"[OK] 寫入 {out_path}  [{action}]")
            print(f"  對局={game_id} · 遊戲日={day} · 玩家={len(raw.get('players', []))} · "
                  f"統計={len(raw.get('playerStats', {}))} · 聯盟={len(raw.get('coalitions', []))} · "
                  f"領地記錄={len(pc)}")

            # 3.5) 僅「當日首次報告」寫入對局 meta（切日鐘點 + 我的 ID），供自動化排程與「我」標註使用
            if is_first:
                start_info = raw.get("startInfo", {})
                switch_clock = parse_switch_clock(start_info) or SWITCH_FALLBACK
                if switch_clock == SWITCH_FALLBACK and start_info:
                    print(f"[WARN] 無法從 GameInfo 推算切日鐘點，暫用預設 {SWITCH_FALLBACK}（不正確可在 games/{game_id}/meta.json 手調）。")
                my_id = raw.get("myIdCandidate")
                if my_id is None:
                    my_id = int(os.environ.get("MY_ID", 22))
                meta = {
                    "gameID": game_id,
                    "switchClock": switch_clock,
                    "myID": my_id,
                    "lastDay": day,
                    "updatedAt": raw.get("reportedAt"),
                }
                with open(os.path.join(game_dir, "meta.json"), "w", encoding="utf-8") as mf:
                    json.dump(meta, mf, ensure_ascii=False, indent=2)
                print(f"[OK] 對局 meta：切日鐘點={switch_clock} · 我的ID={my_id}")

            # 4) 產出可檢視 HTML
            if not os.path.exists(OUT_PY):
                print("[WARN] 找不到 build_dashboard.py，跳過 HTML 產出。")
            elif is_first and not no_build:
                # 當日首次報告 → 重建主面板（含該日基準，會出現在趨勢/變化）
                print("[..] 重建主面板…")
                try:
                    subprocess.run([sys.executable, OUT_PY], cwd=BASE, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"[WARN] 主面板重建失敗：{e}")
            elif not is_first:
                # 額外報告 → 產生獨立快照 HTML（不動主面板、不進趨勢）
                if no_build:
                    print(f"[INFO] --no-build：額外報告不產生獨立 HTML。")
                else:
                    print("[..] 產生額外報告獨立 HTML…")
                    try:
                        subprocess.run([sys.executable, OUT_PY, "--single", out_path], cwd=BASE, check=True)
                    except subprocess.CalledProcessError as e:
                        print(f"[WARN] 額外報告 HTML 產生失敗：{e}")
            return True
        finally:
            _closed = True
            if reader_task is not None:
                reader_task.cancel()
                try:
                    await asyncio.wait_for(reader_task, timeout=1.0)
                except BaseException:
                    pass


def main():
    no_build = "--no-build" in sys.argv
    ok = False
    try:
        ok = asyncio.run(_run(no_build)) or False
    except urllib.error.URLError:
        print("[ERR] 無法連線 127.0.0.1:9222。請確認 Chrome 已以 --remote-debugging-port=9222 啟動。")
    except Exception as e:
        print(f"[ERR] 未預期錯誤：{e}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
