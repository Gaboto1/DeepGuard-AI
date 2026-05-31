'use client';

import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';

type ApiStatus = 'checking' | 'online' | 'offline';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function Navbar() {
  const [status, setStatus] = useState<ApiStatus>('checking');

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        // mode:'no-cors' evita el error CORS en Render/Netlify.
        // El browser envía la petición; si el servidor responde (con cualquier
        // código, incluso sin cabecera CORS), la promesa resuelve con una
        // respuesta opaca (res.type === 'opaque'). Solo lanza si el servidor
        // está COMPLETAMENTE caído (timeout, DNS, conexión rechazada).
        const res = await fetch(`${BASE_URL}/api/v1/health`, {
          method: 'GET',
          mode:   'no-cors',
          signal: AbortSignal.timeout(35_000),
          cache:  'no-store',
        });
        // opaque = CORS bloqueó lectura pero el servidor SÍ respondió
        // ok     = CORS OK, respuesta normal
        if (!cancelled) {
          setStatus(res.type === 'opaque' || res.ok ? 'online' : 'offline');
        }
      } catch {
        // Solo llega aquí si el servidor está caído de verdad
        if (!cancelled) setStatus('offline');
      }
    };

    // Primera verificación con retardo mínimo
    const firstCheck = setTimeout(check, 800);
    // Re-verificar cada 45s
    const interval = setInterval(check, 45_000);

    return () => {
      cancelled = true;
      clearTimeout(firstCheck);
      clearInterval(interval);
    };
  }, []);

  const badge: Record<ApiStatus, { label: string; dot: string; style: React.CSSProperties }> = {
    checking: {
      label: 'VERIFICANDO',
      dot:   'animate-pulse',
      style: { color: '#3d4f62', borderColor: '#1e2d42', background: 'transparent' },
    },
    online: {
      label: 'EN LÍNEA',
      dot:   '',
      style: { color: '#1d7a45', borderColor: 'rgba(29,122,69,0.35)', background: 'rgba(29,122,69,0.07)' },
    },
    offline: {
      label: 'FUERA DE LÍNEA',
      dot:   '',
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

          <span
            className="px-2 py-1 border text-2xs font-mono font-semibold"
            style={b.style}
            title={`API: ${BASE_URL}`}
          >
            {status === 'checking'
              ? <span className="inline-flex items-center gap-1"><span className={b.dot}>·</span> {b.label}</span>
              : b.label}
          </span>
        </nav>
      </div>
    </header>
  );
}
