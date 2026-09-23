import initMsNav from 'utils/ms-nav';
import revealOnScroll from 'utils/reveal-on-scroll';
import initHomepageSearch from '../utils/homepage/homepage-search';
import initShowcaseCarousel from '../utils/homepage/showcase-carousel';
import initXrfCompare from '../utils/homepage/xrf-compare';
import initAnalysisViewer from '../utils/homepage/analysis-viewer';
import initSpectralLogo from '../utils/homepage/spectral-logo';

$(function () {
    'use strict';

    // ================================================================
    // SHARED NAV — header scroll, mobile drawer, About dropdown
    // ================================================================
    initMsNav();

    // ================================================================
    // SCROLL REVEAL
    // ================================================================
    revealOnScroll(0.06, { selector: '.reveal, .reveal-scale', rootMargin: '0px 0px -30px 0px' });

    // ================================================================
    // SEARCH FORM — URL from arches.urls
    // ================================================================
    initHomepageSearch(document);

    // ================================================================
    // SHOWCASE CAROUSEL
    // ================================================================
    initShowcaseCarousel(document);

    // ================================================================
    // ANALYSIS POINTS — Interactive spectral viewer
    // ================================================================
    initAnalysisViewer(document);

    // ================================================================
    // XRF COMPARISON
    // ================================================================
    initXrfCompare(document);

    // ================================================================
    // INTERACTIVE LOGO — crosshair, tooltip and zoom dialog
    // ================================================================
    initSpectralLogo(document);
});
