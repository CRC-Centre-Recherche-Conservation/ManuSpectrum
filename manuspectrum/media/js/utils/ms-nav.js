// Shared nav behaviour for the homepage + About pages:
// glass-scroll header, mobile drawer, and the About dropdown (hover + click + keyboard).
export default function initMsNav() {
    const header = document.getElementById('ms-header');
    if (header) {
        const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 80);
        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    }

    // Mobile drawer
    const hamburger = document.getElementById('ms-hamburger');
    const mobileNav = document.getElementById('ms-mobile-nav');
    if (hamburger && mobileNav) {
        const setDrawer = (open) => {
            mobileNav.classList.toggle('open', open);
            hamburger.classList.toggle('active', open);
            // The hamburger is a disclosure button: its expanded state has to be
            // exposed, otherwise screen readers announce it as a plain button.
            hamburger.setAttribute('aria-expanded', String(open));
            document.body.style.overflow = open ? 'hidden' : '';
        };
        hamburger.addEventListener('click', () => setDrawer(!mobileNav.classList.contains('open')));
        mobileNav.querySelectorAll('a').forEach((a) => a.addEventListener('click', () => setDrawer(false)));
        const mToggle = mobileNav.querySelector('.ms-mobile-nav-group-toggle');
        const mGroup = document.getElementById('ms-mobile-about');
        if (mToggle && mGroup) {
            mToggle.addEventListener('click', () => {
                const open = mGroup.classList.toggle('open');
                mToggle.setAttribute('aria-expanded', String(open));
            });
        }
    }

    // Desktop About dropdown
    const dd = document.getElementById('ms-about-dropdown');
    if (dd) {
        const toggle = dd.querySelector('.ms-nav-dropdown-toggle');
        const menu = dd.querySelector('.ms-nav-dropdown-menu');
        const setOpen = (open) => {
            dd.classList.toggle('open', open);
            toggle.setAttribute('aria-expanded', String(open));
        };
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            setOpen(!dd.classList.contains('open'));
        });

        // Hover-to-open is a pointer affordance only. On touch, the emulated
        // `mouseenter` fires first and opens the panel, then the `click` above
        // toggles it straight back shut — a tap appeared to do nothing.
        const hoverCapable = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
        if (hoverCapable) {
            dd.addEventListener('mouseenter', () => setOpen(true));
            dd.addEventListener('mouseleave', () => {
                // Don't yank the panel out from under a keyboard user whose focus
                // is still inside it just because the pointer drifted away.
                if (!dd.contains(document.activeElement)) setOpen(false);
            });
        }

        document.addEventListener('click', (e) => {
            if (!dd.contains(e.target)) setOpen(false);
        });
        dd.addEventListener('focusout', () => {
            // Fires before focus lands; defer so document.activeElement is current.
            setTimeout(() => {
                if (!dd.contains(document.activeElement)) setOpen(false);
            }, 0);
        });
        dd.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { setOpen(false); toggle.focus(); }
        });
        // Arrow-key navigation across the links (a convenience on top of Tab —
        // this is a disclosure of plain links, not a role="menu" widget).
        const items = Array.from(menu.querySelectorAll('a'));
        menu.addEventListener('keydown', (e) => {
            const i = items.indexOf(document.activeElement);
            if (e.key === 'ArrowDown') { e.preventDefault(); (items[i + 1] || items[0]).focus(); }
            if (e.key === 'ArrowUp') { e.preventDefault(); (items[i - 1] || items[items.length - 1]).focus(); }
        });
    }
}
