import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'DeepGuard AI — Análisis Forense Digital',
  description:
    'Plataforma de análisis de autenticidad digital. Detección de manipulación en imágenes y videos mediante inteligencia artificial.',
  keywords: ['deepfake', 'forense digital', 'autenticidad', 'análisis de imagen', 'IA'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>{children}</body>
    </html>
  );
}
