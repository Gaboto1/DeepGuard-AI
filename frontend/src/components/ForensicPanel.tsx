'use client';

import { motion } from 'framer-motion';
import type { EnsembleBreakdown, ModelAgreement, SemanticAnalysis } from '@/types';

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
  ensemble:          EnsembleBreakdown;
  agreement?:        ModelAgreement;
  agreementStd?:     number;
  facesDetected?:    number;
  semanticAnalysis?: SemanticAnalysis | null;
  chainOfCustody?:   CustodySeal | null;
}

// ─── Score to flat forensic color (no gradients) ─────────────────────────────
function scoreColor(pct: number): string {
  if (pct >= 65) return '#c42b2b';
  if (pct >= 42) return '#b86a1a';
  return '#1d7a45';
}

export default function ForensicPanel({
  ensemble, agreement, agreementStd, facesDetected, semanticAnalysis, chainOfCustody,
}: Props) {

  const modeLabel = ensemble.weights_mode === 'face_detected'
    ? `Modo rostro — ${facesDetected ?? 0} rostro(s) detectado(s)`
    : 'Modo imagen completa — sin rostro detectado';

  return (
    <div className="space-y-4 font-mono text-xs">

      {/* ── Tabla de modelos ────────────────────────────────────────────────── */}
      <div className="overflow-hidden border border-border-subtle">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ background: '#080c15', borderBottom: '1px solid var(--border-strong)' }}>
              <th className="text-left px-3 py-2 text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                Modelo
              </th>
              <th className="text-right px-3 py-2 text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                Score
              </th>
              <th className="text-right px-3 py-2 text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                Peso
              </th>
              <th className="text-right px-3 py-2 text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                Contribución
              </th>
            </tr>
          </thead>
          <tbody>
            {ensemble.models.map((m, i) => {
              const pct = m.score_pct;
              const col = scoreColor(pct);
              return (
                <tr
                  key={i}
                  style={{
                    background: i % 2 === 0 ? '#080c15' : '#0a0f1a',
                    borderBottom: '1px solid #1a2030',
                  }}
                >
                  <td className="px-3 py-2.5" style={{ color: 'var(--fg-secondary)' }}>
                    {m.name}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {/* Square-cornered bar */}
                      <div
                        className="hidden sm:block"
                        style={{ width: '80px', height: '6px', background: '#1a2436', position: 'relative' }}
                      >
                        <motion.div
                          style={{ position: 'absolute', top: 0, left: 0, height: '100%', background: col }}
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 0.6, delay: i * 0.08 }}
                        />
                      </div>
                      <span className="tabular-nums font-bold" style={{ color: col, minWidth: '3rem', textAlign: 'right' }}>
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums" style={{ color: 'var(--fg-muted)' }}>
                    {(m.weight * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums" style={{ color: 'var(--fg-muted)' }}>
                    {(m.contribution * 100).toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr style={{ background: '#080c15', borderTop: '1px solid var(--border-strong)' }}>
              <td colSpan={3} className="px-3 py-2 text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
                Probabilidad final — {modeLabel}
              </td>
              <td className="px-3 py-2 text-right tabular-nums font-bold" style={{ color: 'var(--fg-primary)' }}>
                {(ensemble.final_probability * 100).toFixed(1)}%
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Fórmula */}
      <p className="text-2xs px-1" style={{ color: 'var(--fg-muted)' }}>
        ∑ = {ensemble.models.map(m => `${(m.weight*100).toFixed(0)}%·${m.score_pct.toFixed(0)}%`).join(' + ')}
        {' '}= <span style={{ color: 'var(--fg-secondary)' }}>{(ensemble.final_probability * 100).toFixed(1)}%</span>
      </p>

      {/* ── Consenso ────────────────────────────────────────────────────────── */}
      {agreement && (
        <div
          className="px-3 py-2 border-l-2 text-2xs"
          style={{ borderColor: AGREEMENT_COLOR[agreement], background: '#080c15', color: 'var(--fg-muted)' }}
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
        <div className="border border-border-subtle" style={{ background: '#080c15' }}>
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
          <div className="px-3 py-1 border-t" style={{ borderColor: '#1a2030', background: '#05080f' }}>
            <span className="text-2xs" style={{ color: '#253348' }}>
              {semanticAnalysis.model_used.split('/').pop()} · {semanticAnalysis.quantization} · {semanticAnalysis.analysis_time.toFixed(2)}s
            </span>
          </div>
        </div>
      )}

      {/* ── Sello de cadena de custodia — certificado criptográfico ─────────── */}
      {chainOfCustody && chainOfCustody.custody_token && (
        <div className="border border-border-subtle overflow-hidden" style={{ background: '#05080f' }}>
          {/* Certificate header */}
          <div
            className="flex items-center gap-2 px-3 py-2 border-b"
            style={{ borderColor: '#1a2030', background: '#080c15' }}
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

          {/* Canonical string */}
          {chainOfCustody.canonical_string && (
            <div className="px-3 py-2 border-t" style={{ borderColor: '#1a2030', background: '#030508' }}>
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
