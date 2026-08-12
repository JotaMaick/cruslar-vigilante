# Vigilante externo de Cruslar

Comprueba cada 5 minutos, **desde fuera de la infraestructura de Cruslar**, que
los sitios responden y que su centinela de seguridad sigue vivo. Si algo falla
dos veces seguidas, avisa por Telegram.

## Por qué existe

Dentro del servidor ya hay dos capas de vigilancia: un vigía en tiempo real y un
guardián que lo supervisa. Pero **las dos mueren con el servidor**. Si la máquina
se apaga o pierde la red, no avisa nadie, porque los avisos salían justamente de
ahí. Este repositorio corre en GitHub Actions —otra infraestructura, otro
proveedor— y es el único que puede darse cuenta de que el servidor ha
desaparecido del todo.

También por eso no está en Cloudflare: toda la infraestructura de Cruslar pasa
por Cloudflare, y un vigilante alojado en aquello que vigila se queda ciego
exactamente cuando más falta hace.

## Qué comprueba

1. Que los sitios de `sitios.txt` respondan (no error de conexión, no 5xx).
2. Que el **latido** que publica el servidor esté fresco. Si ese fichero deja de
   actualizarse, el servidor está vivo pero su cron ha muerto — un fallo que
   desde fuera no se vería de ninguna otra forma.
3. Que ese latido diga que el vigía está sano.

## Por qué no avisa a la primera

Un fallo de red puntual entre GitHub y Cloudflare no es una caída. Hacen falta
**dos comprobaciones seguidas** (unos 10 minutos) antes de molestar. Avisa una
sola vez, y manda su mensaje de recuperación cuando vuelve.

## Sobre que sea público

Aquí no hay nada sensible. Las credenciales de Telegram y **hasta la URL del
latido** viven en los secretos cifrados de GitHub, nunca en el código: si la ruta
del latido fuese visible, cualquiera podría consultar si el vigía está caído
justo antes de atacar.

Es público porque GitHub solo regala minutos ilimitados de Actions en
repositorios públicos; en uno privado, comprobar cada 5 minutos agotaría la
cuota mensual en una semana.

## Ficheros

| Fichero | Para qué |
|---|---|
| `vigilar.py` | la comprobación |
| `sitios.txt` | qué URLs se vigilan (editable sin tocar código) |
| `estado.json` | memoria entre pasadas; se escribe solo cuando algo cambia |
| `.github/workflows/vigilar.yml` | el reloj |

El commit diario de `estado.json` no es decorativo: GitHub **desactiva** los cron
de un repositorio sin actividad durante 60 días, y un vigilante apagado en
silencio sería lo peor que podría pasar.
