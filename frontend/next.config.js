/** @type {import('next').NextConfig} */

// Cuando se construye para GitHub Pages, las rutas deben incluir el
// nombre del repositorio como base path (ej. /DeepGuard-AI/).
// Se activa pasando GITHUB_PAGES=true en el entorno de build.
const isGithubPages = process.env.GITHUB_PAGES === 'true';
const repoName = 'DeepGuard-AI';

const nextConfig = {
  output: 'export',
  trailingSlash: true,

  // GitHub Pages sirve desde /RepoName/ → necesitamos basePath.
  // En Render o localhost no se usa basePath (cadena vacía).
  basePath:    isGithubPages ? `/${repoName}` : '',
  assetPrefix: isGithubPages ? `/${repoName}/` : '',

  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
