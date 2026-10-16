import logging
import threading

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://graph.facebook.com/v25.0/{phone_number_id}/messages"
_TEMPLATE_NAME = "cierre_turno"
_TEMPLATE_LANG  = "es_CO"


def _fmt(v):
    return f"${int(v):,}".replace(",", ".")


def _seg(label: str, valor: float) -> str:
    """Segmento inline sin espacios extra: 'Label: $valor'"""
    return f"{label} {_fmt(valor)}"


def _construir_parametros(datos: dict) -> tuple[list[str], list[str]]:
    """
    Plantilla cierre_turno:
      Header → {{1}} tienda
      Body   → {{1}} colaborador | {{2}} fecha | {{3}} detalle financiero | {{4}} cuadre
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

    # ── Ventas del turno por método ──
    ef_ventas = v.get("efectivo", 0)
    partes_metodos = []
    if ef_ventas:
        partes_metodos.append(_seg("Efec:", ef_ventas))
    if v.get("tarjeta", 0):
        partes_metodos.append(_seg("Tarj:", v["tarjeta"]))
    if v.get("transferencia", 0):
        partes_metodos.append(_seg("Transf:", v["transferencia"]))
    if v.get("mixto", 0):
        partes_metodos.append(_seg("Mixto:", v["mixto"]))

    total_ventas_str = _seg("TOTAL VENTAS:", v["total"])
    metodos_str = " | ".join(partes_metodos)

    # ── Ingresos y egresos adicionales ──
    sep_total = sep.get("total", 0)
    sep_cant  = sep.get("cantidad", 0)
    extras = []
    if sep_total:
        extras.append(_seg(f"Separados({sep_cant}):", sep_total))
    if cred:
        extras.append(_seg("Credito:", cred))
    if canc:
        extras.append(_seg("Cancelac:", canc))
    if ing_m:
        extras.append(_seg("Ingresos:", ing_m))
    if dev:
        extras.append(_seg("Devoluc:", dev))
    if gastos:
        extras.append(_seg("Gastos:", gastos))

    partes = [f"{v['num_transacciones']} transac.", metodos_str, total_ventas_str]
    if extras:
        partes.append("+" + " | ".join(extras))
    resumen = " -- ".join(p for p in partes if p)

    # ── Cuadre de efectivo ──
    if dif == 0:
        estado_dif = "Cuadre exacto"
    elif dif < 0:
        estado_dif = f"FALTANTE: {_fmt(abs(dif))}"
    else:
        estado_dif = f"SOBRANTE: {_fmt(dif)}"

    cuadre_partes = []
    if ini:
        cuadre_partes.append(_seg("Base:", ini))
    if ef_ventas:
        cuadre_partes.append(_seg("+Ventas ef:", ef_ventas))
    cuadre_partes.append(_seg("=Esperado:", esperado))
    if contado:
        cuadre_partes.append(_seg("Contado:", contado))
    cuadre_partes.append(estado_dif)
    cuadre = " | ".join(cuadre_partes)

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
