const GROUP_FALLBACK = '#94a3b8';
const DATATYPE_FALLBACK = '#94a3b8';

export function groupColor(groups, id) {
    const g = (groups || []).find((x) => x.id === id);
    return (g && g.color) || GROUP_FALLBACK;
}

export function datatypeColor(datatypes, id) {
    const d = (datatypes || []).find((x) => x.id === id);
    return (d && d.color) || DATATYPE_FALLBACK;
}

export function nodeRadius(fieldCount) {
    // 18px base, +sqrt scaling, capped at 46px.
    return Math.min(46, 18 + Math.sqrt(Math.max(0, fieldCount)) * 4);
}
