(function () {
    var box = document.querySelector("[data-ms-copy-addresses]");
    if (!box) return;
    var button = box.querySelector(".ms-copy-addresses__button");
    var status = box.querySelector(".ms-copy-addresses__status");
    var field = box.querySelector("textarea");
    var timer;
    function done() {
        status.textContent = button.getAttribute("data-copied");
        clearTimeout(timer);
        timer = setTimeout(function () {
            status.textContent = "";
        }, 2500);
    }
    function select() {
        field.focus();
        field.select();
    }
    button.hidden = false;
    button.addEventListener("click", function () {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(field.value).then(done, select);
        } else {
            select();
        }
    });
})();
