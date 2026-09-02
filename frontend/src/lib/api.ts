import axios from 'axios';
import type { AnalysisResult, UploadResponse, TaskStatus } from '@/types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
  // Aceptar 202 como respuesta válida (Celery PENDING/PROCESSING)
  validateStatus: (s) => s >= 200 && s < 300,
});

// ─── Normalización de estados ─────────────────────────────────────────────────
// El backend v1 usa estados Celery en MAYÚSCULAS; el frontend espera minúsculas.
const _STATUS_MAP: Record<string, TaskStatus> = {
  PENDING:    'pending',
  STARTED:    'processing',
  PROCESSING: 'processing',
  RETRY:      'processing',
  SUCCESS:    'completed',
  FAILURE:    'failed',
  FAILED:     'failed',
  REVOKED:    'failed',
  // Por si el backend ya normalizó
  pending:    'pending',
  processing: 'processing',
  completed:  'completed',
  failed:     'failed',
};

function normalizeStatus(raw: string | undefined): TaskStatus {
  return _STATUS_MAP[raw ?? 'PENDING'] ?? 'pending';
}

function normalizeV1Response(raw: Record<string, unknown>): AnalysisResult {
  const status = normalizeStatus(raw.status as string);

  return {
    ...(raw as Partial<AnalysisResult>),
    status,
    task_id:    String(raw.task_id   ?? ''),
    filename:   String(raw.filename  ?? ''),
    file_type:  (raw.file_type as 'image' | 'video') ?? 'image',
    created_at: String(raw.created_at ?? raw.completed_at ?? new Date().toISOString()),
    progress:   typeof raw.progress === 'number'
      ? raw.progress
      : status === 'completed' ? 1.0 : 0.05,
  } as AnalysisResult;
}

// ─── Upload ───────────────────────────────────────────────────────────────────

export async function uploadFile(
  file: File,
  onUploadProgress?: (pct: number) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);

  const { data } = await client.post<Record<string, unknown>>(
    '/api/v1/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onUploadProgress && e.total) {
          onUploadProgress(Math.round((e.loaded / e.total) * 100));
        }
      },
    },
  );

  return {
    task_id: String(data.task_id ?? ''),
    status:  'pending',
    message: String(data.message ?? 'Análisis en cola'),
  };
}

// ─── Consulta de tarea ────────────────────────────────────────────────────────

export async function getTask(taskId: string): Promise<AnalysisResult> {
  const { data } = await client.get<Record<string, unknown>>(
    `/api/v1/tasks/${taskId}`,
  );
  return normalizeV1Response(data);
}

// ─── Polling ──────────────────────────────────────────────────────────────────

export function pollTask(
  taskId: string,
  onUpdate: (result: AnalysisResult) => void,
  intervalMs = 1500,
): () => void {
  let active = true;

  const poll = async () => {
    while (active) {
      try {
        const result = await getTask(taskId);
        onUpdate(result);
        if (result.status === 'completed' || result.status === 'failed') {
          break;
        }
      } catch {
        // Errores transitorios de red se ignoran — el polling continúa
      }
      await new Promise<void>((r) => setTimeout(r, intervalMs));
    }
  };

  poll();
  return () => { active = false; };
}
