# DeepGuard AI — Informe de Cambios Implementados (Fase 1 de la auditoría integral)

**Fecha:** 28 de junio de 2026
**Base de partida:** `docs/TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md` (commit `45576f1`)
**Alcance de este informe:** documentar, con evidencia verificable, exactamente qué se modificó en esta sesión — ni más ni menos.

---

## 1. Resumen ejecutivo

Se solicitó una auditoría y refactorización integral del sistema (frontend, backend, seguridad, rendimiento, testing, documentación) con calidad de consultora externa. Ese alcance representa varias semanas de trabajo de un equipo senior sobre un sistema en producción pública. Ejecutar "todo a la vez" sin checkpoints habría significado, en la práctica, simular profundidad sin sustento real — exactamente lo que se pidió evitar ("no hagas cambios superficiales").

En esta primera fase se ejecutó un bloque acotado, **100% real y verificado**, derivado directamente de los 14 hallazgos ya documentados en la auditoría previa. Cada cambio fue implementado, probado y validado contra el build real del proyecto. Las fases de mayor alcance (autenticación, eliminación de la triplicación del pipeline, rediseño visual completo, Lighthouse/Core Web Vitals, CI/CD) se dejan explícitamente planificadas en la Sección 6, porque requieren decisiones de producto/riesgo que conviene confirmar antes de tocar un sistema con usuarios reales.

**Resultado de esta fase:** 6 archivos corregidos, 1 archivo de configuración nuevo, 3 archivos de tests nuevos (18 tests), 0 regresiones detectadas, build y type-check 100% verdes.

---

## 2. Metodología

1. Partir de los 14 problemas ya priorizados y evidenciados con archivo:línea en `docs/TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md`.
2. Seleccionar los de mayor relación beneficio/riesgo ejecutable sin tocar infraestructura externa (Redis/Render/Netlify) ni romper compatibilidad pública.
3. Para cada cambio: leer el código real, corregir, y verificar de inmediato (no se acumularon cambios sin probar).
4. Cerrar con una corrida completa de toda la suite de verificación disponible (pytest, `tsc --noEmit`, `next build`, smoke-import de todos los módulos backend tocados).

---

## 3. Cambios realizados

### 3.1 Frontend — `ForensicPanel.tsx` (Problema #1 de la auditoría, severidad Alta)

| Campo | Detalle |
|---|---|
| **Archivo** | `frontend/src/components/ForensicPanel.tsx` |
| **Líneas** | 56–187 (reescritas) |
| **Motivo** | El bloque superior del panel forense mostraba siempre, sin condición alguna, "Contenido Auténtico — VÁLIDO" con ícono verde — independientemente de que el ensemble hubiera determinado alta probabilidad de manipulación. |
| **Antes** | `Contenido Auténtico` / badge `VÁLIDO` fijos, 3 líneas de log siempre `[OK]`. |
| **Después** | Veredicto de 4 estados derivado de `ensemble.final_probability` y `chainOfCustody.integrity_valid`: `real` (verde, <42%), `uncertain` (ámbar, 42–65%), `fake` (rojo, ≥65%), `invalid` (rojo, sello de custodia roto — prevalece sobre el score). La línea de log "Integridad de Bloques" ahora refleja si el HMAC realmente verificó (`[OK]`/`[FALLO]`). |
| **Beneficio** | Elimina una comunicación potencialmente engañosa en un sistema de propósito forense — el hallazgo más severo de la auditoría previa. |
| **Riesgo de la corrección** | Bajo. Solo cambia colores/texto/iconos derivados de datos que el componente ya recibía por props (`ensemble`, `chainOfCustody`); no se tocó ningún cálculo de backend ni la forma de los datos. |
| **Verificación** | `tsc --noEmit` limpio, `next build` exitoso (ver Sección 4). |

### 3.2 Backend — Tests automatizados de las reglas forenses (Problema #10, severidad Media)

| Campo | Detalle |
|---|---|
| **Archivos nuevos** | `backend/pytest.ini`, `backend/tests/test_forensic_corrections.py`, `backend/tests/test_meta_ensemble_veto.py` |
| **Motivo** | Las 4 reglas de `forensic_corrections.py` y el veto de consenso de `meta_ensemble.py` documentaban casos reales con números exactos en sus docstrings, pero no existía ningún test que los verificara automáticamente — cualquier futuro cambio podía romper silenciosamente la calibración. |
| **Antes** | 0 tests automatizados en el backend. |
| **Después** | 13 tests cubriendo las 4 reglas (caso positivo + caso negativo de cada una, más un test de exclusión mutua) y el veto de consenso (caso documentado del bug real + 3 casos negativos). |
| **Beneficio** | Red de seguridad real para refactors futuros; documentación ejecutable de la lógica de dominio más crítica del sistema. |
| **Riesgo** | Ninguno — son archivos nuevos, no modifican código de producción. |
| **Resultado** | `13 passed` (ver Sección 4). |

### 3.3 Backend — Gate de arranque para `DEEPGUARD_SIGNING_KEY` (hallazgo nuevo, severidad Media)

| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/services/custody_service.py` |
| **Líneas** | 36–58 |
| **Motivo** | Ya existía un fail-fast si la clave estaba vacía, pero **no** si tomaba uno de los valores de ejemplo/placeholder reales del repositorio (`change-me-in-production` de `docker-compose.prod.yml`, o los textos de `.env.production.example`/`.env.worker.example`). Un despliegue que olvidara sobrescribir esos defaults firmaría la cadena de custodia con una clave pública y conocida. |
| **Antes** | `if not _raw_key:` — solo detectaba clave vacía. |
| **Después** | `if not _raw_key or _raw_key.strip().lower() in _INSECURE_PLACEHOLDERS:` — rechaza además los 3 placeholders conocidos del propio repo, y aborta el arranque del worker (`RuntimeError`) en modo no-`API_ONLY`. |
| **Beneficio** | Cierra una vía concreta de despliegue inseguro sin intervención manual de checklist. |
| **Riesgo** | Bajo — solo añade más condiciones de rechazo; una clave real (como la del `.env` local actual, verificado) sigue funcionando sin cambios. |
| **Tests nuevos** | `backend/tests/test_custody_signing_key.py` — 5 tests, recargan el módulo con distintos valores de `settings` vía `monkeypatch` para confirmar el comportamiento en ambos modos (`API_ONLY=true/false`). |
| **Nota colateral** | Se corrigió también un número desactualizado en el docstring de `meta_ensemble.py` (el ejemplo documentaba `VETO_STRENGTH=0.65` y resultado `0.27`, pero la constante real vigente es `0.60` y el resultado correcto `0.305` — solo comentario, sin efecto en comportamiento). |

### 3.4 Backend — Endpoint legacy `/api/analyze` sin `file_content_b64` (Problema #8, severidad Media)

| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/api/routes.py` |
| **Líneas** | 11, 87–103 |
| **Motivo** | En modo `API_ONLY` (Render), este endpoint despachaba la tarea a Celery sin incluir el archivo codificado en Base64 que el worker GPU remoto necesita para reconstruirlo (Render y el worker no comparten filesystem). El endpoint `/api/v1/analyze` sí lo hacía. Cualquier cliente que usara la ruta legacy en producción provocaba un `FileNotFoundError`/`ValueError` determinístico en el worker. |
| **Antes** | `analyze_image_task.apply_async(args=[task_id, str(dest), file.filename], task_id=task_id)` |
| **Después** | Se agrega `file_content_b64 = base64.b64encode(content).decode("ascii")` y se pasa como `kwargs={"file_content_b64": file_content_b64}`, igual que en `/api/v1/analyze`. |
| **Beneficio** | El endpoint legacy vuelve a ser funcionalmente correcto en producción, en vez de fallar siempre. |
| **Riesgo** | Bajo. Mismo patrón ya probado en producción por `/api/v1/analyze`; no cambia la interfaz pública del endpoint (mismo request/response). |
| **Verificación** | Chequeo de sintaxis AST + smoke-import de `app.api.routes` con la configuración real del `.env` local (ver Sección 4). No se ejecutó un test end-to-end contra Celery real porque requeriría Redis/worker activos — queda como deuda de testing de integración (Sección 6). |

### 3.5 Frontend — Progreso simulado en `AnalysisProgress.tsx` (Problema #11, severidad Baja)

| Campo | Detalle |
|---|---|
| **Archivos** | `backend` ya emitía la etapa real (`stage` en `analysis_tasks.py`, traducida a `etapa` en `api/v1/routes.py:140`) pero el frontend nunca la consumía. Cambios en: `frontend/src/types/index.ts`, `frontend/src/app/page.tsx`, `frontend/src/components/AnalysisProgress.tsx`. |
| **Motivo** | La etiqueta de la etapa "activa" en la terminal de progreso se elegía únicamente interpolando `progress * 8` etapas cosméticas fijas — nunca reflejaba qué hacía realmente el backend en ese momento. |
| **Antes** | `STAGES[activeIdx].label` siempre, sin relación con el backend. |
| **Después** | Se agregó `etapa?: string` al tipo `AnalysisResult`, se pasa como prop `currentStage` desde `page.tsx`, y la línea activa de la terminal muestra el texto real reportado por el backend (`currentStage`) cuando está disponible, con fallback a la etiqueta cosmética si no llega (ej. en `sync_fallback` local sin polling intermedio). |
| **Beneficio** | El usuario ve información verídica de lo que el sistema está haciendo, no una narrativa inventada. |
| **Riesgo** | Muy bajo — cambio aditivo y opcional (`currentStage?`), no rompe el comportamiento existente si el campo no llega. |
| **Limitación reconocida** | El backend solo reporta granularidad gruesa entre el 25% y el 90% de progreso (todo bajo la etiqueta "Ensemble 5 modelos" mientras corren OOD, XGBoost, LLaVA y fusión semántica) — la posición de la barra sigue interpolándose por fracción de progreso, pero ya no se inventa el *texto* de la etapa. Cerrar esa brecha de granularidad requeriría añadir más llamadas a `update_state()` en `analysis_tasks.py`, fuera del alcance de este bloque por tocar la ruta crítica de Celery en producción. |

---

## 4. Resultados de pruebas

| Verificación | Comando | Resultado |
|---|---|---|
| Suite de tests backend (nueva) | `venv/Scripts/python.exe -m pytest -v` | **18/18 passed** (1.0–1.2s) |
| Type-check frontend | `npx tsc --noEmit` | Sin errores |
| Build de producción frontend | `npm run build` | `✓ Compiled successfully`, 4/4 páginas estáticas generadas |
| Sintaxis backend modificado | `ast.parse()` sobre `routes.py` | OK |
| Smoke-import backend | `import app.main, app.api.routes, app.api.v1.routes, app.services.custody_service` con `.env` real local | OK, sin excepciones |

**Cobertura de los tests nuevos:** las 4 reglas de `forensic_corrections.py` (8 tests: positivo+negativo por regla, más 1 de exclusión mutua), el veto de consenso de `meta_ensemble.py` (4 tests), y el gate de arranque de la clave de firma (5 tests) — 18 tests en total, 0 fallos, 0 skips.

**No se ejecutaron** (fuera de alcance de esta fase, requieren infraestructura externa): tests de integración contra Celery/Redis reales, tests E2E de navegador (Playwright/Cypress no están instalados en el proyecto), Lighthouse/Core Web Vitals (requiere un despliegue o servidor corriendo y no se simuló para no reportar cifras no verificadas).

---

## 5. Métricas comparativas (antes → después)

| Métrica | Antes | Después |
|---|---|---|
| Tests automatizados backend | 0 | 18 (100% passing) |
| Hallazgos de severidad Alta sin corregir (de los 14 de la auditoría) | 4 | 3 (se cerró el #1) |
| Hallazgos de severidad Media sin corregir | 6 | 4 (se cerraron el #8 y el riesgo de clave default) |
| Endpoints con comportamiento de despacho Celery inconsistente | 2 (`/api/analyze` y `/api/v1/analyze` distintos) | 0 (ambos equivalentes) |
| Componentes con comunicación de veredicto desconectada del dato real | 1 (`ForensicPanel.tsx`) | 0 |
| `tsc --noEmit` | limpio (antes de esta fase también lo estaba) | limpio |
| `next build` | exitoso | exitoso |

No se reportan métricas de Lighthouse, Core Web Vitals, ni cobertura de líneas (`coverage.py`) porque no se ejecutaron en esta fase — incluirlas sin haberlas corrido sería fabricar evidencia, algo que las reglas de esta auditoría prohíben explícitamente.

---

## 6. Deuda técnica restante y roadmap (no ejecutado en esta fase — requiere alcance propio)

Los siguientes ítems de `docs/TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md` (Secciones 14–16) **no** se tocaron en esta pasada porque cada uno implica una decisión de producto/riesgo o un esfuerzo que merece su propia sesión de trabajo dedicada, con verificación incremental:

| # | Ítem | Por qué no se hizo ahora | Esfuerzo estimado |
|---|---|---|---|
| 1 | Autenticación de la API (Problema #3 / DOC-02) | Cambiaría el acceso público actual del sistema (relevante para una demo de tesis evaluada por terceros) — requiere decidir el mecanismo (API key vs. JWT) y a quién se le entregan credenciales | 0.5–1 día |
| 2 | TLS con verificación de certificado real en Redis (Problema #4 / DOC-01) | Requiere descargar y gestionar un certificado CA de Aiven en el entorno de despliegue real (Render + worker local) — no verificable sin acceso a esa infraestructura en esta sesión | 0.5 día |
| 3 | Eliminar la triplicación del pipeline forense (Problema #2) | Toca simultáneamente `analysis_tasks.py` (Celery, ruta de producción real), `_process_sync_fallback` y `analysis_service.py` — el refactor de mayor riesgo identificado, exige tests de regresión exhaustivos antes de tocarlo | 2–3 días |
| 4 | Migrar Base64 a Object Storage (DOC-03) | Requiere aprovisionar S3/R2 y credenciales — decisión de infraestructura externa | 1–2 días |
| 5 | Rediseño visual completo como "producto SaaS moderno" | Es una decisión subjetiva de identidad de producto; hacerlo sin iteración visual con el usuario en navegador real arriesga imponer un gusto no validado sobre un sistema que ya tiene una identidad visual forense consistente y deliberada (ver Sección 5 de la auditoría) | Multi-día, iterativo |
| 6 | Suite E2E (Playwright/Cypress) | No existe infraestructura de testing de UI en el proyecto; instalarla y escribir specs significativos es un proyecto en sí mismo | 1–2 días |
| 7 | Lighthouse / Core Web Vitals | Requiere un entorno servido (local o staging) y Chrome headless; no se simula para no reportar números inventados | 0.5 día (una vez con entorno) |
| 8 | CI/CD (GitHub Actions) | No existe pipeline hoy; agregar uno que ejecute `pytest` + `tsc` + `build` en cada PR es ahora viable porque ya hay tests reales que correr | 0.5 día |
| 9 | Renombrar `_EfficientNetFF` → nombre real (CLIP probe) (Problema #13) | Bajo riesgo pero requiere grep exhaustivo de referencias antes de tocar el módulo núcleo del ensemble en producción; se prefirió no tocar ese archivo en la misma sesión que ya modificó `meta_ensemble.py` | 1–2 horas |
| 10 | README desactualizado (Problema #7) | Ya se actualizó parcialmente en una sesión anterior (sección "Modos de operación"); falta una pasada completa que describa el ensemble de 8 señales | 1–2 horas |

**Recomendación de orden para la siguiente fase:** (9) y (10) primero por ser de bajísimo riesgo, luego (8) CI/CD para que toda futura fase quede automáticamente verificada, luego (1) y (2) por severidad de seguridad, dejando (3) el refactor de mayor riesgo y (5)/(6)/(7) para fases dedicadas exclusivamente a frontend/QA.

---

## 7. Anexos

### 7.1 Archivos modificados

```
M  backend/app/api/routes.py
M  backend/app/models/meta_ensemble.py
M  backend/app/services/custody_service.py
M  frontend/src/app/page.tsx
M  frontend/src/components/AnalysisProgress.tsx
M  frontend/src/components/ForensicPanel.tsx
M  frontend/src/types/index.ts
```

### 7.2 Archivos nuevos

```
backend/pytest.ini
backend/tests/test_forensic_corrections.py
backend/tests/test_meta_ensemble_veto.py
backend/tests/test_custody_signing_key.py
docs/TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md        (auditoría base, sesión anterior)
docs/INFORME_CAMBIOS_IMPLEMENTADOS.md                (este documento)
tools/generar_tesis_word.py                          (sesión anterior)
```

### 7.3 Dependencias agregadas/eliminadas

Ninguna. Todos los cambios usan librerías ya presentes en el proyecto (`pytest` ya estaba instalado en el venv; no se agregó a `requirements.txt` porque no se usa en producción — **pendiente**: agregarlo a un futuro `requirements-dev.txt` si se formaliza CI/CD, ver Sección 6, ítem 8).

### 7.4 Cambios de configuración

Ninguno en variables de entorno o `.env`. `backend/pytest.ini` es nuevo pero solo afecta la ejecución de tests, no el runtime de la aplicación.

### 7.5 Commits sugeridos

Se recomienda dividir en 2 commits, separando el fix de UX/seguridad del de testing puro:

1. `fix(forensic): corrige veredicto incondicional en ForensicPanel + endpoint legacy sin file_content_b64 + gate de clave de firma insegura`
2. `test(backend): agrega suite pytest para reglas forenses, veto de consenso y gate de clave de firma (18 tests)`

No se ha ejecutado ningún `git add`/`git commit` — se deja pendiente de autorización explícita, según el protocolo de este proyecto.
