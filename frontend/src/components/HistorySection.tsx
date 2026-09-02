'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Trash2, Clock, BarChart2 } from 'lucide-react';
import type { AnalysisResult, EvidenceLevel } from '@/types';

const STORAGE_KEY = 'deepguard_history';

export function saveToHistory(result: AnalysisResult): void {
  try {
    const stored  = localStorage.getItem(STORAGE_KEY);
    const history: AnalysisResult[] = stored ? JSON.parse(stored) : [];
    const updated = [result, ...history.filter(h => h.task_id !== result.task_id)].slice(0, 50);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch {}
}

function evidenceColor(level?: EvidenceLevel): string {
  if (!level) return 'var(--fg-muted)';
  const map: Record<EvidenceLevel, string> = {
    'Strong Evidence':    'var(--risk-critical)',
    'Moderate Evidence':  'var(--risk-high)',
    'Inconclusive':       'var(--risk-medium)',
    'Low Evidence':       'var(--risk-low)',
    'Very Low Evidence':  'var(--risk-minimal)',
  };
  return map[level];
}

function evidenceLabel(level?: EvidenceLevel): string {
  if (!level) return '—';
  const map: Record<EvidenceLevel, string> = {
    'Strong Evidence':    'Evidencia Fuerte',
    'Moderate Evidence':  'Evidencia Moderada',
    'Inconclusive':       'Inconclusa',
    'Low Evidence':       'Evidencia Baja',
    'Very Low Evidence':  'Evidencia Muy Baja',
  };
  return map[level];
}

export default function HistorySection({ currentId }: { currentId?: string }) {
  const [history, setHistory] = useState<AnalysisResult[]>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch { return []; }
  });

  useEffect(() => {
    const load = () => {
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        setHistory(stored ? JSON.parse(stored) : []);
      } catch {
        setHistory([]);
      }
    };
    load();
    window.addEventListener('storage', load);
    return () => window.removeEventListener('storage', load);
  }, [currentId]);

  const clearHistory = () => {
    localStorage.removeItem(STORAGE_KEY);
    setHistory([]);
  };

  const removeItem = (id: string) => {
    const updated = history.filter(h => h.task_id !== id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    setHistory(updated);
  };

  if (history.length === 0) return null;

  return (
    <section id="historial" className="border-t border-border-subtle mt-8 pt-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-fg-primary flex items-center gap-2">
          <BarChart2 size={14} className="text-fg-muted" />
          Historial de análisis
        </h2>
        <button onClick={clearHistory}
          className="flex items-center gap-1.5 text-2xs text-fg-muted hover:text-risk-critical transition-colors">
          <Trash2 size={12} />
          Limpiar historial
        </button>
      </div>

      <div className="space-y-1.5">
        <AnimatePresence>
          {history.map(item => {
            const pct = item.manipulation_probability ?? ((item.fake_probability ?? 0) * 100);
            const col = evidenceColor(item.evidence_level);
            return (
              <motion.div key={item.task_id}
                initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }}
                className={`panel flex items-center gap-3 px-4 py-2.5 group ${
                  item.task_id === currentId ? 'border-border-focus' : ''
                }`}>
                <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: col }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-fg-primary truncate">{item.filename}</span>
                    <span className="badge bg-bg-elevated border-border-subtle text-fg-muted text-2xs flex-shrink-0">
                      {item.file_type === 'image' ? 'IMG' : 'VID'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-2xs mono text-fg-muted">
                    <span className="flex items-center gap-1">
                      <Clock size={9} />
                      {new Date(item.created_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' })}
                    </span>
                    <span style={{ color: col }}>{pct.toFixed(1)}%</span>
                    <span className="text-fg-muted">{evidenceLabel(item.evidence_level)}</span>
                  </div>
                </div>
                <button onClick={() => removeItem(item.task_id)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-bg-elevated text-fg-muted hover:text-risk-critical">
                  <Trash2 size={12} />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </section>
  );
}
