/* eslint-disable */

/**
 * Project additions to the Arches webpack configuration, merged over
 * webpack/webpack.config.{dev,prod}.js by `webpack --merge` (package.json
 * scripts). `manage.py updateproject` deletes and recreates webpack/ at each
 * Arches upgrade; this file lives outside it and keeps applying.
 *
 * - Plotly is one async chunk of its own (`chunks/plotly.<hash>.js`), shared
 *   by the Knockout binding, the model graph page and the Analysis Explorer.
 *   Without this group, the `vendors` group of webpack.common.js (enforced on
 *   every chunk) moves it into a node_modules chunk shared with other modules.
 * - CSS is minified whenever JS is (`optimization.minimize`: production).
 *   The production configuration sets no minimizer and relies on webpack's
 *   built-in JavaScript one, which any `minimizer` list replaces: the `'...'`
 *   token keeps it, in front of the CSS minimizer. Each stylesheet
 *   entry of webpack/webpack-utils/build-filepath-lookup.js also emits its
 *   JavaScript stub under a .css name in `css/css/`; those are left alone.
 */
const CssMinimizerPlugin = require('css-minimizer-webpack-plugin');

module.exports = {
    optimization: {
        minimizer: ['...', new CssMinimizerPlugin({ exclude: /^css\/css\// })],
        splitChunks: {
            cacheGroups: {
                plotly: {
                    test: /[\\/]node_modules[\\/]plotly\.js-cartesian-dist[\\/]/,
                    name: 'plotly',
                    chunks: 'async',
                    enforce: true,
                    priority: 10,
                },
            },
        },
    },
};
