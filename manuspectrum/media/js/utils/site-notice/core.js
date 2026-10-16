/*
 * Site notice: decisions of the announcement banner, with no DOM access.
 * `banner.js` renders what these functions decide. Served as a native ES
 * module (no webpack), so this file imports nothing.
 *
 * Times are epoch milliseconds. The payload comes from `GET /api/site-notice`
 * (`views/site_notice.py`): reminders are seconds before the start, largest
 * first.
 */

export const STORAGE_KEY = "ms-site-notice-dismissed-v2";

const LOCALES = { fr: "fr-FR", en: "en-GB" };

export function pickLanguage(htmlLang) {
    return String(htmlLang || "")
        .toLowerCase()
        .startsWith("fr")
        ? "fr"
        : "en";
}

/**
 * The announcement to show, walking them in start order: a live event not
 * closed wins (a long notice in progress wins over a later maintenance
 * window), else the first one shown that is not dismissed. `dismissed` maps a
 * notice id to the key stored when it was closed. Null when none.
 */
export function pickNotice(notices, now, dismissed = {}) {
    const candidates = (Array.isArray(notices) ? notices : [])
        .filter((notice) => Date.parse(notice.end) > now)
        .sort((a, b) => Date.parse(a.start) - Date.parse(b.start))
        .map((notice) => ({ notice, stage: stageOf(notice, now) }))
        .filter(({ notice, stage }) =>
            shouldShow(stage, dismissed[notice.id], dismissKey(notice, stage)),
        );
    const live = candidates.find(({ stage }) => stage.phase === "live");
    const picked = live || candidates[0];
    return picked ? picked.notice : null;
}

/**
 * `phase` is hidden | upcoming | live | shown | over; `reminder` (seconds)
 * only when upcoming. A notice displayed `once` is `shown` from its start to
 * its end, with no reminder stages.
 */
export function stageOf(notice, now) {
    const start = Date.parse(notice.start);
    const end = Date.parse(notice.end);
    if (now >= end) return { phase: "over", reminder: null };
    if (notice.display === "once") {
        return now >= start
            ? { phase: "shown", reminder: null }
            : { phase: "hidden", reminder: null };
    }
    if (now >= start) return { phase: "live", reminder: null };
    const fired = (notice.reminders || []).filter(
        (seconds) => now >= start - seconds * 1000,
    );
    if (!fired.length) return { phase: "hidden", reminder: null };
    return { phase: "upcoming", reminder: Math.min(...fired) };
}

export function dismissKey(notice, stage) {
    return `${notice.id}:${notice.version}:${stage.reminder}`;
}

export function shouldShow(stage, storedKey, key) {
    if (["live", "upcoming", "shown"].includes(stage.phase))
        return storedKey !== key;
    return false;
}

/** Milliseconds to add to the client clock to get the server clock. */
export function serverSkew(dateHeader, clientNow) {
    const server = Date.parse(dateHeader);
    return Number.isNaN(server) ? 0 : server - clientNow;
}

function dayKey(ms, timeZone) {
    return new Intl.DateTimeFormat("en-CA", { timeZone }).format(ms);
}

export function formatWhen(notice, stage, lang, timeZone, labels) {
    const locale = LOCALES[lang] || LOCALES.en;
    const start = Date.parse(notice.start);
    const end = Date.parse(notice.end);
    const full = new Intl.DateTimeFormat(locale, {
        weekday: "long",
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
        timeZone,
    });
    if (stage.phase === "live") {
        const sameDay = dayKey(start, timeZone) === dayKey(end, timeZone);
        const when = sameDay
            ? new Intl.DateTimeFormat(locale, {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone,
              }).format(end)
            : full.format(end);
        return String(labels.until || "").replace("{time}", when);
    }
    if (typeof full.formatRange === "function") {
        try {
            return full.formatRange(start, end);
        } catch {
            // Fall through to the two-sided form.
        }
    }
    return `${full.format(start)} – ${full.format(end)}`;
}

export function readStorage(key) {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

/** The `{id: dismissKey}` map; empty when absent, unreadable or malformed. */
export function readDismissed() {
    try {
        const parsed = JSON.parse(readStorage(STORAGE_KEY) || "{}");
        return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? parsed
            : {};
    } catch {
        return {};
    }
}

/** Records one dismissal, keeping only the ids still in the payload. */
export function rememberDismissal(id, key, presentIds) {
    const kept = {};
    const current = readDismissed();
    for (const present of presentIds) {
        if (present in current) kept[present] = current[present];
    }
    kept[id] = key;
    return writeStorage(STORAGE_KEY, JSON.stringify(kept));
}

export function writeStorage(key, value) {
    try {
        window.localStorage.setItem(key, value);
        return true;
    } catch {
        return false;
    }
}

/** Safe link target: http(s) only. */
export function safeHref(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === "https:" || parsed.protocol === "http:"
            ? parsed.href
            : null;
    } catch {
        return null;
    }
}
