import ko from 'knockout';
import arches from 'arches';
import 'views/components/language-switcher';

$(function () {
    'use strict';

    var $header = $('#ms-header');
    var $hamburger = $('#ms-hamburger');
    var $mobileNav = $('#ms-mobile-nav');

    // ================================================================
    // HEADER — Glass-like scroll behavior
    // ================================================================
    $(window).on('scroll', function () {
        $header.toggleClass('scrolled', window.scrollY > 80);
    }).trigger('scroll');

    // ================================================================
    // MOBILE NAV
    // ================================================================
    $hamburger.on('click', function () {
        $hamburger.toggleClass('active');
        $mobileNav.toggleClass('open');
        $('body').css('overflow', $mobileNav.hasClass('open') ? 'hidden' : '');
    });

    $mobileNav.on('click', 'a', function () {
        $hamburger.removeClass('active');
        $mobileNav.removeClass('open');
        $('body').css('overflow', '');
    });

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
