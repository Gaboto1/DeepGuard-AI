/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export para Netlify — genera carpeta /out con HTML/CSS/JS puro
  // El frontend llama a la API de Render directamente via NEXT_PUBLIC_API_URL
  output: 'export',
  trailingSlash: true,

  // Optimización de imágenes desactivada (requerido en export estático)
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
