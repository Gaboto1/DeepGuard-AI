'use client';

import { useCallback, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Navbar from '@/components/Navbar';
import UploadZone from '@/components/UploadZone';
import AnalysisProgress from '@/components/AnalysisProgress';
import ResultCard from '@/components/ResultCard';
import HistorySection, { saveToHistory } from '@/components/HistorySection';
import type { AnalysisResult } from '@/types';
import { ComoFunciona, ComoLeerElResultado, Confianza, LlamadaPlanes } from '@/components/Portada';
import { Clock, Gift, ShieldCheck } from 'lucide-react';

// (API_URL ya no se muestra al usuario; ver el mensaje de error.)

type Stage = 'idle' | 'analyzing' | 'done' | 'error';

interface FilePreview {
  url:      string;
  type:     'image' | 'video';
  filename: string;
}

export default function Page() {
  const [stage,       setStage]       = useState<Stage>('idle');
  const [taskId,      setTaskId]      = useState<string | null>(null);
  const [result,      setResult]      = useState<AnalysisResult | null>(null);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);

  const handlePreviewReady = useCallback((url: string, type: 'image' | 'video', filename: string) => {
    setFilePreview(prev => {
      if (prev) URL.revokeObjectURL(prev.url);
      return { url, type, filename };
    });
  }, []);

  const handleAnalysisStart = useCallback((id: string) => {
    setTaskId(id);
    setStage('analyzing');
    setResult(null);
  }, []);

  const handleAnalysisUpdate = useCallback((res: AnalysisResult) => {
    setResult(res);
    if (res.status === 'completed') {
      setStage('done');
      saveToHistory(res);
    } else if (res.status === 'failed') {
      setStage('error');
    }
  }, []);

  const handleReset = useCallback(() => {
    setStage('idle');
    setResult(null);
    setTaskId(null);
    setFilePreview(null);
  }, []);

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg-primary)' }}>
      <Navbar />

      <main className="max-w-3xl mx-auto px-4 py-8">
        {/* Cabecera: que es y por que fiarse, en el idioma de quien lo usa.
            Antes mostraba etiquetas tecnicas (ViT, SDXL, Grad-CAM++, CUDA) que
            no le dicen nada a un periodista y una version (v6.0) que nadie
            necesita saber. */}
        <div className="mb-8">
          <span
            className="text-2xs mono uppercase tracking-widest px-2 py-0.5 border"
            style={{ color: '#1E63D4', borderColor: '#1E3D6A', background: 'rgba(30,99,212,0.06)' }}
          >
            Verificación de imágenes y video
          </span>
          <h1 className="text-2xl sm:text-3xl font-bold mt-3" style={{ color: 'var(--fg-primary)', fontFamily: 'system-ui, sans-serif' }}>
            ¿Esta imagen o video es real?
          </h1>
          <p className="text-sm mt-2 leading-relaxed" style={{ color: 'var(--fg-secondary)', fontFamily: 'system-ui, sans-serif' }}>
            Descubre en segundos si fue generado o manipulado por inteligencia
            artificial, con la evidencia que lo sostiene.
          </p>
          <ul className="flex flex-wrap gap-x-5 gap-y-1.5 mt-4 text-xs" style={{ color: 'var(--fg-secondary)', fontFamily: 'system-ui, sans-serif' }}>
            <li className="inline-flex items-center gap-1.5"><Clock size={13} style={{ color: '#1E63D4' }} /> Resultado en unos 30 segundos</li>
            <li className="inline-flex items-center gap-1.5"><Gift size={13} style={{ color: '#1E63D4' }} /> 5 análisis gratis al día, sin registro</li>
            <li className="inline-flex items-center gap-1.5"><ShieldCheck size={13} style={{ color: '#1E63D4' }} /> Informe con sello verificable</li>
          </ul>
        </div>

        {/* Divider con línea activa */}
        <div className="mb-8" style={{ borderTop: '1px solid #1a2030' }} />

        {/* Main content */}
        <AnimatePresence mode="wait">
          {stage === 'idle' && (
            <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <UploadZone
                onAnalysisStart={handleAnalysisStart}
                onAnalysisUpdate={handleAnalysisUpdate}
                onPreviewReady={handlePreviewReady}
              />
              {/* Lo que explica el producto a quien llega por primera vez.
                  Sustituye a una rejilla tecnica que ademas estaba
                  desactualizada: anunciaba "7 modelos", "meta-ensemble
                  XGBoost" y "EfficientNet FF++", y hoy son seis detectores,
                  cabezales LightGBM y un probe CLIP. */}
              <ComoFunciona />
              <ComoLeerElResultado />
              <Confianza />
              <LlamadaPlanes />
            </motion.div>
          )}

          {stage === 'analyzing' && (
            <motion.div key="analyzing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <AnalysisProgress
                progress={result?.progress ?? 0.02}
                currentStage={result?.etapa}
                fileType={(result?.file_type ?? filePreview?.type ?? 'image') as 'image' | 'video'}
                previewUrl={filePreview?.url}
                previewType={filePreview?.type}
              />
            </motion.div>
          )}

          {stage === 'done' && result && (
            <motion.div key="done" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <ResultCard
                result={result}
                onReset={handleReset}
                previewUrl={filePreview?.url}
                previewType={filePreview?.type}
              />
            </motion.div>
          )}

          {stage === 'error' && (
            <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="panel p-6 text-center">
                <p className="text-xs font-semibold text-risk-critical mb-2">No pudimos completar el análisis</p>
                <p className="text-xs text-fg-secondary mb-4">{result?.error ?? 'Ocurrió un error inesperado.'}</p>
                {/* Antes: "Verifique que el backend esté activo en <URL>", una
                    instrucción para el equipo, no para quien usa la página. */}
                <p className="text-2xs text-fg-muted mb-5">
                  Vuelve a intentarlo en unos minutos. Si el problema continúa, prueba con otro archivo.
                </p>
                <button onClick={handleReset}
                  className="px-4 py-2 rounded border border-border-strong text-xs text-fg-secondary hover:text-fg-primary transition-colors">
                  Intentar de nuevo
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* History */}
        <HistorySection currentId={taskId ?? undefined} />
      </main>

      {/* Footer */}
      <footer className="mt-16 py-6 px-4" style={{ borderTop: '1px solid #1a2030' }}>
        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-2xs" style={{ color: 'var(--fg-muted)', fontFamily: 'system-ui, sans-serif' }}>
          <div>
            <p style={{ color: 'var(--fg-secondary)' }}>DeepScan · Verificación de imágenes y video</p>
            <p className="mt-0.5">Análisis probabilístico: orienta una verificación, no reemplaza un peritaje.</p>
          </div>
          <div className="flex gap-4">
            <a href="https://deepguard-ai-api.onrender.com/docs" target="_blank" rel="noopener noreferrer"
               className="transition-colors hover:text-fg-primary">Documentación de la API</a>
            <a href="https://deepguard-ai-api.onrender.com/api/v1/health" target="_blank" rel="noopener noreferrer"
               className="transition-colors hover:text-fg-primary">Estado del servicio</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
