import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";
import { fileURLToPath } from "node:url";

const featureNames = [
  "app-shell",
  "jobs",
  "job-search",
  "applications",
  "calendar",
  "profile",
  "dashboard",
  "settings",
  "activity",
  "assistant",
  "notifications",
];

const aggregationFeatures = new Set(["app-shell", "dashboard"]);

const featureImportZones = featureNames
  .filter((featureName) => !aggregationFeatures.has(featureName))
  .map((featureName) => ({
    target: `./src/features/${featureName}/**`,
    from: featureNames
      .filter((candidateName) => candidateName !== featureName)
      .filter(
        (candidateName) =>
          !(featureName === "applications" && candidateName === "jobs"),
      )
      .map((candidateName) => `./src/features/${candidateName}/**`),
    message:
      "Feature modules may import only themselves and shared code. " +
      "The applications -> jobs dependency is the only related-feature exception.",
  }));

const lintBasePath = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig([
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    rules: {
      "import/no-restricted-paths": [
        "error",
        {
          basePath: lintBasePath,
          zones: [
            ...featureImportZones,
            {
              target: "./src/features/**",
              from: "./src/app/**",
              message:
                "Feature modules must not import application composition code.",
            },
            {
              target: "./src/shared/**",
              from: ["./src/app/**", "./src/features/**"],
              message:
                "Shared code must not import app or feature modules.",
            },
          ],
        },
      ],
      "react-hooks/immutability": "off",
      "react-hooks/preserve-manual-memoization": "off",
      "react-hooks/purity": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: [
      "src/components/**/*.{ts,tsx}",
      "src/features/**/components/**/*.{ts,tsx}",
      "src/features/**/hooks/**/*.{ts,tsx}",
    ],
    ignores: ["**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='fetch']",
          message:
            "Feature UI must call an endpoint client instead of using fetch directly.",
        },
        {
          selector:
            "MemberExpression[property.name='ok'][object.name=/[Rr]esponse$/]",
          message:
            "Feature UI must not inspect Response.ok; response handling belongs in the shared API transport.",
        },
        {
          selector:
            "ImportDeclaration[source.value='@/shared/api/client'] > ImportSpecifier[imported.name='apiClient']",
          message:
            "Feature UI must call a feature endpoint client instead of the shared transport directly.",
        },
      ],
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/shared/api/config", "@/lib/api-client"],
              message:
                "Feature UI must not construct API URLs or use the removed legacy client.",
            },
          ],
        },
      ],
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);
