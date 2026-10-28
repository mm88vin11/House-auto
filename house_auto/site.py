"""Сайт-визитка дома (для покупателей) и «пульт» продавца со всеми текстами.

build_site() → _site/index.html + фото  (публикуется на GitHub Pages)
build_kit()  → out/kit.html             (для вас: тексты с кнопкой «Копировать», ручные площадки)
"""

from __future__ import annotations

import shutil
from html import escape as e
from pathlib import Path
from urllib.parse import quote

from . import texts
from .config import ROOT, list_photos, load_house, load_targets

CSS = """
:root{--bg:#f7f3ec;--card:#fffdf9;--ink:#2b2620;--muted:#6f655a;--accent:#2f6b3a;--accent-ink:#fff;
--line:#e6dccd;--warm:#b5651d}
@media (prefers-color-scheme:dark){:root{--bg:#1b1916;--card:#25221e;--ink:#efe8de;--muted:#b3a899;
--accent:#6fbf7d;--accent-ink:#10200f;--line:#3a352e;--warm:#e0a060}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:0 16px}
header.hero{position:relative;min-height:62vh;display:flex;align-items:flex-end;color:#fff;background:#4a5a3c center/cover}
header.hero::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.05) 30%,rgba(0,0,0,.7))}
header.hero .wrap{position:relative;z-index:1;padding-bottom:28px;width:100%}
.kicker{display:inline-block;background:rgba(255,255,255,.18);backdrop-filter:blur(4px);padding:4px 12px;border-radius:99px;font-size:14px}
h1{font-size:clamp(28px,6vw,46px);line-height:1.12;margin:12px 0 8px}
.price{font-size:clamp(20px,4vw,28px);font-weight:700}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
.btn{display:inline-flex;align-items:center;gap:8px;padding:12px 20px;border-radius:12px;font-weight:600;text-decoration:none;
background:var(--accent);color:var(--accent-ink)}
.btn.alt{background:rgba(255,255,255,.92);color:#222}
section{padding:36px 0;border-bottom:1px solid var(--line)}
h2{font-size:24px;margin:0 0 16px}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.fact{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
.fact b{display:block;font-size:22px}.fact span{color:var(--muted);font-size:14px}
.honest{background:var(--card);border-left:4px solid var(--warm);padding:14px 16px;border-radius:8px;margin-top:16px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.item{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.item h3{margin:0 0 4px;font-size:17px}.item p{margin:0;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px;padding:0;margin:0;list-style:none}
.chips li{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:6px 14px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.gallery a{display:block;aspect-ratio:4/3;overflow:hidden;border-radius:10px;background:var(--line)}
.gallery img{width:100%;height:100%;object-fit:cover;transition:transform .3s}.gallery a:hover img{transform:scale(1.04)}
.empty{color:var(--muted);font-style:italic}
footer{padding:36px 0 110px;text-align:center;color:var(--muted)}
.sticky{position:fixed;left:0;right:0;bottom:0;padding:10px 16px calc(10px + env(safe-area-inset-bottom));
background:var(--card);border-top:1px solid var(--line);display:flex;gap:10px;justify-content:center;z-index:5}
.sticky .btn{flex:1;max-width:320px;justify-content:center}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;align-items:center;justify-content:center;z-index:9}
#lb.on{display:flex}#lb img{max-width:96vw;max-height:88vh;border-radius:6px}
#lb button{position:absolute;top:50%;background:none;border:0;color:#fff;font-size:44px;padding:20px;cursor:pointer}
#lb .p{left:0}#lb .n{right:0}#lb .x{top:8px;right:8px;transform:none;font-size:34px}
"""

LIGHTBOX_JS = """
const links=[...document.querySelectorAll('.gallery a')],lb=document.getElementById('lb'),im=lb.querySelector('img');let i=0;
function show(k){i=(k+links.length)%links.length;im.src=links[i].href;lb.classList.add('on')}
links.forEach((a,k)=>a.addEventListener('click',ev=>{ev.preventDefault();show(k)}));
lb.querySelector('.p').onclick=()=>show(i-1);lb.querySelector('.n').onclick=()=>show(i+1);
lb.querySelector('.x').onclick=()=>lb.classList.remove('on');
lb.addEventListener('click',ev=>{if(ev.target===lb)lb.classList.remove('on')});
document.addEventListener('keydown',ev=>{if(!lb.classList.contains('on'))return;
if(ev.key==='Escape')lb.classList.remove('on');if(ev.key==='ArrowLeft')show(i-1);if(ev.key==='ArrowRight')show(i+1)});
let x0=null;lb.addEventListener('touchstart',ev=>x0=ev.touches[0].clientX);
lb.addEventListener('touchend',ev=>{if(x0===null)return;const d=ev.changedTouches[0].clientX-x0;if(Math.abs(d)>40)show(i+(d<0?1:-1));x0=null});
"""


def _tel(phone: str) -> str:
    return "tel:" + "".join(ch for ch in phone if ch.isdigit() or ch == "+")


def _contact_buttons(h: dict, alt: bool = False) -> str:
    c, out = h["contact"], []
    if c.get("phone"):
        out.append(f'<a class="btn" href="{_tel(c["phone"])}">📞 Позвонить</a>')
    if c.get("telegram"):
        out.append(f'<a class="btn{" alt" if alt else ""}" href="https://t.me/{e(c["telegram"].lstrip("@"))}">'
                   "✉️ Написать в Telegram</a>")
    return "".join(out)


def site_html(h: dict, photo_names: list[str]) -> str:
    cover = photo_names[0] if photo_names else None
    price = texts.price_line(h)
    title = f"Продаётся дом, {h['city']}, {h['street']}"
    desc = (f"{texts.fmt_num(h['area_house'])} м², участок {texts.fmt_num(h['area_land'])} сот., "
            f"{h['land_category']}{', ЕГРН' if h.get('egrn') else ''}. {texts.cap(price)}.")
    base = (h.get("site_url") or "").rstrip("/") + "/"
    og_img = f'<meta property="og:image" content="{e(base + "photos/" + cover)}">' if cover and h.get("site_url") else ""
    hero_bg = f' style="background-image:url(\'photos/{e(quote(cover))}\')"' if cover else ""
    maps = "https://yandex.ru/maps/?text=" + quote(f"{h['city']}, {h['street']}")
    c = h["contact"]

    facts = [(f"{texts.fmt_num(h['area_house'])} м²", "площадь дома"),
             (f"{texts.fmt_num(h['area_land'])} сот.", "участок"),
             (str(h["year_built"]), "год постройки"),
             (h["land_category"], "категория земли"),
             ("ЕГРН" if h.get("egrn") else "—", "в российском реестре" if h.get("egrn") else "документы"),
             (h["walls"], "стены")]
    gallery = ("".join(f'<a href="photos/{e(quote(n))}"><img src="photos/{e(quote(n))}" loading="lazy" '
                       f'alt="Фото {k + 1}"></a>' for k, n in enumerate(photo_names))
               or '<p class="empty">Фотографии скоро появятся — спросите в сообщениях, пришлём сразу.</p>')
    extra = ", ".join(h.get("extra_rooms", []))
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta property="og:type" content="website"><meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">{og_img}
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🏡</text></svg>">
<style>{CSS}</style></head><body>
<header class="hero"{hero_bg}><div class="wrap">
<span class="kicker">📍 {e(h['city'])}, {e(h['region'])} · {e(h['street'])}</span>
<h1>Дом с садом и участком {e(texts.fmt_num(h['area_land']))} соток</h1>
<div class="price">{e(texts.cap(price))}</div>
<div class="btns">{_contact_buttons(h, alt=True)}</div>
</div></header>

<main class="wrap">
<section><h2>Коротко</h2>
<div class="facts">{"".join(f'<div class="fact"><b>{e(v)}</b><span>{e(k)}</span></div>' for v, k in facts)}</div>
<p>Планировка: {e(h['layout'])}{(", а также " + e(extra)) if extra else ""} — места хватит с запасом.</p>
<div class="honest"><b>Честно:</b> {e(h['condition'])}</div>
</section>

<section><h2>Фотографии</h2><div class="gallery">{gallery}</div></section>

<section><h2>Коммуникации</h2><div class="grid2">
{"".join(f'<div class="item"><h3>{e(u["icon"])} {e(u["name"])}</h3><p>{e(texts.cap(u["text"]))}</p></div>'
         for u in h.get("utilities", []))}
</div></section>

<section><h2>Участок и хозяйство</h2>
<p>Хозяйство под ключ:</p><ul class="chips">{"".join(f"<li>{e(x)}</li>" for x in h.get("outbuildings", []))}</ul>
<p style="margin-top:20px">Сад — полноценный, урожай каждый год без всяких усилий:</p>
<ul class="chips">{"".join(f"<li>🌳 {e(x)}</li>" for x in h.get("garden", []))}</ul>
<p style="margin-top:20px">Земля — {e(h['land_category'])}: расширяться, достраиваться и обустраивать участок можно свободно.
{e(h.get('neighbors', ''))}</p>
</section>

<section><h2>Расположение</h2>
<p>{e(h['street'])}, {e(h['city'])}. {e(h['location'])}</p>
<a class="btn" href="{e(maps)}" target="_blank" rel="noopener">🗺 Открыть на карте</a>
</section>

<section><h2>Посмотреть дом</h2>
<p>Покажем в удобное время, ответим на любые вопросы.{(" Звоните, " + e(c['name']) + ".") if c.get('name') else ""}</p>
<p style="font-size:22px;font-weight:700">{e(c.get('phone') or '')}</p>
<div class="btns">{_contact_buttons(h)}</div>
</section>
</main>
<footer>{e(title)}</footer>
<div class="sticky">{_contact_buttons(h)}</div>
<div id="lb"><button class="x" aria-label="Закрыть">×</button><button class="p" aria-label="Назад">‹</button>
<img alt=""><button class="n" aria-label="Вперёд">›</button></div>
<script>{LIGHTBOX_JS}</script>
</body></html>
"""


def build_site(out: Path = ROOT / "_site") -> Path:
    h = load_house()
    photos = list_photos(h)
    if out.exists():
        shutil.rmtree(out)
    (out / "photos").mkdir(parents=True)
    for p in photos:
        shutil.copy2(p, out / "photos" / p.name)
    (out / "index.html").write_text(site_html(h, [p.name for p in photos]), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return out / "index.html"


KIT_CSS = CSS + """
.v{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:14px 0}
.v header{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.v pre{white-space:pre-wrap;font:15px/1.5 system-ui,sans-serif;margin:12px 0 0;max-height:260px;overflow:auto}
.v small{color:var(--muted)} button.btn{border:0;cursor:pointer;font:inherit}
.m{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--line)}
.m input{width:22px;height:22px;margin-top:3px}.m small{color:var(--muted);display:block}
"""

KIT_JS = """
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{
 const t=document.getElementById(b.dataset.copy).innerText;
 try{await navigator.clipboard.writeText(t)}catch(e){const r=document.createRange();
 r.selectNodeContents(document.getElementById(b.dataset.copy));getSelection().removeAllRanges();getSelection().addRange(r);document.execCommand('copy')}
 const o=b.textContent;b.textContent='✓ Скопировано';setTimeout(()=>b.textContent=o,1500)});
let s={};try{s=JSON.parse(localStorage.getItem('kit-done')||'{}')}catch(e){}
document.querySelectorAll('.m input').forEach(c=>{c.checked=!!s[c.id];c.onchange=()=>{s[c.id]=c.checked;
 try{localStorage.setItem('kit-done',JSON.stringify(s))}catch(e){}}});
"""

VARIANT_INFO = {
    "full": "Полный — свой канал, стена ВК, группы без ограничений",
    "medium": "Средний — подпись к фото в Telegram (до 1024 символов)",
    "short": "Короткий — чаты со строгими правилами",
    "plain": "Без эмодзи — доски объявлений, сайты, Одноклассники",
}


def build_kit(out: Path = ROOT / "out" / "kit.html") -> Path:
    h = load_house()
    targets, _ = load_targets()
    variants = texts.render_all(h)
    manual = [t for t in targets if t.platform == "manual" and t.enabled]
    blocks = "".join(
        f'<div class="v"><header><div><b>{e(VARIANT_INFO[k])}</b><br><small>{len(v)} символов</small></div>'
        f'<button class="btn" data-copy="t-{k}">📋 Копировать</button></header><pre id="t-{k}">{e(v)}</pre></div>'
        for k, v in variants.items())
    rows = "".join(
        f'<label class="m"><input type="checkbox" id="m-{e(t.id)}"><span><b>{e(t.name or t.id)}</b> '
        f'— текст: «{e(t.variant)}»'
        + (f' · <a href="{e(t.url)}" target="_blank" rel="noopener">открыть</a>' if t.url else "")
        + (f"<small>{e(t.note)}</small>" if t.note else "") + "</span></label>"
        for t in manual) or '<p class="empty">Ручных площадок нет.</p>'
    photos = list_photos(h)
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Пульт продажи дома</title>
<style>{KIT_CSS}</style></head><body><main class="wrap">
<section><h1 style="font-size:30px">🏡 Пульт продажи</h1>
<p>Все тексты собраны из <code>house.yaml</code>. Фото: {len(photos)} шт. в папке <code>photos/</code>.</p></section>
<section><h2>Тексты объявления</h2>{blocks}</section>
<section><h2>Ручные площадки</h2><p>Отмечайте галочкой, где уже разместили — отметки сохраняются в этом браузере.</p>{rows}</section>
</main><script>{KIT_JS}</script></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
