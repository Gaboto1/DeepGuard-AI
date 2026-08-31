# Runbook — El broker Redis (Upstash/Aiven) dejó de responder

## Cómo se detecta

- `.github/workflows/health-check.yml` corre cada 3 horas y falla (notificación de GitHub) si `redis_status` es `false`.
- Manualmente: `curl https://deepguard-ai-api.onrender.com/api/v1/health` — si `redis_status` es `false`, este runbook aplica.
- Si el campo `redis_info` menciona `getaddrinfo failed` / `Error -2` / `Non-existent domain`, el proveedor eliminó la instancia (típico de planes "trial" que expiran, p. ej. Aiven free trial a los 30 días).

## Causa raíz histórica

En junio de 2026 el broker (Aiven Valkey, plan free *trial*) expiró sin aviso. El sistema quedó con `dispatch_mode` imposible (sin Redis no hay cola) durante varios días sin que nadie lo notara, porque no había monitoreo. Por eso ahora:
1. Se usa **Upstash** (plan *free* permanente, no *trial*) en vez de Aiven.
2. Existe el workflow de monitoreo de la Sección "Cómo se detecta".

## Pasos de recuperación (15 minutos)

1. **Crear/recuperar la base Redis**
   - [console.upstash.com](https://console.upstash.com) → base de datos (ej. "DeepGuard AI") → pestaña **Connect**.
   - Copiar la URL que empieza con `rediss://default:...@....upstash.io:6379` (con doble `s`, TLS).
   - Si la base ya no existe, crear una nueva (**Create Database**, plan Free, región cercana a Render).

2. **Actualizar Render** (la API en la nube)
   - Dashboard de Render → servicio de la API → **Environment**.
   - Reemplazar `REDIS_URL` **y** `REDIS_BACKEND` por la nueva URL de Upstash (idéntica en ambas).
   - Guardar → Render redeploya solo (1-2 min). Confirmar en la pestaña **Events**.

3. **Actualizar el worker local**
   - Editar `backend/.env` → mismas dos variables, mismo valor que en Render.
   - Volver a ejecutar `INICIAR PAGINA WEB.bat`.

4. **Verificar**
   ```bash
   curl https://deepguard-ai-api.onrender.com/api/v1/health
   ```
   Debe responder `"redis_status":true` y, una vez el worker local esté corriendo ~30s, `"workers_online":true`.

   También se puede disparar manualmente el workflow de monitoreo: pestaña **Actions** del repo → "Monitoreo de salud — API + Redis" → **Run workflow**.

## Cómo evitar que vuelva a pasar

- **No usar planes "trial"** que expiran por fecha fija sin aviso — usar siempre el plan **Free** permanente de Upstash (o Redis Cloud, que también ofrece 30MB gratis sin expiración).
- Si Upstash llegara a pausar la base por inactividad prolongada (algunos free tiers lo hacen tras semanas sin tráfico), el propio workflow de monitoreo genera tráfico cada 3 horas — eso mismo ayuda a mantenerla "activa".
- Revisar cada tanto el correo asociado a la cuenta de Upstash/Render por avisos de cambios en el plan gratuito.
- **Nunca pegar tokens/contraseñas reales en chats o tickets** — si una credencial se expone, considerarla comprometida y regenerarla desde la consola del proveedor.
