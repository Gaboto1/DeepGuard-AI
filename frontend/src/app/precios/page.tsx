'use client';

import Navbar from '@/components/Navbar';
import { PlanesContenido } from '@/components/Planes';

// Se conserva como ruta propia para poder enlazar los planes directamente.
// Desde el menu se abren en una ventana flotante (components/Planes.tsx).
export default function PaginaPrecios() {
  return (
    <div className="min-h-screen" style={{ background: 'var(--bg-primary)' }}>
      <Navbar />
      <main className="max-w-5xl mx-auto px-4 py-10">
        <PlanesContenido />
      </main>
    </div>
  );
}
