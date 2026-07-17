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
        hamburger.addEventListener('click', () => {
            const open = mobileNav.classList.toggle('open');
            hamburger.classList.toggle('active', open);
            document.body.style.overflow = open ? 'hidden' : '';
        });
        mobileNav.querySelectorAll('a').forEach((a) =>
            a.addEventListener('click', () => {
                hamburger.classList.remove('active');
                mobileNav.classList.remove('open');
                document.body.style.overflow = '';
            }),
        );
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
        dd.addEventListener('mouseenter', () => setOpen(true));
        dd.addEventListener('mouseleave', () => setOpen(false));
        document.addEventListener('click', (e) => {
            if (!dd.contains(e.target)) setOpen(false);
        });
        dd.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { setOpen(false); toggle.focus(); }
        });
        // Arrow-key navigation across menu items
        const items = Array.from(menu.querySelectorAll('[role="menuitem"]'));
        menu.addEventListener('keydown', (e) => {
            const i = items.indexOf(document.activeElement);
            if (e.key === 'ArrowDown') { e.preventDefault(); (items[i + 1] || items[0]).focus(); }
            if (e.key === 'ArrowUp') { e.preventDefault(); (items[i - 1] || items[items.length - 1]).focus(); }
        });
    }
}
