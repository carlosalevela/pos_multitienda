import logging
import threading

import requests

logger = logging.getLogger(__name__)

_API_URL   = "https://graph.facebook.com/v25.0/{phone_number_id}/messages"
_MEDIA_URL = "https://graph.facebook.com/v25.0/{phone_number_id}/media"
_TEMPLATE_NAME = "cierre_turno_v2"
_TEMPLATE_LANG  = "es_CO"


def _fmt(v):
    return f"${int(v):,}".replace(",", ".")


def _seg(label: str, valor: float) -> str:
    """Segmento inline sin espacios extra: 'Label: $valor'"""
    return f"{label} {_fmt(valor)}"


def _construir_parametros(datos: dict) -> tuple[list[str], list[str]]:
    """
    Plantilla cierre_turno_v2:
      Header → texto fijo "CIERRE DE TURNO" (sin variables)
      Body   → {{1}} tienda | {{2}} cajero | {{3}} fecha
               {{4}} ventas del turno | {{5}} abonos y gastos | {{6}} cuadre
    NOTA: parámetros deben ser una sola línea sin saltos ni >4 espacios seguidos.
    """
    v        = datos["ventas"]
    gastos   = datos.get("total_gastos", 0)
    esperado = datos["monto_esperado"]
    contado  = datos.get("monto_contado", 0)
    dif      = datos["diferencia"]
    sep      = datos.get("abonos_separados", {})
    dev      = datos.get("devoluciones_neto_ef", 0)
    ini      = datos.get("monto_inicial", 0)
    cred     = datos.get("credito_efectivo", 0)
    canc     = datos.get("cancelaciones_efectivo", 0)
    ing_m    = datos.get("ingresos_manual", 0)

    # ── {{4}} Ventas del turno (cada método en su línea) ──
    ef_ventas = v.get("efectivo", 0)
    partes_v = []
    if ef_ventas:
        partes_v.append(_seg("Efectivo:", ef_ventas))
    if v.get("tarjeta", 0):
        partes_v.append(_seg("Tarjeta:", v["tarjeta"]))
    if v.get("transferencia", 0):
        partes_v.append(_seg("Transferencia:", v["transferencia"]))
    if v.get("mixto", 0):
        partes_v.append(_seg("Mixto:", v["mixto"]))
    partes_v.append(f"TOTAL: {_fmt(v['total'])} ({v['num_transacciones']} transac.)")
    ventas_str = " | ".join(partes_v)

    # ── {{5}} Abonos y gastos (cada item en su línea) ──
    sep_total = sep.get("total", 0)
    sep_cant  = sep.get("cantidad", 0)
    partes_ag = []
    if sep_total:
        partes_ag.append(f"Abonos: {_fmt(sep_total)} ({sep_cant} abonos)")
    if cred:
        partes_ag.append(_seg("Credito:", cred))
    if canc:
        partes_ag.append(_seg("Cancelac:", canc))
    if ing_m:
        partes_ag.append(_seg("Ingresos:", ing_m))
    if dev:
        partes_ag.append(_seg("Devoluc:", dev))
    if gastos:
        partes_ag.append(_seg("Gastos:", gastos))
    abonos_gastos_str = " | ".join(partes_ag) if partes_ag else "Sin movimientos adicionales"

    # ── {{6}} Cuadre de efectivo (cada línea separada) ──
    if dif == 0:
        estado_dif = "Cuadre exacto"
    elif dif < 0:
        estado_dif = f"FALTANTE: {_fmt(abs(dif))}"
    else:
        estado_dif = f"SOBRANTE: {_fmt(dif)}"

    abonos_ef = sep.get("efectivo", 0)
    cuadre_partes = []
    if ini:
        cuadre_partes.append(_seg("Base:", ini))
    if ef_ventas:
        cuadre_partes.append(_seg("+Ventas ef:", ef_ventas))
    if abonos_ef:
        cuadre_partes.append(_seg("+Abonos ef:", abonos_ef))
    cuadre_partes.append(_seg("=Esperado:", esperado))
    if contado:
        cuadre_partes.append(_seg("Contado:", contado))
    cuadre_partes.append(estado_dif)
    cuadre = " | ".join(cuadre_partes)

    header_params = []   # header es texto fijo, sin variables
    body_params   = [
        datos["tienda_nombre"],                                                # {{1}}
        datos.get("colaborador_nombre") or datos.get("empleado_nombre", "—"), # {{2}}
        datos["fecha_cierre"],                                                 # {{3}}
        ventas_str,                                                            # {{4}}
        abonos_gastos_str,                                                     # {{5}}
        cuadre,                                                                # {{6}}
    ]
    return header_params, body_params


def _enviar_template(token: str, phone_number_id: str, numero: str,
                     header_params: list[str], body_params: list[str]):
    url = _API_URL.format(phone_number_id=phone_number_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    components = []
    if header_params:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": p} for p in header_params],
        })
    components.append({
        "type": "body",
        "parameters": [{"type": "text", "text": p} for p in body_params],
    })
    payload = {
        "messaging_product": "whatsapp",
        "to":   numero,
        "type": "template",
        "template": {
            "name":       _TEMPLATE_NAME,
            "language":   {"code": _TEMPLATE_LANG},
            "components": components,
        },
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if not r.ok:
            logger.error("WhatsApp error %s a %s: %s", r.status_code, numero, r.text)
        r.raise_for_status()
        logger.info("WhatsApp template enviado a %s", numero)
    except Exception as exc:
        logger.error("Error enviando WhatsApp a %s: %s", numero, exc)


def enviar_cierre_turno(empresa_id: int, tienda_id: int, datos: dict):
    """
    Envía el resumen de cierre de turno por WhatsApp usando la plantilla aprobada.
    Se ejecuta en un hilo para no bloquear la respuesta HTTP.
    """
    from .models import WhatsAppConfig, WhatsAppDestinatario

    try:
        cfg = WhatsAppConfig.objects.get(empresa_id=empresa_id, activo=True)
    except WhatsAppConfig.DoesNotExist:
        logger.warning("WA: no hay WhatsAppConfig para empresa_id=%s", empresa_id)
        return

    destinatarios = list(WhatsAppDestinatario.objects.filter(
        empresa_id=empresa_id, activo=True,
    ))
    destinatarios = [
        d for d in destinatarios
        if not d.tiendas.exists() or d.tiendas.filter(id=tienda_id).exists()
    ]

    if not destinatarios:
        logger.warning("WA: ningún destinatario aplica para tienda_id=%s", tienda_id)
        return

    header_params, body_params = _construir_parametros(datos)

    def _enviar_todos():
        for d in destinatarios:
            _enviar_template(cfg.token, cfg.phone_number_id, d.numero,
                             header_params, body_params)

    threading.Thread(target=_enviar_todos, daemon=True).start()


# ── Envío de PDF de cierre ────────────────────────────────

def _subir_pdf(token: str, phone_number_id: str, pdf_bytes: bytes, filename: str) -> str:
    """Sube el PDF a la API de Meta y devuelve el media_id."""
    url = _MEDIA_URL.format(phone_number_id=phone_number_id)
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file":              (filename, pdf_bytes, "application/pdf"),
            "type":              (None, "application/pdf"),
            "messaging_product": (None, "whatsapp"),
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def _enviar_documento(token: str, phone_number_id: str, numero: str,
                      media_id: str, caption: str, filename: str):
    """Envía el documento ya subido a un número de WhatsApp."""
    url = _API_URL.format(phone_number_id=phone_number_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to":   numero,
        "type": "document",
        "document": {
            "id":       media_id,
            "caption":  caption,
            "filename": filename,
        },
    }
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    if not r.ok:
        logger.error("WA doc error %s a %s: %s", r.status_code, numero, r.text)
    r.raise_for_status()
    logger.info("WA documento enviado a %s", numero)


def enviar_pdf_cierre(empresa_id: int, tienda_id: int,
                      pdf_bytes: bytes, filename: str, caption: str) -> dict:
    """
    Sube el PDF a Meta una sola vez y lo envía a todos los destinatarios
    configurados para la tienda.
    Devuelve {"enviados": N, "errores": [...]}.
    """
    from .models import WhatsAppConfig, WhatsAppDestinatario

    try:
        cfg = WhatsAppConfig.objects.get(empresa_id=empresa_id, activo=True)
    except WhatsAppConfig.DoesNotExist:
        logger.warning("WA: no hay WhatsAppConfig para empresa_id=%s", empresa_id)
        return {"enviados": 0, "errores": ["Sin configuración de WhatsApp."]}

    destinatarios = list(WhatsAppDestinatario.objects.filter(
        empresa_id=empresa_id, activo=True,
    ))
    destinatarios = [
        d for d in destinatarios
        if not d.tiendas.exists() or d.tiendas.filter(id=tienda_id).exists()
    ]

    if not destinatarios:
        return {"enviados": 0, "errores": ["Sin destinatarios configurados."]}

    try:
        media_id = _subir_pdf(cfg.token, cfg.phone_number_id, pdf_bytes, filename)
    except Exception as exc:
        logger.error("WA: error subiendo PDF: %s", exc)
        return {"enviados": 0, "errores": [f"Error subiendo PDF: {exc}"]}

    enviados = 0
    errores  = []
    for d in destinatarios:
        try:
            _enviar_documento(cfg.token, cfg.phone_number_id, d.numero,
                              media_id, caption, filename)
            enviados += 1
        except Exception as exc:
            errores.append(f"{d.numero}: {exc}")

    return {"enviados": enviados, "errores": errores}


# ── Envío de PDF con template aprobado cierre_pdf ────────
_TEMPLATE_PDF = "cierre_pdf"


def enviar_pdf_cierre_template(empresa_id: int, tienda_id: int,
                                pdf_bytes: bytes, filename: str,
                                tienda_nombre: str, fecha: str) -> dict:
    """
    Sube el PDF a Meta y lo envía usando el template 'cierre_pdf'.
    Body: {{1}} = tienda_nombre, {{2}} = fecha (DD/MM/YYYY).
    """
    from .models import WhatsAppConfig, WhatsAppDestinatario

    try:
        cfg = WhatsAppConfig.objects.get(empresa_id=empresa_id, activo=True)
    except WhatsAppConfig.DoesNotExist:
        logger.warning("WA: no hay WhatsAppConfig para empresa_id=%s", empresa_id)
        return {"enviados": 0, "errores": ["Sin configuración de WhatsApp."]}

    destinatarios = list(WhatsAppDestinatario.objects.filter(
        empresa_id=empresa_id, activo=True,
    ))
    destinatarios = [
        d for d in destinatarios
        if not d.tiendas.exists() or d.tiendas.filter(id=tienda_id).exists()
    ]
    if not destinatarios:
        return {"enviados": 0, "errores": ["Sin destinatarios configurados."]}

    try:
        media_id = _subir_pdf(cfg.token, cfg.phone_number_id, pdf_bytes, filename)
    except Exception as exc:
        logger.error("WA: error subiendo PDF: %s", exc)
        return {"enviados": 0, "errores": [f"Error subiendo PDF: {exc}"]}

    # Convertir fecha YYYY-MM-DD → DD/MM/YYYY si es necesario
    if len(fecha) == 10 and fecha[4] == '-':
        fecha = f"{fecha[8:10]}/{fecha[5:7]}/{fecha[:4]}"

    url = _API_URL.format(phone_number_id=cfg.phone_number_id)
    headers = {"Authorization": f"Bearer {cfg.token}", "Content-Type": "application/json"}

    enviados = 0
    errores  = []
    for d in destinatarios:
        payload = {
            "messaging_product": "whatsapp",
            "to":   d.numero,
            "type": "template",
            "template": {
                "name":     _TEMPLATE_PDF,
                "language": {"code": _TEMPLATE_LANG},
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {
                                "type":     "document",
                                "document": {"id": media_id, "filename": filename},
                            }
                        ],
                    },
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": tienda_nombre},
                            {"type": "text", "text": fecha},
                        ],
                    },
                ],
            },
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            if not r.ok:
                logger.error("WA cierre_pdf error %s a %s: %s", r.status_code, d.numero, r.text)
                errores.append(f"{d.numero}: {r.text[:80]}")
            else:
                logger.info("WA cierre_pdf enviado a %s", d.numero)
                enviados += 1
        except Exception as exc:
            errores.append(f"{d.numero}: {exc}")

    return {"enviados": enviados, "errores": errores}


# ── Recordatorio de separados próximos a vencer ───────────
_TEMPLATE_RECORDATORIO = "recordatorio_separado"


def enviar_recordatorio_separado(empresa_id: int, tienda_id: int, separados: list) -> dict:
    """
    Envía un WhatsApp de recordatorio a los clientes de los separados dados.
    separados: lista de dicts con keys: cliente_nombre, separado_id, tienda_nombre,
               fecha_limite (str DD/MM/YYYY), saldo_pendiente (str), telefono.
    Devuelve {"enviados": N, "sin_telefono": [...], "errores": [...]}.
    """
    from .models import WhatsAppConfig

    try:
        cfg = WhatsAppConfig.objects.get(empresa_id=empresa_id, activo=True)
    except WhatsAppConfig.DoesNotExist:
        logger.warning("WA: no hay WhatsAppConfig para empresa_id=%s", empresa_id)
        return {"enviados": 0, "sin_telefono": [], "errores": ["Sin configuración de WhatsApp."]}

    enviados    = 0
    errores     = []
    sin_telefono = []

    for s in separados:
        numero = (s.get("telefono") or "").strip()
        if not numero:
            sin_telefono.append(f"Separado #{s['separado_id']} - {s['cliente_nombre']}")
            continue
        # Normalizar número: agregar 57 si no tiene código de país
        if not numero.startswith("+") and not numero.startswith("57"):
            numero = "57" + numero

        body_params = [
            s["cliente_nombre"],
            str(s["separado_id"]),
            s["tienda_nombre"],
            s["fecha_limite"],
            s["saldo_pendiente"],
        ]
        try:
            url = _API_URL.format(phone_number_id=cfg.phone_number_id)
            payload = {
                "messaging_product": "whatsapp",
                "to":   numero,
                "type": "template",
                "template": {
                    "name":     _TEMPLATE_RECORDATORIO,
                    "language": {"code": _TEMPLATE_LANG},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": p} for p in body_params],
                        },
                    ],
                },
            }
            r = requests.post(url, json=payload,
                              headers={"Authorization": f"Bearer {cfg.token}",
                                       "Content-Type": "application/json"},
                              timeout=10)
            if not r.ok:
                logger.error("WA recordatorio error %s a %s: %s", r.status_code, numero, r.text)
                errores.append(f"{s['cliente_nombre']} ({numero}): {r.text[:80]}")
            else:
                logger.info("WA recordatorio enviado a %s (separado #%s)", numero, s["separado_id"])
                enviados += 1
        except Exception as exc:
            errores.append(f"{s['cliente_nombre']} ({numero}): {exc}")

    return {"enviados": enviados, "sin_telefono": sin_telefono, "errores": errores}
