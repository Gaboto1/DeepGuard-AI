import type { Metadata } from 'next';
import './globals.css';
import { WorkerStatusProvider } from '@/components/WorkerStatusProvider';

export const metadata: Metadata = {
  title: 'DeepScan — Análisis Forense Digital',
  description:
    'Plataforma de análisis forense de autenticidad digital. Detección de deepfakes e imágenes manipuladas mediante inteligencia artificial.',
  keywords: ['deepfake', 'forense digital', 'autenticidad', 'análisis de imagen', 'IA'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>
        <WorkerStatusProvider>
          {children}
        </WorkerStatusProvider>
      </body>
    </html>
  );
}
