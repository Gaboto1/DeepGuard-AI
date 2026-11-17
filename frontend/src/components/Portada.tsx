'use client';

// Secciones de la portada que explican el producto a quien llega por primera
// vez: que hace, como leer el resultado y por que fiarse.
//
// Escrito para el usuario, no para el equipo: nada de nombres de modelos, de
// tarjetas graficas ni de bibliotecas. Esa informacion sigue en el informe
// tecnico y en el panel forense de cada resultado, que es donde sirve.

import { Upload, ScanSearch, FileCheck2, ArrowRight } from 'lucide-react';
import { abrirPlanes } from '@/lib/identidad';

const SANS = { fontFamily: 'system-ui, sans-serif' } as const;

// Una sola fuente para las cifras que aparecen en la portada y en los planes.
// Todas estan medidas fuera de muestra y declaran de donde salen: no hay
// testimonios ni logos de clientes porque no los hay, e inventarlos seria
// prueba social falsa. Procedencia: reports/MEJORA_ENSEMBLE_v4.md, seccion 13.
export const METRICAS: [string, string, string][] = [
  ['0,9 %', 'falsas alarmas', 'sobre 1.000 fotos que ningún modelo vio'],
  ['84,9 %', 'de imágenes IA señaladas', 'de generadores nunca vistos'],
  ['0,995', 'AUC fuera de muestra', 'FLUX, DALL·E 3, ImageNet, LFW'],
  ['+100', 'pruebas automáticas', 'en verde en cada cambio'],
];

export function Metricas({ className = '' }: { className?: string }) {
  return (
    <div className={`grid grid-cols-2 md:grid-cols-4 gap-px border ${className}`}
         style={{ borderColor: '#1a2030', background: '#1a2030' }}>
      {METRICAS.map(([cifra, que, donde]) => (
        <div key={que} className="px-4 py-3" style={{ background: '#05080f' }}>
          <p className="text-lg font-bold" style={{ color: 'var(--fg-primary)' }}>{cifra}</p>
          <p className="text-2xs" style={{ ...SANS, color: 'var(--fg-secondary)' }}>{que}</p>
          <p className="text-2xs mt-0.5" style={{ ...SANS, color: 'var(--fg-muted)' }}>{donde}</p>
        </div>
      ))}
    </div>
  );
}

function Titulo({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-base font-semibold mb-4" style={{ ...SANS, color: 'var(--fg-primary)' }}>
      {children}
    </h2>
  );
}

export function ComoFunciona() {
  const pasos = [
    { icono: Upload, titulo: 'Sube el archivo',
      texto: 'Una imagen o un video. Sin registro: tienes cinco análisis gratis cada día.' },
    { icono: ScanSearch, titulo: 'Lo examinamos de varias formas',
      texto: 'Seis detectores especializados, un modelo que aprende a combinarlos y una lectura semántica de la escena. Unos 30 segundos.' },
    { icono: FileCheck2, titulo: 'Recibes la fuerza de la evidencia',
      texto: 'No un «real» o «falso», sino cuánta evidencia de manipulación hay, qué la sostiene y un informe sellado que nadie puede alterar después.' },
  ];
  return (
    <section className="mt-12">
      <Titulo>Cómo funciona</Titulo>
      <ol className="grid gap-3 sm:grid-cols-3">
        {pasos.map(({ icono: Icono, titulo, texto }, i) => (
          <li key={titulo} className="border p-4" style={{ borderColor: '#1a2030', background: '#05080f' }}>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-6 h-6 flex items-center justify-center text-2xs font-bold border"
                    style={{ borderColor: '#1E3D6A', color: '#1E63D4' }}>{i + 1}</span>
              <Icono size={15} style={{ color: '#1E63D4' }} />
            </div>
            <p className="text-sm font-semibold mb-1" style={{ ...SANS, color: 'var(--fg-primary)' }}>{titulo}</p>
            <p className="text-xs leading-relaxed" style={{ ...SANS, color: 'var(--fg-secondary)' }}>{texto}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function ComoLeerElResultado() {
  // Las mismas bandas y fronteras que backend/app/utils/helpers.py.
  const bandas = [
    ['Muy baja', '0–20 %', '#1d7a45', 'Nada indica manipulación.'],
    ['Baja', '20–40 %', '#1d7a45', 'Indicios débiles; lo normal en fotografía auténtica comprimida.'],
    ['Inconclusa', '40–60 %', '#9a7c12', 'El sistema no tiene base para pronunciarse. Contrasta con otras fuentes.'],
    ['Moderada', '60–80 %', '#b86a1a', 'Hay evidencia de generación o manipulación.'],
    ['Fuerte', '80–100 %', '#c42b2b', 'Evidencia clara de generación o manipulación por IA.'],
  ];
  return (
    <section className="mt-12">
      <Titulo>Cómo leer el resultado</Titulo>
      <div className="border" style={{ borderColor: '#1a2030' }}>
        {bandas.map(([nombre, rango, color, texto]) => (
          <div key={nombre} className="flex items-start gap-3 px-4 py-2.5 border-b last:border-b-0"
               style={{ borderColor: '#1a2030', background: '#05080f' }}>
            <span className="mt-1.5 w-2 h-2 flex-shrink-0" style={{ background: color }} />
            <div className="flex-1 min-w-0 sm:flex sm:items-baseline sm:gap-3">
              <p className="text-xs font-semibold sm:w-44 flex-shrink-0" style={{ ...SANS, color: 'var(--fg-primary)' }}>
                Evidencia {nombre.toLowerCase()} <span className="font-normal" style={{ color: 'var(--fg-muted)' }}>· {rango}</span>
              </p>
              <p className="text-xs leading-relaxed" style={{ ...SANS, color: 'var(--fg-secondary)' }}>{texto}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-2xs mt-2 leading-relaxed" style={{ ...SANS, color: 'var(--fg-muted)' }}>
        Es un análisis probabilístico: orienta una verificación, no reemplaza un peritaje.
      </p>
    </section>
  );
}

export function Confianza() {
  return (
    <section className="mt-12">
      <Titulo>Medido, no prometido</Titulo>
      <Metricas />
      <p className="text-2xs mt-2 leading-relaxed" style={{ ...SANS, color: 'var(--fg-muted)' }}>
        Todas las cifras se midieron sobre imágenes y generadores que el sistema no vio al entrenarse.
      </p>
    </section>
  );
}

export function LlamadaPlanes() {
  return (
    <section className="mt-12 border p-5 flex flex-col sm:flex-row sm:items-center gap-4"
             style={{ borderColor: 'rgba(30,99,212,0.4)', background: 'rgba(30,99,212,0.05)' }}>
      <div className="flex-1">
        <p className="text-sm font-semibold" style={{ ...SANS, color: 'var(--fg-primary)' }}>
          ¿Verificas imágenes a diario?
        </p>
        <p className="text-xs mt-1 leading-relaxed" style={{ ...SANS, color: 'var(--fg-secondary)' }}>
          Los planes de pago dan más análisis, cola prioritaria e informes sellados para sostener la verificación ante un tercero.
        </p>
      </div>
      <button onClick={abrirPlanes}
        className="flex-shrink-0 inline-flex items-center justify-center gap-2 px-4 py-2.5 border text-xs font-semibold"
        style={{ ...SANS, borderColor: 'rgba(30,99,212,0.6)', color: '#1E63D4', background: 'rgba(30,99,212,0.1)' }}>
        Ver planes <ArrowRight size={13} />
      </button>
    </section>
  );
}
