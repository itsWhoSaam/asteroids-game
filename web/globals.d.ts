// Side-effect style imports (web/main.css) are real modules for esbuild;
// tsc only needs to know the import resolves.
declare module "*.css";
