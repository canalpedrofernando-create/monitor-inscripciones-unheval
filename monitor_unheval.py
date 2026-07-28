from __future__ import annotations

import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests
from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


BASE_URL = "https://intranetestudiante.unheval.edu.pe/"

ALERT_KEY = "UNHEVAL_INSCRIPCIONES_ABIERTAS_2026"

CAPTURE_PATH = Path("captura_unheval.png")
MENU_ERROR_CAPTURE_PATH = Path("captura_menu_no_encontrado.png")

State = Literal[
    "CLOSED",
    "POSSIBLE_OPEN",
    "UNKNOWN",
]

CLOSED_MARKERS = (
    "no existe carga academica para el semestre actual",
    "la inscripcion aun no esta disponible",
    "fue desactivada temporalmente",
)


def normalize(text: str) -> str:
    """
    Convierte el texto a minúsculas, elimina tildes
    y normaliza los espacios.
    """
    decomposed = unicodedata.normalize("NFD", text)

    without_accents = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )

    return " ".join(without_accents.lower().split())


def timestamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def get_required_environment_variable(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Falta configurar el secreto de GitHub: {name}"
        )

    return value


def send_telegram(message: str) -> None:
    """
    Envía un mensaje al bot de Telegram.
    """
    token = get_required_environment_variable(
        "TELEGRAM_BOT_TOKEN"
    )
    chat_id = get_required_environment_variable(
        "TELEGRAM_CHAT_ID"
    )

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


def send_photo(
    image_path: Path,
    caption: str,
) -> None:
    """
    Envía una captura a Telegram.
    """
    if not image_path.exists():
        print(
            f"No se encontró la captura: {image_path}",
            flush=True,
        )
        return

    token = get_required_environment_variable(
        "TELEGRAM_BOT_TOKEN"
    )
    chat_id = get_required_environment_variable(
        "TELEGRAM_CHAT_ID"
    )

    with image_path.open("rb") as image_file:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": caption[:1024],
            },
            files={
                "photo": image_file,
            },
            timeout=60,
        )

    response.raise_for_status()


def body_text(page: Page) -> str:
    """
    Obtiene todo el texto visible de la página normalizado.
    """
    text = page.locator("body").inner_text(
        timeout=20_000
    )

    return normalize(text)


def login_form_visible(page: Page) -> bool:
    """
    Detecta si se encuentra visible el formulario de inicio
    de sesión.
    """
    try:
        password_input = page.locator(
            'input[type="password"]'
        )

        if (
            password_input.count() > 0
            and password_input.first.is_visible(
                timeout=2_000
            )
        ):
            return True

    except Exception:
        pass

    try:
        text = body_text(page)

        login_markers = (
            "codigo de estudiante",
            "contrasena",
            "iniciar sesion",
        )

        matches = sum(
            marker in text
            for marker in login_markers
        )

        return matches >= 2

    except Exception:
        return False


def first_visible(
    locators: list[Locator],
    element_name: str,
) -> Locator:
    """
    Retorna el primer elemento visible de una lista
    de posibles selectores.
    """
    for locator in locators:
        try:
            count = locator.count()

            for index in range(min(count, 10)):
                element = locator.nth(index)

                if element.is_visible(timeout=1_500):
                    return element

        except Exception:
            continue

    raise RuntimeError(
        f"No se encontró el elemento: {element_name}"
    )


def wait_for_dashboard(page: Page) -> bool:
    """
    Espera a que cargue alguna señal característica
    del panel principal de la intranet.
    """
    dashboard_patterns = (
        r"datos personales",
        r"historial de notas",
        r"avance curricular",
        r"inscripciones",
    )

    deadline = time.monotonic() + 30

    while time.monotonic() < deadline:
        if login_form_visible(page):
            time.sleep(1)
            continue

        try:
            text = body_text(page)

            if any(
                re.search(pattern, text, re.IGNORECASE)
                for pattern in dashboard_patterns
            ):
                return True

        except Exception:
            pass

        time.sleep(1)

    return False


def login(page: Page) -> None:
    """
    Completa el formulario de acceso utilizando los secretos
    configurados en GitHub Actions.
    """
    student_code = get_required_environment_variable(
        "UNHEVAL_STUDENT_CODE"
    )
    password = get_required_environment_variable(
        "UNHEVAL_PASSWORD"
    )

    print(
        "Sesión cerrada: iniciando sesión.",
        flush=True,
    )

    code_input = first_visible(
        [
            page.get_by_placeholder(
                re.compile(
                    r"c[oó]digo de estudiante",
                    re.IGNORECASE,
                )
            ),
            page.get_by_label(
                re.compile(
                    r"c[oó]digo de estudiante",
                    re.IGNORECASE,
                )
            ),
            page.locator('input[type="text"]'),
        ],
        "Código de Estudiante",
    )

    password_input = first_visible(
        [
            page.get_by_placeholder(
                re.compile(
                    r"contrase[nñ]a",
                    re.IGNORECASE,
                )
            ),
            page.get_by_label(
                re.compile(
                    r"contrase[nñ]a",
                    re.IGNORECASE,
                )
            ),
            page.locator('input[type="password"]'),
        ],
        "Contraseña",
    )

    login_button = first_visible(
        [
            page.get_by_role(
                "button",
                name=re.compile(
                    r"iniciar sesi[oó]n",
                    re.IGNORECASE,
                ),
            ),
            page.get_by_text(
                re.compile(
                    r"^\s*iniciar sesi[oó]n\s*$",
                    re.IGNORECASE,
                )
            ),
            page.locator(
                'button[type="submit"]'
            ),
        ],
        "Iniciar Sesión",
    )

    code_input.fill(student_code)
    password_input.fill(password)

    login_button.click(
        timeout=10_000
    )

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=20_000,
        )
    except PlaywrightTimeoutError:
        pass

    try:
        page.locator(
            'input[type="password"]'
        ).wait_for(
            state="hidden",
            timeout=20_000,
        )
    except Exception:
        pass

    page.wait_for_timeout(5_000)

    if login_form_visible(page):
        page.screenshot(
            path="captura_login_fallido.png",
            full_page=True,
        )

        raise RuntimeError(
            "El inicio de sesión no se completó. "
            "Comprueba el código, la contraseña o si apareció "
            "una validación adicional."
        )

    if not wait_for_dashboard(page):
        page.screenshot(
            path="captura_panel_no_cargado.png",
            full_page=True,
        )

        raise RuntimeError(
            "El formulario desapareció, pero el panel principal "
            "no terminó de cargar."
        )

    print(
        "Inicio de sesión completado.",
        flush=True,
    )


def close_initial_modal_if_needed(page: Page) -> None:
    """
    Cierra solamente una ventana previa que bloquee el menú.

    No cierra la ventana de Inscripciones que contiene:
    'No existe carga académica para el semestre actual'.
    """
    try:
        text = body_text(page)
    except Exception:
        return

    if (
        "no existe carga academica para el semestre actual"
        in text
    ):
        return

    modal_buttons = [
        page.get_by_role(
            "button",
            name=re.compile(
                r"^(ok|aceptar|continuar|cerrar)$",
                re.IGNORECASE,
            ),
        ),
        page.get_by_text(
            re.compile(
                r"^(ok|aceptar|continuar|cerrar)$",
                re.IGNORECASE,
            )
        ),
        page.locator(
            "button"
        ).filter(
            has_text=re.compile(
                r"ok|aceptar|continuar|cerrar",
                re.IGNORECASE,
            )
        ),
    ]

    for locator in modal_buttons:
        try:
            count = locator.count()

            for index in range(min(count, 5)):
                button = locator.nth(index)

                if button.is_visible(timeout=1_000):
                    button.click(
                        timeout=5_000,
                        force=True,
                    )

                    page.wait_for_timeout(1_500)

                    print(
                        "Se cerró una ventana inicial "
                        "que bloqueaba el menú.",
                        flush=True,
                    )

                    return

        except Exception:
            continue


def click_inscriptions(page: Page) -> None:
    """
    Busca y pulsa el menú Inscripciones utilizando
    varios selectores posibles.
    """
    page.wait_for_timeout(3_000)

    close_initial_modal_if_needed(page)

    if not wait_for_dashboard(page):
        page.screenshot(
            path=str(MENU_ERROR_CAPTURE_PATH),
            full_page=True,
        )

        raise RuntimeError(
            "El panel principal no cargó antes de buscar "
            "el menú Inscripciones."
        )

    candidates = [
        page.get_by_text(
            re.compile(
                r"^\s*inscripciones\s*$",
                re.IGNORECASE,
            )
        ),
        page.locator(
            "a"
        ).filter(
            has_text=re.compile(
                r"inscripciones",
                re.IGNORECASE,
            )
        ),
        page.locator(
            "li"
        ).filter(
            has_text=re.compile(
                r"inscripciones",
                re.IGNORECASE,
            )
        ),
        page.locator(
            "span"
        ).filter(
            has_text=re.compile(
                r"^\s*inscripciones\s*$",
                re.IGNORECASE,
            )
        ),
        page.locator(
            "div"
        ).filter(
            has_text=re.compile(
                r"^\s*inscripciones\s*$",
                re.IGNORECASE,
            )
        ),
        page.locator(
            '[href*="inscripcion" i]'
        ),
        page.locator(
            '[onclick*="inscripcion" i]'
        ),
    ]

    for locator in candidates:
        try:
            count = locator.count()

            for index in range(min(count, 15)):
                element = locator.nth(index)

                if not element.is_visible(
                    timeout=1_000
                ):
                    continue

                try:
                    element.scroll_into_view_if_needed()
                except Exception:
                    pass

                element.click(
                    timeout=10_000,
                    force=True,
                )

                page.wait_for_timeout(5_000)

                print(
                    "Se pulsó el menú Inscripciones.",
                    flush=True,
                )

                return

        except Exception:
            continue

    page.screenshot(
        path=str(MENU_ERROR_CAPTURE_PATH),
        full_page=True,
    )

    try:
        current_text = page.locator(
            "body"
        ).inner_text(
            timeout=10_000
        )

        print(
            "Texto encontrado en la página:",
            flush=True,
        )

        print(
            current_text[:4000],
            flush=True,
        )

    except Exception:
        pass

    raise RuntimeError(
        "No se encontró el menú Inscripciones después "
        "de esperar a que cargara el panel principal."
    )


def inspect_once(
    page: Page,
) -> tuple[State, str]:
    """
    Ejecuta una comprobación completa:

    1. Abre la página principal.
    2. Inicia sesión cuando sea necesario.
    3. Entra a Inscripciones.
    4. Lee el mensaje flotante.
    5. No pulsa el botón Ok del mensaje de inscripción.
    """
    page.goto(
        BASE_URL,
        wait_until="domcontentloaded",
        timeout=60_000,
    )

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=12_000,
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(2_000)

    if login_form_visible(page):
        login(page)

    click_inscriptions(page)

    page.wait_for_timeout(3_000)

    text = body_text(page)

    page.screenshot(
        path=str(CAPTURE_PATH),
        full_page=True,
    )

    for marker in CLOSED_MARKERS:
        if marker in text:
            return (
                "CLOSED",
                (
                    "Se encontró el aviso habitual de cierre: "
                    f"{marker}"
                ),
            )

    if (
        "inscripciones" in text
        or "inscripcion regular" in text
        or "escuela profesional" in text
    ):
        return (
            "POSSIBLE_OPEN",
            (
                "La sección Inscripciones cargó, pero el mensaje "
                "habitual de cierre no apareció."
            ),
        )

    return (
        "UNKNOWN",
        (
            "La página cargó, pero no se reconoció el mensaje "
            "de cierre ni el contenido esperado."
        ),
    )


def main() -> None:
    """
    Función principal ejecutada por GitHub Actions.
    """
    required_secrets = (
        "UNHEVAL_STUDENT_CODE",
        "UNHEVAL_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    )

    for secret_name in required_secrets:
        get_required_environment_variable(
            secret_name
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-notifications",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 900,
            },
            locale="es-PE",
            timezone_id="America/Lima",
        )

        page = context.new_page()

        page.set_default_timeout(
            15_000
        )

        try:
            first_state, first_detail = inspect_once(
                page
            )

            print(
                f"Primera comprobación: "
                f"{first_state} | {first_detail}",
                flush=True,
            )

            if first_state == "CLOSED":
                print(
                    "Las inscripciones continúan cerradas.",
                    flush=True,
                )
                return

            if first_state == "POSSIBLE_OPEN":
                print(
                    "El mensaje de cierre desapareció. "
                    "Confirmando nuevamente en 20 segundos.",
                    flush=True,
                )

                time.sleep(20)

                second_state, second_detail = inspect_once(
                    page
                )

                print(
                    f"Segunda comprobación: "
                    f"{second_state} | {second_detail}",
                    flush=True,
                )

                if second_state == "POSSIBLE_OPEN":
                    alert_message = (
                        f"{ALERT_KEY}\n\n"
                        "🚨 POSIBLE APERTURA DE INSCRIPCIONES "
                        "UNHEVAL 🚨\n\n"
                        "El aviso «No existe carga académica para "
                        "el semestre actual» no apareció en dos "
                        "comprobaciones consecutivas.\n\n"
                        "Ingresa inmediatamente a la intranet y "
                        "verifica.\n\n"
                        f"Hora: {timestamp()}\n"
                        f"Página: {BASE_URL}"
                    )

                    send_telegram(
                        alert_message
                    )

                    send_photo(
                        CAPTURE_PATH,
                        (
                            "Captura automática de la sección "
                            "Inscripciones."
                        ),
                    )

                    print(
                        "Alerta de posible apertura enviada.",
                        flush=True,
                    )

                    return

                if second_state == "CLOSED":
                    print(
                        "La segunda revisión volvió a encontrar "
                        "el aviso de cierre. No se envió alarma.",
                        flush=True,
                    )

                    return

            warning_message = (
                "⚠️ El monitor UNHEVAL no pudo reconocer "
                "correctamente la página.\n\n"
                f"Estado: {first_state}\n"
                f"Detalle: {first_detail}\n"
                f"Hora: {timestamp()}"
            )

            send_telegram(
                warning_message
            )

            send_photo(
                CAPTURE_PATH,
                "Captura de la página no reconocida.",
            )

        except Exception as error:
            error_message = (
                "❌ Error en el monitor UNHEVAL de "
                "GitHub Actions.\n\n"
                f"{type(error).__name__}: {error}\n"
                f"Hora: {timestamp()}"
            )

            print(
                error_message,
                file=sys.stderr,
                flush=True,
            )

            try:
                page.screenshot(
                    path=str(CAPTURE_PATH),
                    full_page=True,
                )
            except Exception:
                pass

            try:
                send_telegram(
                    error_message
                )

                if MENU_ERROR_CAPTURE_PATH.exists():
                    send_photo(
                        MENU_ERROR_CAPTURE_PATH,
                        (
                            "Captura tomada cuando no se encontró "
                            "el menú Inscripciones."
                        ),
                    )

                elif CAPTURE_PATH.exists():
                    send_photo(
                        CAPTURE_PATH,
                        "Captura tomada al producirse el error.",
                    )

            except Exception as telegram_error:
                print(
                    (
                        "No se pudo enviar el error a Telegram: "
                        f"{telegram_error}"
                    ),
                    file=sys.stderr,
                    flush=True,
                )

            raise

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
