/*
 * One submission of the second-factor sign-in form, served as a plain static
 * file (no webpack).
 *
 * The Arches form (`two_factor_authentication_login.htm`, 8.1.5) submits on
 * every key release once the field holds six characters, so a code typed or
 * pasted with a trailing key release posts twice and the second post fails
 * the CSRF check. This script removes that handler and submits once, when
 * the field holds exactly six digits (typed, pasted or autofilled); later
 * submissions of the same form are cancelled. A page restored from the
 * back/forward cache is made editable again.
 */
(function () {
    var CODE = /^[0-9]{6}$/;

    function bind(form) {
        var input = form.elements["two-factor-authentication"];
        if (!input) {
            return;
        }
        input.removeAttribute("onkeyup");
        input.onkeyup = null;

        input.addEventListener("input", function () {
            if (form.dataset.msSubmitted === "1" || !CODE.test(input.value)) {
                return;
            }
            input.readOnly = true;
            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
            } else {
                form.dataset.msSubmitted = "1";
                form.submit();
            }
        });

        form.addEventListener("submit", function (event) {
            if (form.dataset.msSubmitted === "1") {
                event.preventDefault();
                return;
            }
            form.dataset.msSubmitted = "1";
        });

        window.addEventListener("pageshow", function (event) {
            if (event.persisted) {
                input.readOnly = false;
                delete form.dataset.msSubmitted;
            }
        });
    }

    var form = document.forms["two-factor-authentication-form"];
    if (form) {
        bind(form);
    }
})();
