'use client';

import type { MetadataAnalysis, ForensicMetadata } from '@/types';

interface Props { metadata?: MetadataAnalysis | null; forense?: ForensicMetadata | null }

function Row({ k, v }: { k: string; v?: string | number | null }) {
  if (v === null || v === undefined || v === '') return null;
  return (
    <div className="data-row">
      <span className="data-key">{k}</span>
      <span className="data-value">{String(v)}</span>
    </div>
  );
}

function FirmasForenses({ f }: { f: ForensicMetadata }) {
  const ia = f.ai_generator_detected;
  const edicion = f.editing_software_detected;
  return (
    <div className="space-y-2">
      {/* Lo mas importante de la pestana: si el propio archivo declara haber
          sido creado por una IA. Es la evidencia mas directa que existe. */}
      <div className="px-3 py-2.5 border text-xs"
           style={ia
             ? { borderColor: 'rgba(196,43,43,0.45)', background: 'rgba(196,43,43,0.07)' }
             : { borderColor: '#1a2030', background: '#05080f' }}>
        <p className="font-semibold" style={{ color: ia ? '#e05555' : 'var(--fg-primary)' }}>
          {ia
            ? `Los metadatos declaran un generador de IA${f.ai_generator_name ? `: ${f.ai_generator_name}` : ''}`
            : 'Los metadatos no declaran ningún generador de IA'}
        </p>
        <p className="mt-1 leading-relaxed" style={{ color: 'var(--fg-secondary)' }}>
          {ia
            ? 'El propio archivo dice haber sido creado por una herramienta de IA. Es una evidencia directa, aunque se puede borrar al reenviar la imagen.'
            : 'Esto no prueba que sea auténtica: la mayoría de las plataformas eliminan esta información al subir o reenviar una imagen.'}
        </p>
      </div>
      {edicion && (
        <div className="px-3 py-2 border text-xs" style={{ borderColor: 'rgba(154,124,18,0.4)', background: 'rgba(154,124,18,0.06)' }}>
          <span className="font-semibold" style={{ color: '#d4ad2a' }}>Editada con {f.editing_software_name || 'software de edición'}</span>
          <span style={{ color: 'var(--fg-secondary)' }}> — no implica manipulación, pero indica que el archivo no es el original de la cámara.</span>
        </div>
      )}
      {!!f.risk_reasons?.length && (
        <ul className="text-xs space-y-1 pl-1" style={{ color: 'var(--fg-secondary)' }}>
          {f.risk_reasons.map(r => <li key={r}>· {r}</li>)}
        </ul>
      )}
      {!!f.inconsistencies?.length && (
        <ul className="text-xs space-y-1 pl-1" style={{ color: '#d4ad2a' }}>
          {f.inconsistencies.map(r => <li key={r}>· {r}</li>)}
        </ul>
      )}
    </div>
  );
}

export default function MetadataPanel({ metadata, forense }: Props) {
  return (
    <div className="space-y-4">
      {forense && <FirmasForenses f={forense} />}
      {metadata && (<>
      {/* EXIF Status */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded border text-xs ${
        metadata.has_exif
          ? 'border-risk-low-border bg-risk-low-bg text-risk-low'
          : 'border-border-default bg-bg-elevated text-fg-secondary'
      }`}>
        <span className="font-semibold mono">{metadata.has_exif ? 'EXIF PRESENTE' : 'SIN EXIF'}</span>
        <span className="opacity-70">
          {metadata.has_exif
            ? '— Metadatos de cámara encontrados'
            : '— Común en capturas de pantalla, imágenes de redes sociales y contenido IA'}
        </span>
      </div>

      {/* Camera */}
      {(metadata.camera_make || metadata.camera_model || metadata.software) && (
        <div>
          <p className="section-header">Dispositivo de captura</p>
          <div className="panel px-4 py-1">
            <Row k="Marca" v={metadata.camera_make} />
            <Row k="Modelo" v={metadata.camera_model} />
            <Row k="Software" v={metadata.software} />
          </div>
        </div>
      )}

      {/* Settings */}
      {(metadata.iso || metadata.focal_length || metadata.exposure_time || metadata.f_number) && (
        <div>
          <p className="section-header">Parámetros de captura</p>
          <div className="panel px-4 py-1">
            <Row k="ISO" v={metadata.iso} />
            <Row k="Distancia focal" v={metadata.focal_length} />
            <Row k="Exposición" v={metadata.exposure_time} />
            <Row k="Apertura" v={metadata.f_number} />
            <Row k="Flash" v={metadata.flash} />
          </div>
        </div>
      )}

      {/* File */}
      <div>
        <p className="section-header">Archivo</p>
        <div className="panel px-4 py-1">
          <Row k="Dimensiones" v={
            metadata.image_width && metadata.image_height
              ? `${metadata.image_width} × ${metadata.image_height} px`
              : undefined
          } />
          <Row k="Espacio de color" v={metadata.color_space} />
          <Row k="Formato" v={metadata.compression} />
          <Row k="Fecha de captura" v={metadata.datetime_original} />
        </div>
      </div>

      {/* GPS */}
      {metadata.gps_latitude != null && (
        <div>
          <p className="section-header">Ubicación GPS</p>
          <div className="panel px-4 py-1">
            <Row k="Latitud" v={metadata.gps_latitude?.toFixed(6)} />
            <Row k="Longitud" v={metadata.gps_longitude?.toFixed(6)} />
          </div>
        </div>
      )}

      {/* Notes */}
      {metadata.forensic_notes.length > 0 && (
        <div>
          <p className="section-header">Notas forenses</p>
          <div className="space-y-1.5">
            {metadata.forensic_notes.map((note, i) => (
              <div key={i} className="panel-elevated px-3 py-2 text-xs text-fg-secondary">
                {note}
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-2xs text-fg-muted italic">
        Los metadatos son informativos. No modifican la probabilidad de manipulación calculada.
      </p>
      </>)}
    </div>
  );
}
