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
          <div className="flex items-center gap-2 mb-2">
            <span
              className="text-2xs mono uppercase tracking-widest px-2 py-0.5 border"
              style={{ color: '#1E63D4', borderColor: '#1E3D6A', background: 'rgba(30,99,212,0.06)' }}
            >
              Análisis Forense Digital
            </span>
            <span className="text-2xs mono" style={{ color: '#1a2436' }}>v6.0</span>
          </div>
          <h1 className="text-xl font-semibold" style={{ color: 'var(--fg-primary)' }}>
            Autenticidad de Imagen y Video
          </h1>
          <p className="text-sm mt-2 leading-relaxed" style={{ color: 'var(--fg-secondary)' }}>
            Detección de manipulación digital mediante ensemble probabilístico de 7 modelos de IA.
            Resultados no deterministas — sujetos a interpretación pericial.
          </p>
          {/* System tags — agrupados por categoría */}
          <div className="flex flex-wrap gap-1.5 mt-3">
            {[
              { label: 'ViT · SDXL · SigLIP', dim: true },
              { label: 'EfficientNet FF++',    dim: true },
              { label: 'CUDA GPU',             dim: false },
              { label: 'Grad-CAM++',           dim: true },
              { label: 'LLaVA-1.5-7b',        dim: true },
              { label: 'C2PA',                 dim: false },
            ].map(({ label, dim }) => (
              <span
                key={label}
                className="text-2xs mono px-2 py-0.5 border uppercase tracking-wider"
                style={{
                  color:       dim ? '#253348' : '#1E63D4',
                  borderColor: dim ? '#1a2030' : '#1E3D6A',
                  background:  dim ? '#03050a' : 'rgba(30,99,212,0.04)',
                }}
              >
                {label}
              </span>
            ))}
          </div>
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
              {/* Capabilities — formato cards + métricas del sistema */}
              <div className="mt-6 space-y-2">

                {/* Cards de formato */}
                <div className="grid grid-cols-2 gap-2">
                  {[
                    {
                      badge: 'IMG',
                      badgeColor: '#1E63D4',
                      badgeBorder: '#1E3D6A',
                      badgeBg: 'rgba(30,99,212,0.07)',
                      title: 'Imágenes',
                      desc: 'JPG, PNG, WEBP. Grad-CAM++, EXIF/XMP forense y ensemble de 7 modelos.',
                    },
                    {
                      badge: 'VID',
                      badgeColor: '#9a7c12',
                      badgeBorder: '#4a3c09',
                      badgeBg: 'rgba(154,124,18,0.07)',
                      title: 'Videos',
                      desc: 'MP4, MOV, MKV, WEBM. Frame-by-frame con embeddings ViT y flujo óptico.',
                    },
                  ].map(c => (
                    <div
                      key={c.title}
                      className="p-4 border"
                      style={{ borderColor: '#1a2030', background: '#05080f' }}
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        <span
                          className="text-2xs px-1.5 py-0.5 border mono uppercase tracking-wider font-bold flex-shrink-0"
                          style={{ color: c.badgeColor, borderColor: c.badgeBorder, background: c.badgeBg }}
                        >
                          {c.badge}
                        </span>
                        <p className="text-xs font-semibold" style={{ color: 'var(--fg-primary)' }}>
                          {c.title}
                        </p>
                      </div>
                      <p className="text-2xs leading-relaxed" style={{ color: 'var(--fg-secondary)' }}>
                        {c.desc}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Métricas del sistema — strip de 4 columnas */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {[
                    { val: '7 modelos',   sub: 'ensemble XGBoost' },
                    { val: 'GPU CUDA',    sub: 'RTX 4070 SUPER 12GB' },
                    { val: 'C2PA',        sub: 'procedencia criptográfica' },
                    { val: 'HMAC-SHA256', sub: 'cadena de custodia' },
                  ].map(({ val, sub }) => (
                    <div
                      key={val}
                      className="border px-3 py-2 text-center"
                      style={{ borderColor: '#1a2030', background: '#03050a' }}
                    >
                      <p
                        className="text-2xs font-bold mono uppercase tracking-wider"
                        style={{ color: 'var(--fg-secondary)' }}
                      >
                        {val}
                      </p>
                      <p className="text-2xs mt-0.5 leading-tight" style={{ color: '#253348' }}>
                        {sub}
                      </p>
                    </div>
                  ))}
                </div>
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
      <footer className="mt-16 py-5 px-4" style={{ borderTop: '1px solid #1a2030' }}>
        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-2xs mono" style={{ color: '#253348' }}>
          <div className="flex items-center gap-3">
            <span style={{ color: '#1a2436' }}>DeepGuard AI</span>
            <span style={{ color: '#1a2030' }}>·</span>
            <span style={{ color: '#1a2436' }}>Análisis Forense Digital v6.0</span>
          </div>
          <div className="flex gap-4">
            <a
              href="https://deepguard-ai-api.onrender.com/docs"
              target="_blank" rel="noopener noreferrer"
              className="transition-colors hover:text-fg-muted"
            >
              API Docs
            </a>
            <a
              href="https://deepguard-ai-api.onrender.com/api/v1/health"
              target="_blank" rel="noopener noreferrer"
              className="transition-colors hover:text-fg-muted"
            >
              Estado API
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
