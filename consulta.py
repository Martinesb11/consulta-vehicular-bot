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

def cerrar_popups(driver):
    try: driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    except Exception: pass
    for by, sel in [
        (By.CSS_SELECTOR, "[aria-label*='close' i],[aria-label*='cerrar' i]"),
        (By.CSS_SELECTOR, "button[class*='close' i],.close,.cerrar"),
        (By.XPATH, "//button[normalize-space(.)='×' or contains(translate(.,'CERRAR','cerrar'),'cerrar')]")
    ]:
        try:
            for el in driver.find_elements(by, sel):
                if el.is_displayed():
                    try: js_click(driver, el); time.sleep(0.2)
                    except Exception: pass
        except Exception: pass

def login_confirmado(driver):
    txt = texto_normalizado(driver.find_element(By.TAG_NAME, 'body').text)
    if '/reult2' in (driver.current_url or '').lower(): return True
    return any(m in txt for m in ['consultar placa','reporte vehicular','impuesto vehicular','sat lima','sutran'])

def hacer_login(driver, usuario, contrasena):
    driver.get(URL_LOGIN)
    esperar_documento_listo(driver, 25)
    time.sleep(2)
    cerrar_popups(driver)
    campo_user = buscar(driver, [
        (By.CSS_SELECTOR, 'input#email'),
        (By.CSS_SELECTOR, 'input[type="email"]'),
        (By.XPATH, "//input[@id='email' or @placeholder='Correo']"),
    ], timeout=8, visibles=False)
    campo_pass = buscar(driver, [
        (By.CSS_SELECTOR, 'input#password'),
        (By.CSS_SELECTOR, 'input[type="password"]'),
    ], timeout=8, visibles=False)
    if not campo_user or not campo_pass:
        raise Exception('No se encontraron campos de login')
    escribir_input(driver, campo_user, usuario)
    escribir_input(driver, campo_pass, contrasena)
    time.sleep(0.4)
    enviado = False
    for by, sel in [
        (By.XPATH, "//button[contains(translate(.,'INGRESAR','ingresar'),'ingresar')]"),
        (By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
    ]:
        try:
            for btn in driver.find_elements(by, sel):
                if btn.is_displayed():
                    js_click(driver, btn); enviado = True; break
            if enviado: break
        except Exception: pass
    if not enviado: campo_pass.send_keys(Keys.ENTER)
    time.sleep(2)
    esperar_documento_listo(driver, 25)
    fin = time.time() + 25
    while time.time() < fin:
        if login_confirmado(driver): return
        time.sleep(0.8)
    raise Exception('Login no confirmado')

def resumen_estado_carga(driver):
    texto = texto_normalizado(driver.find_element(By.TAG_NAME, 'body').text)
    return {
        'texto_len': len(texto),
        'tablas': len(driver.find_elements(By.TAG_NAME, 'table')),
        'consultando': texto.count('consultando papeletas'),
        'modulos': sum(1 for m in ['soat','vehiculo','sutran','revision tecnica','impuesto vehicular','sat lima','sat callao'] if m in texto),
    }

def esperar_reporte_completo(driver, timeout=320, estable_s=10):
    inicio = time.time()
    ultimo, desde_estable, ultimo_log = None, None, 0
    while time.time() - inicio < timeout:
        try: estado = resumen_estado_carga(driver)
        except Exception: time.sleep(2); continue
        ahora = time.time()
        if ahora - ultimo_log >= 15:
            print(f"  • {int(ahora-inicio)}s | tablas={estado['tablas']} | modulos={estado['modulos']} | consultando={estado['consultando']}")
            ultimo_log = ahora
        if estado['modulos'] >= 4 and estado['texto_len'] > 800 and estado['consultando'] == 0:
            if ultimo == estado:
                if desde_estable is None: desde_estable = ahora
                elif ahora - desde_estable >= estable_s: return True
            else: desde_estable = ahora
        else: desde_estable = None
        ultimo = estado
        try:
            driver.execute_script('window.scrollBy(0,500);')
            time.sleep(0.6)
            driver.execute_script('window.scrollBy(0,-120);')
        except Exception: pass
        time.sleep(2)
    return False

def consultar_placa(driver, placa):
    campo = None
    if login_confirmado(driver):
        campo = buscar(driver, [
            (By.CSS_SELECTOR, 'input[placeholder*="placa" i]'),
            (By.XPATH, "//input[contains(translate(@placeholder,'PLACA','placa'),'placa')]")
        ], timeout=3, visibles=False)
    if not campo:
        for url in [URL_CONSULTA, f'{URL_BASE}/result2.html']:
            try:
                driver.get(url)
                esperar_documento_listo(driver, 20)
                time.sleep(1.5)
                campo = buscar(driver, [
                    (By.CSS_SELECTOR, 'input[placeholder*="placa" i]'),
                    (By.XPATH, "//input[contains(translate(@placeholder,'PLACA','placa'),'placa')]")
                ], timeout=4, visibles=False)
                if campo: break
            except Exception: pass
    if not campo:
        raise Exception('No se encontró el campo de placa')
    escribir_input(driver, campo, placa)
    time.sleep(0.4)
    enviado = False
    for by, sel in [
        (By.XPATH, "//button[contains(translate(.,'CONSULTARBUSCAR','consultarbuscar'),'consultar') or contains(translate(.,'CONSULTARBUSCAR','consultarbuscar'),'buscar')]"),
        (By.CSS_SELECTOR, 'button[type="submit"]')
    ]:
        try:
            for btn in driver.find_elements(by, sel):
                txt = texto_normalizado(btn.text or '')
                if btn.is_displayed() and 'registr' not in txt and 'pagar' not in txt:
                    js_click(driver, btn); enviado = True; break
            if enviado: break
        except Exception: pass
    if not enviado: campo.send_keys(Keys.ENTER)
    time.sleep(4)
    esperar_documento_listo(driver, 25)
    esperar_reporte_completo(driver, timeout=320, estable_s=10)

def archivos_en_descargas(driver):
    carpeta = getattr(driver, '_download_dir', os.getcwd())
    return set(glob.glob(os.path.join(carpeta, '*')))

def esperar_descarga_pdf(driver, antes, timeout=150):
    carpeta = getattr(driver, '_download_dir', os.getcwd())
    inicio = time.time()
    while time.time() - inicio < timeout:
        actuales = set(glob.glob(os.path.join(carpeta, '*')))
        nuevos   = [p for p in (actuales - antes) if os.path.isfile(p)]
        pdfs     = [p for p in nuevos if p.lower().endswith('.pdf')]
        if pdfs and not any(p.endswith('.crdownload') for p in nuevos):
            pdfs.sort(key=os.path.getmtime, reverse=True)
            return pdfs[0]
        time.sleep(1.0)
    return None

def descargar_pdf(driver, placa):
    selectores = [
        (By.XPATH, "//button[contains(translate(normalize-space(.),'GENERARREPORTE','generarreporte'),'generar reporte')]"),
        (By.XPATH, "//a[contains(translate(normalize-space(.),'GENERARREPORTE','generarreporte'),'generar reporte')]"),
        (By.CSS_SELECTOR, 'button[download], a[download]'),
    ]
    fin = time.time() + 50
    btn = None
    while time.time() < fin:
        for by, sel in selectores:
            try:
                for el in driver.find_elements(by, sel):
                    txt = texto_normalizado(el.text or el.get_attribute('aria-label') or '')
                    if ('reporte' in txt or el.get_attribute('download')) and el.is_displayed():
                        disabled = el.get_attribute('disabled') or 'disabled' in (el.get_attribute('class') or '').lower()
                        if not disabled: btn = el; break
                if btn: break
            except Exception: pass
        if btn: break
        time.sleep(0.5)
    if not btn: return None
    antes = archivos_en_descargas(driver)
    try: js_click(driver, btn)
    except Exception:
        try: btn.send_keys(Keys.ENTER)
        except Exception: pass
    time.sleep(2)
    pdf = esperar_descarga_pdf(driver, antes, timeout=150)
    if pdf:
        nombre  = f'reporte_{placa}_{timestamp()}.pdf'
        destino = os.path.abspath(nombre)
        try: shutil.move(pdf, destino)
        except Exception: shutil.copy2(pdf, destino)
        return destino
    return None

def pdf_a_base64(pdf_path):
    with open(pdf_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

def ejecutar_consulta_completa(placa, usuario, contrasena):
    """
    Función principal que ejecuta todo el flujo:
    Login → Consulta → Descarga PDF → Retorna ruta del PDF
    """
    placa  = placa.strip().upper()
    driver = crear_driver()
    try:
        print(f'🔑 Login para placa {placa}...')
        hacer_login(driver, usuario, contrasena)
        print(f'🔎 Consultando placa {placa}...')
        consultar_placa(driver, placa)
        print(f'📄 Descargando PDF...')
        pdf_path = descargar_pdf(driver, placa)
        if pdf_path:
            print(f'✅ PDF listo: {pdf_path}')
            return pdf_path
        else:
            print('⚠️ No se pudo descargar el PDF')
            return None
    finally:
        try: driver.quit()
        except Exception: pass
