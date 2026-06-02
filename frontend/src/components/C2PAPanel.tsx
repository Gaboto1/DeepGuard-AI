'use client';

import { motion } from 'framer-motion';
import {
  ShieldCheck, ShieldX, Shield, Clock, Wrench,
  GitBranch, AlertTriangle, CheckCircle2,
} from 'lucide-react';
import type { C2PAProvenance } from '@/types';

// ── Etiquetas en español para los action codes C2PA ──────────────────────────
const ACTION_LABELS: Record<string, string> = {
  'c2pa.created':           'Creación original',
  'c2pa.edited':            'Edición del contenido',
  'c2pa.published':         'Publicación',
  'c2pa.cropped':           'Recorte',
  'c2pa.resized':           'Redimensionado',
  'c2pa.color_adjustments': 'Ajuste de color',
  'c2pa.converted':         'Conversión de formato',
  'c2pa.filtered':          'Filtros aplicados',
  'c2pa.placed':            'Elemento insertado',
  'c2pa.repackaged':        'Reempaquetado',
  'c2pa.transcoded':        'Transcodificado',
  'c2pa.watermarked':       'Marca de agua',
  'ai.created':             'Generación por IA',
  'ai.edited':              'Edición por IA',
};

function actionLabel(code: string): string {
  if (ACTION_LABELS[code]) return ACTION_LABELS[code];
  // Fallback: limpiar prefijo c2pa. / ai.
  return code.replace(/^c2pa\./, '').replace(/^ai\./, 'IA · ').replace(/_/g, ' ');
}

function formatDate(iso?: string | null): string {
  if (!iso) return 'Fecha desconocida';
  try {
    return new Date(iso).toLocaleDateString('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

interface Props {
  provenance: C2PAProvenance;
}

export default function C2PAPanel({ provenance }: Props) {
  const {
    has_c2pa, verified, signed_by, claim_generator,
    issued_at, history_log, error,
  } = provenance;

  return (
    <div className="space-y-3 font-mono text-xs">

      {/* ── Badge de estado principal ────────────────────────────────────────── */}
      {!has_c2pa ? (
        /* Sin manifiesto C2PA — caso neutro (mayoría de archivos) */
        <div
          className="flex items-start gap-3 px-3 py-3 border"
          style={{ borderColor: '#1a2030', background: '#05080f' }}
        >
          <Shield size={16} style={{ color: '#253348', flexShrink: 0, marginTop: 2 }} />
          <div>
            <p className="text-xs font-bold uppercase tracking-wider" style={{ color: '#3d4f62' }}>
              Sin manifiesto C2PA
            </p>
            <p className="text-2xs mt-1 leading-relaxed" style={{ color: '#253348' }}>
              Este archivo no incorpora metadatos de procedencia C2PA. La ausencia de manifiesto
              no implica manipulación — la mayoría de imágenes y videos todavía no utilizan este
              estándar. La cobertura aumenta con cámaras Sony/Nikon/Leica recientes y generadores
              IA como Adobe Firefly y DALL·E 3.
            </p>
            {error && error !== 'c2pa-python not installed' && (
              <p className="text-2xs mt-1.5 px-2 py-1 border"
                style={{ color: '#4a3030', borderColor: '#3a1a1a', background: '#100808' }}>
                Diagnóstico: {error}
              </p>
            )}
          </div>
        </div>

      ) : verified ? (
        /* ── Firma válida — contenido auténtico verificado ─────────────────── */
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="border overflow-hidden"
          style={{ borderColor: 'rgba(29,122,69,0.45)', background: 'rgba(29,122,69,0.04)' }}
        >
          {/* Header verificado */}
          <div
            className="flex items-center gap-3 px-3 py-2.5 border-b"
            style={{ borderColor: 'rgba(29,122,69,0.2)', background: 'rgba(29,122,69,0.07)' }}
          >
            <ShieldCheck size={18} style={{ color: '#1d7a45', flexShrink: 0 }} />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-bold uppercase tracking-wider" style={{ color: '#1d7a45' }}>
                Contenido Auténtico — Firma C2PA Válida
              </p>
              {signed_by && (
                <p className="text-2xs mt-0.5" style={{ color: '#2d6a45' }}>
                  Firmado por: <span className="font-semibold" style={{ color: '#1d7a45' }}>{signed_by}</span>
                </p>
              )}
            </div>
            <span
              className="flex items-center gap-1 text-2xs px-2 py-0.5 border font-bold flex-shrink-0"
              style={{ color: '#1d7a45', borderColor: '#1d7a45', background: 'transparent' }}
            >
              <CheckCircle2 size={9} />
              VERIFICADO
            </span>
          </div>

          {/* Metadata del sello */}
          <div className="px-3 py-2 flex flex-wrap gap-x-6 gap-y-1.5">
            {claim_generator && (
              <div className="flex items-center gap-1.5">
                <Wrench size={9} style={{ color: '#253348' }} />
                <span className="text-2xs" style={{ color: '#253348' }}>Software: </span>
                <span className="text-2xs font-semibold" style={{ color: '#2d6a45' }}>{claim_generator}</span>
              </div>
            )}
            {issued_at && (
              <div className="flex items-center gap-1.5">
                <Clock size={9} style={{ color: '#253348' }} />
                <span className="text-2xs" style={{ color: '#253348' }}>Emitido: </span>
                <span className="text-2xs" style={{ color: '#2d6a45' }}>{formatDate(issued_at)}</span>
              </div>
            )}
          </div>

          <div className="px-3 pb-2.5">
            <p className="text-2xs leading-relaxed" style={{ color: '#253348' }}>
              La firma criptográfica confirma que este archivo no fue modificado desde su emisión
              y fue producido o certificado por la entidad indicada. Este certificado puede
              presentarse como evidencia forense independiente.
            </p>
          </div>
        </motion.div>

      ) : (
        /* ── Firma INVÁLIDA — posible alteración ─────────────────────────────── */
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="border overflow-hidden"
          style={{ borderColor: 'rgba(196,43,43,0.4)', background: 'rgba(196,43,43,0.05)' }}
        >
          <div
            className="flex items-center gap-3 px-3 py-2.5 border-b"
            style={{ borderColor: 'rgba(196,43,43,0.2)', background: 'rgba(196,43,43,0.08)' }}
          >
            <ShieldX size={18} style={{ color: '#c42b2b', flexShrink: 0 }} />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-bold uppercase tracking-wider" style={{ color: '#c42b2b' }}>
                Manifiesto C2PA Presente — Firma INVÁLIDA
              </p>
              {signed_by && (
                <p className="text-2xs mt-0.5" style={{ color: '#8a2020' }}>
                  Emisor original declarado: {signed_by}
                </p>
              )}
            </div>
            <span
              className="text-2xs px-2 py-0.5 border font-bold flex-shrink-0 uppercase tracking-wider"
              style={{ color: '#c42b2b', borderColor: '#c42b2b', background: 'transparent' }}
            >
              ALTERADO
            </span>
          </div>
          <div className="px-3 py-2.5">
            <div className="flex items-start gap-2">
              <AlertTriangle size={11} style={{ color: '#c42b2b', flexShrink: 0, marginTop: 1 }} />
              <p className="text-2xs leading-relaxed" style={{ color: '#9a3030' }}>
                El archivo contiene un manifiesto C2PA pero su firma criptográfica no pasa
                la verificación. Esto indica que el contenido fue modificado después de ser
                firmado — señal forense de alta relevancia para la clasificación como deepfake.
              </p>
            </div>
          </div>
        </motion.div>
      )}

      {/* ── Historial de procedencia (ingredientes C2PA) ─────────────────────── */}
      {has_c2pa && history_log && history_log.length > 0 && (
        <div className="border overflow-hidden" style={{ borderColor: '#1a2030' }}>

          {/* Header del historial */}
          <div
            className="flex items-center gap-2 px-3 py-1.5 border-b"
            style={{ background: '#080c15', borderColor: '#1a2030' }}
          >
            <GitBranch size={11} style={{ color: 'var(--fg-muted)' }} />
            <span className="text-2xs uppercase tracking-widest" style={{ color: 'var(--fg-muted)' }}>
              Historial de Procedencia
            </span>
            <span
              className="ml-auto text-2xs px-1.5 py-0.5 border"
              style={{ color: '#3d4f62', borderColor: '#1a2436', background: '#05080f' }}
            >
              {history_log.length} etapa{history_log.length !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Timeline */}
          <div className="relative" style={{ background: '#05080f' }}>
            {/* Línea vertical de conexión */}
            <div
              className="absolute"
              style={{
                left: '26px',
                top: '12px',
                bottom: '12px',
                width: '1px',
                background: '#1a2436',
              }}
            />

            {history_log.map((entry, i) => {
              const isActive     = entry.relationship === 'active';
              const isFirst      = i === 0;
              const dotColor     = isActive
                ? '#1E63D4'
                : (verified ? '#1d7a45' : '#3d4f62');
              const stepLabel    = isActive ? 'ACTUAL' : `${i + 1}`;

              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2, delay: i * 0.06 }}
                  className="relative flex gap-3 px-3"
                  style={{
                    paddingTop:    isFirst ? '12px' : '8px',
                    paddingBottom: i === history_log.length - 1 ? '12px' : '8px',
                    paddingLeft:   '48px',
                    borderBottom:  i < history_log.length - 1 ? '1px solid #0d111a' : 'none',
                  }}
                >
                  {/* Nodo de la timeline */}
                  <div
                    className="absolute flex items-center justify-center"
                    style={{
                      left: '18px',
                      top:  isFirst ? '14px' : '10px',
                      width:  '16px',
                      height: '16px',
                      background: dotColor,
                      boxShadow: isActive ? `0 0 8px ${dotColor}44` : 'none',
                    }}
                  >
                    <span style={{
                      color: '#fff',
                      fontSize: '8px',
                      fontWeight: 700,
                      fontFamily: 'monospace',
                      lineHeight: 1,
                    }}>
                      {isActive ? '▶' : stepLabel}
                    </span>
                  </div>

                  {/* Contenido del nodo */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className="text-xs font-semibold truncate"
                          style={{ color: isActive ? '#1E63D4' : 'var(--fg-secondary)' }}
                        >
                          {entry.title || entry.tool || 'Origen desconocido'}
                        </span>
                        {isActive && (
                          <span
                            className="text-2xs px-1 py-0.5 uppercase tracking-wider flex-shrink-0"
                            style={{ color: '#1E63D4', background: 'rgba(30,99,212,0.1)', border: '1px solid rgba(30,99,212,0.2)' }}
                          >
                            Esta versión
                          </span>
                        )}
                      </div>
                      {entry.date && (
                        <span className="text-2xs flex-shrink-0" style={{ color: '#253348' }}>
                          {formatDate(entry.date)}
                        </span>
                      )}
                    </div>

                    {/* Herramienta (si difiere del título) */}
                    {entry.tool && entry.tool !== entry.title && (
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <Wrench size={8} style={{ color: '#253348' }} />
                        <span className="text-2xs" style={{ color: '#3d4f62' }}>{entry.tool}</span>
                      </div>
                    )}

                    {/* Acciones realizadas */}
                    {entry.actions && entry.actions.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-1.5">
                        {entry.actions.map((action, j) => (
                          <span
                            key={j}
                            className="text-2xs px-1.5 py-0.5 border"
                            style={{ color: '#3d4f62', borderColor: '#1a2030', background: '#03050a' }}
                            title={action.software_agent || undefined}
                          >
                            {actionLabel(action.action)}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Tipo de relación */}
                    {entry.relationship && entry.relationship !== 'active' && entry.relationship !== 'parentOf' && (
                      <p className="text-2xs mt-0.5" style={{ color: '#1a2436' }}>
                        {entry.relationship === 'componentOf' ? 'Componente de composición' : entry.relationship}
                      </p>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Nota técnica C2PA ────────────────────────────────────────────────── */}
      <div
        className="px-3 py-2 border text-2xs leading-relaxed"
        style={{ borderColor: '#1a2030', background: '#03050a', color: '#1a2436' }}
      >
        <span style={{ color: '#253348' }}>C2PA</span> (Coalition for Content Provenance
        and Authenticity) es el estándar criptográfico de la industria para procedencia
        de contenido digital. Soportado por Adobe, Sony, Nikon, Leica, Canon, Reuters,
        AP, Getty, DALL·E 3 y Adobe Firefly. La verificación usa firmas X.509 — no puede
        ser falsificada sin acceso a la clave privada del certificado.
      </div>
    </div>
  );
}
