from __future__ import annotations

import html
import json
from typing import Any, Mapping


REALTIME_TERMS = (
    "webrtc",
    "video call",
    "voice call",
    "audio call",
    "calling app",
    "video conference",
    "voice conference",
    "realtime communication",
    "real-time communication",
    "مكالم",
    "محادثة صوت",
    "محادثة فيديو",
    "اتصال صوتي",
    "اتصال مرئي",
)


def is_realtime_objective(objective: str) -> bool:
    lowered = objective.casefold()
    if any(term.casefold() in lowered for term in REALTIME_TERMS):
        return True
    arabic_communication = any(term in lowered for term in ("اتصال", "اتصالات", "محادثة"))
    arabic_media = any(term in lowered for term in ("صوت", "فيديو", "صوره", "صورة"))
    english_communication = any(term in lowered for term in ("call", "calling", "conference", "communication"))
    english_media = any(term in lowered for term in ("audio", "voice", "video"))
    return (arabic_communication and arabic_media) or (english_communication and english_media)

MOBILE_TERMS = (
    "mobile app", "android", "ios", "تطبيق موبايل", "تطبيق هاتف",
    "اندرويد", "أندرويد", "ايفون", "آيفون",
)
API_TERMS = ("api service", "backend api", "rest api", "خدمة api", "واجهة برمجية")


def infer_application_type(objective: str, declared: str) -> str:
    """Select the governed implementation family without rejecting valid project ideas.

    Realtime communications keeps its dedicated hardened runtime. Every other legal,
    buildable project is routed to the universal capability composer, which can emit
    multiple targets (web/API/mobile/desktop/AI/data/bots/etc.) in one delivery.
    """
    if is_realtime_objective(objective):
        return "realtime_communications"
    return "universal_application"


def render_realtime_communications(
    project: str,
    objective: str,
    spec: Mapping[str, Any],
    planning: Mapping[str, Any],
) -> dict[str, str]:
    brand = dict(spec["brand"])
    primary = str(brand["primary"])
    secondary = str(brand["secondary"])
    accent = str(brand["accent"])
    surface = str(brand["surface"])
    title = html.escape(str(spec["title"]))
    tagline = html.escape(str(spec["tagline"]))
    safe_spec = json.dumps(spec, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")

    index = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />
  <meta name="theme-color" content="{surface}" />
  <meta name="description" content="{html.escape(str(spec['summary']))}" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'" />
  <link rel="manifest" href="manifest.webmanifest" />
  <link rel="stylesheet" href="styles.css" />
  <title>{title}</title>
</head>
<body>
  <header class="topbar">
    <div class="brand"><img src="logo.svg" alt="" /><div><strong>{title}</strong><span>Secure member calling</span></div></div>
    <button id="logout-button" class="ghost" type="button" hidden>Sign out</button>
  </header>
  <main>
    <section class="hero">
      <span class="eyebrow">AIONEX governed realtime application</span>
      <h1>{title}</h1>
      <p>{tagline}</p>
      <div class="trust-row"><span>Registered members</span><span>Audio + video</span><span>Same-origin signaling</span></div>
    </section>

    <section id="auth-panel" class="panel auth-grid">
      <form id="register-form" autocomplete="off">
        <h2>Create member account</h2>
        <label>Username<input name="username" minlength="3" maxlength="40" required autocomplete="username" /></label>
        <label>Password<input name="password" type="password" minlength="12" maxlength="128" required autocomplete="new-password" /></label>
        <button type="submit">Register</button>
      </form>
      <form id="login-form" autocomplete="off">
        <h2>Sign in</h2>
        <label>Username<input name="username" minlength="3" maxlength="40" required autocomplete="username" /></label>
        <label>Password<input name="password" type="password" minlength="12" maxlength="128" required autocomplete="current-password" /></label>
        <button type="submit">Sign in</button>
      </form>
      <p id="auth-status" class="status" aria-live="polite"></p>
    </section>

    <section id="call-panel" class="app-grid" hidden>
      <aside class="panel members-panel">
        <div class="section-head"><div><span class="eyebrow">Members</span><h2>Available people</h2></div><button id="refresh-members" class="ghost" type="button">Refresh</button></div>
        <ul id="member-list" class="member-list"></ul>
      </aside>
      <section class="panel call-stage">
        <div class="section-head"><div><span class="eyebrow">Call</span><h2 id="peer-name">Select a member</h2></div><span id="call-badge" class="badge">Idle</span></div>
        <div class="videos">
          <figure><video id="remote-video" autoplay playsinline></video><figcaption>Remote</figcaption></figure>
          <figure class="local"><video id="local-video" autoplay muted playsinline></video><figcaption>You</figcaption></figure>
        </div>
        <div class="call-actions">
          <button id="start-call" type="button" disabled>Start secure call</button>
          <button id="hangup-call" class="danger" type="button" disabled>Hang up</button>
        </div>
        <p id="call-status" class="status" aria-live="polite">Sign in and select a member.</p>
      </section>
    </section>

    <section class="panel boundary">
      <h2>Runtime boundary</h2>
      <p>This delivery contains functional local member authentication, signaling and browser WebRTC. Public-internet reliability still requires operator-provided STUN/TURN infrastructure and HTTPS deployment; no external relay credential is embedded.</p>
    </section>
  </main>
  <footer>Generated from a governed plan. Production deployment is not claimed.</footer>
  <script id="project-data" type="application/json">{safe_spec}</script>
  <script src="app.js" defer></script>
</body>
</html>
'''

    css = f''':root{{--primary:{primary};--secondary:{secondary};--accent:{accent};--surface:{surface};font-family:Inter,ui-sans-serif,system-ui,sans-serif;color-scheme:dark;background:#020308;color:#fff}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 2%,color-mix(in srgb,var(--secondary) 28%,transparent),transparent 34%),radial-gradient(circle at 90% 18%,color-mix(in srgb,var(--primary) 20%,transparent),transparent 38%),#020308;color:#f8fafc}}button,input{{font:inherit}}button{{border:0;border-radius:1rem;padding:.85rem 1rem;background:linear-gradient(135deg,var(--secondary),var(--accent));color:white;font-weight:800;cursor:pointer}}button:disabled{{opacity:.45;cursor:not-allowed}}button.ghost{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12)}}button.danger{{background:linear-gradient(135deg,var(--primary),#7f1d1d)}}.topbar{{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;padding:1rem clamp(1rem,5vw,4rem);background:rgba(2,3,8,.88);backdrop-filter:blur(20px);border-bottom:1px solid rgba(255,255,255,.08)}}.brand{{display:flex;align-items:center;gap:.8rem}}.brand img{{width:48px;height:48px}}.brand div{{display:grid}}.brand span,.eyebrow{{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:#94a3b8}}main{{width:min(1180px,calc(100% - 2rem));margin:auto}}.hero{{padding:clamp(4rem,10vw,7rem) 0 2rem}}.hero h1{{font-size:clamp(3rem,9vw,6.4rem);line-height:.92;margin:.8rem 0;max-width:900px}}.hero p{{max-width:760px;color:#cbd5e1;line-height:1.75;font-size:1.05rem}}.trust-row{{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1.4rem}}.trust-row span,.badge{{border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.04);border-radius:999px;padding:.5rem .75rem;color:#cbd5e1}}.panel{{border:1px solid rgba(255,255,255,.09);background:linear-gradient(150deg,rgba(255,255,255,.055),rgba(255,255,255,.025));border-radius:1.6rem;padding:1.25rem;box-shadow:0 24px 70px rgba(0,0,0,.25)}}.auth-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}}form{{display:grid;gap:.9rem}}label{{display:grid;gap:.45rem;color:#cbd5e1}}input{{width:100%;min-width:0;border:1px solid rgba(255,255,255,.12);background:#05070d;color:#fff;border-radius:1rem;padding:1rem;outline:none}}input:focus{{border-color:var(--secondary);box-shadow:0 0 0 3px color-mix(in srgb,var(--secondary) 18%,transparent)}}.status{{min-height:1.5rem;color:#94a3b8}}.auth-grid>.status{{grid-column:1/-1}}.app-grid{{display:grid;grid-template-columns:minmax(250px,.7fr) minmax(0,1.8fr);gap:1rem}}.section-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}}.section-head h2{{margin:.35rem 0}}.member-list{{list-style:none;padding:0;margin:1rem 0 0;display:grid;gap:.55rem}}.member-list button{{width:100%;text-align:left;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);display:flex;justify-content:space-between}}.member-list button.active{{border-color:var(--secondary);background:color-mix(in srgb,var(--secondary) 12%,transparent)}}.videos{{position:relative;display:grid;grid-template-columns:1fr;min-height:420px;background:#000;border-radius:1.4rem;overflow:hidden}}figure{{margin:0;position:relative}}video{{width:100%;height:100%;object-fit:cover;background:#000}}figcaption{{position:absolute;left:.8rem;bottom:.8rem;background:rgba(0,0,0,.55);padding:.35rem .55rem;border-radius:.6rem;font-size:.75rem}}figure.local{{position:absolute;right:1rem;bottom:1rem;width:min(30%,220px);aspect-ratio:3/4;border:1px solid rgba(255,255,255,.2);border-radius:1rem;overflow:hidden;box-shadow:0 16px 40px rgba(0,0,0,.45)}}.call-actions{{display:flex;gap:.7rem;flex-wrap:wrap;margin-top:1rem}}.boundary{{margin:1rem 0 3rem}}.boundary p{{color:#94a3b8;line-height:1.7}}footer{{padding:2rem;text-align:center;color:#64748b}}@media(max-width:800px){{.auth-grid,.app-grid{{grid-template-columns:1fr}}.videos{{min-height:360px}}figure.local{{width:34%}}}}@media(max-width:520px){{main{{width:min(100% - 1rem,1180px)}}.topbar{{padding:.8rem}}.hero{{padding-top:3rem}}.panel{{border-radius:1.2rem;padding:1rem}}.videos{{min-height:310px}}figure.local{{width:38%;right:.65rem;bottom:.65rem}}input{{font-size:16px}}}}
'''

    app = r'''"use strict";
const spec=JSON.parse(document.getElementById("project-data").textContent);
const authPanel=document.getElementById("auth-panel"),callPanel=document.getElementById("call-panel"),memberList=document.getElementById("member-list"),authStatus=document.getElementById("auth-status"),callStatus=document.getElementById("call-status"),localVideo=document.getElementById("local-video"),remoteVideo=document.getElementById("remote-video"),startButton=document.getElementById("start-call"),hangupButton=document.getElementById("hangup-call"),logoutButton=document.getElementById("logout-button"),peerName=document.getElementById("peer-name"),callBadge=document.getElementById("call-badge");
let me=null,csrf="",selected=null,peer=null,localStream=null,lastSignal=0,pollTimer=null,runtimeConfig={iceServers:[]};
const request=async(path,options={})=>{const response=await fetch(path,{...options,headers:{"Content-Type":"application/json",...(csrf?{"X-CSRF-Token":csrf}:{}),...(options.headers||{})}});const payload=await response.json();if(!response.ok)throw new Error(payload.error||"Request failed");return payload};
const formPayload=form=>Object.fromEntries(new FormData(form).entries());
const setCallState=(text,badge=text)=>{callStatus.textContent=text;callBadge.textContent=badge};
async function loadRuntime(){try{runtimeConfig=await request("/runtime-config.json")}catch(_){runtimeConfig={iceServers:[]}}}
async function restoreSession(){try{const payload=await request("/api/me");me=payload.user;csrf=payload.csrf_token||"";await enterApp()}catch(_){authPanel.hidden=false;callPanel.hidden=true}}
async function enterApp(){authPanel.hidden=true;callPanel.hidden=false;logoutButton.hidden=false;await loadMembers();startPolling();setCallState(`Signed in as ${me.username}`)}
async function loadMembers(){const payload=await request("/api/members");memberList.replaceChildren();for(const member of payload.members){const button=document.createElement("button");button.type="button";button.dataset.userId=String(member.id);button.textContent=member.username;button.addEventListener("click",()=>{selected=member;for(const node of memberList.querySelectorAll("button"))node.classList.toggle("active",node===button);peerName.textContent=member.username;startButton.disabled=false;setCallState(`Ready to call ${member.username}`)});const row=document.createElement("li");row.append(button);memberList.append(row)}}
async function ensureMedia(){if(localStream)return localStream;localStream=await navigator.mediaDevices.getUserMedia({audio:true,video:true});localVideo.srcObject=localStream;return localStream}
async function createPeer(targetId){if(peer)peer.close();peer=new RTCPeerConnection({iceServers:runtimeConfig.iceServers||[]});const stream=await ensureMedia();for(const track of stream.getTracks())peer.addTrack(track,stream);peer.addEventListener("track",event=>{remoteVideo.srcObject=event.streams[0]});peer.addEventListener("icecandidate",event=>{if(event.candidate)void sendSignal(targetId,"ice",event.candidate.toJSON())});peer.addEventListener("connectionstatechange",()=>{if(peer)setCallState(`Connection: ${peer.connectionState}`,peer.connectionState)});return peer}
async function sendSignal(targetId,type,payload){return request("/api/signals",{method:"POST",body:JSON.stringify({to_user_id:targetId,type,payload})})}
async function startCall(){if(!selected)return;startButton.disabled=true;hangupButton.disabled=false;setCallState(`Calling ${selected.username}...`,"Calling");const pc=await createPeer(selected.id);const offer=await pc.createOffer();await pc.setLocalDescription(offer);await sendSignal(selected.id,"offer",pc.localDescription)}
async function handleSignal(signal){const sender={id:signal.from_user_id,username:signal.from_username};if(signal.type==="offer"){selected=sender;peerName.textContent=sender.username;startButton.disabled=true;hangupButton.disabled=false;setCallState(`Incoming call from ${sender.username}`,"Incoming");const pc=await createPeer(sender.id);await pc.setRemoteDescription(signal.payload);const answer=await pc.createAnswer();await pc.setLocalDescription(answer);await sendSignal(sender.id,"answer",pc.localDescription);setCallState(`Connected with ${sender.username}`,"Connected");return}if(!peer||!selected||selected.id!==sender.id)return;if(signal.type==="answer"){await peer.setRemoteDescription(signal.payload);setCallState(`Connected with ${sender.username}`,"Connected")}else if(signal.type==="ice"){try{await peer.addIceCandidate(signal.payload)}catch(_){setCallState("ICE candidate could not be applied","Network")}}else if(signal.type==="hangup"){endLocalCall(false)}}
async function pollSignals(){try{const payload=await request(`/api/signals?after=${lastSignal}`);for(const signal of payload.signals){lastSignal=Math.max(lastSignal,signal.id);await handleSignal(signal)}}catch(error){callStatus.textContent=error.message}}
function startPolling(){if(pollTimer)clearInterval(pollTimer);pollTimer=setInterval(()=>void pollSignals(),900);void pollSignals()}
function endLocalCall(notify=true){if(notify&&selected)void sendSignal(selected.id,"hangup",{});if(peer){peer.close();peer=null}remoteVideo.srcObject=null;hangupButton.disabled=true;startButton.disabled=!selected;setCallState(selected?`Ready to call ${selected.username}`:"Select a member","Idle")}
document.getElementById("register-form").addEventListener("submit",async event=>{event.preventDefault();try{await request("/api/register",{method:"POST",body:JSON.stringify(formPayload(event.currentTarget))});authStatus.textContent="Account created. Sign in to continue.";event.currentTarget.reset()}catch(error){authStatus.textContent=error.message}});
document.getElementById("login-form").addEventListener("submit",async event=>{event.preventDefault();try{const payload=await request("/api/login",{method:"POST",body:JSON.stringify(formPayload(event.currentTarget))});me=payload.user;csrf=payload.csrf_token;await enterApp()}catch(error){authStatus.textContent=error.message}});
document.getElementById("refresh-members").addEventListener("click",()=>void loadMembers());startButton.addEventListener("click",()=>void startCall().catch(error=>setCallState(error.message,"Error")));hangupButton.addEventListener("click",()=>endLocalCall(true));logoutButton.addEventListener("click",async()=>{try{await request("/api/logout",{method:"POST",body:"{}"})}finally{location.reload()}});
window.addEventListener("beforeunload",()=>{if(peer)peer.close();if(localStream)for(const track of localStream.getTracks())track.stop()});
void loadRuntime().then(restoreSession);
'''

    server = r'''from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parent
MAX_BODY_BYTES=64*1024
SESSION_SECONDS=12*60*60
USERNAME=re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
SIGNAL_TYPES={"offer","answer","ice","hangup"}

def _hash_password(password:str,salt:bytes)->str:
    return hashlib.scrypt(password.encode("utf-8"),salt=salt,n=2**15,r=8,p=1,maxmem=64*1024*1024,dklen=32).hex()

def initialize(database_path:Path)->None:
    with sqlite3.connect(database_path) as db:
        db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,salt TEXT NOT NULL,created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,csrf TEXT NOT NULL,expires_at INTEGER NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,from_user_id INTEGER NOT NULL,to_user_id INTEGER NOT NULL,type TEXT NOT NULL,payload TEXT NOT NULL,created_at INTEGER NOT NULL,FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS ix_signals_recipient ON signals(to_user_id,id);
        """)
        db.commit()

def build_handler(database_path:Path):
    initialize(database_path)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
        def end_headers(self):
            self.send_header("X-Content-Type-Options","nosniff");self.send_header("X-Frame-Options","DENY");self.send_header("Referrer-Policy","no-referrer");self.send_header("Permissions-Policy","camera=(self), microphone=(self), geolocation=()");self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'");super().end_headers()
        def log_message(self,format,*args):return
        def _json(self,status,payload,headers=None):
            body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode();self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store")
            for name,value in (headers or {}).items():self.send_header(name,value)
            self.end_headers();self.wfile.write(body)
        def _body(self):
            try:length=int(self.headers.get("Content-Length","0"))
            except ValueError:raise ValueError("Invalid content length")
            if length<=0 or length>MAX_BODY_BYTES:raise ValueError("Invalid request body")
            try:payload=json.loads(self.rfile.read(length).decode())
            except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError("Invalid JSON")
            if not isinstance(payload,dict):raise ValueError("JSON object required")
            return payload
        def _session(self):
            cookie=SimpleCookie();cookie.load(self.headers.get("Cookie",""));morsel=cookie.get("aionex_session")
            if not morsel:return None
            token_hash=hashlib.sha256(morsel.value.encode()).hexdigest();now=int(time.time())
            with sqlite3.connect(database_path) as db:
                db.row_factory=sqlite3.Row;row=db.execute("SELECT sessions.user_id,sessions.csrf,users.username FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND sessions.expires_at>?",(token_hash,now)).fetchone()
            return dict(row) if row else None
        def _require(self,csrf=False):
            session=self._session()
            if not session:self._json(401,{"error":"Authentication required"});return None
            if csrf and not hmac.compare_digest(str(session["csrf"]),self.headers.get("X-CSRF-Token","")):self._json(403,{"error":"CSRF validation failed"});return None
            return session
        def do_GET(self):
            parsed=urlsplit(self.path);path=parsed.path
            if path=="/api/health":self._json(200,{"status":"healthy"});return
            if path=="/api/me":
                session=self._require()
                if session:self._json(200,{"user":{"id":session["user_id"],"username":session["username"]},"csrf_token":session["csrf"]})
                return
            if path=="/api/members":
                session=self._require()
                if not session:return
                with sqlite3.connect(database_path) as db:
                    db.row_factory=sqlite3.Row;rows=db.execute("SELECT id,username FROM users WHERE id<>? ORDER BY username LIMIT 200",(session["user_id"],)).fetchall()
                self._json(200,{"members":[dict(row) for row in rows]});return
            if path=="/api/signals":
                session=self._require()
                if not session:return
                try:after=max(0,int(parse_qs(parsed.query).get("after",["0"])[0]))
                except ValueError:after=0
                with sqlite3.connect(database_path) as db:
                    db.row_factory=sqlite3.Row;rows=db.execute("SELECT signals.id,signals.from_user_id,users.username AS from_username,signals.type,signals.payload FROM signals JOIN users ON users.id=signals.from_user_id WHERE signals.to_user_id=? AND signals.id>? ORDER BY signals.id LIMIT 100",(session["user_id"],after)).fetchall()
                result=[]
                for row in rows:
                    item=dict(row);item["payload"]=json.loads(item["payload"]);result.append(item)
                self._json(200,{"signals":result});return
            super().do_GET()
        def do_POST(self):
            path=urlsplit(self.path).path
            try:payload=self._body()
            except ValueError as exc:self._json(400,{"error":str(exc)});return
            if path=="/api/register":
                username=str(payload.get("username") or "").strip();password=str(payload.get("password") or "")
                if not USERNAME.fullmatch(username) or not 12<=len(password)<=128:self._json(422,{"error":"Username or password requirements are not met"});return
                salt=secrets.token_bytes(16)
                try:
                    with sqlite3.connect(database_path) as db:db.execute("INSERT INTO users(username,password_hash,salt,created_at) VALUES(?,?,?,?)",(username,_hash_password(password,salt),salt.hex(),int(time.time())));db.commit()
                except sqlite3.IntegrityError:self._json(409,{"error":"Username already exists"});return
                self._json(201,{"registered":True});return
            if path=="/api/login":
                username=str(payload.get("username") or "").strip();password=str(payload.get("password") or "")
                with sqlite3.connect(database_path) as db:
                    db.row_factory=sqlite3.Row;row=db.execute("SELECT id,username,password_hash,salt FROM users WHERE username=?",(username,)).fetchone()
                    valid=bool(row) and hmac.compare_digest(str(row["password_hash"]),_hash_password(password,bytes.fromhex(str(row["salt"]))))
                    if not valid:self._json(401,{"error":"Invalid credentials"});return
                    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);db.execute("INSERT OR REPLACE INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),row["id"],csrf,int(time.time())+SESSION_SECONDS));db.commit()
                self._json(200,{"user":{"id":row["id"],"username":row["username"]},"csrf_token":csrf},{"Set-Cookie":f"aionex_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}"});return
            session=self._require(csrf=True)
            if not session:return
            if path=="/api/logout":
                cookie=SimpleCookie();cookie.load(self.headers.get("Cookie",""));morsel=cookie.get("aionex_session")
                if morsel:
                    with sqlite3.connect(database_path) as db:db.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(morsel.value.encode()).hexdigest(),));db.commit()
                self._json(200,{"logged_out":True},{"Set-Cookie":"aionex_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"});return
            if path=="/api/signals":
                try:target=int(payload.get("to_user_id"));kind=str(payload.get("type") or "");signal_payload=payload.get("payload")
                except (TypeError,ValueError):self._json(422,{"error":"Invalid signal target"});return
                if target==session["user_id"] or kind not in SIGNAL_TYPES or not isinstance(signal_payload,dict):self._json(422,{"error":"Invalid signal"});return
                encoded=json.dumps(signal_payload,separators=(",",":"),ensure_ascii=False)
                if len(encoded.encode())>16_384:self._json(413,{"error":"Signal payload too large"});return
                with sqlite3.connect(database_path) as db:
                    exists=db.execute("SELECT 1 FROM users WHERE id=?",(target,)).fetchone()
                    if not exists:self._json(404,{"error":"Target member not found"});return
                    cursor=db.execute("INSERT INTO signals(from_user_id,to_user_id,type,payload,created_at) VALUES(?,?,?,?,?)",(session["user_id"],target,kind,encoded,int(time.time())));db.commit();signal_id=int(cursor.lastrowid)
                self._json(201,{"id":signal_id,"queued":True});return
            self._json(404,{"error":"Not found"})
    return Handler

def build_server(host="127.0.0.1",port=8088,database_path=None):
    selected=database_path or (ROOT/"realtime.db");return ThreadingHTTPServer((host,port),build_handler(selected))

if __name__=="__main__":
    server=build_server();print("AIONEX governed realtime application running on http://127.0.0.1:8088");server.serve_forever()
'''

    readme = f'''# {project}

This delivery is a functional governed **realtime communications web application** scaffold generated from the accepted AIONEX plan.

## Implemented runtime

- Local member registration and password authentication using memory-hard scrypt + per-user salts.
- HttpOnly same-site sessions and CSRF protection for authenticated mutations.
- Member directory and same-origin signaling queue backed by SQLite.
- Browser-native WebRTC audio/video (`getUserMedia` + `RTCPeerConnection`).
- Offer/answer/ICE/hangup signaling through the local API.
- Responsive branded UI, SVG logo, and installable web-app manifest.
- No provider credential, TURN credential, or production secret is embedded.

## Run locally

```text
python3 server.py
```

Open `http://127.0.0.1:8088`. Use two browser profiles to register two members and test signaling/calls.

## Production requirements not fabricated by AIOS

Public-internet WebRTC normally requires HTTPS plus operator-controlled STUN/TURN infrastructure. This package intentionally leaves `runtime-config.json` with an empty ICE-server list so no third-party relay or credential is silently introduced. Before public launch, configure audited STUN/TURN endpoints, use Secure session cookies behind HTTPS, run browser interoperability/load tests, and complete the final deployment review.

## Governed evidence

- Planning manifest: `{planning['manifest_sha256']}`
- Application type: `realtime_communications`
- Provider role: structured architecture/product specification only
- Executable source origin: deterministic reviewed AIONEX archetype
- Production deployment: not performed

## Requested objective

{objective}
'''

    logo = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="{title} mark"><defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="{secondary}"/><stop offset="1" stop-color="{primary}"/></linearGradient></defs><rect width="128" height="128" rx="32" fill="{surface}"/><circle cx="64" cy="64" r="43" fill="none" stroke="url(#g)" stroke-width="10"/><path d="M42 58c0-13 10-23 22-23s22 10 22 23v12c0 12-10 22-22 22S42 82 42 70V58Z" fill="none" stroke="{accent}" stroke-width="8"/><path d="M32 68h10m44 0h10" stroke="{secondary}" stroke-width="8" stroke-linecap="round"/></svg>'''
    manifest = json.dumps(
        {"name": str(spec["title"]), "short_name": str(spec["title"])[:18], "start_url": "/", "display": "standalone", "background_color": surface, "theme_color": secondary, "icons": []},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    runtime_config = json.dumps(
        {"iceServers": [], "publicInternetTurnRequired": True, "transport": "same-origin-polling-signaling"},
        indent=2,
    ) + "\n"
    return {
        "index.html": index,
        "styles.css": css,
        "app.js": app,
        "server.py": server,
        "README.md": readme,
        "logo.svg": logo,
        "manifest.webmanifest": manifest,
        "runtime-config.json": runtime_config,
    }
