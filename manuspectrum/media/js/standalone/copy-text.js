/*
 * Copy-to-clipboard buttons, served as a plain static file (no webpack).
 *
 * <div data-ms-copy data-ms-copy-source="<selector>" [data-ms-copy-text="<text>"]>
 *   <button type="button" data-ms-copy-button hidden data-copied="Copied">Copy</button>
 *   <span data-ms-copy-status role="status"></span>
 * </div>
 *
 * The copied text is `data-ms-copy-text` when present, else the value (form
 * control) or the text of the source element, found inside the box. Without
 * the Clipboard API, or when it refuses, the source is selected so the reader
 * can copy it by hand. The button stays hidden until this script runs.
 */
(function () {
    var STATUS_MS = 2500;

    function selectSource(source) {
        if (typeof source.select === "function") {
            source.focus();
            source.select();
            return;
        }
        var range = document.createRange();
        range.selectNodeContents(source);
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
    }

    function bind(box) {
        var button = box.querySelector("[data-ms-copy-button]");
        var status = box.querySelector("[data-ms-copy-status]");
        var source = box.querySelector(box.getAttribute("data-ms-copy-source"));
        if (!button || !source) return;
        var timer;

        function text() {
            var given = box.getAttribute("data-ms-copy-text");
            if (given !== null) return given;
            return "value" in source ? source.value : source.textContent;
        }

        function done() {
            if (!status) return;
            status.textContent = button.getAttribute("data-copied");
            clearTimeout(timer);
            timer = setTimeout(function () {
                status.textContent = "";
            }, STATUS_MS);
        }

        function fallback() {
            selectSource(source);
        }

        button.hidden = false;
        button.addEventListener("click", function () {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text()).then(done, fallback);
            } else {
                fallback();
            }
        });
    }

    Array.prototype.forEach.call(
        document.querySelectorAll("[data-ms-copy]"),
        bind,
    );
})();
