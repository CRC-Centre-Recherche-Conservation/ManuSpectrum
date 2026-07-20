import arches from "arches";
import initMsNav from "utils/ms-nav";

const t = (key, fallback) =>
    (arches.translations && arches.translations[key]) || fallback;
const tv = (key, fallback, vars) =>
    String(t(key, fallback)).replace(/\{(\w+)\}/g, (m, name) =>
        Object.prototype.hasOwnProperty.call(vars || {}, name)
            ? String(vars[name])
            : m,
    );

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function composeBody(data) {
    return (
        `${t("msContactLblName", "Name")}: ${data.name}\n` +
        `${t("msContactLblEmail", "Email")}: ${data.email}\n` +
        `${t("msContactLblReason", "Reason")}: ${data.typeLabel}\n\n` +
        `${data.message}`
    );
}

function composeSubject(data) {
    const subjectMap = {
        project: t("msContactSubjProject", "Project submission"),
        access: t("msContactSubjAccess", "Access request"),
        question: t("msContactSubjQuestion", "Question"),
        other: t("msContactSubjOther", "Message"),
    };
    const label = subjectMap[data.type] || subjectMap.other;
    return `[ManuSpectrum] ${label} — ${data.name}`;
}

function buildMailto(email, data) {
    const subject = encodeURIComponent(composeSubject(data));
    const body = encodeURIComponent(composeBody(data));
    return `mailto:${email}?subject=${subject}&body=${body}`;
}

// Same pattern as team.js / conceptual-model.js / graph-explorer.js: the hero and
// the form section ship with `.reveal` (opacity 0) and need `.is-visible` applied,
// otherwise they never paint. `prefers-reduced-motion` is handled in pages.scss.
function revealOnScroll() {
    const els = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) {
        els.forEach((e) => e.classList.add("is-visible"));
        return;
    }
    const io = new IntersectionObserver(
        (entries) => {
            entries.forEach((en) => {
                if (en.isIntersecting) {
                    en.target.classList.add("is-visible");
                    io.unobserve(en.target);
                }
            });
        },
        { threshold: 0.15 },
    );
    els.forEach((e) => io.observe(e));
}

// WAVE 4f — per-field errors.
// `novalidate` is kept (the native bubbles are unstyleable and disappear on
// scroll), but the replacement has to carry the same information: WHICH field,
// and WHY. Each control points at its own error node through aria-describedby,
// so a screen reader reads the message as part of the field, not as a detached
// alert at the bottom of the form.
function setFieldError(input, message) {
    const errId = (input.getAttribute("aria-describedby") || "")
        .split(/\s+/)
        .find((id) => id.endsWith("-err"));
    const err = errId && document.getElementById(errId);
    if (message) {
        input.setAttribute("aria-invalid", "true");
        if (err) {
            err.textContent = message;
            err.hidden = false;
        }
    } else {
        input.removeAttribute("aria-invalid");
        if (err) {
            err.textContent = "";
            err.hidden = true;
        }
    }
}

function validate(fields) {
    const problems = [];
    if (!fields.name.value.trim()) {
        problems.push([
            fields.name,
            t("msContactErrName", "Please enter your name."),
        ]);
    }
    if (!EMAIL_RE.test(fields.email.value.trim())) {
        problems.push([
            fields.email,
            t("msContactErrEmail", "Please enter a valid email address."),
        ]);
    }
    if (!fields.message.value.trim()) {
        problems.push([
            fields.message,
            t("msContactErrMessage", "Please write a message."),
        ]);
    }
    return problems;
}

// Clipboard, with the pre-`navigator.clipboard` path kept: this page is served
// over plain HTTP in development and to anyone behind a proxy that strips the
// secure context, where `navigator.clipboard` is simply undefined.
function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.classList.add("ms-visually-hidden");
        document.body.appendChild(ta);
        ta.select();
        try {
            const ok = document.execCommand("copy");
            document.body.removeChild(ta);
            if (ok) resolve();
            else reject(new Error("copy rejected"));
        } catch (e) {
            document.body.removeChild(ta);
            reject(e);
        }
    });
}

function wireCopyButtons() {
    const status = document.getElementById("ms-contact-copied");
    document.querySelectorAll(".ms-contact-copy").forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = document.getElementById(btn.dataset.copyTarget);
            if (!target) return;
            const text = "value" in target ? target.value : target.textContent;
            copyText(text.trim()).then(
                () => {
                    if (status)
                        status.textContent = t("msContactCopied", "Copied.");
                },
                () => {
                    if (status)
                        status.textContent = t(
                            "msContactCopyFailed",
                            "Copy failed — select the text and copy it manually.",
                        );
                },
            );
        });
    });
}

function wireCounter(message) {
    const counter = document.getElementById("ms-contact-count");
    const max = Number(message.getAttribute("maxlength"));
    if (!counter || !max) return;
    const update = () => {
        const left = max - message.value.length;
        counter.textContent = tv(
            "msContactCharsLeft",
            "{n} characters left",
            { n: left },
        );
        counter.classList.toggle("is-low", left <= 100);
    };
    message.addEventListener("input", update);
    update();
}

document.addEventListener("DOMContentLoaded", () => {
    initMsNav();
    revealOnScroll();
    const form = document.getElementById("ms-contact-form");
    if (!form) return;
    const email = (form.dataset.contactEmail || "").trim();
    const submit = document.getElementById("ms-contact-submit");
    const note = document.getElementById("ms-contact-note");
    const error = document.getElementById("ms-contact-error");
    const fallback = document.getElementById("ms-contact-fallback");
    const fallbackBody = document.getElementById("ms-contact-body");

    // `form.name` / `form.email` / `form.message` resolve to the CONTROLS, not to
    // HTMLFormElement's own properties: the interface is [LegacyOverrideBuiltIns],
    // so the named-control getter shadows the built-ins. Verified, not a footgun.
    const fields = {
        name: form.name,
        email: form.email,
        type: form.type,
        message: form.message,
    };

    wireCounter(fields.message);
    wireCopyButtons();

    // Clear a field's error as soon as the user starts fixing it — leaving a
    // stale "please enter your name" under a field that now has a name in it is
    // worse than showing nothing.
    [fields.name, fields.email, fields.message].forEach((input) =>
        input.addEventListener("input", () => setFieldError(input, "")),
    );

    if (!email) {
        submit.disabled = true;
        if (note) note.hidden = false;
        return;
    }

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const data = {
            name: fields.name.value.trim(),
            email: fields.email.value.trim(),
            type: fields.type.value,
            typeLabel: fields.type.options[fields.type.selectedIndex].text,
            message: fields.message.value.trim(),
        };

        [fields.name, fields.email, fields.message].forEach((input) =>
            setFieldError(input, ""),
        );
        const problems = validate(fields);
        if (problems.length) {
            problems.forEach(([input, message]) => setFieldError(input, message));
            error.textContent = t(
                "msContactFill",
                "Please fill in all fields with a valid email.",
            );
            error.hidden = false;
            problems[0][0].focus();
            return;
        }
        error.hidden = true;

        // The fallback is revealed BEFORE navigating, not after: if the handler
        // does open a mail client the page is left behind anyway, and if it does
        // not, the panel is already there instead of the user staring at a
        // button that appears to do nothing.
        if (fallback && fallbackBody) {
            fallbackBody.value = `${composeSubject(data)}\n\n${composeBody(data)}`;
            fallback.hidden = false;
        }
        window.location.href = buildMailto(email, data);
    });
});
