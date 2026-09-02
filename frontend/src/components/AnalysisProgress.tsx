'use client';

import { useEffect, useRef, useState } from 'react';

// Pipeline stages mapped to actual backend steps
const STAGES = [
  { id: 'sha256',    label: 'Calculando huella SHA-256 del archivo original...' },
  { id: 'exif',      label: 'Extrayendo metadatos forenses EXIF/XMP/IPTC...' },
  { id: 'ood',       label: 'Evaluando señales detector Out-of-Distribution...' },
  { id: 'ensemble',  label: 'Inferencia ensemble 5 modelos (ViT · SDXL · CLIP · AiArt · SigLIP)...' },
  { id: 'xgboost',   label: 'Meta-ensemble XGBoost + calibración temperatura T=0.581...' },
  { id: 'llava',     label: 'Análisis semántico LLaVA-1.5-7b-hf (4-bit NF4)...' },
  { id: 'fusion',    label: 'Fusión semántica + correcciones forenses post-hoc...' },
  { id: 'custody',   label: 'Generando sello HMAC-SHA256 cadena de custodia v2...' },
];

const FILLED  = '█';
const EMPTY   = '░';
const BAR_LEN = 20;

interface Props {
  progress:     number;
  currentStage?: string;   // etapa real reportada por el worker (ej. "Ensemble 5 modelos")
  fileType:     'image' | 'video';
  previewUrl?:  string;
  previewType?: 'image' | 'video';
}

export default function AnalysisProgress({ progress, currentStage, fileType, previewUrl, previewType }: Props) {
  const startRef   = useRef(Date.now());
  const [tick, setTick] = useState(0);

  // Blinking cursor
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 530);
    return () => clearInterval(t);
  }, []);

  const pct      = Math.min(Math.round(progress * 100), 100);
  const activeIdx = Math.min(Math.floor(progress * STAGES.length), STAGES.length - 1);
  const showCursor = tick % 2 === 0;

  // Derive a realistic timestamp for each completed stage
  const stageTs = (idx: number): string => {
    const elapsed = Date.now() - startRef.current;
    const frac    = idx / STAGES.length;
    const ms      = Math.min(frac * elapsed * 1.1, elapsed);
    const d       = new Date(startRef.current + ms);
    const hh      = d.getHours().toString().padStart(2, '0');
    const mm      = d.getMinutes().toString().padStart(2, '0');
    const ss      = d.getSeconds().toString().padStart(2, '0');
    const ms3     = d.getMilliseconds().toString().padStart(3, '0');
    return `${hh}:${mm}:${ss}.${ms3}`;
  };

  // Block-character progress bar
  const filled  = Math.round((pct / 100) * BAR_LEN);
  const barStr  = FILLED.repeat(filled) + EMPTY.repeat(BAR_LEN - filled);

  return (
    <div className="w-full font-mono text-xs" style={{ color: 'var(--fg-primary)' }}>

      {/* Optional preview — dimmed, positioned above terminal */}
      {previewUrl && (
        <div className="relative border border-border-subtle mb-2 overflow-hidden" style={{ background: 'var(--bg-primary)' }}>
          {previewType === 'image' ? (
            <img src={previewUrl} alt="Analizando" className="w-full max-h-48 object-contain opacity-30" />
          ) : (
            <video src={previewUrl} muted autoPlay loop playsInline className="w-full max-h-48 opacity-30" />
          )}
          <div className="absolute inset-0 flex items-end p-2">
            <span className="text-2xs" style={{ color: '#1E63D4' }}>
              {fileType === 'video' ? '[ VIDEO ]' : '[ IMAGE ]'} &nbsp;{previewUrl.split('/').pop()?.slice(0, 40)}
            </span>
          </div>
        </div>
      )}

      {/* Terminal window */}
      <div
        className="border border-border-subtle overflow-hidden"
        style={{ background: '#05080f' }}
      >

        {/* Title bar */}
        <div
          className="flex items-center justify-between px-3 py-1.5 border-b border-border-subtle"
          style={{ background: '#080c15' }}
        >
          <span style={{ color: 'var(--fg-muted)' }} className="text-2xs uppercase tracking-widest">
            deepscan@forensic-node — pipeline de análisis
          </span>
          <span style={{ color: 'var(--fg-muted)' }} className="text-2xs">
            {fileType === 'video' ? 'VIDEO' : 'IMAGE'} · {pct}%
          </span>
        </div>

        {/* Command line */}
        <div className="px-3 pt-2 pb-1" style={{ color: '#3d4f62' }}>
          <span style={{ color: '#1d7a45' }}>deepscan</span>
          <span>@forensic</span>
          <span style={{ color: '#1E63D4' }}>:~$</span>
          <span style={{ color: 'var(--fg-secondary)' }}> analyze --pipeline=full --type={fileType}</span>
        </div>

        <div className="px-3 pb-1" style={{ borderBottom: '1px solid #1a2030', color: '#253348' }}>
          {'─'.repeat(62)}
        </div>

        {/* Stage log lines */}
        <div className="px-3 py-1.5 space-y-0.5">
          {STAGES.map((stage, i) => {
            const done    = i < activeIdx;
            const active  = i === activeIdx;
            const pending = i > activeIdx;

            if (done) {
              return (
                <div key={stage.id} className="flex items-baseline gap-2">
                  <span className="flex-shrink-0 text-2xs" style={{ color: '#1d7a45', minWidth: '7rem' }}>
                    [ OK&nbsp;&nbsp;&nbsp;&nbsp;]
                  </span>
                  <span className="flex-shrink-0 text-2xs" style={{ color: '#253348', minWidth: '7.5rem' }}>
                    {stageTs(i)}
                  </span>
                  <span className="text-2xs" style={{ color: 'var(--fg-secondary)' }}>
                    {stage.label}
                  </span>
                </div>
              );
            }

            if (active) {
              // Si el worker reporta una etapa real (vía polling), se muestra
              // en lugar de la etiqueta cosmética — evita narrar una etapa
              // ficticia mientras el backend ya está en otra distinta.
              const label = currentStage && currentStage.trim() ? currentStage : stage.label;
              return (
                <div key={stage.id} className="flex items-baseline gap-2">
                  <span className="flex-shrink-0 text-2xs" style={{ color: '#b86a1a', minWidth: '7rem' }}>
                    [ PROC&nbsp;&nbsp;]
                  </span>
                  <span className="flex-shrink-0 text-2xs" style={{ color: '#253348', minWidth: '7.5rem' }}>
                    {stageTs(i)}
                  </span>
                  <span className="text-2xs" style={{ color: 'var(--fg-primary)' }}>
                    {label}
                    <span style={{ color: '#1E63D4', opacity: showCursor ? 1 : 0 }}>█</span>
                  </span>
                </div>
              );
            }

            // pending
            return (
              <div key={stage.id} className="flex items-baseline gap-2">
                <span className="flex-shrink-0 text-2xs" style={{ color: '#1a2436', minWidth: '7rem' }}>
                  [ ------&nbsp;]
                </span>
                <span className="flex-shrink-0 text-2xs" style={{ color: '#1a2436', minWidth: '7.5rem' }}>
                  --:--.---.---
                </span>
                <span className="text-2xs" style={{ color: '#253348' }}>
                  {stage.label}
                </span>
              </div>
            );
          })}
        </div>

        <div className="px-3" style={{ borderTop: '1px solid #1a2030', color: '#253348' }}>
          {'─'.repeat(62)}
        </div>

        {/* Progress bar in terminal style */}
        <div className="px-3 py-2 flex items-center gap-3">
          <span className="text-2xs" style={{ color: 'var(--fg-muted)' }}>Progreso</span>
          <span className="text-2xs tracking-tight" style={{ color: pct >= 80 ? '#1d7a45' : pct >= 40 ? '#b86a1a' : '#1E63D4' }}>
            {barStr}
          </span>
          <span
            className="text-xs font-bold tabular-nums"
            style={{ color: pct >= 80 ? '#1d7a45' : pct >= 40 ? '#b86a1a' : '#1E63D4', minWidth: '2.5rem' }}
          >
            {pct.toString().padStart(3, ' ')}%
          </span>
        </div>
      </div>
    </div>
  );
}
