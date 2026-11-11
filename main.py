import asyncio
import json
import logging
import os
import shlex
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "128835770"))
DB_PATH = os.getenv("DB_PATH", "/data/scores.sqlite3")
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(Path(DB_PATH).parent / "media")))
PUBLIC_BASE_URL = os.getenv("APP_URL", "").strip().rstrip("/")
if not PUBLIC_BASE_URL and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_BASE_URL = "https://" + os.getenv("RAILWAY_PUBLIC_DOMAIN").strip()
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("team-score")

WIDGET_HTML = r"""<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;padding:4px;font:13px system-ui;color:var(--tg-theme-text-color);background:var(--tg-theme-bg-color);background-image:var(--bg);background-size:cover;background-position:center}.board{padding:4px;border-radius:10px;background:color-mix(in srgb,var(--tg-theme-bg-color) 88%,transparent)}.podium{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-bottom:6px}.place,.team{background:var(--tg-theme-secondary-bg-color);border:1px solid var(--tg-theme-section-separator-color);border-radius:7px}.place{text-align:center;padding:6px 3px;min-width:0}.medal{font-size:15px}.pic{width:48px;height:48px;object-fit:cover;border-radius:50%;display:block;margin:4px auto}.pname{font-size:10px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.score{font-weight:900;font-size:14px}.section{font-size:9px;color:var(--tg-theme-hint-color);margin:5px 0}.rows{display:grid;gap:3px}.team{display:grid;grid-template-columns:18px 1fr auto;align-items:center;gap:4px;padding:4px}.rank{font-size:10px;color:var(--tg-theme-hint-color)}.name{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.controls{display:flex;gap:3px;margin-top:4px}.team .controls{margin:0}.controls button{border:0;border-radius:4px;padding:4px;background:var(--tg-theme-bg-color);color:var(--tg-theme-text-color);font-weight:800;font-size:10px}.admin-mode .team{grid-template-columns:18px 1fr auto 82px}.status{font-size:10px;color:var(--tg-theme-hint-color);margin-top:4px}
</style><div class="board"><div id="podium" class="podium"></div><div class="section">ОСТАЛЬНЫЕ КОМАНДЫ</div><div id="rows" class="rows"></div></div><div id="admin" hidden class="section">Переименовать: /rename 3 Новое название</div><div id="status" class="status">Загрузка…</div>
<script>
const W=window.TelegramWidget,$=id=>document.getElementById(id);let state={teams:[]},busy=false;
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function render(){let ts=[...state.teams].sort((a,b)=>b.score-a.score||a.id-b.id),admin=Number(W.viewer&&W.viewer.id)===128835770;document.body.classList.toggle('admin-mode',admin);$('admin').hidden=!admin;
$('podium').innerHTML=ts.slice(0,3).map((t,i)=>'<div class="place"><div class="medal">'+['🥇','🥈','🥉'][i]+'</div>'+(t.image_url?'<img class="pic" src="'+esc(t.image_url)+'">':'')+'<div class="pname">'+esc(t.name)+'</div><div class="score">'+t.score+'</div>'+(admin?'<div class="controls"><button data-id="'+t.id+'" data-d="50">+50</button><button data-id="'+t.id+'" data-d="100">+100</button></div>':'')+'</div>').join('');
$('rows').innerHTML=ts.slice(3).map((t,i)=>'<div class="team"><span class="rank">'+(i+4)+'</span><span class="name">'+esc(t.name)+'</span><b class="score">'+t.score+'</b>'+(admin?'<div class="controls"><button data-id="'+t.id+'" data-d="50">+50</button><button data-id="'+t.id+'" data-d="100">+100</button></div>':'')+'</div>').join('');$('status').textContent=admin?'Режим администратора':'Просмотр'}
function read(){try{state=JSON.parse(W.chatData||'{}')}catch(e){state={teams:[]}}if(!Array.isArray(state.teams))state.teams=[];if(state.background_url)document.body.style.setProperty('--bg','url("'+state.background_url+'")');render()}
document.addEventListener('click',e=>{let b=e.target.closest('button[data-id]');if(!b||busy)return;busy=true;$('status').textContent='Сохраняем…';W.request('score:'+b.dataset.id+':'+b.dataset.d).then(a=>{if(a.result){state=JSON.parse(a.result);render()}$('status').textContent='Обновлено'}).catch(()=>$('status').textContent='Ошибка').finally(()=>busy=false)});
W.onEvent('chatDataChanged',read);read();W.request('refresh').then(a=>{if(a.result){state=JSON.parse(a.result);render()}}).catch(()=>{});
</script>"""

def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=20000")
    return con

def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY, name TEXT NOT NULL, score INTEGER NOT NULL DEFAULT 0)")
        columns = {r["name"] for r in c.execute("PRAGMA table_info(teams)")}
        if "image_file" not in columns:
            c.execute("ALTER TABLE teams ADD COLUMN image_file TEXT")
        c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER, team_name TEXT, delta INTEGER, reason TEXT, created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS subscribers(chat_id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL)")
        if c.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 0:
            c.executemany("INSERT INTO teams(id,name,score) VALUES(?,?,0)", [(i, f"Команда {i}") for i in range(1,11)])

def snapshot():
    with db() as c:
        teams = [dict(r) for r in c.execute("SELECT id,name,score,image_file FROM teams ORDER BY score DESC,id")]
        background = c.execute("SELECT value FROM settings WHERE key='background'").fetchone()
    for team in teams:
        team["image_url"] = f"{PUBLIC_BASE_URL}/media/{team['image_file']}" if team.get("image_file") and PUBLIC_BASE_URL else None
        team.pop("image_file", None)
    return {"teams": teams, "background_url": f"{PUBLIC_BASE_URL}/media/{background['value']}" if background and PUBLIC_BASE_URL else None}

async def api(session, method, payload):
    request_timeout = aiohttp.ClientTimeout(
        total=70 if method == "getUpdates" else 25,
        connect=15,
        sock_read=65 if method == "getUpdates" else 20,
    )
    async with session.post(f"{API}/{method}", json=payload, timeout=request_timeout) as resp:
        data = await resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"{method}: {data.get('description', data)}")
        return data["result"]

async def send_state_to_subscribers(session):
    state = json.dumps(snapshot(), ensure_ascii=False, separators=(",",":"))
    with db() as c:
        subscribers = [dict(r) for r in c.execute("SELECT chat_id,message_id FROM subscribers")]
    for s in subscribers:
        try:
            await api(session, "editMessageWidgetData", {"chat_id":s["chat_id"],"message_id":s["message_id"],"chat_data":state})
        except Exception as e:
            log.warning("Could not update widget for %s: %s", s["chat_id"], e)

async def send_widget(session, chat_id):
    msg = await api(session, "sendWidget", {
        "chat_id": chat_id,
        "html": WIDGET_HTML,
        "allow_queries": True,
        "chat_data": json.dumps(snapshot(), ensure_ascii=False, separators=(",",":"))
    })
    with db() as c:
        c.execute("INSERT OR REPLACE INTO subscribers(chat_id,message_id) VALUES(?,?)", (chat_id,msg["message_id"]))

async def answer_query(session, query_id, data=None):
    payload = {"widget_query_id": query_id}
    if data is not None:
        payload["data"] = json.dumps(data, ensure_ascii=False, separators=(",",":")) if not isinstance(data,str) else data
    await api(session, "answerWidgetQuery", payload)

async def handle_message(session, msg):
    chat = msg.get("chat", {})
    if chat.get("type") != "private":
        await api(session, "sendMessage", {"chat_id":chat["id"],"text":"Табло пока доступно в личном чате с ботом. Откройте @newscorept_bot."})
        return
    text = (msg.get("text") or "").strip()
    user_id = msg.get("from",{}).get("id")
    if text.startswith("/start"):
        await send_widget(session, chat["id"])
        return
    if text.startswith("/rename"):
        if user_id != ADMIN_ID:
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":"У тебя нет прав администратора."}); return
        try:
            parts=shlex.split(text)
            if len(parts)<3: raise ValueError()
            team_id=int(parts[1]); name=" ".join(parts[2:]).strip()
            if not 1<=team_id<=10 or not name or len(name)>32: raise ValueError()
            with db() as c:
                c.execute("UPDATE teams SET name=? WHERE id=?",(name,team_id))
                c.execute("INSERT INTO history(team_id,team_name,delta,reason,created_at) VALUES(?,?,?,?,?)",(team_id,name,0,"Изменено название",datetime.now(timezone.utc).isoformat()))
            await send_state_to_subscribers(session)
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":f"Название команды {team_id} изменено на «{name}»."})
        except Exception:
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":"Формат: /rename 3 Новое название (номер команды от 1 до 10, до 32 символов)."})
        return
    if msg.get("photo"):
        if user_id != ADMIN_ID:
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":"Загружать изображения может только администратор."}); return
        caption=(msg.get("caption") or "").strip().split()
        try:
            if len(caption)==1 and caption[0].lower()=="/background":
                kind="background"; team_id=None
            elif len(caption)==2 and caption[0].lower()=="/team":
                team_id=int(caption[1])
                if not 1<=team_id<=10: raise ValueError()
                kind="team"
            else: raise ValueError()
            if not PUBLIC_BASE_URL: raise RuntimeError("Set APP_URL or RAILWAY_PUBLIC_DOMAIN")
            photo=msg["photo"][-1]
            file_info=await api(session,"getFile",{"file_id":photo["file_id"]})
            async with session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info['file_path']}") as response:
                response.raise_for_status()
                image_bytes=await response.read()
            if len(image_bytes)>10*1024*1024: raise ValueError("Image exceeds 10 MB")
            MEDIA_DIR.mkdir(parents=True,exist_ok=True)
            filename=f"{kind}_{team_id if team_id is not None else 'main'}.jpg"
            (MEDIA_DIR/filename).write_bytes(image_bytes)
            with db() as c:
                if kind=="team": c.execute("UPDATE teams SET image_file=? WHERE id=?",(filename,team_id))
                else: c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('background',?)",(filename,))
            await send_state_to_subscribers(session)
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":("Изображение команды "+str(team_id)+" обновлено.") if kind=="team" else "Фон табло обновлён."})
        except Exception:
            log.exception("Image upload failed")
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":"Не удалось загрузить. Отправь фото с подписью /team 3 или /background. Убедись, что задан публичный URL приложения (APP_URL)."})
        return
    if text.startswith("/reset"):
        if user_id != ADMIN_ID:
            await api(session,"sendMessage",{"chat_id":chat["id"],"text":"У тебя нет прав администратора."}); return
        with db() as c:
            c.execute("UPDATE teams SET score=0")
            c.execute("INSERT INTO history(team_id,team_name,delta,reason,created_at) VALUES(NULL,'Все команды',0,'Сброс всех баллов',?)",(datetime.now(timezone.utc).isoformat(),))
        await send_state_to_subscribers(session)
        await api(session,"sendMessage",{"chat_id":chat["id"],"text":"Баллы всех команд сброшены до нуля."})
        return
    await api(session,"sendMessage",{"chat_id":chat["id"],"text":"Нажми /start, чтобы открыть табло.\n\nИзменить название: /rename 3 Новое название\nФото команды: отправь фото с подписью /team 3\nФон табло: отправь фото с подписью /background\nСбросить баллы: /reset"})

async def handle_widget_query(session, q):
    user_id=q.get("from",{}).get("id")
    chat=q.get("chat",{})
    chat_id=chat.get("id")
    message_id=q.get("message_id")
    data=(q.get("data") or "").strip()
    if not chat_id or chat.get("type")!="private":
        await answer_query(session,q["id"],{"error":"Табло доступно только в личном чате с ботом."}); return
    if data=="refresh":
        await answer_query(session,q["id"],snapshot()); return
    if data.startswith("score:"):
        if user_id != ADMIN_ID:
            await answer_query(session,q["id"],{"error":"Нет прав администратора"}); return
        try:
            _, team_id, delta = data.split(":")
            team_id=int(team_id); delta=int(delta)
            if not 1<=team_id<=10 or delta not in (50,100): raise ValueError()
            with db() as c:
                row=c.execute("SELECT name,score FROM teams WHERE id=?",(team_id,)).fetchone()
                if row is None: raise ValueError()
                new_score=max(0,row["score"]+delta)
                actual=new_score-row["score"]
                c.execute("UPDATE teams SET score=? WHERE id=?",(new_score,team_id))
                if actual:
                    c.execute("INSERT INTO history(team_id,team_name,delta,reason,created_at) VALUES(?,?,?,?,?)",(team_id,row["name"],actual,"Начисление через табло",datetime.now(timezone.utc).isoformat()))
            state=snapshot()
            if message_id:
                try: await api(session,"editMessageWidgetData",{"chat_id":chat_id,"message_id":message_id,"chat_data":json.dumps(state,ensure_ascii=False,separators=(",",":"))})
                except Exception as e: log.warning("Widget state update failed: %s",e)
            await answer_query(session,q["id"],state)
            await send_state_to_subscribers(session)
        except Exception as e:
            log.exception("Score action failed")
            await answer_query(session,q["id"],{"error":"Не удалось изменить баллы"})
        return
    await answer_query(session,q["id"],{"error":"Неизвестная команда"})

async def media_handler(request):
    filename=Path(request.match_info["filename"]).name
    path=MEDIA_DIR/filename
    if not path.is_file(): raise web.HTTPNotFound()
    return web.FileResponse(path,headers={"Cache-Control":"public, max-age=3600"})

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN in Railway Variables")
    init_db()
    app=web.Application()
    app.router.add_get("/media/{filename}",media_handler)
    runner=web.AppRunner(app)
    await runner.setup()
    site=web.TCPSite(runner,"0.0.0.0",int(os.getenv("PORT","8080")))
    await site.start()
    async with aiohttp.ClientSession() as session:
        me=await api(session,"getMe",{})
        log.info("Bot started: @%s; admin=%s; database=%s",me["username"],ADMIN_ID,DB_PATH)
        offset=None
        while True:
            try:
                payload={"timeout":50,"allowed_updates":["message","widget_query"]}
                if offset is not None: payload["offset"]=offset
                updates=await api(session,"getUpdates",payload)
                for update in updates:
                    offset=update["update_id"]+1
                    try:
                        if "message" in update: await handle_message(session,update["message"])
                        elif "widget_query" in update: await handle_widget_query(session,update["widget_query"])
                    except Exception:
                        log.exception("Update handler failed")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Polling failed; retrying in 3 seconds")
                await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
