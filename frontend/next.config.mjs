/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  webpack: (config) => {
    // Stage 4: pdfjs-dist 4.x ships its worker as `pdf.worker.min.mjs`.
    // Next.js 14's default loaders route `.mjs` through Babel + Terser
    // which mangled the `import` / `export` syntax → "SyntaxError: cannot
    // be used outside of module code". The worker file IS a module
    // (that's what `.mjs` means) so we tell webpack to treat it as
    // such without Babel rewriting it.
    config.module.rules.push({
      test: /pdf\.worker\.min\.mjs$/,
      type: "javascript/auto",
      resolve: {
        fullySpecified: false,
      },
    });
    return config;
  },
};

export default nextConfig;