'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import axios from 'axios';

// ─── Tipos ────────────────────────────────────────────────────────────────────
export type WorkerStatus = 'checking' | 'online' | 'offline';

interface WorkerStatusCtx {
  status:  WorkerStatus;
  tooltip: string;
}

// ─── Context ──────────────────────────────────────────────────────────────────
const WorkerStatusContext = createContext<WorkerStatusCtx>({
  status:  'checking',
  tooltip: 'Verificando worker GPU...',
});

export function useWorkerStatus(): WorkerStatusCtx {
  return useContext(WorkerStatusContext);
}

// ─── Cliente Axios para el health check ──────────────────────────────────────
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const _healthClient = axios.create({
  baseURL:        BASE_URL,
  timeout:        50_000,       // 50s: 6s ping worker + latencia + margen
  validateStatus: (s) => s >= 200 && s < 600,
});

// ─── Provider ─────────────────────────────────────────────────────────────────
export function WorkerStatusProvider({ children }: { children: React.ReactNode }) {
  const [status,  setStatus]  = useState<WorkerStatus>('checking');
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
          const mode = String(data.mode ?? '');

          if (mode === 'full-gpu') {
            // Modo local: el propio backend procesa con su GPU (sync_fallback),
            // no depende de un worker remoto vía heartbeat en Redis.
            const cudaOk = data.cuda === true;
            setStatus(cudaOk ? 'online' : 'offline');
            setTooltip(
              cudaOk
                ? `GPU local disponible — ${String(data.gpu ?? '')}`
                : 'Modo local sin GPU — procesando en CPU',
            );
          } else {
            const workerOnline = data.workers_online === true;
            const info         = String(data.workers_status ?? 'desconocido');
            setStatus(workerOnline ? 'online' : 'offline');
            setTooltip(workerOnline ? info : `Worker GPU no disponible — ${info}`);
          }
        } else {
          setStatus('offline');
          setTooltip(`API respondió con HTTP ${httpStatus}`);
        }
      } catch {
        if (!cancelled) {
          setStatus('offline');
          setTooltip('Sin conexión con el servidor');
        }
      }
    };

    const first    = setTimeout(check, 1200);
    const interval = setInterval(check, 30_000);

    return () => {
      cancelled = true;
      clearTimeout(first);
      clearInterval(interval);
    };
  }, []);

  return (
    <WorkerStatusContext.Provider value={{ status, tooltip }}>
      {children}
    </WorkerStatusContext.Provider>
  );
}
