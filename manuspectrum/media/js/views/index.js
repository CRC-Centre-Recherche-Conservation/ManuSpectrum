import ko from 'knockout';
import arches from 'arches';
import 'views/components/language-switcher';
import initMsNav from 'utils/ms-nav';

$(function () {
    'use strict';

    // ================================================================
    // SHARED NAV — header scroll, mobile drawer, About dropdown
    // ================================================================
    initMsNav();

    // ================================================================
    // SCROLL REVEAL (IntersectionObserver)
    // ================================================================
    if ('IntersectionObserver' in window) {
        var revealObserver = new IntersectionObserver(function (entries) {
            $.each(entries, function (_, entry) {
                if (entry.isIntersecting) {
                    $(entry.target).addClass('visible');
                }
            });
        }, { threshold: 0.06, rootMargin: '0px 0px -30px 0px' });

        $('.reveal, .reveal-scale').each(function () {
            revealObserver.observe(this);
        });
    } else {
        $('.reveal, .reveal-scale').addClass('visible');
    }

    // ================================================================
    // SEARCH FORM — URL from arches.urls
    // ================================================================
    var $searchInput = $('#ms-search-input');
    var searchUrl = arches.urls.search_home;

    function navigateToSearch(query) {
        if (query) {
            var termFilter = JSON.stringify([{
                inverted: false,
                type: 'string',
                context: '',
                context_label: '',
                id: query,
                text: query,
                value: query
            }]);
            window.location.href = searchUrl + '?paging-filter=1&term-filter=' + encodeURIComponent(termFilter);
        } else {
            window.location.href = searchUrl;
        }
    }

    $('#ms-search-form').on('submit', function (e) {
        e.preventDefault();
        navigateToSearch($searchInput.val().trim());
    });

    $('.ms-search-chip').on('click', function () {
        navigateToSearch($(this).data('term'));
    });

    // ================================================================
    // SHOWCASE CAROUSEL
    // ================================================================
    var $track = $('#ms-showcase-track');
    var $dots = $('#ms-showcase-nav .ms-showcase-dot');
    var slideCount = $track.children().length;
    var currentSlide = 0;

    function goToSlide(idx) {
        currentSlide = (idx + slideCount) % slideCount;
        $track[0].scrollTo({ left: $track[0].offsetWidth * currentSlide, behavior: 'smooth' });
        $dots.removeClass('active').eq(currentSlide).addClass('active');
    }

    $('#ms-showcase-prev').on('click', function () { goToSlide(currentSlide - 1); });
    $('#ms-showcase-next').on('click', function () { goToSlide(currentSlide + 1); });
    $dots.on('click', function () { goToSlide($(this).data('slide')); });

    // Sync dots on manual scroll
    var scrollTimer;
    $track.on('scroll', function () {
        clearTimeout(scrollTimer);
        scrollTimer = setTimeout(function () {
            var idx = Math.round($track[0].scrollLeft / $track[0].offsetWidth);
            if (idx !== currentSlide) {
                currentSlide = idx;
                $dots.removeClass('active').eq(currentSlide).addClass('active');
            }
        }, 80);
    });

    // ================================================================
    // ANALYSIS POINTS — Interactive spectral viewer
    // ================================================================
    var $analysis = $('#ms-analysis-viewer');
    var $analysisPopup = $('#ms-analysis-popup');

    if ($analysis.length) {
        var t = arches.translations;
        var analysisData = [
            {
                technique: 'XRF', id: 'P-01', color: '#3b82f6',
                material: t.analysisLapisLazuli, layer: t.analysisPigment, range: '1 – 40 keV',
                elements: [{ s: 'Cu', p: true }, { s: 'S', p: true }, { s: 'Ca', p: false }, { s: 'Si', p: false }, { s: 'Fe', p: false }],
                spectrum: 'M0,42 8,41 18,39 25,34 30,38 38,36 45,10 50,32 55,38 62,35 70,39 80,18 88,36 95,34 105,38 115,40 130,39 150,40 175,39 200,40 232,41'
            },
            {
                technique: 'Raman', id: 'P-02', color: '#dc3545',
                material: t.analysisVermilion, layer: t.analysisPaint, range: '100 – 3000 cm⁻¹',
                elements: [{ s: 'Hg', p: true }, { s: 'S', p: true }, { s: 'Pb', p: false }],
                spectrum: 'M0,40 15,39 30,40 42,38 47,6 51,38 60,40 75,39 85,40 91,24 96,40 110,39 125,40 140,39 165,30 172,39 195,40 220,39 232,40'
            },
            {
                technique: 'FORS', id: 'P-03', color: '#10b981',
                material: t.analysisGoldLeaf, layer: t.analysisGilding, range: '350 – 2500 nm',
                elements: [{ s: 'Au', p: true }, { s: 'Ag', p: false }, { s: 'Cu', p: false }],
                spectrum: 'M0,40 20,39 40,38 60,34 80,26 100,16 120,10 140,8 160,10 180,13 200,15 220,16 232,17'
            },
            {
                technique: 'XRF', id: 'P-04', color: '#8b5cf6',
                material: t.analysisIronGallInk, layer: t.analysisText, range: '1 – 40 keV',
                elements: [{ s: 'Fe', p: true }, { s: 'Zn', p: false }, { s: 'Cu', p: false }, { s: 'K', p: false }],
                spectrum: 'M0,40 12,39 22,38 30,34 38,10 43,34 52,38 62,36 70,20 76,35 85,38 100,39 120,38 140,39 160,26 168,38 185,39 210,40 232,40'
            }
        ];

        var activePointIdx = null;

        function buildPopupHTML(d) {
            var elems = '';
            for (var i = 0; i < d.elements.length; i++) {
                var e = d.elements[i];
                elems += '<span class="ms-popup-element' + (e.p ? ' ms-popup-element--primary' : '') + '">' + e.s + '</span>';
            }
            return '<div class="ms-popup-header">' +
                '<span class="ms-popup-technique" style="color:' + d.color + ';background:' + d.color + '14">' + d.technique + '</span>' +
                '<span class="ms-popup-id">' + d.id + '</span></div>' +
                '<div class="ms-popup-spectrum"><svg viewBox="0 0 232 46" preserveAspectRatio="none">' +
                '<path d="' + d.spectrum + ' L232,44 0,44Z" fill="' + d.color + '" opacity="0.12"/>' +
                '<path d="' + d.spectrum + '" fill="none" stroke="' + d.color + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
                '</svg></div>' +
                '<div class="ms-popup-data">' +
                '<div class="ms-popup-row"><span class="ms-popup-label">' + t.analysisMaterial + '</span><span class="ms-popup-value">' + d.material + '</span></div>' +
                '<div class="ms-popup-row"><span class="ms-popup-label">' + t.analysisLayer + '</span><span class="ms-popup-value">' + d.layer + '</span></div>' +
                '<div class="ms-popup-row"><span class="ms-popup-label">' + t.analysisRange + '</span><span class="ms-popup-value">' + d.range + '</span></div>' +
                '</div><div class="ms-popup-elements">' + elems + '</div>';
        }

        function openAnalysisPopup($btn, idx) {
            var d = analysisData[idx];
            $analysisPopup.html(buildPopupHTML(d));

            var box = $analysis[0].getBoundingClientRect();
            var pt = $btn[0].getBoundingClientRect();
            var popupW = 260;
            var popupH = 210;
            var l = pt.left - box.left + pt.width / 2 - popupW / 2;
            var t = pt.bottom - box.top + 8;

            // Clamp horizontal
            if (l < 4) l = 4;
            if (l + popupW > box.width - 4) l = box.width - popupW - 4;

            // If no room below, show above — but never go above 0
            if (t + popupH > box.height) t = pt.top - box.top - popupH - 8;
            if (t < 4) t = 4;

            $analysisPopup.css({ left: l, top: t });
            $analysis.addClass('has-popup');
            requestAnimationFrame(function () {
                $analysisPopup.addClass('active');
            });
        }

        function closeAnalysisPopup() {
            $analysisPopup.removeClass('active');
            $analysis.removeClass('has-popup');
            $('.ms-analysis-point').removeClass('active');
            activePointIdx = null;
        }

        $analysis.on('click', '.ms-analysis-point', function (e) {
            e.stopPropagation();
            var idx = parseInt($(this).data('point'), 10);
            if (activePointIdx === idx) { closeAnalysisPopup(); return; }
            $('.ms-analysis-point').removeClass('active');
            $(this).addClass('active');
            activePointIdx = idx;
            openAnalysisPopup($(this), idx);
        });

        $(document).on('click', function (e) {
            if (activePointIdx !== null && !$(e.target).closest('.ms-analysis-popup, .ms-analysis-point').length) {
                closeAnalysisPopup();
            }
        });
    }

    // ================================================================
    // XRF COMPARISON — clip-path reveal on hover
    // ================================================================
    var $compare = $('#ms-xrf-compare');
    if ($compare.length) {
        var topImg = $compare.find('.ms-compare-top')[0];

        $compare.on('mouseenter', function () {
            $(this).addClass('is-comparing');
        });

        $compare.on('mousemove', function (e) {
            var rect = this.getBoundingClientRect();
            var x = ((e.clientX - rect.left) / rect.width) * 100;
            topImg.style.clipPath = 'inset(0 ' + (100 - x) + '% 0 0)';
        });

        $compare.on('mouseleave', function () {
            $(this).removeClass('is-comparing');
            topImg.style.clipPath = 'inset(0 0 0 0)';
        });
    }

    // ================================================================
    // INTERACTIVE LOGO — Plotly-style crosshair & tooltip
    // ================================================================
    var svg = document.getElementById('ms-logo-svg');
    if (!svg) return;

    var curveBlue = document.getElementById('curve-blue');
    var curveRed = document.getElementById('curve-red');
    var $crosshair = $('#ms-logo-crosshair');
    var $tooltip = $('#ms-logo-tooltip');
    var crossV = document.getElementById('ms-cross-v');
    var crossHB = document.getElementById('ms-cross-h-blue');
    var crossHR = document.getElementById('ms-cross-h-red');
    var dotBlue = document.getElementById('ms-dot-blue');
    var dotRed = document.getElementById('ms-dot-red');
    var ttBg = document.getElementById('ms-tt-bg');
    var ttWl = document.getElementById('ms-tt-wl');
    var ttBlue = document.getElementById('ms-tt-blue');
    var ttRedTxt = document.getElementById('ms-tt-red');

    var xMin = 40, xMax = 620, yMin = 4, yMax = 82;
    var wlMin = 380, wlMax = 780;

    function svgPoint(e) {
        var pt = svg.createSVGPoint();
        pt.x = e.clientX; pt.y = e.clientY;
        return pt.matrixTransform(svg.getScreenCTM().inverse());
    }

    function sampleY(path, targetX) {
        var len = path.getTotalLength();
        var lo = 0, hi = len, mid, pt, iter = 0;
        while (hi - lo > 0.5 && iter < 50) {
            mid = (lo + hi) / 2;
            pt = path.getPointAtLength(mid);
            if (pt.x < targetX) lo = mid; else hi = mid;
            iter++;
        }
        return path.getPointAtLength((lo + hi) / 2).y;
    }

    function toIntensity(y) {
        return Math.max(0, Math.min(1, (yMax - y) / (yMax - yMin)));
    }

    function toWavelength(x) {
        return wlMin + (x - xMin) / (xMax - xMin) * (wlMax - wlMin);
    }

    function setAttr(el, attrs) {
        for (var k in attrs) { el.setAttribute(k, attrs[k]); }
    }

    function onMove(e) {
        var p = svgPoint(e);
        var x = p.x;
        if (x < xMin || x > xMax) { onLeave(); return; }

        $crosshair.show();
        $tooltip.show();

        setAttr(crossV, { x1: x, x2: x });

        var yB = sampleY(curveBlue, x);
        var yR = sampleY(curveRed, x);
        var wl = toWavelength(x);

        var showBlue = x <= 438;
        var showRed = x <= 444;

        setAttr(dotBlue, { cx: x, cy: yB, opacity: showBlue ? '0.9' : '0' });
        setAttr(crossHB, { y1: yB, y2: yB, x2: x, opacity: showBlue ? '0.35' : '0' });

        setAttr(dotRed, { cx: x, cy: yR, opacity: showRed ? '0.9' : '0' });
        setAttr(crossHR, { y1: yR, y2: yR, x2: x, opacity: showRed ? '0.35' : '0' });

        var tx = x + 8;
        var ty = Math.min(yB, yR) - 48;
        if (tx + 125 > xMax) tx = x - 130;
        if (ty < 0) ty = 4;

        setAttr(ttBg, { x: tx, y: ty });
        setAttr(ttWl, { x: tx + 6, y: ty + 12 });
        ttWl.textContent = '\u03BB = ' + Math.round(wl) + ' nm';

        setAttr(ttBlue, { x: tx + 6, y: ty + 24 });
        ttBlue.textContent = showBlue ? ('\u25CF I\u2081 = ' + toIntensity(yB).toFixed(3)) : '';

        setAttr(ttRedTxt, { x: tx + 6, y: ty + 35 });
        ttRedTxt.textContent = showRed ? ('\u25CF I\u2082 = ' + toIntensity(yR).toFixed(3)) : '';
    }

    function onLeave() {
        $crosshair.hide();
        $tooltip.hide();
    }

    var $svg = $(svg);
    $svg.on('mousemove', onMove).on('mouseleave', onLeave);
    svg.addEventListener('touchmove', function (e) { e.preventDefault(); onMove(e.touches[0]); }, { passive: false });
    svg.addEventListener('touchend', onLeave);

    // --- Zoom / fullscreen ---
    var $overlay = $('#ms-logo-overlay');
    var $wrap = $('#ms-logo-wrap');
    var $target = $('#ms-logo-zoom-target');

    function openZoom() {
        $target.append(svg);
        $overlay.addClass('active');
        $('body').css('overflow', 'hidden');
    }

    function closeZoom() {
        $overlay.removeClass('active');
        $('body').css('overflow', '');
        $wrap.prepend(svg);
    }

    $('#ms-logo-zoom').on('click', function (e) {
        e.stopPropagation();
        openZoom();
    });

    $('#ms-logo-close').on('click', closeZoom);

    $overlay.on('click', function (e) {
        if (e.target === this) closeZoom();
    });

    $(document).on('keydown', function (e) {
        if (e.key === 'Escape' && $overlay.hasClass('active')) closeZoom();
    });

    // ================================================================
    // KNOCKOUT — Apply bindings for language-switcher
    // ================================================================
    ko.applyBindings({});
});
