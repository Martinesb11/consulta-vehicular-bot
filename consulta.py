import os, re, time, glob, shutil, base64
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

URL_BASE     = 'https://www.consultavehicular.services'
URL_LOGIN    = f'{URL_BASE}/'
URL_CONSULTA = f'{URL_BASE}/reult2.html'

def timestamp():
    return datetime.now().strftime('%Y%m%d_%H%M%S')

def texto_normalizado(txt):
    return re.sub(r'\s+', ' ', (txt or '').strip()).lower()

def limpiar_campo(txt):
    return re.sub(r'\s+', ' ', (txt or '').strip()).strip(' :')

def limpiar_nombre_hoja(nombre, fallback='Hoja'):
    nombre = re.sub(r'[\\/*?:\[\]]+', '_', (nombre or '').strip())
    nombre = re.sub(r'\s+', '_', nombre).strip('_')
    return (nombre[:31] or fallback)

def crear_driver():
    download_dir = os.path.abspath('descargas_cv')
    os.makedirs(download_dir, exist_ok=True)
    base = [
        '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars', '--disable-popup-blocking',
        '--window-size=1600,3200', '--lang=es-PE',
    ]
    ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
    prefs = {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'download.restrictions': 0,
        'plugins.always_open_pdf_externally': True,
        'safebrowsing.enabled': True,
    }
    def _opts(binary=None):
        opts = Options()
        for a in base: opts.add_argument(a)
        opts.add_argument(f'--user-agent={ua}')
        opts.add_experimental_option('prefs', prefs)
        if binary: opts.binary_location = binary
        return opts
    try:
        d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=_opts())
    except Exception:
        ultimo = None
        for binary in ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']:
            try: d = webdriver.Chrome(options=_opts(binary)); break
            except Exception as e: ultimo = e
        else:
            raise RuntimeError(f'No se pudo iniciar Chrome. {ultimo}')
    try:
        d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'language', {get: () => 'es-PE'});
                Object.defineProperty(navigator, 'languages', {get: () => ['es-PE','es','en']});
            """
        })
    except Exception: pass
    try:
        d.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    except Exception: pass
    d._download_dir = download_dir
    return d

def esperar_documento_listo(driver, timeout=25):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script('return document.readyState') in ('interactive', 'complete')
    )

def js_click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({behavior:'instant',block:'center'});", el)
    time.sleep(0.25)
    try: el.click(); return
    except Exception: pass
    try: ActionChains(driver).move_to_element(el).pause(0.15).click(el).perform(); return
    except Exception: pass
    driver.execute_script("arguments[0].click();", el)

def escribir_input(driver, el, valor):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    try: el.click()
    except Exception: pass
    try: el.clear()
    except Exception: pass
    try:
        el.send_keys(Keys.CONTROL, 'a')
        el.send_keys(Keys.DELETE)
        el.send_keys(valor)
    except Exception:
        driver.execute_script("""
            const el=arguments[0], value=arguments[1];
            el.focus(); el.value=value;
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            el.dispatchEvent(new Event('blur',{bubbles:true}));
        """, el, valor)

def buscar(driver, selectores, timeout=12, visibles=True):
    fin = time.time() + timeout
    while time.time() < fin:
        for by, sel in selectores:
            try:
                for el in driver.find_elements(by, sel):
                    if (visibles and el.is_displayed()) or not visibles:
                        return el
            except Exception: pass
        time.sleep(0.25)
    return None

def
