// Progressive enhancement of the password fields on the public account pages.
// The markup (toggle buttons, strength meter, match line) ships `hidden` in the
// template and every text comes from its data attributes; this module only
// reveals and drives it. The server stays the only judge of a password: the
// value is read on `input` events, never sent, logged or stored.

// Length counts code points like Python's `len()`. The Unicode classes below
// may be stricter than `isdigit`/`isupper`/`islower`: a client hint only, the
// server decides.
const RULE_TESTS = {
    length: (value, meter) =>
        [...value].length >= (Number(meter.dataset.minLength) || 0),
    upper: (value) => /\p{Lu}/u.test(value),
    lower: (value) => /\p{Ll}/u.test(value),
    digit: (value) => /\p{Nd}/u.test(value),
    symbol: (value, meter) => {
        const symbols = meter.dataset.symbols || "";
        return [...value].some((char) => symbols.includes(char));
    },
};

export function strengthOf(value, results) {
    if (!value) return { level: "", met: 0 };
    const rules = Object.values(results);
    const met = rules.filter(Boolean).length;
    if (rules.length && met === rules.length) return { level: "strong", met };
    const lengthOk = results.length !== false;
    if (lengthOk && met / rules.length >= 0.6) return { level: "fair", met };
    return { level: "weak", met };
}

function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
}

function wireToggle(wrap, cleanups) {
    const input = wrap.querySelector("input");
    const button = wrap.querySelector(".ms-pw-toggle");
    if (!input || !button) return null;
    button.hidden = false;
    const apply = (shown) => {
        input.type = shown ? "text" : "password";
        button.setAttribute("aria-pressed", String(shown));
        button.setAttribute(
            "aria-label",
            shown ? button.dataset.hide : button.dataset.show,
        );
        button.classList.toggle("is-shown", shown);
    };
    const onClick = () => apply(input.type === "password");
    button.addEventListener("click", onClick);
    cleanups.push(() => {
        button.removeEventListener("click", onClick);
        button.hidden = true;
        apply(false);
    });
    return () => apply(false);
}

function wireMeter(root, meter, cleanups) {
    const input = root.querySelector(`#${meter.dataset.for}`);
    if (!input) return;
    const items = [...meter.querySelectorAll("[data-rule]")];
    const word = meter.querySelector("[data-ms-pw-word]");
    const render = () => {
        const value = input.value;
        const results = {};
        items.forEach((item) => {
            const test = RULE_TESTS[item.dataset.rule];
            const ok = test ? test(value, meter) : false;
            results[item.dataset.rule] = ok;
            item.classList.toggle("is-met", ok);
            setText(
                item.querySelector(".ms-pw-state"),
                ok ? item.dataset.met : item.dataset.unmet,
            );
        });
        const { level } = strengthOf(value, results);
        meter.dataset.level = level;
        setText(word, level ? word.dataset[level] : "");
    };
    meter.hidden = false;
    input.addEventListener("input", render);
    render();
    cleanups.push(() => {
        input.removeEventListener("input", render);
        meter.hidden = true;
    });
}

function wireMatch(root, line, cleanups) {
    const input = root.querySelector(`#${line.dataset.for}`);
    const other = root.querySelector(`#${line.dataset.with}`);
    if (!input || !other) return;
    const render = () => {
        if (!input.value) {
            line.dataset.state = "";
            setText(line, "");
            return;
        }
        const same = input.value === other.value;
        line.dataset.state = same ? "match" : "mismatch";
        setText(line, same ? line.dataset.match : line.dataset.mismatch);
    };
    input.addEventListener("input", render);
    other.addEventListener("input", render);
    render();
    cleanups.push(() => {
        input.removeEventListener("input", render);
        other.removeEventListener("input", render);
        line.dataset.state = "";
        setText(line, "");
    });
}

export default function init(root = document) {
    const cleanups = [];
    const remask = [];
    root.querySelectorAll("[data-ms-pw-wrap]").forEach((wrap) => {
        const reset = wireToggle(wrap, cleanups);
        if (reset) remask.push(reset);
    });
    root.querySelectorAll("[data-ms-pw-meter]").forEach((meter) =>
        wireMeter(root, meter, cleanups),
    );
    root.querySelectorAll("[data-ms-pw-match]").forEach((line) =>
        wireMatch(root, line, cleanups),
    );
    root.querySelectorAll("form").forEach((form) => {
        if (!form.querySelector("[data-ms-pw-wrap]")) return;
        const onSubmit = () => remask.forEach((reset) => reset());
        form.addEventListener("submit", onSubmit);
        cleanups.push(() => form.removeEventListener("submit", onSubmit));
    });
    return function destroy() {
        cleanups.splice(0).forEach((fn) => fn());
    };
}
