#!/usr/bin/env python3
"""
Vigilante externo de Cruslar — comprueba desde FUERA que todo sigue en pie.

POR QUÉ EXISTE
Dentro del servidor ya hay dos capas: el vigía (tiempo real) y su guardián
(cron). Pero las dos mueren con el servidor. Si la máquina se apaga, se queda
sin disco o pierde la red, nadie avisa: los avisos salían justamente de ahí.
Este script corre en GitHub Actions, en otra infraestructura y en otro país, y
es el único que puede darse cuenta de que el servidor entero ha desaparecido.

QUÉ COMPRUEBA
  1. Que los sitios respondan (no 5xx, no error de conexión).
  2. Que el LATIDO que publica el servidor esté fresco — si el fichero deja de
     actualizarse, el servidor vive pero su cron está muerto.
  3. Que ese latido diga que el vigía está sano.

POR QUÉ NO AVISA A LA PRIMERA
Un fallo suelto de red entre GitHub y Cloudflare no es una caída. Hace falta
que dos comprobaciones seguidas (10 minutos) fallen antes de avisar. Y avisa
UNA vez, no en cada pasada, con su mensaje de recuperación al volver.

Nada sensible vive aquí: las credenciales y hasta la URL del latido son
secretos de GitHub. Por eso el repositorio puede ser público sin riesgo.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ESTADO = "estado.json"
FRESCURA_MAX = 25 * 60      # el guardián escribe cada 10 min: 25 da margen a 2 fallos
FALLOS_PARA_AVISAR = 2      # dos pasadas seguidas (10 min) antes de molestar
AGENTE = "VigilanteCruslar/1.0 (+https://github.com/JotaMaick/cruslar-vigilante)"


def ahora():
    return datetime.now(timezone.utc)


def pedir(url, intentos=3):
    """Devuelve (codigo, texto) o (None, motivo del fallo). Reintenta: un fallo
    de red puntual no puede confundirse con una caída."""
    ultimo = "sin intentar"
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""          # responde, aunque sea un error: el servidor vive
        except Exception as e:
            ultimo = type(e).__name__ + ": " + str(e)[:80]
            time.sleep(3 * (i + 1))
        # (los HTTPError salen arriba: solo se reintentan los fallos de conexión)
    return None, ultimo


def revisar_sitios(sitios):
    malos = []
    for url in sitios:
        codigo, detalle = pedir(url)
        if codigo is None:
            malos.append(f"{url} → no responde ({detalle})")
        elif codigo >= 500:
            malos.append(f"{url} → error {codigo} del servidor")
    return malos


def revisar_latido(url):
    if not url:
        return ["falta el secreto URL_LATIDO: el latido no se está comprobando"]
    codigo, texto = pedir(url)
    if codigo is None:
        return [f"el latido no responde ({texto})"]
    if codigo != 200:
        return [f"el latido devuelve {codigo}"]
    datos = dict(l.split("=", 1) for l in texto.split() if "=" in l)
    try:
        antiguedad = int(ahora().timestamp()) - int(datos.get("momento", 0))
    except ValueError:
        return ["el latido está corrupto (no entiendo su fecha)"]
    fallos = []
    if antiguedad > FRESCURA_MAX:
        fallos.append(f"el latido lleva {antiguedad // 60} min sin actualizarse "
                      f"(el servidor responde, pero su cron no escribe)")
    if datos.get("vigia") != "ok":
        fallos.append(f"el servidor dice que el vigía está MAL: {datos.get('averias', '?')}")
    return fallos


def telegram(texto):
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("!! faltan las credenciales de Telegram: no se puede avisar")
        return False
    datos = json.dumps({"chat_id": chat, "text": texto[:4000],
                        "disable_web_page_preview": True}).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=datos, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print("!! no salió el aviso de Telegram:", e)
        return False


def main():
    try:
        previo = json.load(open(ESTADO, encoding="utf-8"))
    except Exception:
        previo = {}
    estado = {"fallos_seguidos": previo.get("fallos_seguidos", 0),
              "avisado": previo.get("avisado", False),
              "dia": previo.get("dia", "")}

    sitios = [l.strip() for l in open("sitios.txt", encoding="utf-8")
              if l.strip() and not l.startswith("#")]
    fallos = revisar_sitios(sitios) + revisar_latido(os.environ.get("URL_LATIDO", ""))

    if fallos:
        # El contador se TOPA en el umbral: si no, durante una caída larga
        # cambiaría en cada pasada y haría un commit cada 5 minutos.
        estado["fallos_seguidos"] = min(estado["fallos_seguidos"] + 1, FALLOS_PARA_AVISAR)
        print(f"MAL ({estado['fallos_seguidos']} seguidas):")
        for f in fallos:
            print("  -", f)
    else:
        print("todo correcto")
        estado["fallos_seguidos"] = 0

    if estado["fallos_seguidos"] >= FALLOS_PARA_AVISAR and not estado["avisado"]:
        telegram("🔴 CRUSLAR NO RESPONDE\n\n"
                 + "\n".join("· " + f for f in fallos)
                 + "\n\nComprobado dos veces desde fuera del servidor (GitHub), "
                   "con 10 minutos de diferencia, así que no es un fallo de red puntual.\n\n"
                   "Si el servidor entero está caído, los avisos de dentro tampoco "
                   "van a llegar: este es el único que lo ve.")
        estado["avisado"] = True
    elif not fallos and estado["avisado"]:
        telegram("🟢 CRUSLAR RECUPERADO\n\n"
                 "Los sitios responden y el latido del vigía vuelve a estar fresco.")
        estado["avisado"] = False

    # El estado SOLO sobrevive si se hace commit: el runner de GitHub se destruye
    # al terminar. Por eso se guarda cuando cambia algo de fondo... y además una
    # vez al día, porque GitHub desactiva los cron de un repositorio sin actividad
    # durante 60 días, y un vigilante apagado en silencio sería lo peor de todo.
    hoy = ahora().strftime("%Y-%m-%d")
    de_fondo = {k: estado[k] for k in ("fallos_seguidos", "avisado")}
    cambio = de_fondo != {k: previo.get(k) for k in de_fondo} or previo.get("dia") != hoy
    if cambio:
        estado["dia"] = hoy
        estado["comprobado"] = ahora().strftime("%Y-%m-%d %H:%M UTC")
        json.dump(estado, open(ESTADO, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("estado guardado (habrá commit)")
    sys.exit(0)


if __name__ == "__main__":
    main()
