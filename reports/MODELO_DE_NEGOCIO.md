# Modelo de negocio de DeepScan

Documento de diseño e implementación. Fecha: 16 de noviembre de 2026.

---

## 1. De dónde sale el modelo

El recurso escaso de DeepScan no es el almacenamiento ni el ancho de banda: es
el **tiempo de GPU**. Las cifras están medidas, no estimadas
(`reports/latencia_medida.json`):

| | mediana | p95 |
|---|---|---|
| Análisis completo, GPU dedicada | 32,4 s | 61,6 s |
| Solo el ensemble, sin análisis semántico | 5,3 s | 11,7 s |

Con una RTX 4070 SUPER y concurrencia 2, el techo práctico son del orden de
**150 análisis por hora**. Cualquier modelo de negocio que no mida análisis
está midiendo lo que no cuesta.

De ahí las tres decisiones que lo definen:

**Se cobra por capacidad, no por calidad.** El análisis es idéntico en todos
los planes: los seis detectores, el meta-ensemble y el análisis semántico.
Degradar el resultado del plan gratuito sería vender un detector peor a quien
no paga, y el producto es precisamente la fiabilidad del detector.

**El plan gratuito no pide registro.** El caso de uso principal es alguien que
recibe una imagen dudosa y quiere comprobarla ahora. Un formulario de registro
mata ese momento. La cuota diaria protege la GPU sin pedir nada a cambio.

**Ningún plan promete análisis ilimitados.** Con una sola tarjeta sería una
promesa incumplible, y prometer capacidad inexistente es la forma más rápida de
perder al primer cliente serio.

---

## 2. Qué se vende exactamente

Lo que distingue los planes de pago no es «más IA», son tres cosas concretas:

**El informe sellado.** Un PDF con el resultado, las salidas de los seis
detectores y un sello HMAC-SHA256 calculado sobre el hash del archivo original,
el score y la marca de tiempo. Permite a un tercero comprobar que el informe
corresponde a ese archivo exacto y que no se alteró después. Es la diferencia
entre «lo comprobé» y «puedo demostrar que lo comprobé». **El sistema ya emite
ese sello** (`backend/app/services/custody_service.py`); el plan de pago es lo
que da derecho a llevárselo.

**La prioridad en la cola.** Con concurrencia 2, en horas de uso un suscriptor
no debería esperar detrás de los gratuitos. Celery ya soporta prioridades en la
cola `images` (`x-max-priority: 10`), de modo que el campo `prioridad` del plan
se mapea directamente.

**El acceso por API y el lote**, para quien integra la verificación en su propio
flujo de trabajo.

Esto encaja con el cliente declarado en el informe ES2: *medios de comunicación
y organizaciones de verificación*. Para una redacción, el sello es el producto.

---

## 3. Los planes

| | Gratuito | Profesional | Pericial |
|---|---|---|---|
| Precio | $0 | **$9.990 CLP/mes** | **$29.990 CLP/mes** |
| Cuota | 5 análisis/día | 300 análisis/mes | 1.500 análisis/mes |
| Prioridad en cola | 1 | 5 | 9 |
| Informe PDF sellado | — | sí | sí |
| Análisis de video | — | sí | sí |
| Análisis por lote | — | sí | sí |
| Acceso por API | — | — | sí |
| Historial | 1 día | 90 días | 365 días |

Las cuotas se contrastaron contra la capacidad real: el plan Pericial, con 1.500
al mes, son 50 al día — cabe de sobra incluso con varios suscriptores
simultáneos.

Referencia de mercado: las herramientas equivalentes cobran por créditos o por
cuota mensual, con los análisis de imagen consumiendo bastante más que los de
texto (Copyleaks, Winston AI, Pangram). El esquema de cuota mensual con
prioridad es el habitual del sector.

---

## 4. El medio de pago: por qué no es Stripe

Esta es la parte donde la respuesta obvia es la equivocada.

**Stripe es la mejor opción técnica para suscripciones, y probablemente no
puedas usarlo.** Su disponibilidad para empresas chilenas es dudosa: las guías
se contradicen abiertamente —unas lo dan por operativo en Chile desde 2023,
otras dicen que Chile no figura en la lista pública de países soportados— y
varias coinciden en que la vía practicada es constituir una sociedad en Estados
Unidos. **Hay que confirmarlo en la lista oficial de países de Stripe antes de
comprometerse con nada.**

Alternativas, en orden de encaje con este proyecto:

| Pasarela | Encaje | Nota |
|---|---|---|
| **Flow** | **Recomendada** | La alternativa local más citada para suscripciones recurrentes en Chile. |
| Mercado Pago | Buena si se quiere cobrar también fuera de Chile | Suscripciones vía `preapproval`. |
| Transbank / Webpay | Estándar chileno, pero orientado a pago único | Encaja mal con una suscripción mensual. |
| Stripe | La mejor técnicamente | Bloqueada por disponibilidad; requiere sociedad extranjera. |

**Recomendación: Flow**, y Mercado Pago como segunda si más adelante se quiere
cobrar en el resto de LATAM.

---

## 5. Qué está implementado y qué no

### Implementado y probado (25 pruebas automatizadas)

- **Catálogo de planes y derechos** — `backend/app/billing/plans.py`
- **Licencias firmadas** — `backend/app/billing/licenses.py`. HMAC-SHA256 con
  clave propia. Sin base de datos, sin contraseñas y sin datos personales.
- **Contador de consumo** — `backend/app/billing/usage.py`. Ventanas de
  calendario en Redis, con TTL.
- **Identidad** — `backend/app/billing/identity.py`. Suscriptor por licencia;
  anónimo por dispositivo o IP, siempre con hash.
- **Pasarela simulada** — recorre el flujo completo sin mover dinero.
- **Endpoints** — `/api/v1/billing/plans`, `/me`, `/checkout`, `/webhook/{...}`
- **Página de precios** — `frontend/src/app/precios`

### Deliberadamente NO implementado

**La llamada real a Flow y a Mercado Pago.** El andamio está, leen sus
credenciales del entorno y se declaran no disponibles si faltan, pero la
petición HTTP no está escrita. No se completó por una razón concreta: **una
integración de cobro a medias, desplegada en una página pública, puede acabar
aceptando dinero real que nadie sabe devolver.** Eso necesita que tú crees las
cuentas y supervises la primera transacción.

**El webhook no concede licencias.** Responde 501 a propósito. Un webhook que
otorga un plan sin verificar la firma de la pasarela es una puerta abierta:
basta un POST para regalarse una suscripción. La verificación de firma es
específica de cada pasarela y debe escribirse **a la vez** que su checkout,
nunca antes.

**La cuota viene apagada.** `BILLING_ENABLED=false` por defecto. Todo el módulo
se puede consultar, pero nadie se queda sin servicio. Se escribió sin poder
probarlo en vivo, y un fallo contando cuotas se manifiesta dejando usuarios
fuera.

---

## 6. Para ponerlo en marcha

**Paso 1 — generar la clave de licencias** y ponerla en el entorno de la API en
Render (nunca en el repositorio):

```
python -c "import secrets; print(secrets.token_hex(32))"
DEEPGUARD_BILLING_KEY=<lo que salga>
```

Es independiente de `DEEPGUARD_SIGNING_KEY` a propósito: una acredita un
peritaje y la otra autoriza un cobro. Compartirlas significaría que comprometer
la facturación compromete la prueba forense.

**Paso 2 — probar en modo demostración.** Con solo esa clave, la pasarela
simulada queda disponible y se puede recorrer todo el flujo en la defensa, sin
cobrar nada y diciéndolo en pantalla.

**Paso 3 — encender la cuota** cuando te convenza: `BILLING_ENABLED=true`.

**Paso 4 — cobrar de verdad**, cuando decidas hacerlo:
1. Crear la cuenta en Flow y obtener `apiKey` y `secretKey`.
2. Implementar `PasarelaFlow.crear_checkout` contra `payment/create`.
3. Implementar la verificación de firma del webhook **antes** de que emita
   ninguna licencia.
4. Ponerlas en el entorno: `FLOW_API_KEY`, `FLOW_SECRET_KEY`.

**Antes del paso 4, lo que no es código:** cobrar en Chile obliga a emitir
boleta o factura y a declarar el IVA. Decide si facturas como persona natural o
constituyes una empresa, e inscribe la actividad en el SII. Esto no es
opcional y no lo resuelve ninguna pasarela.

---

## 7. Límites conocidos de lo implementado

**La identidad del plan gratuito es débil a propósito.** Un identificador
guardado en el navegador se borra vaciando la caché. Endurecerlo —huella del
navegador, bloqueo por IP— castigaría a universidades y oficinas tras un NAT,
que son parte del público objetivo. La cuota gratuita disuade el uso casual
excesivo; no pretende ser infranqueable.

**La licencia es un portador.** Quien la tenga, la usa, igual que una clave de
API. Por eso caduca a los 30 días. Revocar una licencia concreta antes de su
caducidad exigiría una lista de revocación, que no está implementada; cambiar
`DEEPGUARD_BILLING_KEY` invalida todas de golpe.

**El contador falla abierto.** Si Redis no responde, se permite el análisis y
se registra en el log. Un contador caído no es razón para dejar sin servicio a
quien paga.

**La prioridad de cola está definida pero no conectada.** El campo `prioridad`
existe en cada plan y Celery admite prioridades en la cola `images`, pero
`/analyze` todavía no la pasa al encolar. Es el siguiente paso natural y es
pequeño.

**El informe PDF sellado no está generado.** El sello HMAC existe y se emite
con cada análisis; lo que falta es componer el PDF que lo presenta. Es el
derecho que más justifica el precio, así que conviene que sea lo primero que se
construya.
