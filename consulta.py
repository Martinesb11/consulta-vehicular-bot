import os, re, time, glob, shutil, base64, random
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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

def crear_driver():
    download_dir = os.path.abspath('descargas_cv')
    os.makedirs(download_dir, exist_ok=True)
    base = [
        '--headless=new',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-software-rasterizer',
        '--disable-extensions',
        '--disable-plugins',
        '--no-zygote',
        '--disable-blink-features=AutomationControlled',
        '--window-size=1280,900',
        '--lang=es-PE',
        '--no-first-run',
        '--disable-background-networking',
        '--disable-sync',
        '--disable-translate',
        '--hide-scrollbars',
        '--metrics-recording-only',
        '--mute-audio',
        '--safebrowsing-disable-auto-update',
        '--js-flags=--max-old-space-size=256',
    ]
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    prefs = {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'plugins.always_open_pdf_externally': True,
        'safebrowsing.enabled': True,
    }
    def _opts(binary=None):
        opts = Options()
        for a in base:
            opts.add_argument(a)
        opts.add_argument(f'--user-agent={ua}')
        opts.add_experimental_option('prefs', prefs)
        opts.add_experimental_option('excludeSwitches', ['enable-automation'])
        opts.add_experimental_option('useAutomationExtension', False)
        if binary:
            opts.binary_location = binary
        return opts
    try:
        d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=_opts())
    except Exception:
        for binary in ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']:
            try:
                d = webdriver.Chrome(options=_opts(binary))
                break
            except Exception:
                continue
        else:
            raise RuntimeError('No se pudo iniciar Chrome.')
    try:
        d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['es-PE','es','en-US']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                window.chrome = { runtime: {} };
            """
        })
    except Exception:
        pass
    try:
        d.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    except Exception:
        pass
    d._download_dir = download_dir
    return d

def esperar_documento_listo(driver, timeout=25):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script('return document.readyState') in ('interactive', 'complete')
    )

def js_click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({behavior:'instant',block:'center'});", el)
    time.sleep(0.3)
    try:
        el.click()
        return
    except Exception:
        pass
    try:
        ActionChains(driver).move_to_element(el).pause(0.2).click(el).perform()
        return
    except Exception:
        pass
    driver.execute_script("arguments[0].click();", el)

def escribir_humano(driver, el, valor):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.3)
    try:
        el.click()
    except Exception:
        pass
    time.sleep(0.2)
    try:
        el.send_keys(Keys.CONTROL, 'a')
        time.sleep(0.1)
        el.send_keys(Keys.DELETE)
        time.sleep(0.1)
    except Exception:
        pass
    driver.execute_script("arguments[0].value = '';", el)
    driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", el)
    time.sleep(0.2)
    for char in valor:
        el.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    time.sleep(0.3)

def buscar(driver, selectores, timeout=12, visibles=True):
    fin = time.time() + timeout
    while time.time() < fin:
        for by, sel in selectores:
            try:
                for el in driver.find_elements(by, sel):
                    if (visibles and el.is_displayed()) or not visibles:
                        return el
            except Exception:
                pass
        time.sleep(0.3)
    return None

def cerrar_popups(driver):
    try:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    except Exception:
        pass
    time.sleep(0.3)
    for by, sel in [
        (By.CSS_SELECTOR, "[aria-label*='close' i],[aria-label*='cerrar' i]"),
        (By.CSS_SELECTOR, "button[class*='close' i],.close,.cerrar"),
        (By.XPATH, "//button[normalize-space(.)='×']"),
    ]:
        try:
            for el in driver.find_elements(by, sel):
                if el.is_displayed():
                    try:
                        js_click(driver, el)
                        time.sleep(0.2)
                    except Exception:
                        pass
        except Exception:
            pass

def cerrar_alerta_si_existe(driver):
    try:
        WebDriverWait(driver, 3).until(EC.alert_is_present())
        alerta = driver.switch_to.alert
        print(f'Alerta detectada: {alerta.text}')
        alerta.accept()
        time.sleep(0.5)
        return True
    except Exception:
        return False

def hacer_login(driver, usuario, contrasena):
    print('Cargando pagina de login...')
    driver.get(URL_LOGIN)
    esperar_documento_listo(driver, 30)
    time.sleep(3)
    cerrar_alerta_si_existe(driver)
    cerrar_popups(driver)

    campo_user = buscar(driver, [
        (By.CSS_SELECTOR, 'input#email'),
        (By.CSS_SELECTOR, 'input[type="email"]'),
        (By.XPATH, "//input[@placeholder='Correo' or @placeholder='Email' or @placeholder='Usuario']"),
    ], timeout=10, visibles=False)
    campo_pass = buscar(driver, [
        (By.CSS_SELECTOR, 'input#password'),
        (By.CSS_SELECTOR, 'input[type="password"]'),
    ], timeout=10, visibles=False)
    if not campo_user or not campo_pass:
        raise Exception('No se encontraron los campos de login')

    print('Escribiendo credenciales...')
    escribir_humano(driver, campo_user, usuario)
    print(f'Usuario ingresado')
    time.sleep(0.5)

    # Re-buscar por si el DOM se actualizó
    campo_pass = buscar(driver, [
        (By.CSS_SELECTOR, 'input#password'),
        (By.CSS_SELECTOR, 'input[type="password"]'),
    ], timeout=5, visibles=False)
    escribir_humano(driver, campo_pass, contrasena)
    print(f'Contrasena ingresada')
    time.sleep(0.5)

    # Enviar formulario
    enviado = False
    for by, sel in [
        (By.XPATH, "//button[contains(translate(.,'INGRESAR','ingresar'),'ingresar')]"),
        (By.XPATH, "//button[contains(translate(.,'INICIAR','iniciar'),'iniciar')]"),
        (By.CSS_SELECTOR, 'button[type="submit"]'),
        (By.CSS_SELECTOR, 'input[type="submit"]'),
    ]:
        try:
            for btn in driver.find_elements(by, sel):
                if btn.is_displayed():
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.3)
                    js_click(driver, btn)
                    enviado = True
                    break
            if enviado:
                break
        except Exception:
            pass
    if not enviado:
        campo_pass.send_keys(Keys.ENTER)

    time.sleep(3)
    cerrar_alerta_si_existe(driver)
    esperar_documento_listo(driver, 25)

    fin = time.time() + 30
    while time.time() < fin:
        cerrar_alerta_si_existe(driver)
        url_actual = (driver.current_url or '').lower()
        txt = texto_normalizado(driver.find_element(By.TAG_NAME, 'body').text)
        if 'reult2' in url_actual or 'result2' in url_actual:
            print('✅ Login exitoso')
            return
        if any(m in txt for m in ['consultar placa', 'reporte vehicular', 'impuesto vehicular']):
            print('✅ Login exitoso')
            return
        time.sleep(1.0)
    raise Exception(f'Login no confirmado. URL: {driver.current_url}')

def resumen_estado_carga(driver):
    texto = texto_normalizado(driver.find_element(By.TAG_NAME, 'body').text)
    return {
        'texto_len': len(texto),
        'tablas': len(driver.find_elements(By.TAG_NAME, 'table')),
        'consultando': texto.count('consultando papeletas'),
        'modulos': sum(1 for m in ['soat', 'vehiculo', 'sutran', 'revision tecnica', 'impuesto vehicular', 'sat lima', 'sat callao'] if m in texto),
    }

def esperar_reporte_completo(driver, timeout=320, estable_s=10):
    inicio = time.time()
    ultimo, desde_estable, ultimo_log = None, None, 0
    while time.time() - inicio < timeout:
        try:
            estado = resumen_estado_carga(driver)
        except Exception:
            time.sleep(2)
            continue
        ahora = time.time()
        if ahora - ultimo_log >= 15:
            print(f"  {int(ahora-inicio)}s | tablas={estado['tablas']} | modulos={estado['modulos']} | consultando={estado['consultando']}")
            ultimo_log = ahora
        if estado['modulos'] >= 4 and estado['texto_len'] > 800 and estado['consultando'] == 0:
            if ultimo == estado:
                if desde_estable is None:
                    desde_estable = ahora
                elif ahora - desde_estable >= estable_s:
                    return True
            else:
                desde_estable = ahora
        else:
            desde_estable = None
        ultimo = estado
        try:
            driver.execute_script('window.scrollBy(0,500);')
            time.sleep(0.6)
            driver.execute_script('window.scrollBy(0,-120);')
        except Exception:
            pass
        time.sleep(2)
    return False

def consultar_placa(driver, placa):
    campo = None
    for url in [URL_CONSULTA, f'{URL_BASE}/result2.html']:
        try:
            driver.get(url)
            esperar_documento_listo(driver, 20)
            time.sleep(2)
            campo = buscar(driver, [
                (By.CSS_SELECTOR, 'input[placeholder*="placa" i]'),
                (By.XPATH, "//input[contains(translate(@placeholder,'PLACA','placa'),'placa')]"),
            ], timeout=5, visibles=False)
            if campo:
                break
        except Exception:
            pass
    if not campo:
        raise Exception('No se encontro el campo de placa')
    escribir_humano(driver, campo, placa)
    time.sleep(0.5)
    enviado = False
    for by, sel in [
        (By.XPATH, "//button[contains(translate(.,'CONSULTARBUSCAR','consultarbuscar'),'consultar') or contains(translate(.,'CONSULTARBUSCAR','consultarbuscar'),'buscar')]"),
        (By.CSS_SELECTOR, 'button[type="submit"]'),
    ]:
        try:
            for btn in driver.find_elements(by, sel):
                txt = texto_normalizado(btn.text or '')
                if btn.is_displayed() and 'registr' not in txt and 'pagar' not in txt:
                    js_click(driver, btn)
                    enviado = True
                    break
            if enviado:
                break
        except Exception:
            pass
    if not enviado:
        campo.send_keys(Keys.ENTER)
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
        nuevos = [p for p in (actuales - antes) if os.path.isfile(p)]
        pdfs = [p for p in nuevos if p.lower().endswith('.pdf')]
        if pdfs and not any(p.endswith('.crdownload') for p in nuevos):
            pdfs.sort(key=os.path.getmtime, reverse=True)
            return pdfs[0]
        time.sleep(1.0)
    return None

def descargar_pdf(driver, placa):
    selectores = [
        (By.XPATH, "//button[contains(normalize-space(.), 'Generar Reporte')]"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Generar')]"),
        (By.XPATH, "//a[contains(normalize-space(.), 'Generar Reporte')]"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Reporte')]"),
        (By.CSS_SELECTOR, 'button.btn-success'),
        (By.CSS_SELECTOR, 'button.btn-primary'),
        (By.CSS_SELECTOR, 'button[download], a[download]'),
    ]
    fin = time.time() + 60
    btn = None
    while time.time() < fin:
        for by, sel in selectores:
            try:
                for el in driver.find_elements(by, sel):
                    if el.is_displayed():
                        disabled = el.get_attribute('disabled') or 'disabled' in (el.get_attribute('class') or '').lower()
                        if not disabled:
                            btn = el
                            print(f'Boton encontrado: [{el.text}]')
                            break
                if btn:
                    break
            except Exception:
                pass
        if btn:
            break
        time.sleep(0.5)
    if not btn:
        print('ERROR: No se encontro el boton de descarga')
        return None
    antes = archivos_en_descargas(driver)
    try:
        js_click(driver, btn)
    except Exception:
        try:
            btn.send_keys(Keys.ENTER)
        except Exception:
            pass
    time.sleep(2)
    pdf = esperar_descarga_pdf(driver, antes, timeout=150)
    if pdf:
        nombre = f'reporte_{placa}_{timestamp()}.pdf'
        destino = os.path.abspath(nombre)
        try:
            shutil.move(pdf, destino)
        except Exception:
            shutil.copy2(pdf, destino)
        return destino
    return None

def pdf_a_base64(pdf_path):
    with open(pdf_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

# ── Consulta: driver nuevo por cada placa ─────────────────
def ejecutar_consulta_completa(placa, usuario, contrasena):
    placa      = placa.strip().upper()
    usuario    = usuario.strip()
    contrasena = contrasena.strip()
    driver     = None
    try:
        print(f'🚀 Creando driver para placa {placa}...')
        driver = crear_driver()
        hacer_login(driver, usuario, contrasena)
        print(f'Consultando placa {placa}...')
        consultar_placa(driver, placa)
        print('Descargando PDF...')
        pdf_path = descargar_pdf(driver, placa)
        if pdf_path:
            print(f'PDF listo: {pdf_path}')
            return pdf_path
        else:
            print('No se pudo descargar el PDF')
            return None
    except Exception as e:
        print(f'❌ Error en consulta: {e}')
        import traceback
        traceback.print_exc()
        return None
    finally:
        if driver:
            try:
                driver.quit()
                print(f'🔒 Driver cerrado para {placa}')
            except Exception:
                pass

# ── Mantener compatibilidad con app.py ────────────────────
def inicializar_driver_global():
    print('ℹ️ Modo driver-por-consulta activo (no se usa driver global)')
