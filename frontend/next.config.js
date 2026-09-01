/** @type {import('next').NextConfig} */

// GitHub Pages sirve desde /RepoName/, no desde la raíz.
// GITHUB_PAGES=true lo activa solo en el workflow de CI — en local no tiene efecto.
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
