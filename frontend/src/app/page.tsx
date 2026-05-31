'use client';

import { useCallback, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Navbar from '@/components/Navbar';
import UploadZone from '@/components/UploadZone';
import AnalysisProgress from '@/components/AnalysisProgress';
import ResultCard from '@/components/ResultCard';
import HistorySection, { saveToHistory } from '@/components/HistorySection';
import type { AnalysisResult } from '@/types';

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
        {/* Header */}
        <div className="mb-8">
          <p className="text-xs mono text-fg-muted mb-1">ANÁLISIS FORENSE DIGITAL</p>
          <h1 className="text-xl font-semibold text-fg-primary">
            Análisis de Autenticidad de Imagen y Video
          </h1>
          <p className="text-sm text-fg-secondary mt-2 leading-relaxed">
            Plataforma de análisis probabilístico para detección de manipulación digital mediante ensemble de modelos de inteligencia artificial.
            Los resultados son probabilísticos, no deterministas.
          </p>
          {/* System tags */}
          <div className="flex flex-wrap gap-2 mt-3">
            {[
              'ViT Face-Deepfake',
              'SDXL Detector',
              'EfficientNet FF++',
              'CUDA GPU',
              'Grad-CAM',
              'EXIF Analysis',
            ].map(tag => (
              <span key={tag} className="badge bg-bg-elevated border-border-subtle text-fg-muted text-2xs">
                {tag}
              </span>
            ))}
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-border-subtle mb-8" />

        {/* Main content */}
        <AnimatePresence mode="wait">
          {stage === 'idle' && (
            <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <UploadZone
                onAnalysisStart={handleAnalysisStart}
                onAnalysisUpdate={handleAnalysisUpdate}
                onPreviewReady={handlePreviewReady}
              />
              {/* Capabilities */}
              <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-3">
                {[
                  { title: 'Imágenes', desc: 'JPG, PNG, WEBP. Análisis completo con mapa de atención y metadatos EXIF.' },
                  { title: 'Videos',   desc: 'MP4, MOV, MKV. Extracción de fotogramas y análisis temporal.' },
                  { title: 'Forense',  desc: 'Ensemble de 3 modelos. Desglose por modelo, consenso y verificación externa.' },
                ].map(c => (
                  <div key={c.title} className="panel p-4">
                    <p className="text-xs font-semibold text-fg-primary mb-1">{c.title}</p>
                    <p className="text-2xs text-fg-secondary leading-relaxed">{c.desc}</p>
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {stage === 'analyzing' && (
            <motion.div key="analyzing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <AnalysisProgress
                progress={result?.progress ?? 0.02}
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
                <p className="text-xs font-semibold text-risk-critical mb-2">Error en el análisis</p>
                <p className="text-xs text-fg-secondary mb-4">{result?.error ?? 'Error desconocido'}</p>
                <p className="text-2xs text-fg-muted mb-5">
                  Verifique que el backend esté activo en {' '}
                  <span className="mono text-fg-secondary">http://localhost:8000</span>
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
      <footer className="border-t border-border-subtle mt-16 py-5 px-4">
        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-2xs text-fg-muted mono">
          <span>DeepGuard AI — Análisis Forense Digital</span>
          <div className="flex gap-4">
            <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer"
               className="hover:text-fg-secondary transition-colors">API Docs</a>
            <a href="http://localhost:8000/api/health" target="_blank" rel="noopener noreferrer"
               className="hover:text-fg-secondary transition-colors">Estado del sistema</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
