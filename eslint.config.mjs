
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import globals from "globals";
import js from "@eslint/js";
import pluginVue from 'eslint-plugin-vue';
import tseslint from 'typescript-eslint';
import eslintConfigPrettier from "eslint-config-prettier";

import vueESLintParser from 'vue-eslint-parser';

// The app directory is named in the generated frontend metadata, which webpack
// and vitest already read. Hard-coding it here would be the one config that
// stops following a rename.
const projectRoot = path.dirname(fileURLToPath(import.meta.url));
const metadataPath = path.join(
    projectRoot,
    'frontend_configuration',
    'webpack-metadata.json'
);

let APP_RELATIVE_PATH;
try {
    ({ APP_RELATIVE_PATH } = JSON.parse(fs.readFileSync(metadataPath, 'utf-8')));
} catch {
    // Generated, and gitignored: a fresh clone has none until the Django check
    // writes it. Say so, rather than let ENOENT surface from a lint run.
    throw new Error(
        `${metadataPath} is missing. It is generated — run ` +
            '`python manage.py check` before linting.'
    );
}

export default [
    js.configs.recommended,
    ...pluginVue.configs['flat/recommended'],
    ...tseslint.configs.recommended,
    eslintConfigPrettier,
    {
        "languageOptions": {
            "globals": {
                ...globals.browser,
            },
            "parser": vueESLintParser,
            "parserOptions": {
                "ecmaVersion": 11,
                "sourceType": "module",
                "requireConfigFile": false,
                "parser": {
                    "ts": "@typescript-eslint/parser"
                }
            },
        },
        "rules": {
            "@typescript-eslint/no-unused-vars": [
                "error", { 
                    "argsIgnorePattern": "^_", 
                    "varsIgnorePattern": "^_",
                    "caughtErrorsIgnorePattern": "^_",
                }
            ],
            "semi": ["error", "always"],
        },
    },
    {
        // The KnockoutJS tree. Webpack aliases these imports rather than
        // resolving them through node_modules, and the page supplies jQuery and
        // AMD's `define` as globals — neither is imported, so both read as
        // undefined here.
        //
        // `const self = this` is the idiom every viewmodel in this tree is
        // written in, and Knockout's binding callbacks need it; flagging it
        // would report 14 deliberate uses as mistakes.
        "files": [`${APP_RELATIVE_PATH}/media/js/**/*.js`],
        "languageOptions": {
            "globals": {
                ...globals.browser,
                ...globals.jquery,
                ...globals.amd,
            },
        },
        "rules": {
            "@typescript-eslint/no-this-alias": "off",
        },
    },
];