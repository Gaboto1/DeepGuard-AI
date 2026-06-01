'use client';

import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import axios from 'axios';

type ApiStatus = 'checking' | 'online' | 'offline';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Cliente Axios independiente para el health check.
// Axios maneja CORS correctamente; fetch con no-cors no permite leer el cuerpo.
const _healthClient = axios.create({
  baseURL: BASE_URL,
  timeout: 50_000,   // 50s: 6s ping worker + latencia red + margen
  validateStatus: (s) => s >= 200 && s < 600,  // no lanzar en 4xx/5xx
});

export default function Navbar() {
  const [status,  setStatus]  = useState<ApiStatus>('checking');
  const [tooltip, setTooltip] = useState('Verificando worker GPU...');

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const { data, status: httpStatus } = await _healthClient.get<Record<string, unknown>>(
          '/api/v1/health',
        );

        if (cancelled) return;

        if (httpStatus >= 200 && httpStatus < 300) {
          // workers_online: true → al menos un worker GPU respondió al ping
          const workerOnline  = data.workers_online === true;
          const workersInfo   = String(data.workers_status ?? 'desconocido');

          setStatus(workerOnline ? 'online' : 'offline');
          setTooltip(
            workerOnline
              ? workersInfo
              : `Worker GPU no disponible — ${workersInfo}`,
          );
        } else {
          setStatus('offline');
          setTooltip(`API respondió con HTTP ${httpStatus}`);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setStatus('offline');
        setTooltip(`Sin conexión: ${msg.slice(0, 60)}`);
      }
    };

    const first    = setTimeout(check, 1200);
    const interval = setInterval(check, 30_000);  // cada 30s

    return () => {
      cancelled = true;
      clearTimeout(first);
      clearInterval(interval);
    };
  }, []);

  const badge: Record<ApiStatus, { label: string; dot?: boolean; style: React.CSSProperties }> = {
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
            DeepGuard<span className="text-fg-secondary font-normal"> AI</span>
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
          <a href={`${BASE_URL}/docs`} target="_blank" rel="noopener noreferrer"
             className="px-3 py-1.5 rounded hover:text-fg-primary hover:bg-bg-elevated transition-colors">
            API
          </a>
          <div className="w-px h-4 bg-border-subtle mx-1" />

          {/* Badge — verde solo cuando hay ≥1 worker GPU respondiendo al ping */}
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
    </header>
  );
}
