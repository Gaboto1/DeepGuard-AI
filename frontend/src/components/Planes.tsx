'use client';

// Contenido de planes compartido por la ventana flotante del menu y por la
// pagina /precios, para que las dos no puedan desalinearse.

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { Check, Minus, ShieldCheck, Zap, FileLock2, AlertTriangle, X } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// La licencia vive en el navegador. Es un portador: quien la tenga, la usa.
// Por eso caduca a los 30 dias y por eso no se guarda nada mas junto a ella.
import { CLAVE_LICENCIA, cabecerasIdentidad, avisarConsumo } from '@/lib/identidad';

interface Plan {
  id: string;
  nombre: string;
  descripcion: string;
  analisis_por_dia: number | null;
  analisis_por_mes: number | null;
  prioridad: number;
  informe_pdf_sellado: boolean;
  acceso_api: boolean;
  analisis_por_lote: boolean;
  historial_dias: number;
  video: boolean;
  precio_clp: number;
  precio_anual_clp: number;
}

interface Catalogo {
  planes: Plan[];
  moneda: string;
  cuota_aplicada: boolean;
  pasarelas: { id: string; nombre: string }[];
  se_puede_contratar: boolean;
  nota: string;
}

// Copia local del catalogo, para que los planes se vean al instante y sin
// depender de la API ni del worker. La API en Render duerme en el plan
// gratuito y tarda hasta un minuto en despertar; mientras tanto la ventana
// quedaba vacia. La fuente de verdad sigue siendo backend/app/billing/plans.py:
// si la API responde, su catalogo reemplaza a este. Solo CONTRATAR necesita la
// API. Si se cambia un precio o una cuota, hay que cambiarlo en los dos sitios;
// lo comprueba backend/tests/test_catalogo_frontend.py.
const CATALOGO_LOCAL: Catalogo = {
  moneda: 'CLP',
  cuota_aplicada: false,
  pasarelas: [],
  se_puede_contratar: false,
  nota: '',
  planes: [
    { id: 'gratis', nombre: 'Gratuito',
      descripcion: 'Para comprobar una imagen suelta. Sin registro y sin tarjeta: el analisis completo con los seis detectores y el meta-ensemble.',
      analisis_por_dia: 5, analisis_por_mes: null, prioridad: 1,
      informe_pdf_sellado: false, acceso_api: false, analisis_por_lote: false,
      historial_dias: 1, video: false, precio_clp: 0, precio_anual_clp: 0 },
    { id: 'pro', nombre: 'Profesional',
      descripcion: 'Para quien verifica a diario. Cola prioritaria, informe PDF con el sello de cadena de custodia, historial de 90 dias y analisis de video.',
      analisis_por_dia: null, analisis_por_mes: 300, prioridad: 5,
      informe_pdf_sellado: true, acceso_api: false, analisis_por_lote: true,
      historial_dias: 90, video: true, precio_clp: 9990, precio_anual_clp: 99900 },
    { id: 'pericial', nombre: 'Pericial',
      descripcion: 'Para redacciones y peritajes. Todo lo del plan Profesional mas acceso por API, prioridad maxima y un ano de historial.',
      analisis_por_dia: null, analisis_por_mes: 1500, prioridad: 9,
      informe_pdf_sellado: true, acceso_api: true, analisis_por_lote: true,
      historial_dias: 365, video: true, precio_clp: 29990, precio_anual_clp: 299900 },
  ],
};

function clp(n: number) {
  return n === 0 ? 'Gratis' : `$${n.toLocaleString('es-CL')}`;
}

function cuota(p: Plan) {
  if (p.analisis_por_dia != null) return `${p.analisis_por_dia} análisis al día`;
  if (p.analisis_por_mes != null) return `${p.analisis_por_mes.toLocaleString('es-CL')} análisis al mes`;
  return 'Sin límite declarado';
}

function Rasgo({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-xs leading-relaxed"
        style={{ color: ok ? 'var(--fg-secondary)' : '#2b3a4d' }}>
      {ok ? <Check size={13} className="flex-shrink-0 mt-0.5" style={{ color: '#1d7a45' }} />
          : <Minus size={13} className="flex-shrink-0 mt-0.5" />}
      <span>{children}</span>
    </li>
  );
}

export function PlanesContenido({ alCerrar }: { alCerrar?: () => void }) {
  const [cat, setCat] = useState<Catalogo>(CATALOGO_LOCAL);
  const [anual, setAnual] = useState(false);
  // True cuando el catalogo viene de la API y no de la copia local.
  const [enLinea, setEnLinea] = useState(false);
  const [contratando, setContratando] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [licencia, setLicencia] = useState<string | null>(null);

  useEffect(() => {
    try { setLicencia(localStorage.getItem(CLAVE_LICENCIA)); } catch { /* modo privado */ }
  }, []);

  useEffect(() => {
    // Los planes ya se ven con la copia local. Esto solo trae el estado real
    // (si se puede contratar, que pasarelas hay) y, si falla, no muestra
    // ningun error: el catalogo sigue ahi.
    fetch(`${API_URL}/api/v1/billing/plans`)
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then((j: Catalogo) => {
        if (j && Array.isArray(j.planes) && j.planes.length) {
          setCat(j);
          setEnLinea(true);
        }
      })
      .catch(() => { /* sin API: se queda la copia local */ });
  }, []);

  const contratar = useCallback(async (plan: Plan) => {
    setContratando(plan.id);
    setAviso(null);
    try {
      const r = await fetch(`${API_URL}/api/v1/billing/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...cabecerasIdentidad() },
        body: JSON.stringify({ plan: plan.id, email: '', periodo: anual ? 'anual' : 'mensual' }),
      });
      const j = await r.json();
      if (!r.ok) {
        setAviso(j.mensaje || j.error || 'No se pudo iniciar la contratación.');
        return;
      }
      if (j.url_pago) { window.location.href = j.url_pago; return; }
      if (j.licencia) {
        try {
          localStorage.setItem(CLAVE_LICENCIA, j.licencia);
          setLicencia(j.licencia);
          avisarConsumo();
        } catch { /* modo privado: la licencia se pierde al cerrar */ }
        setAviso(j.mensaje || 'Licencia activada.');
      }
    } catch {
      setAviso('No se pudo contactar con la API.');
    } finally {
      setContratando(null);
    }
  }, [anual]);

  const quitarLicencia = useCallback(() => {
    try { localStorage.removeItem(CLAVE_LICENCIA); } catch { /* nada */ }
    setLicencia(null);
    avisarConsumo();
    setAviso('Licencia retirada de este navegador.');
  }, []);

  const soloSimulada = cat != null
    && cat.pasarelas.length > 0
    && cat.pasarelas.every(p => p.id === 'simulada');

  return (
    <>
        <div className="mb-8">
          <span className="text-2xs mono px-2 py-1 border"
                style={{ borderColor: '#1a2030', color: '#1E63D4' }}>
            PLANES
          </span>
          <h1 className="text-2xl font-bold mt-4 mb-2"
              style={{ color: 'var(--fg-primary)', fontFamily: 'system-ui,sans-serif' }}>
            Verificar una imagen es gratis. Sostener la verificación, no.
          </h1>
          <p className="text-sm max-w-2xl leading-relaxed"
             style={{ color: 'var(--fg-secondary)', fontFamily: 'system-ui,sans-serif' }}>
            El análisis es el mismo en todos los planes: los seis detectores, el
            meta-ensemble y el análisis semántico. Lo que cambia es cuántos puedes
            hacer, si esperas en la cola y si te llevas el informe sellado que
            permite sostener el resultado ante un tercero.
          </p>
        </div>

        {/* Por que se cobra. Si el modelo de negocio no se explica, parece arbitrario. */}
        <div className="border px-4 py-3 mb-8 flex gap-3"
             style={{ borderColor: '#1a2030', background: '#05080f' }}>
          <Zap size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#9a7c12' }} />
          <p className="text-xs leading-relaxed"
             style={{ color: 'var(--fg-muted)', fontFamily: 'system-ui,sans-serif' }}>
            <span style={{ color: 'var(--fg-secondary)' }}>Por qué hay un límite: </span>
            cada análisis ocupa una GPU durante unos 30 segundos, y DeepScan corre
            sobre una sola tarjeta que procesa dos a la vez. Las cuotas no son un
            truco comercial: son la capacidad real de la máquina. Por eso ningún
            plan promete análisis ilimitados.
          </p>
        </div>

        {soloSimulada && (
          <div className="border px-4 py-3 mb-6 flex gap-3"
               style={{ borderColor: 'rgba(154,124,18,0.35)', background: 'rgba(154,124,18,0.07)' }}>
            <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#9a7c12' }} />
            <p className="text-xs leading-relaxed"
               style={{ color: '#9a7c12', fontFamily: 'system-ui,sans-serif' }}>
              <strong>Modo demostración.</strong> No hay ninguna pasarela de pago
              conectada todavía, así que contratar aquí <strong>no cobra nada</strong> y
              activa una licencia de prueba de 30 días. Está así a propósito: una
              integración de cobro a medias en una página pública puede aceptar
              dinero que nadie sabe devolver.
            </p>
          </div>
        )}

        {licencia && (
          <div className="border px-4 py-3 mb-6 flex items-center justify-between gap-4"
               style={{ borderColor: 'rgba(29,122,69,0.35)', background: 'rgba(29,122,69,0.07)' }}>
            <div className="flex gap-3 min-w-0">
              <ShieldCheck size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#1d7a45' }} />
              <p className="text-xs" style={{ color: '#1d7a45', fontFamily: 'system-ui,sans-serif' }}>
                Tienes una licencia activa en este navegador. Se envía en cada
                análisis y caduca a los 30 días.
              </p>
            </div>
            <button onClick={quitarLicencia}
                    className="flex-shrink-0 text-2xs px-3 py-1.5 border transition-colors"
                    style={{ borderColor: '#1a2030', color: 'var(--fg-muted)' }}>
              Retirar
            </button>
          </div>
        )}

        {aviso && (
          <div className="border px-4 py-3 mb-6 text-xs"
               style={{ borderColor: '#253348', background: '#05080f', color: 'var(--fg-secondary)' }}>
            {aviso}
          </div>
        )}

        {/* Planes */}
        {/* Selector de periodo. El anual son diez meses: dos de regalo. */}
        <div className="flex items-center justify-center gap-1 mb-5">
          {([['mensual', false], ['anual', true]] as const).map(([etq, val]) => (
            <button key={etq} onClick={() => setAnual(val)}
              aria-pressed={anual === val}
              className="px-4 py-1.5 text-xs border transition-colors"
              style={{
                borderColor: anual === val ? 'rgba(30,99,212,0.55)' : '#1a2030',
                background: anual === val ? 'rgba(30,99,212,0.10)' : 'transparent',
                color: anual === val ? '#1E63D4' : 'var(--fg-muted)',
                fontFamily: 'system-ui,sans-serif',
              }}>
              {etq === 'mensual' ? 'Mensual' : 'Anual'}
              {etq === 'anual' && (
                <span className="ml-1.5 text-2xs px-1 py-0.5" style={{ background: 'rgba(29,122,69,0.15)', color: '#1d7a45' }}>
                  2 meses gratis
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {(cat?.planes ?? []).map(p => {
            const destacado = p.id === 'pro';
            return (
              <div key={p.id} className="border flex flex-col"
                   style={{
                     borderColor: destacado ? 'rgba(30,99,212,0.45)' : '#1a2030',
                     background: destacado ? 'rgba(30,99,212,0.04)' : '#05080f',
                   }}>
                <div className="px-5 pt-5 pb-4 border-b" style={{ borderColor: '#1a2030' }}>
                  <div className="flex items-baseline justify-between mb-1">
                    <h2 className="text-base font-bold"
                        style={{ color: 'var(--fg-primary)', fontFamily: 'system-ui,sans-serif' }}>
                      {p.nombre}
                    </h2>
                    {destacado && (
                      <span className="text-2xs mono px-1.5 py-0.5 border"
                            style={{ borderColor: 'rgba(30,99,212,0.45)', color: '#1E63D4' }}>
                        HABITUAL
                      </span>
                    )}
                  </div>
                  <p className="text-xl font-bold mb-1" style={{ color: destacado ? '#1E63D4' : 'var(--fg-primary)' }}>
                    {clp(anual && p.precio_clp > 0 ? Math.round(p.precio_anual_clp / 12) : p.precio_clp)}
                    {p.precio_clp > 0 && (
                      <span className="text-2xs font-normal ml-1" style={{ color: 'var(--fg-muted)' }}>
                        CLP / mes
                      </span>
                    )}
                  </p>
                  {p.precio_clp > 0 && (
                    <p className="text-2xs" style={{ color: 'var(--fg-muted)', fontFamily: 'system-ui,sans-serif' }}>
                      {anual
                        ? `${clp(p.precio_anual_clp)} al año · ahorras ${clp(p.precio_clp * 12 - p.precio_anual_clp)}`
                        : `o ${clp(p.precio_anual_clp)} al año, con 2 meses gratis`}
                    </p>
                  )}
                  <p className="text-xs leading-relaxed mt-2"
                     style={{ color: 'var(--fg-muted)', fontFamily: 'system-ui,sans-serif' }}>
                    {p.descripcion}
                  </p>
                </div>

                <ul className="px-5 py-4 flex flex-col gap-2 flex-1">
                  <Rasgo ok>{cuota(p)}</Rasgo>
                  <Rasgo ok={p.prioridad > 1}>
                    {p.prioridad > 1 ? `Cola prioritaria (nivel ${p.prioridad})` : 'Cola estándar'}
                  </Rasgo>
                  <Rasgo ok={p.informe_pdf_sellado}>Informe PDF con sello de cadena de custodia</Rasgo>
                  <Rasgo ok={p.video}>Análisis de video</Rasgo>
                  <Rasgo ok={p.analisis_por_lote}>Análisis por lote</Rasgo>
                  <Rasgo ok={p.acceso_api}>Acceso por API</Rasgo>
                  <Rasgo ok={p.historial_dias > 1}>
                    Historial de {p.historial_dias} {p.historial_dias === 1 ? 'día' : 'días'}
                  </Rasgo>
                </ul>

                <div className="px-5 pb-5">
                  {p.precio_clp === 0 ? (
                    alCerrar ? (
                      <button onClick={alCerrar}
                              className="block w-full text-center text-xs py-2.5 border transition-colors"
                              style={{ borderColor: '#253348', color: 'var(--fg-secondary)' }}>
                        Empezar a analizar
                      </button>
                    ) : (
                      <Link href="/"
                            className="block text-center text-xs py-2.5 border transition-colors"
                            style={{ borderColor: '#253348', color: 'var(--fg-secondary)' }}>
                        Empezar a analizar
                      </Link>
                    )
                  ) : (
                    <button
                      onClick={() => contratar(p)}
                      disabled={contratando !== null || !cat?.se_puede_contratar}
                      className="w-full text-xs py-2.5 border font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{
                        borderColor: destacado ? 'rgba(30,99,212,0.55)' : '#253348',
                        color: destacado ? '#1E63D4' : 'var(--fg-secondary)',
                        background: destacado ? 'rgba(30,99,212,0.08)' : 'transparent',
                      }}
                    >
                      {contratando === p.id
                        ? 'Procesando…'
                        : !enLinea
                        ? 'Conectando…'
                        : !cat?.se_puede_contratar
                        ? 'Aún no disponible'
                        : soloSimulada
                        ? 'Probar sin coste'
                        : 'Contratar'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Prueba en vez de promesas. No hay testimonios ni logos de clientes
            porque no los hay: inventarlos seria prueba social falsa. Lo que si
            hay son mediciones, y cada una dice de donde sale. */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-px mt-8 border" style={{ borderColor: '#1a2030', background: '#1a2030' }}>
          {[
            ['0,9 %', 'falsas alarmas', 'sobre 1.000 fotos que ningún modelo vio'],
            ['84,9 %', 'de imágenes IA señaladas', 'de generadores nunca vistos'],
            ['0,995', 'AUC fuera de muestra', 'FLUX, DALL·E 3, ImageNet, LFW'],
            ['+100', 'pruebas automáticas', 'en verde en cada cambio'],
          ].map(([cifra, que, donde]) => (
            <div key={que} className="px-4 py-3" style={{ background: '#05080f' }}>
              <p className="text-lg font-bold" style={{ color: 'var(--fg-primary)' }}>{cifra}</p>
              <p className="text-2xs" style={{ color: 'var(--fg-secondary)', fontFamily: 'system-ui,sans-serif' }}>{que}</p>
              <p className="text-2xs mt-0.5" style={{ color: '#3d4f62', fontFamily: 'system-ui,sans-serif' }}>{donde}</p>
            </div>
          ))}
        </div>

        {/* Que es exactamente el informe sellado: es el producto, conviene explicarlo */}
        <div className="border mt-8 px-5 py-4" style={{ borderColor: '#1a2030', background: '#05080f' }}>
          <div className="flex gap-3">
            <FileLock2 size={15} className="flex-shrink-0 mt-0.5" style={{ color: '#1E63D4' }} />
            <div>
              <h3 className="text-sm font-semibold mb-1"
                  style={{ color: 'var(--fg-primary)', fontFamily: 'system-ui,sans-serif' }}>
                Qué es el informe sellado
              </h3>
              <p className="text-xs leading-relaxed"
                 style={{ color: 'var(--fg-muted)', fontFamily: 'system-ui,sans-serif' }}>
                Un PDF que recoge el resultado, las salidas de los seis detectores y
                un sello HMAC-SHA256 calculado sobre el hash del archivo original, el
                score y la marca de tiempo. Permite a un tercero comprobar que el
                informe corresponde exactamente a ese archivo y que no se ha
                modificado después. Es lo que distingue «lo comprobé» de «puedo
                demostrar que lo comprobé», y es la razón por la que una redacción o
                un perito pagarían por esto.
              </p>
            </div>
          </div>
        </div>

        {/* Preguntas frecuentes: las dudas que frenan una contratacion */}
        <div className="mt-8">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--fg-primary)', fontFamily: 'system-ui,sans-serif' }}>
            Preguntas frecuentes
          </h3>
          <div className="border" style={{ borderColor: '#1a2030' }}>
            {[
              ["¿El análisis gratuito es peor que el de pago?", "No. Los tres planes usan exactamente el mismo análisis: los seis detectores, el meta-ensemble y el análisis semántico. Lo que cambia es cuántos puedes hacer, la prioridad en la cola y el informe sellado."],
              ["¿Necesito crear una cuenta?", "No. El plan gratuito no pide registro. Al contratar recibes una licencia que queda guardada en este navegador; no guardamos contraseñas ni datos personales."],
              ["¿Se renueva solo?", "No. La licencia caduca al terminar el período contratado y no se vuelve a cobrar nada. Si quieres seguir, la renuevas tú."],
              ["¿Qué pasa si agoto la cuota?", "El análisis se detiene hasta que la cuota se renueva: cada día en el plan gratuito y cada mes en los de pago. Nunca se cobra por exceso."],
              ["¿Sirve como prueba ante un tribunal?", "No reemplaza un peritaje oficial. El informe sellado permite demostrar que el resultado corresponde a ese archivo exacto y que no se alteró, que es lo que suele exigirse a una verificación periodística."],
            ].map(([q, a]) => (
              <details key={q} className="group px-4 py-3 border-b last:border-b-0" style={{ borderColor: '#1a2030' }}>
                <summary className="text-xs cursor-pointer list-none flex items-center justify-between gap-3"
                         style={{ color: 'var(--fg-secondary)', fontFamily: 'system-ui,sans-serif' }}>
                  {q}
                  <span className="transition-transform group-open:rotate-45" style={{ color: 'var(--fg-muted)' }}>+</span>
                </summary>
                <p className="text-xs leading-relaxed mt-2" style={{ color: 'var(--fg-muted)', fontFamily: 'system-ui,sans-serif' }}>{a}</p>
              </details>
            ))}
          </div>
        </div>

        <p className="text-2xs mt-6 leading-relaxed"
           style={{ color: '#253348', fontFamily: 'system-ui,sans-serif' }}>
          Los precios están en pesos chilenos. DeepScan es un análisis probabilístico
          y no constituye evidencia forense definitiva ni equivale a un peritaje
          legal, en ningún plan.
        </p>
    </>
  );
}

/**
 * Ventana flotante con los planes, sobre la pagina actual.
 *
 * Se cierra con la X, con Escape o pulsando fuera. Mientras esta abierta se
 * bloquea el scroll del fondo, para que la rueda del raton desplace los
 * planes y no la pagina de atras.
 */
export function PlanesModal({ abierto, alCerrar }: { abierto: boolean; alCerrar: () => void }) {
  useEffect(() => {
    if (!abierto) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') alCerrar(); };
    document.addEventListener('keydown', onKey);
    const previo = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previo;
    };
  }, [abierto, alCerrar]);

  if (!abierto) return null;
  return (
    <div
      className="fixed inset-0 z-[100] flex items-start sm:items-center justify-center p-3 sm:p-6"
      style={{ background: 'rgba(2, 4, 9, 0.78)', backdropFilter: 'blur(3px)' }}
      onMouseDown={e => { if (e.target === e.currentTarget) alCerrar(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Planes de DeepScan"
    >
      <div
        className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto border"
        style={{ background: 'var(--bg-primary)', borderColor: '#253348',
                 boxShadow: '0 20px 60px rgba(0,0,0,0.55)' }}
      >
        <button
          onClick={alCerrar}
          aria-label="Cerrar planes"
          className="sticky top-0 float-right z-10 m-2 w-8 h-8 flex items-center justify-center border transition-colors"
          style={{ background: '#0a0f1a', borderColor: '#253348', color: 'var(--fg-secondary)' }}
          onMouseEnter={e => { e.currentTarget.style.color = 'var(--fg-primary)'; e.currentTarget.style.borderColor = '#3d4f62'; }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--fg-secondary)'; e.currentTarget.style.borderColor = '#253348'; }}
        >
          <X size={16} />
        </button>
        <div className="px-5 sm:px-8 py-6">
          <PlanesContenido alCerrar={alCerrar} />
        </div>
      </div>
    </div>
  );
}
