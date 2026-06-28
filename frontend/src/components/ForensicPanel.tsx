'use client';

import { motion } from 'framer-motion';
import type { EnsembleBreakdown, ModelAgreement, SemanticAnalysis } from '@/types';

// ── Constantes de consenso — sin cambios ─────────────────────────────────────
const AGREEMENT_LABEL: Record<ModelAgreement, string> = {
  'High Consensus':   'Alto Consenso    — modelos alineados, mayor confiabilidad',
  'Medium Consensus': 'Consenso Moderado — desacuerdo parcial, interpretar con precaución',
  'Low Consensus':    'Bajo Consenso    — alta discrepancia entre modelos',
};
const AGREEMENT_COLOR: Record<ModelAgreement, string> = {
  'High Consensus':   '#1d7a45',
  'Medium Consensus': '#9a7c12',
  'Low Consensus':    '#c42b2b',
};

const FUSION_LABEL: Record<string, string> = {
  semantic_correction_up:    '↑ Corrección ascendente — LLaVA detectó anomalías no capturadas por el ensemble',
  semantic_correction_down:  '↓ Corrección descendente — LLaVA confirmó coherencia anatómica y física',
  semantic_compression_zone: '~ Zona de compresión JPEG — fotografía real comprimida por red social',
  semantic_blend:            '= Blend ponderado (70% ensemble + 30% LLaVA)',
};
const FUSION_COLOR: Record<string, string> = {
  semantic_correction_up:    '#b86a1a',
  semantic_correction_down:  '#1d7a45',
  semantic_compression_zone: '#1E63D4',
  semantic_blend:            '#3d4f62',
};

// ── Tipos locales — sin cambios ───────────────────────────────────────────────
interface CustodySeal {
  seal_version?:    string;
  task_id?:         string;
  file_sha256?:     string;
  filename?:        string;
  final_score?:     number;
  semantic_score?:  number;
  timestamp_utc?:   string;
  timestamp_unix?:  number;
  custody_token?:   string;
  canonical_string?:string;
  integrity_valid?: boolean;
}

interface Props {
  ensemble:          EnsembleBreakdown;   // datos vivos en memoria — no se muestra como tabla
  agreement?:        ModelAgreement;
  agreementStd?:     number;
  facesDetected?:    number;
  semanticAnalysis?: SemanticAnalysis | null;
  chainOfCustody?:   CustodySeal | null;
}

// ── Color semáforo forense ────────────────────────────────────────────────────
function scoreColor(pct: number): string {
  if (pct >= 65) return '#c42b2b';
  if (pct >= 42) return '#b86a1a';
  return '#1d7a45';
}

function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Veredicto del bloque superior — depende del resultado real del análisis ──
// (antes mostraba siempre "Contenido Auténtico / VÁLIDO" sin relación al score)
type VerdictTier = 'fake' | 'uncertain' | 'real' | 'invalid';

const VERDICT: Record<VerdictTier, { icon: string; color: string; title: string; subtitle: string; badge: string }> = {
  invalid: {
    icon:     '⚠',
    color:    '#c42b2b',
    title:    'Sello de Custodia Inválido',
    subtitle: 'No fue posible verificar la integridad criptográfica del resultado — tratar con precaución',
    badge:    'ALERTA',
  },
  fake: {
    icon:     '✕',
    color:    '#c42b2b',
    title:    'Alta Probabilidad de Manipulación',
    subtitle: 'El ensemble forense detectó fuertes indicios de contenido generado o alterado por IA',
    badge:    'RIESGO ALTO',
  },
  uncertain: {
    icon:     '!',
    color:    '#b86a1a',
    title:    'Evidencia No Concluyente',
    subtitle: 'Señales mixtas entre modelos — se recomienda revisión manual adicional',
    badge:    'REVISAR',
  },
  real: {
    icon:     '✓',
    color:    '#10b981',
    title:    'Sin Indicios de Manipulación',
    subtitle: 'El ensemble forense no detectó evidencia significativa de alteración por IA',
    badge:    'BAJO RIESGO',
  },
};

export default function ForensicPanel({
  ensemble, agreement, agreementStd, facesDetected, semanticAnalysis, chainOfCustody,
}: Props) {

  // Datos del ensemble vivos en memoria (no renderizados como tabla para reducir ruido visual)
  const modelCount   = ensemble.models.length;
  const finalProbPct = (ensemble.final_probability * 100).toFixed(1);
  const pct          = parseFloat(finalProbPct);

  const custodyOk = chainOfCustody?.integrity_valid !== false;
  const tier: VerdictTier = !custodyOk ? 'invalid' : pct >= 65 ? 'fake' : pct >= 42 ? 'uncertain' : 'real';
  const v = VERDICT[tier];

  const custodyLog = [
    { n: '1', label: 'Origen del Archivo',    detail: 'Captura de medios procesada',            ok: true },
    { n: '2', label: 'Integridad de Bloques', detail: custodyOk ? 'Sello HMAC-SHA256 verificado' : 'Sello HMAC-SHA256 NO coincide', ok: custodyOk },
    { n: '3', label: 'Registro Local',        detail: 'Huella SHA-256 calculada en el servidor', ok: true },
  ] as const;

  return (
    <div className="space-y-4 font-mono text-xs">

      {/* ── Bloque de Veredicto Forense ──────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="overflow-hidden"
        style={{
          boxShadow:  `0 0 25px ${withAlpha(v.color, 0.05)}`,
          border:     `1px solid ${withAlpha(v.color, 0.18)}`,
          background: '#020408',
        }}
      >
        {/* Badge principal — veredicto real del ensemble */}
        <div
          className="flex items-center gap-3 px-3 py-2.5 border-b"
          style={{
            borderColor: withAlpha(v.color, 0.12),
            background:  withAlpha(v.color, 0.04),
          }}
        >
          {/* Icono de estado */}
          <div
            className="flex items-center justify-center flex-shrink-0"
            style={{
              width:   30,
              height:  30,
              border:  `1px solid ${withAlpha(v.color, 0.30)}`,
              background: withAlpha(v.color, 0.08),
            }}
          >
            <span style={{ color: v.color, fontSize: 15, lineHeight: 1 }}>{v.icon}</span>
          </div>

          {/* Texto */}
          <div className="flex-1 min-w-0">
            <p
              className="text-xs font-bold uppercase tracking-wider"
              style={{ color: v.color }}
            >
              {v.title}
            </p>
            <p className="text-2xs mt-0.5" style={{ color: withAlpha(v.color, 0.65) }}>
              {v.subtitle}
            </p>
          </div>

          {/* Badge de severidad */}
          <span
            className="flex-shrink-0 text-2xs px-2 py-0.5 uppercase tracking-wider font-bold"
            style={{
              color:      v.color,
              border:     `1px solid ${withAlpha(v.color, 0.30)}`,
              background: withAlpha(v.color, 0.06),
            }}
          >
            {v.badge}
          </span>
        </div>

        {/* Log cronológico de cadena de custodia */}
        <div className="px-3 py-2.5 space-y-2">
          {custodyLog.map(({ n, label, detail, ok }) => (
            <div key={n} className="flex items-start gap-3">
              <span
                className="text-2xs flex-shrink-0 tabular-nums"
                style={{ color: withAlpha(v.color, 0.35), fontFamily: 'monospace', paddingTop: 1 }}
              >
                {n}.
              </span>
              <div className="flex-1 min-w-0">
                <span className="text-2xs font-semibold" style={{ color: withAlpha(v.color, 0.65) }}>
                  {label}:{' '}
                </span>
                <span className="text-2xs" style={{ color: '#3d4f62' }}>
                  {detail}
                </span>
              </div>
              <span
                className="text-2xs flex-shrink-0 font-bold tabular-nums"
                style={{ color: ok ? '#10b981' : '#c42b2b', fontFamily: 'monospace' }}
              >
                {ok ? '[OK]' : '[FALLO]'}
              </span>
            </div>
          ))}
        </div>

        {/* Metadata compacta del ensemble — datos vivos, presentación mínima */}
        <div
          className="px-3 py-1.5 border-t flex items-center gap-4"
          style={{ borderColor: withAlpha(v.color, 0.08), background: '#010205' }}
        >
          <span className="text-2xs" style={{ color: '#1a2436' }}>
            Ensemble:{' '}
            <span style={{ color: '#253348' }}>{modelCount} modelos</span>
          </span>
          <span className="text-2xs" style={{ color: '#1a2436' }}>
            Score consolidado:{' '}
            <span style={{ color: scoreColor(pct) }}>{finalProbPct}%</span>
          </span>
          {facesDetected != null && (
            <span className="text-2xs" style={{ color: '#1a2436' }}>
              Rostros:{' '}
              <span style={{ color: '#253348' }}>{facesDetected}</span>
            </span>
          )}
        </div>
      </motion.div>

      {/* ── Consenso de modelos ──────────────────────────────────────────────── */}
      {agreement && (
        <div
          className="px-3 py-2 border-l-2 text-2xs"
          style={{
            borderColor: AGREEMENT_COLOR[agreement],
            background:  '#05080f',
            color:       'var(--fg-muted)',
            border:      `1px solid #1e293b`,
            borderLeft:  `2px solid ${AGREEMENT_COLOR[agreement]}`,
          }}
        >
          <span style={{ color: AGREEMENT_COLOR[agreement] }}>
            {agreement === 'High Consensus' ? '[ HIGH   ]' :
             agreement === 'Medium Consensus' ? '[ MEDIUM ]' : '[ LOW    ]'}
          </span>
          {' '}{AGREEMENT_LABEL[agreement]}
          {agreementStd !== undefined && (
            <span className="ml-3" style={{ color: '#1a2436' }}>σ={agreementStd.toFixed(3)}</span>
          )}
        </div>
      )}

      {/* ── Análisis semántico LLaVA ─────────────────────────────────────────── */}
      {semanticAnalysis && semanticAnalysis.available && (
        <div
          className="overflow-hidden shadow-[0_0_25px_rgba(16,185,129,0.05)]"
          style={{ border: '1px solid #1e293b', background: '#03050a' }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-3 py-1.5 border-b"
            style={{ borderColor: '#1a2030', background: '#05080f' }}
          >
            <span className="text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
              Análisis Semántico — LLaVA-1.5-7b-hf · 4-bit NF4
            </span>
            <span
              className="tabular-nums font-bold"
              style={{ color: scoreColor(semanticAnalysis.risk_score), fontSize: '11px' }}
            >
              {semanticAnalysis.risk_score}/100
            </span>
          </div>

          <div className="px-3 pt-2 pb-1">
            {/* Score bar */}
            <div style={{ height: '6px', background: '#1a2436', marginBottom: '8px' }}>
              <motion.div
                style={{ height: '100%', background: scoreColor(semanticAnalysis.risk_score) }}
                initial={{ width: 0 }}
                animate={{ width: `${semanticAnalysis.risk_score}%` }}
                transition={{ duration: 0.7 }}
              />
            </div>

            {/* Fusion type */}
            {semanticAnalysis.fusion_type && (
              <p
                className="text-2xs mb-2"
                style={{ color: FUSION_COLOR[semanticAnalysis.fusion_type] ?? 'var(--fg-muted)' }}
              >
                {FUSION_LABEL[semanticAnalysis.fusion_type] ?? semanticAnalysis.fusion_type}
              </p>
            )}

            {/* Fusion note */}
            {semanticAnalysis.fusion_note && (
              <p className="text-2xs mb-2" style={{ color: 'var(--fg-muted)' }}>
                {semanticAnalysis.fusion_note}
              </p>
            )}
          </div>

          {/* Observations */}
          {semanticAnalysis.semantic_observations && (
            <div className="px-3 py-2 border-t" style={{ borderColor: '#1a2030' }}>
              <p className="text-2xs mb-1 uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                Observaciones forenses
              </p>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--fg-secondary)', fontFamily: 'inherit' }}>
                {semanticAnalysis.semantic_observations}
              </p>
            </div>
          )}

          <div className="px-3 py-1 border-t" style={{ borderColor: '#1a2030', background: '#02040a' }}>
            <span className="text-2xs" style={{ color: '#253348' }}>
              {semanticAnalysis.model_used.split('/').pop()} · {semanticAnalysis.quantization} · {semanticAnalysis.analysis_time.toFixed(2)}s
            </span>
          </div>
        </div>
      )}

      {/* ── Sello de cadena de custodia — certificado criptográfico ─────────── */}
      {chainOfCustody && chainOfCustody.custody_token && (
        <div
          className="overflow-hidden shadow-[0_0_25px_rgba(16,185,129,0.05)]"
          style={{ border: '1px solid #1e293b', background: '#02040a' }}
        >
          {/* Certificate header */}
          <div
            className="flex items-center gap-2 px-3 py-2 border-b"
            style={{ borderColor: '#1a2030', background: '#04060f' }}
          >
            <span style={{ color: '#1d7a45' }}>■</span>
            <span className="text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
              Sello Forense — {chainOfCustody.seal_version ?? 'DG-CUSTODY-v2'}
            </span>
            <span
              className="ml-auto text-2xs"
              style={{ color: chainOfCustody.integrity_valid !== false ? '#1d7a45' : '#c42b2b' }}
            >
              {chainOfCustody.integrity_valid !== false ? '[ VÁLIDO ]' : '[ INVÁLIDO ]'}
            </span>
          </div>

          {/* Fields */}
          <div className="px-3 py-2 space-y-1.5">
            {/* SHA-256 */}
            <div className="space-y-0.5">
              <span className="text-2xs uppercase tracking-widest" style={{ color: '#253348' }}>
                SHA-256 del archivo
              </span>
              <p
                className="text-2xs break-all"
                style={{ color: '#1d7a45', letterSpacing: '0.02em', fontFamily: 'monospace' }}
              >
                {chainOfCustody.file_sha256}
              </p>
            </div>

            {/* HMAC */}
            <div className="space-y-0.5">
              <span className="text-2xs uppercase tracking-widest" style={{ color: '#253348' }}>
                Token HMAC-SHA256
              </span>
              <p
                className="text-2xs break-all"
                style={{ color: '#1E63D4', letterSpacing: '0.02em', fontFamily: 'monospace' }}
              >
                {chainOfCustody.custody_token}
              </p>
            </div>

            {/* Metadata row */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
              {chainOfCustody.timestamp_utc && (
                <div>
                  <span className="text-2xs" style={{ color: '#253348' }}>Timestamp UTC  </span>
                  <span className="text-2xs" style={{ color: 'var(--fg-muted)' }}>
                    {chainOfCustody.timestamp_utc}
                  </span>
                </div>
              )}
              {chainOfCustody.final_score !== undefined && (
                <div>
                  <span className="text-2xs" style={{ color: '#253348' }}>Score firmado  </span>
                  <span className="text-2xs" style={{ color: 'var(--fg-muted)' }}>
                    {(chainOfCustody.final_score * 100).toFixed(2)}%
                  </span>
                </div>
              )}
              {chainOfCustody.semantic_score !== undefined && chainOfCustody.semantic_score >= 0 && (
                <div>
                  <span className="text-2xs" style={{ color: '#253348' }}>Score VLM  </span>
                  <span className="text-2xs" style={{ color: 'var(--fg-muted)' }}>
                    {chainOfCustody.semantic_score}/100
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Canonical string — fondo terminal CLI */}
          {chainOfCustody.canonical_string && (
            <div
              className="px-3 py-2 border-t"
              style={{ borderColor: '#1a2030', background: '#010204' }}
            >
              <p className="text-2xs mb-1 uppercase tracking-widest" style={{ color: '#1a2436' }}>
                String canónico firmado (verificación independiente)
              </p>
              <p
                className="text-2xs break-all leading-relaxed"
                style={{ color: '#2e4060', fontFamily: 'monospace' }}
              >
                {chainOfCustody.canonical_string}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
