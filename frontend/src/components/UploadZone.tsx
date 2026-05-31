'use client';

import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { AnimatePresence, motion } from 'framer-motion';
import { Upload, X, AlertTriangle } from 'lucide-react';
import { uploadFile, pollTask } from '@/lib/api';
import type { AnalysisResult } from '@/types';

const MAX_MB = 500;
const ACCEPTED = {
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/png':  ['.png'],
  'image/webp': ['.webp'],
  'video/mp4':       ['.mp4'],
  'video/quicktime': ['.mov'],
  'video/x-matroska':['.mkv'],
  'video/webm':      ['.webm'],
};

interface Props {
  onAnalysisStart:  (taskId: string) => void;
  onAnalysisUpdate: (result: AnalysisResult) => void;
  onPreviewReady?:  (url: string, type: 'image' | 'video', filename: string) => void;
}

export default function UploadZone({ onAnalysisStart, onAnalysisUpdate, onPreviewReady }: Props) {
  const [error,    setError]    = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress]  = useState(0);
  const [preview,  setPreview]   = useState<{ url: string; type: 'image'|'video'; name: string } | null>(null);

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    const isImage = file.type.startsWith('image/');
    const isVideo = file.type.startsWith('video/');

    if (!isImage && !isVideo) {
      setError('Formato no soportado. Use JPG, PNG, WEBP, MP4, MOV, MKV o WEBM.');
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`Archivo demasiado grande. Máximo: ${MAX_MB}MB`);
      return;
    }

    const url  = URL.createObjectURL(file);
    const type = isImage ? 'image' : 'video';
    setPreview({ url, type, name: file.name });
    onPreviewReady?.(url, type, file.name);
    setUploading(true);
    setProgress(0);

    try {
      const resp = await uploadFile(file, p => setProgress(p));
      onAnalysisStart(resp.task_id);
      const stop = pollTask(resp.task_id, res => {
        onAnalysisUpdate(res);
        if (res.status === 'completed' || res.status === 'failed') {
          stop();
          setUploading(false);
        }
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al subir el archivo');
      setUploading(false);
    }
  }, [onAnalysisStart, onAnalysisUpdate, onPreviewReady]);

  const clear = () => {
    if (preview) URL.revokeObjectURL(preview.url);
    setPreview(null);
    setError(null);
    setUploading(false);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop:   accepted => accepted[0] && handleFile(accepted[0]),
    accept:   ACCEPTED,
    multiple: false,
    disabled: uploading,
    maxSize:  MAX_MB * 1024 * 1024,
  });

  return (
    <div id="analizar" className="w-full">
      <AnimatePresence mode="wait">
        {!preview ? (
          <motion.div key="dz" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div
              {...getRootProps()}
              className={`upload-zone p-10 text-center ${isDragActive ? 'drag-active' : ''}`}
            >
              <input {...getInputProps()} />
              <Upload size={24} className="mx-auto text-fg-muted mb-3" strokeWidth={1.5} />
              <p className="text-sm font-medium text-fg-primary mb-1">
                {isDragActive ? 'Suelte el archivo aquí' : 'Arrastre un archivo aquí o haga clic para seleccionar'}
              </p>
              <p className="text-xs text-fg-secondary">
                Imágenes: JPG, PNG, WEBP — Videos: MP4, MOV, MKV, WEBM
              </p>
              <p className="text-2xs text-fg-muted mt-1 mono">Máximo {MAX_MB}MB</p>
            </div>
          </motion.div>
        ) : (
          <motion.div key="prev" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="panel overflow-hidden">
            {/* File header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-border-subtle">
              <div className="flex items-center gap-2 min-w-0">
                <span className="badge bg-bg-elevated border-border-subtle text-fg-secondary">
                  {preview.type === 'image' ? 'IMAGEN' : 'VIDEO'}
                </span>
                <span className="text-xs text-fg-secondary truncate mono">{preview.name}</span>
              </div>
              {!uploading && (
                <button onClick={clear} className="p-1 rounded hover:bg-bg-elevated text-fg-muted hover:text-fg-primary transition-colors">
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Preview */}
            {preview.type === 'image' ? (
              <img src={preview.url} alt="Vista previa" className="w-full max-h-72 object-contain bg-bg-primary" />
            ) : (
              <video src={preview.url} controls className="w-full max-h-72 bg-bg-primary" />
            )}

            {/* Upload progress */}
            {uploading && (
              <div className="px-4 py-3 border-t border-border-subtle">
                <div className="flex justify-between text-2xs text-fg-muted mono mb-1.5">
                  <span>Transfiriendo archivo...</span>
                  <span>{progress}%</span>
                </div>
                <div className="prob-bar">
                  <div className="prob-bar-fill bg-accent-blue" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="mt-2 flex items-center gap-2 px-3 py-2 rounded border border-risk-critical-border bg-risk-critical-bg text-risk-critical text-xs">
          <AlertTriangle size={13} className="flex-shrink-0" />
          {error}
        </motion.div>
      )}
    </div>
  );
}
