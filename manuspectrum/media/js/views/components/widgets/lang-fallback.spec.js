// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import ko from 'knockout';
import '../../../utils/lang-fallback.js';

const TEMPLATES = path.resolve(globalThis.process.cwd(), 'manuspectrum/templates');

function inline(source) {
    return source.replace(/\{%\s*include\s+"([^"]+)"\s*%\}/g, (_m, p) =>
        inline(fs.readFileSync(path.join(TEMPLATES, p), 'utf8')),
    );
}

function renderBlock(templatePath, blockName) {
    const source = fs.readFileSync(path.join(TEMPLATES, templatePath), 'utf8');
    const start = source.indexOf(`{% block ${blockName} %}`);
    const end = source.indexOf(`{% endblock ${blockName} %}`);
    if (start < 0 || end < 0) throw new Error(`block ${blockName} not found`);
    let html = inline(source.slice(start + `{% block ${blockName} %}`.length, end));
    const titles = {};
    html = html.replace(/\{%\s*trans\s+"([^"]*)"\s+as\s+(\w+)\s*%\}/g, (_m, s, v) => {
        titles[v] = s;
        return '';
    });
    html = html.replace(/\{\{\s*(\w+)\|escapejs\s*\}\}/g, (_m, v) => titles[v]);
    html = html.replace(/\{%\s*load[^%]*%\}/g, '');
    if (html.includes('{%') || html.includes('{{')) throw new Error('template tag left: ' + html);
    return html;
}

function makeVm(values, over = {}) {
    return {
        displayValue: ko.observable(values),
        currentLanguage: ko.observable('en'),
        languages: ko.observableArray([{ code: 'en' }, { code: 'fr' }]),
        hideEmptyNodes: false,
        label: ko.observable('Title'),
        nodeCssClasses: '',
        displayfullvalue: false,
        translations: { none: 'None', richText: 'rich text' },
        ...over,
    };
}

function mount(html, vm) {
    globalThis.ko = ko;
    const div = document.createElement('div');
    div.innerHTML = `<dl>${html}</dl>`;
    document.body.appendChild(div);
    ko.applyBindings(vm, div);
    return div;
}

const report = renderBlock('views/components/widgets/text.htm', 'report');
const displayValue = renderBlock('views/components/widgets/text.htm', 'display_value');

const text = (el) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll('.sr-only').forEach((node) => node.remove());
    return copy.textContent.replace(/\s+/g, ' ').trim();
};
let mounted;
const show = (html, values, over) => {
    mounted = mount(html, makeVm(values, over));
    return mounted;
};
afterEach(() => {
    if (mounted) {
        ko.cleanNode(mounted);
        mounted.remove();
        mounted = null;
    }
});

describe('text.htm report block', () => {
    it('report shows the French text marked FR on an English page', () => {
        const div = show(report, {
            en: { value: '' },
            fr: { value: 'Lettrine' },
        });
        const dd = div.querySelector('dd');
        expect(text(dd)).toBe('Lettrine FR');
        expect(dd.querySelector('span').getAttribute('lang')).toBe('fr');
        const abbr = dd.querySelector('abbr.ms-lang-fallback');
        expect(abbr.getAttribute('title')).toBe('Not entered in this language, shown in French');
    });

    it('report shows the page language without marker', () => {
        const div = show(report, {
            en: { value: 'Initial' },
            fr: { value: 'Lettrine' },
        });
        expect(text(div.querySelector('dd'))).toBe('Initial');
        expect(div.querySelector('abbr')).toBeNull();
        expect(div.querySelector('dd span').hasAttribute('lang')).toBe(false);
    });

    it('a blank page value is treated as empty', () => {
        const div = show(report, {
            en: { value: '  ' },
            fr: { value: 'Lettrine' },
        });
        expect(text(div.querySelector('dd'))).toBe('Lettrine FR');
    });

    it('no language filled gives None', () => {
        const div = show(report, { en: { value: '' }, fr: { value: ' ' } });
        expect(text(div.querySelector('dd'))).toBe('None');
        expect(div.querySelector('abbr')).toBeNull();
    });

    it('hidden empty nodes reappear when another language is filled', () => {
        let div = show(
            report,
            { en: { value: '' }, fr: { value: 'Lettrine' } },
            { hideEmptyNodes: true },
        );
        expect(div.querySelector('dt')).not.toBeNull();
        expect(div.querySelector('dd')).not.toBeNull();
        ko.cleanNode(div);
        div.remove();
        div = show(report, { en: { value: '' }, fr: { value: '' } }, { hideEmptyNodes: true });
        expect(div.querySelector('dt')).toBeNull();
    });

    it('follows a live edit of an inner observable', () => {
        const en = ko.observable('');
        const div = show(report, {
            en: { value: en },
            fr: { value: ko.observable('Lettrine') },
        });
        expect(text(div.querySelector('dd'))).toBe('Lettrine FR');
        en('Initial');
        expect(text(div.querySelector('dd'))).toBe('Initial');
        expect(div.querySelector('abbr')).toBeNull();
    });

    it('languages are tried in their order', () => {
        const languages = ko.observableArray([{ code: 'en' }, { code: 'fr' }, { code: 'de' }]);
        let div = show(report, { fr: { value: '' }, de: { value: 'Initiale' } }, { languages });
        expect(text(div.querySelector('dd'))).toBe('Initiale DE');
        ko.cleanNode(div);
        div.remove();
        div = show(report, { fr: { value: 'Lettrine' }, de: { value: 'Initiale' } }, { languages });
        expect(text(div.querySelector('dd'))).toBe('Lettrine FR');
    });

    it('no languages yet means page language only', () => {
        const languages = ko.observableArray([]);
        const div = show(report, { fr: { value: 'Lettrine' } }, { languages });
        expect(text(div.querySelector('dd'))).toBe('None');
        languages([{ code: 'en' }, { code: 'fr' }]);
        expect(text(div.querySelector('dd'))).toBe('Lettrine FR');
    });

    it('null, undefined or a plain string value gives None', () => {
        for (const value of [null, undefined, 'plain']) {
            const div = show(report, value);
            expect(text(div.querySelector('dd'))).toBe('None');
            ko.cleanNode(div);
            div.remove();
        }
    });

    it('a French page shows the English text marked EN', () => {
        const div = show(
            report,
            { en: { value: 'Initial' }, fr: { value: '' } },
            { currentLanguage: ko.observable('fr') },
        );
        expect(text(div.querySelector('dd'))).toBe('Initial EN');
        expect(div.querySelector('abbr').getAttribute('title').endsWith('anglais')).toBe(true);
    });
});

describe('text.htm display_value block', () => {
    it('display_value shows the fallback with its marker', () => {
        let div = show(displayValue, {
            en: { value: '' },
            fr: { value: 'Lettrine' },
        });
        expect(text(div)).toBe('Lettrine FR');
        ko.cleanNode(div);
        div.remove();
        div = show(displayValue, { en: { value: '' }, fr: { value: '' } });
        expect(text(div)).toBe('None');
    });
});

const precedes = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

const richReport = renderBlock('views/components/widgets/rich-text.htm', 'report');
const richDisplay = renderBlock('views/components/widgets/rich-text.htm', 'display_value');

describe('rich-text.htm blocks', () => {
    it('rich text report renders the French HTML marked FR', () => {
        const div = show(richReport, { en: { value: '' }, fr: { value: '<p>Lettrine</p>' } });
        const dd = div.querySelector('dd');
        expect(dd.querySelector('p').textContent).toBe('Lettrine');
        expect(dd.querySelector('div:not(.ms-lang-fallback-line)').getAttribute('lang')).toBe('fr');
        const abbr = dd.querySelector('abbr.ms-lang-fallback');
        expect(abbr.textContent).toBe('FR');
        expect(precedes(abbr, dd.querySelector('p'))).toBe(true);
    });

    it('rich text report without marker on the page language and None when empty', () => {
        let div = show(richReport, { en: { value: '<p>Initial</p>' }, fr: { value: '<p>L</p>' } });
        expect(div.querySelector('abbr')).toBeNull();
        expect(div.querySelector('dd div').hasAttribute('lang')).toBe(false);
        ko.cleanNode(div);
        div.remove();
        div = show(richReport, { en: { value: '' }, fr: { value: '' } }, { hideEmptyNodes: true });
        expect(div.querySelector('dt')).toBeNull();
    });

    it('short display value marks the fallback', () => {
        let div = show(richDisplay, { en: { value: '' }, fr: { value: '<p>Lettrine</p>' } });
        expect(text(div)).toBe('[rich text] FR');
        ko.cleanNode(div);
        div.remove();
        div = show(richDisplay, { en: { value: '<p>I</p>' }, fr: { value: '<p>L</p>' } });
        expect(text(div)).toBe('[rich text]');
        expect(div.querySelector('abbr')).toBeNull();
        ko.cleanNode(div);
        div.remove();
        div = show(richDisplay, { en: { value: '' }, fr: { value: '' } });
        expect(text(div)).toBe('None');
    });

    it('full display value renders the fallback HTML', () => {
        for (const displayfullvalue of [true, ko.observable(true)]) {
            const div = show(
                richDisplay,
                { en: { value: '' }, fr: { value: '<p>Lettrine</p>' } },
                { displayfullvalue },
            );
            expect(div.querySelector('p').textContent).toBe('Lettrine');
            const abbr = div.querySelector('abbr');
            expect(abbr.textContent).toBe('FR');
            expect(precedes(abbr, div.querySelector('p'))).toBe(true);
            ko.cleanNode(div);
            div.remove();
        }
    });
});

describe('marker and viewmodel names', () => {
    it('the marker hides the abbreviation from readers and spells the explanation out', () => {
        const div = show(report, { en: { value: '' }, fr: { value: 'Lettrine' } });
        expect(div.querySelector('abbr').getAttribute('aria-hidden')).toBe('true');
        expect(div.querySelector('.sr-only').textContent).toBe(
            'Not entered in this language, shown in French',
        );
    });

    it('a viewmodel without languages shows the page language only and does not throw', () => {
        const vm = makeVm({ en: { value: '' }, fr: { value: 'Lettrine' } });
        delete vm.languages;
        const div = mount(report, vm);
        mounted = div;
        expect(text(div.querySelector('dd'))).toBe('None');
    });
});
