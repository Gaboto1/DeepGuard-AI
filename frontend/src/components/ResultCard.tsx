'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RotateCcw, Eye, EyeOff, Clock, Cpu, Users, TrendingUp, Image as ImageIcon, Film, ChevronDown, Sparkles } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import type { AnalysisResult, EvidenceLevel, ModelAgreement } from '@/types';
import ForensicPanel from './ForensicPanel';
import MetadataPanel from './MetadataPanel';
import OsintPanel from './OsintPanel';
import C2PAPanel from './C2PAPanel';

// ── Evidence level labels ─────────────────────────────────────────────────────
const EVIDENCE_ES: Record<EvidenceLevel, { label: string; labelCorto: string; color: string }> = {
  'Very Low Evidence':  { label: 'Evidencia Muy Baja', labelCorto: 'MUY BAJA',  color: '#1d7a45' },
  'Low Evidence':       { label: 'Evidencia Baja',     labelCorto: 'BAJA',      color: '#1d7a45' },
  'Inconclusive':       { label: 'Inconclusa',         labelCorto: 'INCONCLUSA',color: '#9a7c12' },
  'Moderate Evidence':  { label: 'Evidencia Moderada', labelCorto: 'MODERADA',  color: '#b86a1a' },
  'Strong Evidence':    { label: 'Evidencia Fuerte',   labelCorto: 'FUERTE',    color: '#c42b2b' },
};

// Flat, semantic, no-gradient colors
function scoreColor(pct: number): string {
  if (pct >= 65) return '#c42b2b';
  if (pct >= 42) return '#b86a1a';
  if (pct >= 20) return '#9a7c12';
  return '#1d7a45';
}

const TABS = ['Resumen', 'Ensemble', 'Metadatos', 'Verificación', 'Procedencia C2PA', 'Mapa de Atención'] as const;
type Tab = (typeof TABS)[number];

interface Props {
  result:       AnalysisResult;
  onReset:      () => void;
  previewUrl?:  string;
  previewType?: 'image' | 'video';
}

// ─── Segmented SVG gauge (flat, institutional) ────────────────────────────────
function SegmentedGauge({ pct, color }: { pct: number; color: string }) {
  const r     = 58;
  const cx    = 72;
  const cy    = 72;
  const circ  = 2 * Math.PI * r;

  // 48 segments: each = circ/48, 65% filled / 35% gap
  const total     = 48;
  const segLen    = (circ / total) * 0.62;
  const segGap    = (circ / total) * 0.38;
  const dashPat   = `${segLen.toFixed(2)} ${segGap.toFixed(2)}`;

  // Filled circumference
  const filled    = circ * (pct / 100);
  // Empty (remainder shown as background color)
  const empty     = circ - filled;

  return (
    <svg width="144" height="144" viewBox="0 0 144 144" className="-rotate-90" style={{ display: 'block' }}>
      {/* Background segments — all 48 in dark color */}
      <circle
        cx={cx} cy={cy} r={r}
        fill="none"
        stroke="#1a2436"
        strokeWidth="9"
        strokeDasharray={dashPat}
        strokeLinecap="butt"
      />
      {/* Foreground segments — filled portion in risk color */}
      <circle
        cx={cx} cy={cy} r={r}
        fill="none"
        stroke={color}
        strokeWidth="9"
        strokeDasharray={`${filled.toFixed(2)} ${empty.toFixed(2)}`}
        strokeLinecap="butt"
        style={{ transition: 'stroke-dasharray 1s ease-out' }}
      />
      {/* 10% tick marks — thin radial lines */}
      {[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map(mark => {
        const angle = (mark / 100) * 2 * Math.PI;
        const x1 = cx + (r - 13) * Math.cos(angle);
        const y1 = cy + (r - 13) * Math.sin(angle);
        const x2 = cx + (r + 1)  * Math.cos(angle);
        const y2 = cy + (r + 1)  * Math.sin(angle);
        return (
          <line key={mark} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="#0f1623" strokeWidth="1.5" strokeLinecap="butt" />
        );
      })}
    </svg>
  );
}

export default function ResultCard({ result, onReset, previewUrl, previewType }: Props) {
  const [activeTab, setActiveTab]   = useState<Tab>('Resumen');
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showPreview, setShowPreview] = useState(true);

  const pct    = result.manipulation_probability ?? ((result.fake_probability ?? 0) * 100);
  const pctR   = Math.round(pct * 10) / 10;
  const color  = scoreColor(pctR);
  const evInfo = result.evidence_level ? EVIDENCE_ES[result.evidence_level] : null;

  const timelineData = result.frame_timeline?.map(f => ({
    t:    f.timestamp.toFixed(1) + 's',
    prob: Math.round(f.manipulation_probability * 100),
  }));

  const custody = result.chain_of_custody;

  return (
    <div className="w-full space-y-2 font-mono">

      {/* ── Scan ID bar ────────────────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-3 py-1.5 text-2xs border"
        style={{ background: '#05080f', borderColor: '#1a2030', color: 'var(--fg-muted)' }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span style={{ color: '#1E63D4' }}>■</span>
          <span className="truncate">TASK <span style={{ color: 'var(--fg-secondary)' }}>{result.task_id.slice(0, 16).toUpperCase()}...</span></span>
          <span className="hidden sm:inline truncate" style={{ color: '#253348' }}>FILE: {result.filename}</span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          {result.analysis_time != null && (
            <span className="flex items-center gap-1"><Clock size={9} /> {result.analysis_time.toFixed(2)}s</span>
          )}
          {result.device_used && (
            <span className="flex items-center gap-1"><Cpu size={9} /> {result.device_used}</span>
          )}
          {result.completed_at && (
            <span className="hidden md:inline">
              {new Date(result.completed_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'medium' })}
            </span>
          )}
        </div>
      </div>

      {/* ── Verdict banner — lo más importante, primero ─────────────────────── */}
      <div
        className="px-5 py-4 border"
        style={{ background: `${color}0a`, borderColor: `${color}35` }}
      >
        <div className="flex items-center gap-4">
          <div
            className="flex-shrink-0 w-12 h-12 flex items-center justify-center border-2 text-2xl font-bold"
            style={{ borderColor: color, color, background: `${color}12`, borderRadius: 0 }}
          >
            {pctR >= 65 ? '✕' : pctR >= 42 ? '!' : '✓'}
          </div>
          <div>
            <p className="text-lg font-bold" style={{ color, fontFamily: 'system-ui,sans-serif', lineHeight: 1.2 }}>
              {pctR >= 65
                ? 'Alta probabilidad de manipulación'
                : pctR >= 42
                ? 'Resultado no concluyente'
                : 'Sin indicios de manipulación detectables'}
            </p>
            <p className="text-sm mt-0.5" style={{ color: 'var(--fg-secondary)', fontFamily: 'system-ui,sans-serif' }}>
              {pctR.toFixed(1)}% de probabilidad de ser IA
              {evInfo ? ` — ${evInfo.label}` : ''}
            </p>
          </div>
        </div>
      </div>

      {/* ── Preview ─────────────────────────────────────────────────────────── */}
      {previewUrl && (
        <div className="border overflow-hidden" style={{ borderColor: '#1a2030', background: '#05080f' }}>
          <div className="flex items-center justify-between px-3 py-1.5 border-b" style={{ borderColor: '#1a2030' }}>
            <div className="flex items-center gap-2 text-2xs" style={{ color: 'var(--fg-muted)' }}>
              {previewType === 'image' ? <ImageIcon size={11} /> : <Film size={11} />}
              <span>{result.filename}</span>
            </div>
            <button
              onClick={() => setShowPreview(v => !v)}
              className="text-2xs flex items-center gap-1"
              style={{ color: 'var(--fg-muted)' }}
            >
              {showPreview ? 'Ocultar' : 'Mostrar'}
              <ChevronDown size={11} className={`transition-transform ${showPreview ? 'rotate-180' : ''}`} />
            </button>
          </div>
          <AnimatePresence>
            {showPreview && (
              <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }} className="overflow-hidden">
                <div className="relative">
                  {previewType === 'image' ? (
                    <img
                      src={showHeatmap && result.heatmap ? result.heatmap : previewUrl}
                      alt="Archivo analizado"
                      className="w-full max-h-80 object-contain"
                      style={{ background: '#05080f' }}
                    />
                  ) : (
                    <video src={previewUrl} controls className="w-full max-h-80" style={{ background: '#05080f' }} />
                  )}
                  {result.heatmap && previewType === 'image' && (
                    <button
                      onClick={() => setShowHeatmap(h => !h)}
                      className="absolute bottom-2 right-2 flex items-center gap-1.5 px-2 py-1 text-xs border"
                      style={{ background: '#080c15', borderColor: '#1a2030', color: 'var(--fg-secondary)' }}
                    >
                      {showHeatmap ? <EyeOff size={11} /> : <Eye size={11} />}
                      {showHeatmap ? 'Original' : 'Grad-CAM'}
                    </button>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ── Core result — gauge + score ──────────────────────────────────────── */}
      <div className="border p-4" style={{ background: '#080c15', borderColor: '#1a2030' }}>
        <div className="flex flex-col sm:flex-row items-center sm:items-start gap-5">

          {/* Segmented gauge */}
          <div className="relative flex-shrink-0 w-36 h-36">
            <SegmentedGauge pct={pctR} color={color} />
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-4xl font-bold tabular-nums" style={{ color, fontFamily: 'JetBrains Mono, Courier New, monospace' }}>
                {pctR.toFixed(0)}
              </span>
              <span className="text-xs" style={{ color: 'var(--fg-muted)' }}>%</span>
            </div>
          </div>

          {/* Right side info */}
          <div className="flex-1 min-w-0 space-y-3">
            {/* Score + evidence */}
            <div>
              <p className="text-2xs uppercase tracking-widest mb-1" style={{ color: 'var(--fg-muted)' }}>
                Probabilidad de Manipulación
              </p>
              <div className="flex items-baseline gap-3 flex-wrap">
                <span className="text-3xl font-bold tabular-nums" style={{ color, fontFamily: 'JetBrains Mono, Courier New, monospace' }}>
                  {pctR.toFixed(1)}%
                </span>
                {evInfo && (
                  <span
                    className="text-2xs px-2 py-0.5 border uppercase tracking-wider"
                    style={{ color: evInfo.color, borderColor: evInfo.color, background: 'transparent' }}
                  >
                    {evInfo.labelCorto}
                  </span>
                )}
              </div>
              {evInfo && (
                <p className="text-xs mt-1" style={{ color: 'var(--fg-secondary)' }}>
                  {evInfo.label}
                </p>
              )}
            </div>

            {/* Flat progress bar */}
            <div>
              <div className="flex justify-between text-2xs mb-1" style={{ color: 'var(--fg-muted)' }}>
                <span>0% — Sin evidencia</span>
                <span>100% — Máxima evidencia</span>
              </div>
              <div style={{ height: '4px', background: '#1a2436', position: 'relative' }}>
                <motion.div
                  style={{ position: 'absolute', top: 0, left: 0, height: '100%', background: color }}
                  initial={{ width: 0 }}
                  animate={{ width: `${pctR}%` }}
                  transition={{ duration: 1.1, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* Facts row */}
            <div className="flex flex-wrap gap-3 text-2xs" style={{ color: 'var(--fg-muted)' }}>
              {result.model_agreement && (
                <span>
                  Consenso:{' '}
                  <span style={{ color: 'var(--fg-secondary)' }}>
                    {result.model_agreement === 'High Consensus' ? 'Alto' :
                     result.model_agreement === 'Medium Consensus' ? 'Moderado' : 'Bajo'}
                  </span>
                </span>
              )}
              {result.faces_detected != null && (
                <span className="flex items-center gap-1">
                  <Users size={9} /> Rostros: <span style={{ color: 'var(--fg-secondary)' }}>{result.faces_detected}</span>
                </span>
              )}
              {result.frames_analyzed != null && (
                <span className="flex items-center gap-1">
                  <TrendingUp size={9} /> Frames: <span style={{ color: 'var(--fg-secondary)' }}>{result.frames_analyzed}</span>
                </span>
              )}
            </div>

            {result.explanation && (
              <div
                className="leading-relaxed px-3 py-2.5 border-l-2"
                style={{
                  color: 'var(--fg-primary)',
                  borderColor: color,
                  background: `${color}0d`,
                  fontFamily: 'system-ui, sans-serif',
                  fontSize: '0.82rem',
                }}
              >
                <span
                  className="block text-2xs uppercase tracking-widest mb-1.5 font-mono"
                  style={{ color: color, opacity: 0.85 }}
                >
                  Análisis forense
                </span>
                {result.explanation}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Model breakdown — always visible ──────────────────────────────────── */}
      {result.ensemble?.models && result.ensemble.models.length > 0 && (
        <div className="border overflow-hidden" style={{ borderColor: '#1a2030' }}>
          {/* Header */}
          <div
            className="flex items-center justify-between px-3 py-2 border-b text-2xs uppercase tracking-widest"
            style={{ background: '#05080f', borderColor: '#1a2030', color: 'var(--fg-muted)' }}
          >
            <span>Scores individuales por modelo</span>
            <span style={{ color: '#253348' }}>
              {result.ensemble.weights_mode === 'face_detected' ? 'modo-rostro' : 'modo-imagen'}
            </span>
          </div>

          {/* Model rows */}
          <div className="px-3 py-2.5 space-y-2" style={{ background: '#080c15' }}>
            {result.ensemble.models.map((m, i) => {
              const pct = m.score_pct;
              const col = scoreColor(pct);
              return (
                <div key={i} className="flex items-center gap-3">
                  <span
                    className="text-2xs flex-shrink-0 truncate"
                    style={{ color: 'var(--fg-muted)', minWidth: '9rem', maxWidth: '9rem' }}
                    title={m.name}
                  >
                    {m.name}
                  </span>
                  {/* Flat rectangular bar — rounded-none */}
                  <div className="flex-1" style={{ height: '6px', background: '#1a2436', position: 'relative' }}>
                    <motion.div
                      style={{ position: 'absolute', top: 0, left: 0, height: '100%', background: col }}
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.6, delay: i * 0.07 }}
                    />
                  </div>
                  <span
                    className="text-xs font-bold tabular-nums flex-shrink-0"
                    style={{ color: col, minWidth: '3.5rem', textAlign: 'right' }}
                  >
                    {pct.toFixed(1)}%
                  </span>
                  <span
                    className="text-2xs flex-shrink-0 hidden sm:block"
                    style={{ color: '#253348', minWidth: '2rem', textAlign: 'right' }}
                  >
                    ×{(m.weight * 100).toFixed(0)}%
                  </span>
                </div>
              );
            })}

            {/* LLaVA row */}
            {result.semantic_analysis?.available && (
              <div className="pt-2 mt-0.5 space-y-1.5" style={{ borderTop: '1px solid #1a2030' }}>
                {(() => {
                  const sp  = result.semantic_analysis!.risk_score;
                  const col = scoreColor(sp);
                  const ft  = result.semantic_analysis!.fusion_type;
                  const ftLabel: Record<string, string> = {
                    semantic_correction_up:    '↑ corrección ascendente',
                    semantic_correction_down:  '↓ corrección descendente',
                    semantic_compression_zone: '~ zona compresión JPEG',
                    semantic_blend:            '= blend ponderado',
                  };
                  return (
                    <>
                      <div className="flex items-center gap-3">
                        <span
                          className="text-2xs flex-shrink-0 flex items-center gap-1"
                          style={{ color: 'var(--fg-muted)', minWidth: '9rem', maxWidth: '9rem' }}
                        >
                          <Sparkles size={9} style={{ color: '#1E63D4', flexShrink: 0 }} />
                          LLaVA-1.5-7b
                        </span>
                        <div className="flex-1" style={{ height: '6px', background: '#1a2436', position: 'relative' }}>
                          <motion.div
                            style={{ position: 'absolute', top: 0, left: 0, height: '100%', background: col }}
                            initial={{ width: 0 }}
                            animate={{ width: `${sp}%` }}
                            transition={{ duration: 0.6, delay: 0.42 }}
                          />
                        </div>
                        <span
                          className="text-xs font-bold tabular-nums flex-shrink-0"
                          style={{ color: col, minWidth: '3.5rem', textAlign: 'right' }}
                        >
                          {sp}/100
                        </span>
                        <span
                          className="text-2xs flex-shrink-0 hidden sm:block"
                          style={{ color: '#253348', minWidth: '2rem', textAlign: 'right' }}
                        >
                          VLM
                        </span>
                      </div>
                      {ft && ft !== 'semantic_blend' && (
                        <p className="text-2xs" style={{ color: '#253348', paddingLeft: '9.75rem' }}>
                          {ftLabel[ft] ?? ft}
                        </p>
                      )}
                    </>
                  );
                })()}
              </div>
            )}
          </div>

          {/* Formula footer */}
          <div
            className="px-3 py-1.5 border-t text-2xs"
            style={{ background: '#05080f', borderColor: '#1a2030', color: 'var(--fg-muted)' }}
          >
            ∑ = {result.ensemble.models
              .map(m => `${(m.weight*100).toFixed(0)}%·${m.score_pct.toFixed(0)}%`)
              .join(' + ')}
            {' '}={' '}
            <span style={{ color: 'var(--fg-secondary)', fontWeight: 600 }}>
              {(result.ensemble.final_probability * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {/* ── Tabbed sections ──────────────────────────────────────────────────── */}
      <div className="border overflow-hidden" style={{ borderColor: '#1a2030' }}>
        {/* Tab bar */}
        <div
          className="flex overflow-x-auto border-b"
          style={{ background: '#05080f', borderColor: '#1a2030' }}
        >
          {(TABS as readonly Tab[]).filter(t => {
            if (t === 'Mapa de Atención'  && !result.heatmap)          return false;
            if (t === 'Metadatos'         && !result.metadata_analysis) return false;
            if (t === 'Verificación'      && !result.osint)             return false;
            if (t === 'Ensemble'          && !result.ensemble)          return false;
            if (t === 'Procedencia C2PA'  && !result.c2pa_provenance)   return false;
            return true;
          }).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className="px-4 py-2.5 text-2xs uppercase tracking-wider flex-shrink-0 transition-colors border-b-2"
              style={{
                color:       activeTab === tab ? 'var(--fg-primary)' : 'var(--fg-muted)',
                borderColor: activeTab === tab ? '#1E63D4' : 'transparent',
                background:  'transparent',
                fontFamily:  'inherit',
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-4" style={{ background: '#080c15' }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.1 }}
            >
              {/* ── Resumen ─────────────────────────────────────────────────── */}
              {activeTab === 'Resumen' && (
                <div className="space-y-3 text-xs">
                  <div className="border" style={{ borderColor: '#1a2030' }}>
                    {[
                      ['Archivo',                   result.filename],
                      ['Tipo',                      result.file_type === 'image' ? 'Imagen' : 'Video'],
                      ['Probabilidad manipulación', `${pctR.toFixed(2)}%`],
                      ['Nivel de evidencia',        evInfo?.label ?? '—'],
                      ['Consenso de modelos',
                        result.model_agreement === 'High Consensus'   ? 'Alto' :
                        result.model_agreement === 'Medium Consensus'  ? 'Moderado' :
                        result.model_agreement === 'Low Consensus'     ? 'Bajo' : '—'],
                      ...(result.model_agreement_std != null
                        ? [['Dispersión (σ)', result.model_agreement_std.toFixed(4)]]
                        : []),
                      ['Rostros detectados',        String(result.faces_detected ?? 0)],
                      ...(result.frames_analyzed != null
                        ? [['Frames analizados', String(result.frames_analyzed)]]
                        : []),
                      ...(result.video_duration != null
                        ? [['Duración video', `${result.video_duration.toFixed(1)}s`]]
                        : []),
                      ['Tiempo de análisis',        result.analysis_time != null ? `${result.analysis_time.toFixed(3)}s` : '—'],
                      ['GPU utilizada',             result.device_used ?? '—'],
                    ].map(([k, v], i) => (
                      <div
                        key={k}
                        className="flex items-baseline justify-between px-3 py-1.5"
                        style={{
                          background:   i % 2 === 0 ? '#080c15' : '#05080f',
                          borderBottom: '1px solid #1a2030',
                        }}
                      >
                        <span className="text-2xs uppercase tracking-wider" style={{ color: 'var(--fg-muted)' }}>{k}</span>
                        <span
                          className="text-xs tabular-nums ml-4 text-right"
                          style={{
                            color: k === 'Probabilidad manipulación' ? color : 'var(--fg-secondary)',
                            maxWidth: '60%',
                            wordBreak: 'break-all',
                          }}
                        >{v}</span>
                      </div>
                    ))}
                  </div>

                  {/* Video timeline chart */}
                  {timelineData && timelineData.length > 0 && (
                    <div>
                      <p className="text-2xs uppercase tracking-widest mb-2" style={{ color: 'var(--fg-muted)' }}>
                        Probabilidad de manipulación por frame
                      </p>
                      <ResponsiveContainer width="100%" height={130}>
                        <AreaChart data={timelineData} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
                          <defs>
                            <linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor={color} stopOpacity={0.18} />
                              <stop offset="95%" stopColor={color} stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <XAxis dataKey="t" tick={{ fill: '#3d4f62', fontSize: 9, fontFamily: 'monospace' }} />
                          <YAxis domain={[0, 100]} tick={{ fill: '#3d4f62', fontSize: 9, fontFamily: 'monospace' }} />
                          <Tooltip
                            contentStyle={{ background: '#080c15', border: '1px solid #1a2030', borderRadius: 0, fontSize: 10, fontFamily: 'monospace' }}
                            formatter={(v: number) => [`${v}%`, 'Prob.']}
                          />
                          <ReferenceLine y={50} stroke="#1a2436" strokeDasharray="4 3" />
                          <Area type="monotone" dataKey="prob" stroke={color} fill="url(#cg)" strokeWidth={1.5} dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                      {result.inconsistency_score != null && (
                        <p className="text-2xs mt-1" style={{ color: '#253348' }}>
                          Inconsistencia temporal: σ={result.inconsistency_score.toFixed(3)}
                          {result.inconsistency_score > 0.20 && ' — variación alta entre frames'}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ── Ensemble ────────────────────────────────────────────────── */}
              {activeTab === 'Ensemble' && result.ensemble && (
                <ForensicPanel
                  ensemble={result.ensemble}
                  agreement={result.model_agreement}
                  agreementStd={result.model_agreement_std}
                  facesDetected={result.faces_detected}
                  semanticAnalysis={result.semantic_analysis}
                  chainOfCustody={custody}
                />
              )}

              {/* ── Metadatos ───────────────────────────────────────────────── */}
              {activeTab === 'Metadatos' && result.metadata_analysis && (
                <MetadataPanel metadata={result.metadata_analysis} />
              )}

              {/* ── Verificación ────────────────────────────────────────────── */}
              {activeTab === 'Verificación' && result.osint && (
                <OsintPanel osint={result.osint} />
              )}

              {/* ── Procedencia C2PA ────────────────────────────────────────── */}
              {activeTab === 'Procedencia C2PA' && result.c2pa_provenance && (
                <C2PAPanel provenance={result.c2pa_provenance} />
              )}

              {/* ── Heatmap ─────────────────────────────────────────────────── */}
              {activeTab === 'Mapa de Atención' && result.heatmap && (
                <div className="space-y-3">
                  <p className="text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                    Regiones de mayor peso en la predicción — Grad-CAM++ sobre ViT
                  </p>
                  <img
                    src={result.heatmap}
                    alt="Mapa de atención Grad-CAM"
                    className="w-full max-h-80 object-contain"
                    style={{ background: '#05080f' }}
                  />
                  <div className="px-3 py-2 text-2xs border" style={{ borderColor: '#1a2030', color: 'var(--fg-muted)' }}>
                    Las regiones en rojo/amarillo reflejan zonas de alta atención del modelo. No implican
                    manipulación confirmada — representan los patrones que más influyeron en la decisión.
                  </div>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* ── Disclaimer ───────────────────────────────────────────────────────── */}
      <div
        className="px-4 py-3 border text-xs leading-relaxed"
        style={{
          background: '#05080f',
          borderColor: '#1a2030',
          color: 'var(--fg-muted)',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        <span className="font-semibold" style={{ color: 'var(--fg-secondary)' }}>Aviso: </span>
        Este análisis es probabilístico y no constituye evidencia forense definitiva ni equivale a
        un peritaje legal. Siempre contraste los resultados con otras fuentes antes de tomar decisiones.
      </div>

      <button
        onClick={onReset}
        className="w-full flex items-center justify-center gap-2 py-2 text-xs border transition-colors"
        style={{
          background: 'transparent', borderColor: '#1a2030',
          color: 'var(--fg-muted)', fontFamily: 'inherit',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = '#253348'; (e.currentTarget as HTMLButtonElement).style.color = 'var(--fg-secondary)'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = '#1a2030'; (e.currentTarget as HTMLButtonElement).style.color = 'var(--fg-muted)'; }}
      >
        <RotateCcw size={12} />
        Analizar otro archivo
      </button>
    </div>
  );
}
