from __future__ import annotations
import os, re, sys, time, unicodedata
from datetime import datetime
from pathlib import Path
import requests
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
BASE_URL='https://intranetestudiante.unheval.edu.pe/'
ALERT_KEY='UNHEVAL_INSCRIPCIONES_ABIERTAS_2026'
CAPTURE_PATH=Path('captura_unheval.png')
CLOSED_MARKERS=('no existe carga academica para el semestre actual','la inscripcion aun no esta disponible','fue desactivada temporalmente')
def normalize(text:str)->str:
 d=unicodedata.normalize('NFD',text); return ' '.join(''.join(c for c in d if unicodedata.category(c)!='Mn').lower().split())
def timestamp(): return datetime.now().strftime('%d/%m/%Y %H:%M:%S')
def send_telegram(message:str):
 r=requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",json={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':message,'disable_web_page_preview':True},timeout=30); r.raise_for_status()
def send_photo(caption:str):
 if not CAPTURE_PATH.exists(): return
 with CAPTURE_PATH.open('rb') as image:
  r=requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendPhoto",data={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'caption':caption[:1024]},files={'photo':image},timeout=60); r.raise_for_status()
def login_form_visible(page:Page)->bool:
 try:
  p=page.locator('input[type="password"]'); return p.count()>0 and p.first.is_visible(timeout=2000)
 except Exception: return False
def first_visible(candidates):
 for loc in candidates:
  try:
   if loc.count()>0 and loc.first.is_visible(timeout=1500): return loc.first
  except Exception: pass
 raise RuntimeError('No se encontró un elemento requerido del formulario.')
def login(page:Page):
 code=first_visible([page.get_by_placeholder(re.compile(r'c[oó]digo de estudiante',re.I)),page.get_by_label(re.compile(r'c[oó]digo de estudiante',re.I)),page.locator('input[type="text"]')])
 pwd=first_visible([page.get_by_placeholder(re.compile(r'contrase[nñ]a',re.I)),page.get_by_label(re.compile(r'contrase[nñ]a',re.I)),page.locator('input[type="password"]')])
 btn=first_visible([page.get_by_role('button',name=re.compile(r'iniciar sesi[oó]n',re.I)),page.locator('button[type="submit"]'),page.get_by_text(re.compile(r'^iniciar sesi[oó]n$',re.I))])
 code.fill(os.environ['UNHEVAL_STUDENT_CODE']); pwd.fill(os.environ['UNHEVAL_PASSWORD']); btn.click()
 try: page.wait_for_load_state('networkidle',timeout=15000)
 except PlaywrightTimeoutError: pass
 page.wait_for_timeout(4000)
 if login_form_visible(page): raise RuntimeError('No se pudo iniciar sesión. Verifica credenciales o validación adicional.')
def click_inscriptions(page:Page):
 for loc in [page.get_by_text('Inscripciones',exact=True),page.locator('a').filter(has_text='Inscripciones'),page.locator('li').filter(has_text='Inscripciones')]:
  try:
   if loc.count()>0 and loc.first.is_visible(timeout=2000): loc.first.click(timeout=10000); page.wait_for_timeout(4000); return
  except Exception: pass
 raise RuntimeError('No se encontró el menú Inscripciones.')
def inspect_once(page:Page):
 page.goto(BASE_URL,wait_until='domcontentloaded',timeout=60000)
 try: page.wait_for_load_state('networkidle',timeout=12000)
 except PlaywrightTimeoutError: pass
 if login_form_visible(page): print('Sesión cerrada: iniciando sesión.'); login(page)
 click_inscriptions(page)
 text=normalize(page.locator('body').inner_text(timeout=20000)); page.screenshot(path=str(CAPTURE_PATH),full_page=True)
 for marker in CLOSED_MARKERS:
  if marker in text: return 'CLOSED',marker
 if 'inscripciones' in text or 'inscripcion regular' in text: return 'POSSIBLE_OPEN','El mensaje habitual de cierre no apareció.'
 return 'UNKNOWN','No se reconoció el contenido de la página.'
def main():
 missing=[n for n in ('UNHEVAL_STUDENT_CODE','UNHEVAL_PASSWORD','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID') if not os.getenv(n)]
 if missing: raise RuntimeError('Faltan secretos: '+', '.join(missing))
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage']); context=browser.new_context(viewport={'width':1366,'height':768}); page=context.new_page(); page.set_default_timeout(15000)
  try:
   s1,d1=inspect_once(page); print('Primera comprobación:',s1,d1)
   if s1=='CLOSED': return
   if s1=='POSSIBLE_OPEN':
    time.sleep(20); s2,d2=inspect_once(page); print('Segunda comprobación:',s2,d2)
    if s2=='POSSIBLE_OPEN':
     send_telegram(f"{ALERT_KEY}\n\n🚨 POSIBLE APERTURA DE INSCRIPCIONES UNHEVAL 🚨\n\nEl aviso de cierre no apareció en dos comprobaciones consecutivas.\nIngresa inmediatamente a la intranet.\n\nHora: {timestamp()}\nPágina: {BASE_URL}"); send_photo('Captura automática de la sección Inscripciones.'); return
   send_telegram(f"⚠️ El monitor UNHEVAL no pudo reconocer la página.\nEstado: {s1}\nDetalle: {d1}\nHora: {timestamp()}"); send_photo('Captura de la página no reconocida.')
  except Exception as e:
   msg=f"❌ Error en el monitor UNHEVAL de GitHub Actions.\n{type(e).__name__}: {e}\nHora: {timestamp()}"; print(msg,file=sys.stderr)
   try: page.screenshot(path=str(CAPTURE_PATH),full_page=True); send_telegram(msg); send_photo('Captura tomada al producirse el error.')
   except Exception: pass
   raise
  finally: context.close(); browser.close()
if __name__=='__main__': main()
