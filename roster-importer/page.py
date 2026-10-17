"""The look of every DA Management page: the frame around it (title, menu, colours) and small helpers for writing HTML.

Every page builds only its own middle part (the "body") as HTML text and hands it to render(), which puts it into the
frame below. The frame also:
  - loads the portal's translations (i18n.js), so the page shows in the language the person chose in the portal;
  - shows the short messages of the last action (Flask's "flash" messages) at the top;
  - follows the portal's light or dark theme (the portal sends it with a message, because DA Management is shown
    inside the portal as an iframe).
"""
import re
import secrets
from functools import cache
from html import escape
from zoneinfo import ZoneInfo

from flask import current_app, request, session

import settings

# Times are shown in the mission's own time zone.
MISSION_TIME_ZONE = ZoneInfo(settings.TIME_ZONE_NAME)  # a wrong GFM_TIME_ZONE stops DA Management at start

# The portal's 14 interface languages (portal/i18n.js). The Church's language codes (deu, pes, ...) are accepted too.
PAGE_LANGUAGES = {"en", "de", "es", "fr", "pt", "uk", "ru", "it", "tr", "fa", "ro", "sv", "da", "ar"}
CHURCH_CODES = {"eng": "en", "deu": "de", "spa": "es", "fra": "fr", "por": "pt", "ukr": "uk", "rus": "ru", "ita": "it",
                "tur": "tr", "pes": "fa", "ron": "ro", "swe": "sv", "dan": "da", "ara": "ar"}
RIGHT_TO_LEFT = ("fa", "ar")

# The menu at the top of every page (round 13): five tabs, each with the pages of its group underneath. Every page of
# DA Management is in exactly one group, so every function stays reachable and every address works as before. A tab
# opens the first page of its group. A page that belongs to a group but has its own sub-addresses (a form that sends,
# a detail page) lists them as the third part of its entry, so the right tab stays lit there.
# [(group key, tab text, [(address, page text, [more address starts])])]; the texts are in the portal's catalogs
# (dam.* and uploads.geo.title already; dam.tab.* are new, see portal/i18n/en.json).
# Round 14 (clean UI): four tabs. Uploads is ONE page that lists every file import (roster, historical CSV, people,
# geo, vollzogen, the other data uploads). Planning questions sit with Places. DA Docs and the old Wiki tab are gone
# (the portal's side-menu Wiki opens /wiki/). Addresses of the old pages still work; they light the right tab.
MENU_GROUPS = [
    ("uploads", "Uploads", [
        ("/uploads", "Uploads", ["/", "/preview", "/apply", "/historical", "/people-upload", "/people/",
                                 "/uploads/geo", "/uploads/vollzogen", "/uploads/finding",
                                 "/uploads/zone-history",
                                 "/uploads/baptisms", "/uploads/names"]),
    ]),
    ("people", "People", [
        ("/accounts", "Account Manager", []),
        ("/staff", "Staff accounts", []),
        ("/abilities", "Role abilities", []),
    ]),
    ("places", "Places", [
        ("/places", "Places", []),
        ("/mappings", "Area mappings", []),
        ("/planning-questions", "Planning questions", []),
        ("/retire", "Delete retired", []),
    ]),
    ("history", "History", [
        ("/imports", "Import history", ["/docs", "/wiki-link"]),
        ("/updates", "Updates", []),
        ("/links", "Links to web services", []),
    ]),
]

# The same pages as one flat list (address, text), in menu order.
MENU = [(address, text) for _key, _tab, pages in MENU_GROUPS for address, text, _more in pages]


def _starts(path, start):
    """True when path is the start or lies below it ("/uploads/geo/table" is below "/uploads/geo"). "/" is only itself."""
    if start == "/":
        return path == "/"
    return path == start or path.startswith(start.rstrip("/") + "/") or (start.endswith("/") and path.startswith(start))


def current_page(path):
    """(group key, address) of the menu page that path belongs to, or (None, None). The longest matching start wins
    ("/uploads/geo/table" is Geo data, an address of a removed page is Data uploads)."""
    best_length, best = 0, (None, None)
    for key, _tab, pages in MENU_GROUPS:
        for address, _text, more in pages:
            for start in [address, *more]:
                if _starts(path, start) and len(start) > best_length:
                    best_length, best = len(start), (key, address)
    return best


def _link(address, text, lit):
    """One menu link; the lit one (the page or tab the person is on) says so for screen readers too."""
    mark = ' class="on" aria-current="page"' if lit else ""
    return f'<a href="{escape(address)}"{mark}>{escape(text)}</a>'


def menu_html(path):
    """The two rows of links at the top: the tabs (groups) and, under them, the pages of the group the person is in."""
    group, address = current_page(path)
    tabs = "".join(_link(pages[0][0], tab, key == group) for key, tab, pages in MENU_GROUPS)
    html = f'<nav class="nav tabs" aria-label="Sections">{tabs}</nav>'
    for key, _tab, pages in MENU_GROUPS:
        if key == group:
            links = "".join(_link(page, text, page == address) for page, text, _more in pages)
            html += f'<nav class="nav sub" aria-label="Pages in this section">{links}</nav>'
    return html


STYLE = """
/* The look of every page */
:root{color-scheme:light;background:#f4f7f8;--navy:#153441;--teal:#087f8c;--line:#dce7ea}*{box-sizing:border-box}
body{font-family:Inter,system-ui,sans-serif;max-width:1220px;margin:0 auto;padding:26px 24px;background:#f4f7f8;color:#183240}
.scroll{overflow:auto;border:1px solid var(--line);border-radius:10px}/* before .card: a card that scrolls keeps its round corners */
a{color:var(--teal);text-decoration:none}.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px;margin:18px 0;box-shadow:0 2px 8px #17394704}
h1{font-size:25px;letter-spacing:-.035em}h2{font-size:19px}h3{font-size:15px}h1,h2,h3{margin-top:0}.muted{color:#687d88}.good{color:#087f5b}.warn{color:#b26a00}.bad{color:#c92a2a}
input,select,button{font:inherit;padding:10px 12px;border-radius:9px;border:1px solid #bccbd1}input,select{border-color:#c6d7dc;background:#fff;max-width:100%}input:focus,select:focus{outline:0;border-color:var(--teal);box-shadow:0 0 0 3px #087f8c16}
button{background:var(--teal);border-color:var(--teal);color:#fff;cursor:pointer;font-weight:650}.secondary{background:#fff;color:#23434f;border-color:#c9d9de}.danger{background:#b42318;border-color:#b42318}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px;border-bottom:1px solid #e9eff1;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#f7fafb}
code{background:#edf2f3;padding:2px 5px;border-radius:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.metric{padding:14px;background:#eef5f5;border-radius:10px}.metric b{font-size:23px;color:#153441}
.error{background:#fff0f0;border:1px solid #f4bcbc;padding:12px;border-radius:10px;white-space:pre-wrap;line-height:1.6}.flash{background:#fff8df;padding:12px;border-radius:10px;margin:10px 0}
ul{line-height:1.5}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 20px}.nav a{padding:9px 12px;border:1px solid var(--line);background:#fff;border-radius:9px;color:var(--navy);font-size:12px;font-weight:700}.nav a:hover{background:#eaf4f3;border-color:#acd0cd}
.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end}.filters label{font-size:12px;font-weight:700;color:#526975}.filters select,.filters input{width:100%;margin-top:4px}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.status{font-weight:700}
label{font-size:12px;font-weight:650}.form-field{display:grid;gap:6px;margin:15px 0}.split{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.step{font-size:11px;font-weight:800;color:#087f8c;letter-spacing:.09em;text-transform:uppercase}
.badge{display:inline-block;border-radius:30px;background:#e8f3f2;color:#17716f;padding:4px 8px;font-size:11px;font-weight:750}
.choice{display:block;margin:6px 0;font-size:13px;font-weight:500}.choice-group{border-top:1px solid #e9eff1;padding-top:10px;margin-top:10px}
.plan{background:#eef5f5;border-radius:10px;padding:12px 14px;margin:14px 0}.plan ul{margin:6px 0 0;padding-left:20px}

/* Dark theme (the portal says which theme it shows) */
[data-theme="dark"]{color-scheme:dark;background:#101a21}[data-theme="dark"] body{background:#101a21;color:#f2f8f9}[data-theme="dark"] .card{background:#1e303a;border-color:#4c6875}[data-theme="dark"] input,[data-theme="dark"] select{background:#101a21;color:#f2f8f9;border-color:#6a8794}[data-theme="dark"] .muted{color:#c0d0d5}[data-theme="dark"] .metric{background:#2a414d}[data-theme="dark"] .plan{background:#2a414d}[data-theme="dark"] .metric b{color:#f2f8f9}
[data-theme="dark"] a,[data-theme="dark"] .step{color:#6fd3d6}[data-theme="dark"] label,[data-theme="dark"] .filters label{color:#d7e6ea}[data-theme="dark"] th{background:#2a414d;color:#f2f8f9}[data-theme="dark"] th,[data-theme="dark"] td{border-bottom-color:#4c6875}[data-theme="dark"] .scroll,[data-theme="dark"] .choice-group{border-color:#4c6875}[data-theme="dark"] code{background:#2a414d;color:#f2f8f9}
[data-theme="dark"] .error{background:#3a1f23;border-color:#8a3b40;color:#ffd9d5}[data-theme="dark"] .flash{background:#3a3219;color:#fbe7b0}[data-theme="dark"] .good{color:#62d6ab}[data-theme="dark"] .warn{color:#f5bd62}[data-theme="dark"] .bad{color:#ff9b91}[data-theme="dark"] .badge{background:#173d3f;color:#9fe3dc}
[data-theme="dark"] .nav a,[data-theme="dark"] .secondary{background:#1e303a;border-color:#6a8794;color:#f2f8f9}[data-theme="dark"] .nav a:hover{background:#2a414d;border-color:#7f9ba7}

/* A missionary's account page: tick boxes for roles, and boxes big enough for a finger on a phone */
.role-choice{display:flex;gap:10px;align-items:flex-start;min-height:44px;padding:8px 0;font-size:14px;font-weight:600}
.role-choice input{width:22px;height:22px;margin:1px 0 0;flex:none}.role-choice span{display:block;font-weight:400;font-size:13px;color:#687d88}.role-choice[hidden]{display:none}
.role-group{border:0;border-top:1px solid #e9eff1;margin:12px 0 0;padding:10px 0 0}.role-group legend{font-size:12px;font-weight:650;padding:0}
#accountForm input,#accountForm select{font-size:16px;min-height:44px}#accountForm input[type=checkbox]{min-height:0}
#accountForm .split>*,#accountForm .form-field{min-width:0}#accountForm select{width:100%}
[data-theme="dark"] .role-choice span{color:#c0d0d5}[data-theme="dark"] .role-group{border-color:#4c6875}

/* The menu: tabs (groups) with the pages of the open group under them (round 13) */
.nav.tabs{margin-bottom:6px}.nav.tabs a{font-size:13px;font-weight:700}.nav.sub{margin-top:0;padding-bottom:10px;border-bottom:1px solid var(--line)}
.nav.sub a{background:transparent;border-color:transparent;font-weight:600;color:#3d5966}
.nav a.on{background:var(--teal);border-color:var(--teal);color:#fff}.nav.sub a.on{background:#e3f1f2;border-color:#bfdfe2;color:var(--navy)}
[data-theme="dark"] .nav a.on{background:#087f8c;border-color:#087f8c;color:#fff}[data-theme="dark"] .nav.sub a{background:transparent;border-color:transparent;color:#d7e6ea}
[data-theme="dark"] .nav.sub a.on{background:#2a414d;border-color:#7f9ba7;color:#f2f8f9}[data-theme="dark"] .nav.sub{border-color:#4c6875}

/* Round 14: a styled file picker (not the browser's default) and a red danger button for deletes. */
.file-pick{position:relative;display:inline-flex;align-items:center;gap:10px;min-height:44px;padding:10px 14px;border:1px dashed #9db5bc;border-radius:10px;background:#f7fbfb;cursor:pointer;font-weight:650;color:#173644}
.file-pick input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.file-pick:hover{border-color:var(--teal);background:#eef6f6}
.file-pick .name{font-weight:500;color:#687d88;font-size:13px;overflow-wrap:anywhere;min-width:0}
.file-pick.has-file .name{color:var(--navy);font-weight:650}
.card.drag-over,.file-pick.drag-over{border-color:var(--teal);outline:2px dashed var(--teal);outline-offset:-2px;background:#eef6f6}
@media(max-width:700px){.file-pick{display:flex;flex-wrap:wrap;width:100%;box-sizing:border-box}}
button.danger,.danger{background:#b42318;border-color:#b42318;color:#fff}
[data-theme="dark"] .file-pick{background:#101a21;border-color:#6a8794;color:#f2f8f9}[data-theme="dark"] .file-pick .name{color:#c0d0d5}[data-theme="dark"] .file-pick.has-file .name{color:#f2f8f9}
[data-theme="dark"] .card.drag-over,[data-theme="dark"] .file-pick.drag-over{background:#243943}
[data-theme="dark"] button.danger,[data-theme="dark"] .danger{background:#b42318;border-color:#b42318;color:#fff}
@media(max-width:700px){.nav.tabs a,.nav.sub a{min-height:44px;padding:10px 12px}.nav.tabs{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch}}

/* Sortable tables (table.sortable): the heading is a button with an arrow for the column and direction in use */
th .sort-head{display:inline-flex;align-items:center;gap:5px;padding:0;border:0;background:none;color:inherit;font:inherit;font-weight:700;text-align:inherit;cursor:pointer}
th .sort-head:focus-visible{outline:2px solid var(--teal);outline-offset:3px;border-radius:4px}.sort-arrow:after{content:"\\2195";opacity:.45}
th[aria-sort=ascending] .sort-arrow:after{content:"\\25B2";opacity:1;font-size:.8em}th[aria-sort=descending] .sort-arrow:after{content:"\\25BC";opacity:1;font-size:.8em}
[data-theme="dark"] th .sort-head:focus-visible{outline-color:#6fd3d6}

/* Phones */
@media(max-width:700px){body{padding:16px 12px}.split{grid-template-columns:1fr}.card{padding:17px}.nav{gap:6px}.nav a{padding:8px}}

/* Planning questions (inside <div class="pq">) */
.pq input:not([type=checkbox]):not([type=radio]),.pq select,.pq textarea{font-size:16px;width:100%;max-width:100%}
.pq textarea{min-height:88px;border:1px solid #c6d7dc;border-radius:9px;padding:10px 12px;font-family:inherit}
.pq button,.pq .button{min-height:44px;font-size:14px}.pq .button{display:inline-flex;align-items:center;padding:0 14px;border-radius:9px;background:#087f8c;color:#fff;font-weight:650}
.pq .inline{display:inline}.pq .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.pq .grow{flex:1 1 220px;min-width:0}
.pq .item{border-top:1px solid #e9eff1;padding:12px 0;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}
.pq .item:first-child{border-top:0}.pq .item .what{flex:1 1 260px;min-width:0;overflow-wrap:anywhere}.pq .retired{opacity:.62}
.pq .tools{display:flex;flex-wrap:wrap;gap:6px}.pq .tools button{padding:0 12px}.pq details{margin-top:12px}.pq summary{cursor:pointer;font-weight:700;display:list-item;padding:12px 0;min-height:44px}
.pq .lock{background:#fff5dc;border:1px solid #f0d58a;border-radius:10px;padding:10px 12px;margin:10px 0}.pq .lock b{color:#7a5300}
.pq .note{font-size:13px;color:#647985}.pq .check{display:flex;gap:10px;align-items:center;font-size:14px;font-weight:600;min-height:44px}.pq .check input{width:22px;height:22px}
.pq .two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pq code{overflow-wrap:anywhere}
.pq .preview .question{margin:14px 0}.pq .preview .q-label{font-weight:650;font-size:14px;margin-bottom:6px;display:block}.pq .req{color:#b74c42}
.pq .pills{display:flex;flex-wrap:wrap;gap:8px}.pq .pills label{display:inline-flex;gap:8px;align-items:center;min-height:44px;padding:0 14px;border:1px solid #c6d7dc;border-radius:999px;font-size:14px;font-weight:600}
.pq .gridq{width:100%;border-collapse:collapse}.pq .gridq th,.pq .gridq td{padding:6px;border-bottom:1px solid #e9eff1;text-align:center}.pq .gridq th[scope=row]{text-align:left}
.pq .history .item{display:block}.pq .change{margin:4px 0 0;padding-left:18px}
[data-theme="dark"] .pq .lock{background:#3a3219;border-color:#6b5a26}[data-theme="dark"] .pq .lock b{color:#fbe7b0}[data-theme="dark"] .pq textarea{background:#101a21;color:#f2f8f9;border-color:#6a8794}[data-theme="dark"] .pq .item{border-color:#4c6875}[data-theme="dark"] .pq .pills label{border-color:#6a8794}[data-theme="dark"] .pq .note{color:#c0d0d5}[data-theme="dark"] .pq .req{color:#ff9b91}[data-theme="dark"] .pq .gridq th,[data-theme="dark"] .pq .gridq td{border-color:#4c6875}
@media(max-width:700px){.pq .two{grid-template-columns:1fr}.pq .gridq thead{display:none}.pq .gridq,.pq .gridq tbody,.pq .gridq tr,.pq .gridq th{display:block}.pq .gridq tr{border:1px solid #dce7ea;border-radius:10px;padding:8px;margin-bottom:8px}.pq .gridq td{display:inline-block;border:0}.pq .gridq th{border:0}}

/* Staff accounts (inside <div class="staff">) */
.staff input,.staff select{font-size:16px;min-height:44px;width:100%}.staff input[type=checkbox]{width:22px;height:22px;min-height:0;flex:none;margin:1px 0 0}
.staff .form-field{min-width:0}.staff button{min-height:44px}.staff .check{display:flex;gap:10px;align-items:flex-start;min-height:44px;padding:8px 0;font-size:14px;font-weight:600}
.staff .check span{font-weight:400;font-size:13px;display:block}.staff td:nth-child(2){overflow-wrap:anywhere}
#accountForm button{min-height:44px}

/* Role abilities: a switch in every cell, big enough for a finger */
.abil th,.abil td{vertical-align:middle}.abil td.cell{text-align:center;min-width:76px}.abil input[type=checkbox]{width:26px;height:26px;margin:0}.abil .muted{font-weight:400}
.abil-card .actions button{min-height:44px}

/* Area mappings: each row's list is as wide as the whole list, also before the page's script fills it in */
#mappingTable select{width:27em}
"""

# The frame of every page. {{ ... }} are the holes that render() fills (Jinja, Flask's template language).
FRAME = r"""
<!doctype html>
<html lang="{{ page_lang }}" dir="{{ page_dir }}" data-theme="{{ page_theme }}">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<script>/* Interface translation (round 6): the portal's i18n.js, in the language the portal chose (cookie gfm_lang or ?lang=). */(function(){var s=document.createElement("script");s.src={{ i18n_src|tojson }}||location.protocol+"//"+location.hostname+":8070/i18n.js";document.head.appendChild(s)})()</script>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mission Admin</title>
<style>{{ style|safe }}</style>
</head>
<body>
<h1>Mission Admin</h1>
<div class="menu">{{ nav|safe }}</div>
{% with messages = get_flashed_messages() %}
{% if messages %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endif %}
{% endwith %}
{{ body|safe }}
<script>/* Round 16: a file picker shows the chosen file's name and size, highlights while a file is dragged over, and takes a dropped file. */(function(){
function tr(k,f){try{var v=window.MissionI18n&&MissionI18n.t&&MissionI18n.t(k);return v&&v!==k?v:f}catch(e){return f}}
function size(n){return n<1024?n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB"}
document.querySelectorAll(".file-pick").forEach(function(pick){
var input=pick.querySelector("input[type=file]"),name=pick.querySelector(".name");if(!input||!name)return;
var card=pick.closest(".card");var zone=card&&card.querySelectorAll(".file-pick").length===1?card:pick;
function show(){var f=input.files&&input.files[0];pick.classList.toggle("has-file",!!f);
name.textContent=f?f.name+" · "+size(f.size):tr("uploads.page.noneChosen",name.getAttribute("data-empty")||"No file chosen")}
input.addEventListener("change",show);document.addEventListener("mission-i18n-change",function(){if(!(input.files&&input.files[0]))show()});
function over(e){e.preventDefault();zone.classList.add("drag-over")}
zone.addEventListener("dragenter",over);zone.addEventListener("dragover",over);
zone.addEventListener("dragleave",function(e){if(!e.relatedTarget||!zone.contains(e.relatedTarget))zone.classList.remove("drag-over")});
zone.addEventListener("drop",function(e){e.preventDefault();zone.classList.remove("drag-over");
var files=e.dataTransfer&&e.dataTransfer.files;if(files&&files.length){try{input.files=files}catch(x){return}show()}});
});
addEventListener("dragover",function(e){if(e.target.closest&&e.target.closest(".file-pick,.card"))return;e.preventDefault()});
addEventListener("drop",function(e){if(!(e.target.closest&&e.target.closest(".file-pick,.card")))e.preventDefault()});
})()</script>
<script>/* Round 18: a table.sortable sorts by a column when its heading (a button) is clicked, again reverses; the arrow and aria-sort show how.
A cell's data-sort (else its text) is compared case- and accent-blind, numbers as numbers; empty cells last. th[data-sort-default]: A to Z at the start. */(function(){
var compare=new Intl.Collator(document.documentElement.lang||undefined,{sensitivity:"base",numeric:true}).compare;
document.querySelectorAll("table.sortable").forEach(function(table){
var heads=[].slice.call(table.tHead.rows[0].cells),body=table.tBodies[0];
function key(row,i){var c=row.cells[i];return (c.hasAttribute("data-sort")?c.getAttribute("data-sort"):c.textContent).trim()}
function sort(i,dir){
[].slice.call(body.rows).filter(function(r){return r.cells.length===heads.length})
.sort(function(a,b){var x=key(a,i),y=key(b,i);return (!x-!y)||dir*compare(x,y)}).forEach(function(r){body.appendChild(r)});
heads.forEach(function(th,j){if(th.hasAttribute("aria-sort"))th.setAttribute("aria-sort",j===i?(dir>0?"ascending":"descending"):"none")})}
heads.forEach(function(th,i){if(!th.textContent.trim())return;
var b=document.createElement("button");b.type="button";b.className="sort-head";
while(th.firstChild)b.appendChild(th.firstChild);b.insertAdjacentHTML("beforeend",'<span class="sort-arrow" aria-hidden="true"></span>');
th.appendChild(b);th.setAttribute("aria-sort","none");
b.addEventListener("click",function(){sort(i,th.getAttribute("aria-sort")==="ascending"?-1:1)})});
var first=heads.findIndex(function(th){return th.hasAttribute("data-sort-default")});if(first>=0)sort(first,1);
});})()</script>
<script>addEventListener("message",e=>{if(e.data?.type!=="portal-theme")return;var t=e.data.theme||"mission";document.documentElement.dataset.theme=t;document.cookie=["gfm_theme="+t,"path=/","max-age=31536000"].join(";")})</script></body>
</html>
"""

# Every form that sends (method="post"). render() adds the session's secret form token to each of them, so no page
# can forget it: sign_in.check_form_token() refuses a sent form without the right token (this stops another website
# from sending forms in the name of a signed-in manager).
POST_FORM = re.compile(r"""(<form\b[^>]*\bmethod=["']post["'][^>]*>)""", flags=re.IGNORECASE)


def i18n_source():
    """Where this page loads the portal's i18n.js: the setting, else on the public name the public portal (round 10),
    else '' (the page's script then uses this computer's portal on port 8070)."""
    if settings.PORTAL_I18N_SRC:
        return settings.PORTAL_I18N_SRC
    if settings.PUBLIC_NAME and settings.PUBLIC_PORTAL and request.host.lower() == settings.PUBLIC_NAME:
        return settings.PUBLIC_PORTAL + "/i18n.js?v=6"
    return ""


def render(body, status=200, bare=False):
    """The whole page around `body` (HTML text), with the HTTP status code (200 = all right).
    bare=True: no tabs (the login page and other signed-out pages)."""
    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    body = POST_FORM.sub(lambda found: found.group(1) + f'<input type="hidden" name="csrf_token" value="{token}">', body)
    language = page_language()
    nav = "" if bare else menu_html(request.path)
    html = frame(current_app.jinja_env).render(body=body, style=STYLE, nav=nav, page_lang=language,
                                               page_dir="rtl" if language in RIGHT_TO_LEFT else "ltr",
                                               i18n_src=i18n_source(), page_theme=page_theme())
    return html, status


@cache
def frame(jinja):
    """FRAME, made ready once (Jinja reads a template before it can fill it; doing that for every page cost more than
    most pages need for their database questions)."""
    return jinja.from_string(FRAME)


def page_language():
    """The page's language (lang and dir are set before i18n.js runs, so a right-to-left page never flashes
    left-to-right first). From ?lang= or the portal's gfm_lang cookie; English when it is not one of the 14."""
    raw = (request.args.get("lang") or request.cookies.get("gfm_lang") or "en").strip().lower().replace("_", "-")
    base = CHURCH_CODES.get(raw, raw.split("-")[0])
    return base if base in PAGE_LANGUAGES else "en"


def page_theme():
    """The page's theme, known on the server so the very first byte has the right colour (no light flash in dark mode).
    From ?theme= or the gfm_theme cookie (the portal writes it, and this page rewrites it on every portal message)."""
    raw = request.args.get("theme") or request.cookies.get("gfm_theme") or "mission"
    return raw if raw in ("mission", "light", "dark") else "mission"


def h(value):
    """Text made safe to put into HTML (so a name like <b>Tom</b> shows as written). None, 0 and False show as
    nothing."""
    return escape(str(value or ""))


def day(value):
    """A date the way DA Management writes it: 04 Oct 2026."""
    return value.strftime("%d %b %Y")


def mission_time(value):
    """A moment (with time zone) in the mission's time: 04 Oct 2026 14:05."""
    return value.astimezone(MISSION_TIME_ZONE).strftime("%d %b %Y %H:%M")
