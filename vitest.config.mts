import fs from 'fs';
import path from 'path';
import vue from "@vitejs/plugin-vue";

import { fileURLToPath } from 'url';
import { defineConfig } from 'vitest/config';

import type { UserConfig } from 'vitest/config';

function generateConfig(): Promise<UserConfig> {
    return new Promise((resolve, reject) => {
        const filePath = path.dirname(fileURLToPath(import.meta.url));

        const exclude = [
            '**/*.d.ts',
            '**/node_modules/**',
            '**/dist/**',
            '**/install/**',
            '**/cypress/**',
            '**/.{idea,git,cache,output,temp}/**',
            '**/{karma,rollup,webpack,vite,vitest,jest,ava,babel,nyc,cypress,tsup,build}.config.*',
            '**/build/**',
            '**/staticfiles/**',
        ];

        const rawData = fs.readFileSync(path.join(__dirname, 'frontend_configuration', 'webpack-metadata.json'), 'utf-8');
        const parsedData = JSON.parse(rawData);

        const alias: { [key: string]: string } = {
            '@/arches': path.join(parsedData['ROOT_DIR'], 'app', 'src', 'arches'),
            'arches': path.join(parsedData['ROOT_DIR'], 'app', 'media', 'js', 'arches.js'),
            // Webpack builds an alias for every file under media/js from its path
            // relative to that directory (see `javascriptRelativeFilepathToAbsoluteFilepathLookup`
            // in webpack/webpack.common.js), which is how the KnockoutJS side writes
            // `import { createForceGraph } from 'utils/force-graph'`. Mirroring the
            // `utils/` prefix here lets a spec import a page module that uses those
            // bare specifiers instead of only leaf utilities via relative paths.
            'utils': path.join(parsedData['APP_ROOT'], 'media', 'js', 'utils'),
        };

        for (
            const [archesApplicationName, archesApplicationPath] 
            of Object.entries(
                parsedData['ARCHES_APPLICATIONS_PATHS'] as { [key: string]: string }
            )
        ) {
            alias[`@/${archesApplicationName}`] = path.join(archesApplicationPath, 'src', archesApplicationName);
        }

        // Virtual-module plugin: resolves webpack-specific import aliases
        // (bindings/, viewmodels/, templates/) that are not in node_modules.
        // The empty stub is sufficient because vi.mock() in spec files
        // replaces these modules before any code runs.
        const webpackCompatStubs = {
            name: 'webpack-compat-stubs',
            resolveId(source: string) {
                if (
                    source.startsWith('bindings/') ||
                    source.startsWith('viewmodels/') ||
                    (source.startsWith('templates/') && source.endsWith('.htm'))
                ) {
                    return '\0' + source;
                }
            },
            load(id: string) {
                if (
                    id.startsWith('\0bindings/') ||
                    id.startsWith('\0viewmodels/') ||
                    (id.startsWith('\0templates/') && id.endsWith('.htm'))
                ) {
                    return 'export default {};';
                }
            },
        };

        resolve({
            plugins: [vue() as any, webpackCompatStubs],
            test: {
                alias: alias,
                coverage: {
                    // src/ (Vue) plus the public-pages KnockoutJS-era code that
                    // actually carries specs (utils/, views/pages/). Deliberately
                    // NOT all of media/js: pulling in the untested legacy tree
                    // (bindings, widgets, workflows…) would crater the ratio and
                    // trip CI's "no coverage decrease" gate for every branch.
                    include: [
                        path.join(parsedData['APP_RELATIVE_PATH'], 'src', path.sep),
                        path.join(parsedData['APP_RELATIVE_PATH'], 'media', 'js', 'utils', path.sep),
                        path.join(parsedData['APP_RELATIVE_PATH'], 'media', 'js', 'views', 'pages', path.sep),
                    ],
                    exclude: [...exclude, '**/*.spec.js'],
                    reporter: [
                        ['clover', { 'file': 'coverage.xml' }],
                        'text',
                    ],
                    reportsDirectory: path.join(filePath, 'coverage', 'frontend'),
                },
                environment: "jsdom",
                globals: true,
                exclude: exclude,
                passWithNoTests: true,
                setupFiles: ['vitest.setup.mts'],
            },
        });

    });
};

export default (async () => {
    const config = await generateConfig();
    return defineConfig(config);
})();
