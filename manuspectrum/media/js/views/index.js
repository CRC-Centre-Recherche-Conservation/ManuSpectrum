import initMsNav from 'utils/ms-nav';
import revealOnScroll from 'utils/reveal-on-scroll';
import initHomepageSearch from '../utils/homepage/homepage-search';
import initShowcaseCarousel from '../utils/homepage/showcase-carousel';
import initXrfCompare from '../utils/homepage/xrf-compare';
import initAnalysisViewer from '../utils/homepage/analysis-viewer';
import initSpectralLogo from '../utils/homepage/spectral-logo';

const BLOCKS = [initHomepageSearch, initShowcaseCarousel, initXrfCompare, initAnalysisViewer, initSpectralLogo];

/**
 * Homepage entry, loaded with `defer`: the document is parsed when it runs.
 * Starts the shared nav and the reveal, then each interactive block; a block
 * that throws is logged and does not stop the others.
 *
 * @param {Array<(root: ParentNode) => unknown>} [blocks]
 */
export function initHomepage(blocks = BLOCKS) {
    initMsNav();
    revealOnScroll(0.06, { selector: '.reveal, .reveal-scale', rootMargin: '0px 0px -30px 0px' });
    blocks.forEach((init) => {
        try {
            init(document);
        } catch (error) {
            console.error('A homepage block failed to start', error);
        }
    });
}

initHomepage();
