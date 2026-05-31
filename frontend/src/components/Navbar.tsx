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
        const res = await fetch(`${BASE_URL}/api/v1/health`, {
          method:  'GET',
          signal:  AbortSignal.timeout(5000),
          cache:   'no-store',
        });
        if (!cancelled) setStatus(res.ok ? 'online' : 'offline');
      } catch {
        if (!cancelled) setStatus('offline');
      }
    };

    // Comprobación inicial
    check();

    // Re-verificar cada 30 segundos
    const interval = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const badge = {
    checking: {
      label: 'VERIFICANDO',
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
  }[status];

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

          {/* Badge de estado real de la API */}
          <span
            className="px-2 py-1 border text-2xs font-mono font-semibold transition-colors"
            style={badge.style}
            title={`API: ${BASE_URL}`}
          >
            {status === 'checking' ? (
              <span className="inline-flex items-center gap-1">
                <span className="animate-pulse">·</span> {badge.label}
              </span>
            ) : badge.label}
          </span>
        </nav>
      </div>
    </header>
  );
}
