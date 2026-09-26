import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Regras do React Compiler (eslint-plugin-react-hooks v7). O compilador NÃO está habilitado neste projeto e os
    // padrões sinalizados são intencionais: callbacks estáveis guardados em refs para o TipTap (o editor é criado uma
    // única vez) e reset de estado ao abrir diálogos. Ficam como aviso para revisão, não como erro de build.
    rules: {
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "react-hooks/immutability": "warn",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "playwright-report/**", "test-results/**", "next-env.d.ts"]),
]);
