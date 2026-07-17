import arches from "arches";
import initMsNav from "utils/ms-nav";

function buildMailto(email, data) {
    const tr = arches.translations;
    const subjectMap = {
        project: tr.msContactSubjProject,
        access: tr.msContactSubjAccess,
        question: tr.msContactSubjQuestion,
        other: tr.msContactSubjOther,
    };
    const subject = `[ManuSpectrum] ${subjectMap[data.type] || tr.msContactSubjOther} — ${data.name}`;
    const body =
        `${tr.msContactLblName}: ${data.name}\n` +
        `${tr.msContactLblEmail}: ${data.email}\n` +
        `${tr.msContactLblReason}: ${data.typeLabel}\n\n` +
        `${data.message}`;
    return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

document.addEventListener("DOMContentLoaded", () => {
    initMsNav();
    const form = document.getElementById("ms-contact-form");
    if (!form) return;
    const email = (form.dataset.contactEmail || "").trim();
    const submit = document.getElementById("ms-contact-submit");
    const note = document.getElementById("ms-contact-note");
    const error = document.getElementById("ms-contact-error");

    if (!email) {
        submit.disabled = true;
        if (note) note.hidden = false;
        return;
    }

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const data = {
            name: form.name.value.trim(),
            email: form.email.value.trim(),
            type: form.type.value,
            typeLabel: form.type.options[form.type.selectedIndex].text,
            message: form.message.value.trim(),
        };
        const valid =
            data.name &&
            data.message &&
            /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email);
        if (!valid) {
            error.textContent = arches.translations.msContactFill;
            error.hidden = false;
            return;
        }
        error.hidden = true;
        window.location.href = buildMailto(email, data);
    });
});
