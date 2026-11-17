'use client';

import { ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cabecerasIdentidad, EVENTO_ABRIR_PLANES, EVENTO_CONSUMO } from '@/lib/identidad';
import { PlanesModal } from '@/components/Planes';
import { useWorkerStatus } from '@/components/WorkerStatusProvider';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function Navbar() {
  const { status, tooltip } = useWorkerStatus();
  const [planesAbierto, setPlanesAbierto] = useState(false);
  const [consumo, setConsumo] = useState<{ plan: string; nombre: string; suscriptor: boolean;
                                           restantes: number | null; limite: number | null;
                                           periodo: 'día' | 'mes' } | null>(null);

  // Cualquier parte de la pagina puede abrir los planes (por ejemplo, al
  // agotarse la cuota) sin cablear estado entre componentes.
  useEffect(() => {
    const abrir = () => setPlanesAbierto(true);
    window.addEventListener(EVENTO_ABRIR_PLANES, abrir);
    return () => window.removeEventListener(EVENTO_ABRIR_PLANES, abrir);
  }, []);

  // Contador de analisis restantes. Solo se muestra si la cuota se aplica de
  // verdad y el contador responde: un numero inventado seria peor que ninguno.
  useEffect(() => {
    const cargar = () => {
      fetch(`${BASE_URL}/api/v1/billing/me`, { headers: cabecerasIdentidad() })
        .then(r => (r.ok ? r.json() : Promise.reject()))
        .then(j => {
          if (!j?.cuota_aplicada || !j?.consumo?.contador_disponible) { setConsumo(null); return; }
          const porDia = j.consumo.limite_dia != null;
          setConsumo({
            plan: j.plan.id, nombre: j.plan.nombre, suscriptor: j.identidad.es_suscriptor,
            restantes: porDia ? j.consumo.restantes_dia : j.consumo.restantes_mes,
            limite: porDia ? j.consumo.limite_dia : j.consumo.limite_mes,
            periodo: porDia ? 'día' : 'mes',
          });
        })
        .catch(() => setConsumo(null));
    };
    cargar();
    window.addEventListener(EVENTO_CONSUMO, cargar);
    return () => window.removeEventListener(EVENTO_CONSUMO, cargar);
  }, []);

  const badge: Record<typeof status, { label: string; dot?: boolean; style: React.CSSProperties }> = {
    checking: {
      label: 'VERIFICANDO',
      dot:   true,
      style: { color: '#3d4f62', borderColor: '#1e2d42', background: 'transparent' },
    },
    online: {
      label: 'EN LÍNEA',
      style: { color: '#1d7a45', borderColor: 'rgba(29,122,69,0.35)', background: 'rgba(29,122,69,0.07)' },
    },
    offline: {
      label: 'FUERA DE LÍNEA',
      style: { color: '#c42b2b', borderColor: 'rgba(196,43,43,0.35)', background: 'rgba(196,43,43,0.07)' },
    },
  };

  const b = badge[status];

  return (
    <header className="border-b border-border-subtle bg-bg-secondary sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4 h-11 flex items-center justify-between">

        {/* Logo */}
        <div className="flex items-center gap-2">
          <ShieldCheck size={16} className="text-accent-blue" strokeWidth={2} />
          <span className="text-sm font-semibold text-fg-primary tracking-tight">
            DeepScan
          </span>
          <span className="hidden sm:inline text-2xs text-fg-muted mono px-1.5 py-0.5 rounded border border-border-subtle ml-1">
            FORENSE
          </span>
        </div>

        {/* Nav */}
        <nav className="flex items-center gap-1 text-xs text-fg-secondary">
          <a href="#analizar"
             className="px-3 py-1.5 rounded hover:text-fg-primary hover:bg-bg-elevated transition-colors">
            Analizar
          </a>
          <a href="#historial"
             className="px-3 py-1.5 rounded hover:text-fg-primary hover:bg-bg-elevated transition-colors">
            Historial
          </a>
          {/* Los planes se abren en una ventana flotante sobre la pagina
              actual, no en otra pagina: no se pierde el analisis en curso. */}
          {consumo && (
            <button onClick={() => setPlanesAbierto(true)}
              title={`Plan ${consumo.nombre}: te quedan ${consumo.restantes} de ${consumo.limite} análisis este ${consumo.periodo}`}
              className="hidden sm:inline-flex items-center gap-1.5 px-2 py-1 border text-2xs font-mono"
              style={{
                borderColor: consumo.restantes === 0 ? 'rgba(196,43,43,0.4)' : '#1e2d42',
                color: consumo.restantes === 0 ? '#c42b2b' : consumo.suscriptor ? '#1E63D4' : 'var(--fg-muted)',
              }}>
              {consumo.suscriptor ? consumo.nombre.toUpperCase() : 'GRATIS'}
              <span style={{ color: '#3d4f62' }}>·</span>
              {consumo.restantes}/{consumo.limite}
            </button>
          )}
          <button onClick={() => setPlanesAbierto(true)}
             className="px-3 py-1.5 rounded hover:text-fg-primary hover:bg-bg-elevated transition-colors">
            Planes
          </button>
          <a href={`${BASE_URL}/docs`} target="_blank" rel="noopener noreferrer"
             className="px-3 py-1.5 rounded hover:text-fg-primary hover:bg-bg-elevated transition-colors">
            API
          </a>
          <div className="w-px h-4 bg-border-subtle mx-1" />

          <span
            className="px-2 py-1 border text-2xs font-mono font-semibold cursor-default select-none"
            style={b.style}
            title={tooltip}
          >
            {b.dot
              ? <span className="inline-flex items-center gap-1"><span className="animate-pulse">·</span> {b.label}</span>
              : b.label}
          </span>
        </nav>
      </div>
      <PlanesModal abierto={planesAbierto} alCerrar={() => setPlanesAbierto(false)} />
    </header>
  );
}
