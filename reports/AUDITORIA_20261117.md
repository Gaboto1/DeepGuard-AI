# Auditoría del proyecto — 17 de noviembre de 2026

Revisión completa de DeepScan en seis frentes: seguridad, dependencias, API en
vivo, frontend, coherencia de datos y documentos, e higiene del repositorio.
Cada hallazgo se comprobó contra el sistema real (la API publicada en Render,
la página publicada en GitHub Pages o el código), no por inspección del texto.

## Resumen

| gravedad | hallazgo | estado |
|---|---|---|
| **Alta** | `scikit-learn`, `joblib` y `lightgbm` no estaban en `requirements.txt`. Una instalación nueva no cargaba ningún cabezal y caía **en silencio** a pesos fijos | corregido, versiones exactas fijadas y prueba |
| **Alta** | Límite de subida de 500 MB frente a 512 MB de RAM en Render, con el archivo leído entero en memoria y copiado en Base64: una sola subida podía tumbar la API | corregido: 100 MB y rechazo previo por `Content-Length`, con prueba |
| **Alta** | `/api/v1/history` devolvía los análisis de todos los usuarios sin pedir identidad | desactivado por defecto, con prueba |
| **Alta** | Los cabezales están entrenados con OpenFake, licencia **CC BY-NC 4.0** (no comercial), mientras el proyecto plantea un modelo de pago | documentado en README y en el modelo de negocio; decisión pendiente antes de cobrar |
| Media | python-multipart 0.0.6 y starlette 0.27 con vulnerabilidades de denegación de servicio en el procesado de subidas | actualizado a FastAPI 0.115.14 / python-multipart 0.0.20; 132 pruebas en verde |
| Media | Next.js 14.0.4 con un aviso crítico y axios con varios altos | actualizado a Next 14.2.35 y axios 1.21; ver «riesgo aceptado» |
| Media | El objeto de configuración mostraba fragmentos de claves al imprimirse (visto en un mensaje de error de pytest) | `repr=False` en los campos con credenciales, con prueba |
| Media | Un cabezal que no carga solo dejaba un `warning` | ahora es `error` explicando la consecuencia |
| Media | El README describía otro sistema (un solo ViT, 0,3 s por imagen, 500 MB, componentes inexistentes) y afirmaba una licencia MIT que no existe | reescrito con cifras medidas y procedencia |
| Baja | `ESTRUCTURA_PROYECTO.md` describía los cabezales anteriores | corregido |
| Baja | El monitor de salud de GitHub Actions lleva desde el 1 de noviembre desactivado por inactividad | **pendiente del dueño**: reactivarlo |
| Baja | «API» en el menú principal de la página | movido al pie de página |

## Lo que se comprobó y está bien

- **Secretos:** ninguno en los archivos versionados ni en todo el historial de
  git, incluido el token de Cloudflare expuesto en una sesión anterior. Los
  `.env` versionados solo contienen ejemplos y la URL pública de la API.
- **Carpetas privadas** (`privado/`, `ev 4/`, `evaluacion*/`, `data/`): fuera
  del repositorio.
- **CORS:** los cinco endpoints que usa la página aceptan el origen de GitHub
  Pages y las cabeceras de identidad.
- **Facturación en vivo:** catálogo, contratación simulada, licencia anual de
  365 días y rechazo de licencias manipuladas.
- **Repositorio:** ningún archivo versionado supera 2 MB; sin restos `.bak`,
  `.orig` ni logs.

## Riesgo aceptado

Quedan dos avisos de `npm audit` que solo se resuelven saltando a Next.js 16,
un cambio de versión mayor. Ninguno aplica a este despliegue:

- Los de Next.js (DoS del optimizador de imágenes, Server Components, *request
  smuggling* en *rewrites*, caché de `next/image`) afectan a un **servidor de
  Next en ejecución**. La página se publica como HTML estático en GitHub
  Pages: ese servidor no existe.
- El de PostCSS se ejecuta solo al **compilar**, sobre el CSS propio del
  proyecto; no procesa datos de terceros.

Si algún día el frontend pasa a servirse con `next start`, hay que actualizar.

## Acciones pendientes del dueño

1. **Desplegar la API en Render** (*Manual Deploy*): las correcciones de
   `/history`, del límite de subida y la actualización de FastAPI no llegan a
   producción hasta entonces.
2. **Reactivar el monitor de salud:** GitHub → Actions → «Monitoreo de salud —
   API + Redis» → *Enable workflow*.
3. **Rotar `DEEPGUARD_BILLING_KEY` en Render** si se usó la clave que se pegó
   en la conversación.
4. **Decidir la licencia** del repositorio y, antes de cobrar, resolver la de
   los datos de entrenamiento.
