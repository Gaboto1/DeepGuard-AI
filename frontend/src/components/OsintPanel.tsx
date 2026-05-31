'use client';

import { ExternalLink, AlertCircle } from 'lucide-react';
import type { OsintResult } from '@/types';

interface Props { osint: OsintResult }

export default function OsintPanel({ osint }: Props) {
  const FUENTES_PRIORITARIAS = [
    'Reuters', 'Associated Press', 'Getty Images', 'AFP', 'BBC', 'Wikimedia Commons',
    'Sitios gubernamentales', 'Instituciones académicas',
  ];

  return (
    <div className="space-y-4">
      {/* Status */}
      <div className="flex gap-3 panel-elevated p-3 rounded text-xs">
        <AlertCircle size={14} className="text-risk-medium flex-shrink-0 mt-0.5" />
        <div>
          <p className="font-semibold text-fg-primary mb-0.5">Verificación manual requerida</p>
          <p className="text-fg-secondary leading-relaxed">{osint.note}</p>
        </div>
      </div>

      {/* Search links */}
      {osint.search_links.length > 0 && (
        <div>
          <p className="section-header">Búsqueda inversa de imagen</p>
          <div className="grid grid-cols-2 gap-2">
            {osint.search_links.map((link, i) => (
              <a key={i} href={link.url} target="_blank" rel="noopener noreferrer"
                className="flex items-center justify-between gap-2 px-3 py-2 rounded border border-border-subtle bg-bg-elevated hover:border-border-strong hover:text-fg-primary text-fg-secondary text-xs transition-colors group">
                <span className="font-medium">{link.engine}</span>
                <ExternalLink size={11} className="opacity-40 group-hover:opacity-80 flex-shrink-0" />
              </a>
            ))}
          </div>
          <p className="text-2xs text-fg-muted mt-2">
            Descargue la imagen y cárguela manualmente en cada motor de búsqueda.
          </p>
        </div>
      )}

      {/* Priority sources */}
      <div>
        <p className="section-header">Fuentes prioritarias a verificar</p>
        <div className="flex flex-wrap gap-1.5">
          {FUENTES_PRIORITARIAS.map(src => (
            <span key={src} className="badge bg-bg-elevated border-border-subtle text-fg-secondary">
              {src}
            </span>
          ))}
        </div>
      </div>

      {/* Hash */}
      {osint.perceptual_hash && (
        <div>
          <p className="section-header">Hash perceptual</p>
          <div className="panel-elevated px-3 py-2">
            <code className="text-2xs text-fg-muted mono break-all">{osint.perceptual_hash}</code>
          </div>
          <p className="text-2xs text-fg-muted mt-1">
            Utilice este hash para detectar imágenes casi idénticas en una base de datos local.
          </p>
        </div>
      )}

      {/* Disclaimer */}
      <div className="panel px-3 py-2 text-2xs text-fg-muted italic leading-relaxed">
        {osint.disclaimer}
      </div>
    </div>
  );
}
