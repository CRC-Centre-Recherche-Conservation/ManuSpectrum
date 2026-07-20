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
    // Kept for callers that size by field count; the Graph Explorer now sizes by
    // published records instead (see instanceRadius / WAVE 3 item 3).
    return Math.min(46, 18 + Math.sqrt(Math.max(0, fieldCount)) * 4);
}

// WAVE 3 item 3 — node radius used to encode `counts.nodes` (22–62 fields), which
// maps to 36.8–46px: a 9px spread across the whole dataset, with 8 of 12 models
// visually identical. `instances` (published records) spans 0–80, so a sqrt-area
// scale over that range gives a channel you can actually read: 0 → 18px (and the
// caller draws those with a dashed "no records yet" ring), 80 → ~55px.
export function instanceRadius(instances) {
    return Math.min(56, 18 + Math.sqrt(Math.max(0, Number(instances) || 0)) * 4.2);
}

// --- contrast helpers --------------------------------------------------------
// The group hues arrive from the API (DB-authored) and are tuned as a decorative
// spectrum, not for legibility: as strokes on the white stage, green #10b981 is
// 2.54:1 and orange #e67e22 is 2.85:1, both below the 3:1 WCAG 1.4.11 floor for
// graphical objects. Rather than hardcode a parallel palette keyed by group id,
// derive a safe variant from whatever the payload sends.

function parseHex(hex) {
    const s = String(hex || '').trim();
    const m3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s);
    if (m3) return [parseInt(m3[1] + m3[1], 16), parseInt(m3[2] + m3[2], 16), parseInt(m3[3] + m3[3], 16)];
    const m6 = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(s);
    if (m6) return [parseInt(m6[1], 16), parseInt(m6[2], 16), parseInt(m6[3], 16)];
    return null;
}

const toHex = (rgb) => `#${rgb.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')}`;

function channelLum(v) {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex) {
    const rgb = parseHex(hex);
    if (!rgb) return 0;
    return 0.2126 * channelLum(rgb[0]) + 0.7152 * channelLum(rgb[1]) + 0.0722 * channelLum(rgb[2]);
}

// Contrast of `hex` against white (#fff), the stage/paper background.
export function contrastVsWhite(hex) {
    return 1.05 / (relativeLuminance(hex) + 0.05);
}

// Darken `hex` (preserving hue) until it clears `min`:1 against white. Used for
// edge strokes, matrix cell borders and any other thin graphical mark.
export function contrastSafeStroke(hex, min = 3) {
    const rgb = parseHex(hex);
    if (!rgb) return hex;
    if (contrastVsWhite(hex) >= min) return toHex(rgb);
    for (let f = 0.95; f >= 0.1; f -= 0.05) {
        const candidate = toHex(rgb.map((v) => v * f));
        if (contrastVsWhite(candidate) >= min) return candidate;
    }
    return '#1a1a2e';
}

// Blend `hex` toward white by `pct` (0–100 = share of the hue kept). The SCSS
// side does this with color-mix(); Plotly and inline SVG fills need a real value.
export function mixWhite(hex, pct) {
    const rgb = parseHex(hex);
    if (!rgb) return hex;
    const k = Math.max(0, Math.min(100, pct)) / 100;
    return toHex(rgb.map((v) => v * k + 255 * (1 - k)));
}
