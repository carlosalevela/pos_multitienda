import logging
import threading

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://graph.facebook.com/v25.0/{phone_number_id}/messages"
_TEMPLATE_NAME = "cierre_turno"
_TEMPLATE_LANG  = "es_CO"


def _fmt(v):
    return f"${int(v):,}".replace(",", ".")


def _fila(label: str, valor: float) -> str:
    return f"  {label:<18}{_fmt(valor)}"


def _construir_parametros(datos: dict) -> tuple[list[str], list[str]]:
    """
    Plantilla cierre_turno:
      Header → {{1}} tienda
      Body   → {{1}} colaborador | {{2}} fecha | {{3}} detalle financiero | {{4}} cuadre
    """
    v     = datos["ventas"]
    gastos  = datos.get("total_gastos", 0)
    esperado = datos["monto_esperado"]
    dif   = datos["diferencia"]
    sep   = datos.get("abonos_separados", {})
    dev   = datos.get("devoluciones_neto_ef", 0)
    ini   = datos.get("monto_inicial", 0)
    cred  = datos.get("credito_efectivo", 0)
    canc  = datos.get("cancelaciones_efectivo", 0)
    ing_m = datos.get("ingresos_manual", 0)

    # ── Ventas ──
    lineas = [f"VENTAS ({v['num_transacciones']} transacciones)"]
    lineas.append(_fila("Efectivo:", v["efectivo"]))
    if v.get("tarjeta", 0):
        lineas.append(_fila("Datáfono:", v["tarjeta"]))
    if v.get("transferencia", 0):
        lineas.append(_fila("Transferencia:", v["transferencia"]))
    if v.get("mixto", 0):
        lineas.append(_fila("Mixto:", v["mixto"]))
    lineas.append(_fila("TOTAL ventas:", v["total"]))

    # ── Separados / créditos ──
    sep_total = sep.get("total", 0)
    sep_cant  = sep.get("cantidad", 0)
    if sep_total or cred or canc or ing_m:
        lineas.append("")
        lineas.append("INGRESOS ADICIONALES")
        if sep_total:
            lineas.append(_fila(f"Separados ({sep_cant}):", sep_total))
        if cred:
            lineas.append(_fila("Abonos crédito:", cred))
        if canc:
            lineas.append(_fila("Cancelaciones:", canc))
        if ing_m:
            lineas.append(_fila("Ingresos manual:", ing_m))

    # ── Devoluciones y gastos ──
    if dev or gastos:
        lineas.append("")
        lineas.append("EGRESOS")
        if dev:
            lineas.append(_fila("Devoluciones:", dev))
        if gastos:
            lineas.append(_fila("Gastos:", gastos))

    resumen = "\n".join(lineas)

    # ── Cuadre ──
    if dif == 0:
        estado_dif = "✅ Cuadre exacto"
    elif dif < 0:
        estado_dif = f"❌ Faltante: {_fmt(abs(dif))}"
    else:
        estado_dif = f"⚠️ Sobrante: {_fmt(dif)}"

    cuadre_lineas = []
    if ini:
        cuadre_lineas.append(_fila("Base caja:", ini))
    cuadre_lineas.append(_fila("Ef. esperado:", esperado))
    cuadre_lineas.append(estado_dif)
    cuadre = "\n".join(cuadre_lineas)

    header_params = [datos["tienda_nombre"]]
    body_params   = [
        datos.get("colaborador_nombre") or datos.get("empleado_nombre", "—"),
        datos["fecha_cierre"],
        resumen,
        cuadre,
    ]
    return header_params, body_params


def _enviar_template(token: str, phone_number_id: str, numero: str,
                     header_params: list[str], body_params: list[str]):
    url = _API_URL.format(phone_number_id=phone_number_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to":   numero,
        "type": "template",
        "template": {
            "name":     _TEMPLATE_NAME,
            "language": {"code": _TEMPLATE_LANG},
            "components": [
                {
                    "type": "header",
                    "parameters": [{"type": "text", "text": p} for p in header_params],
                },
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in body_params],
                },
            ],
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
