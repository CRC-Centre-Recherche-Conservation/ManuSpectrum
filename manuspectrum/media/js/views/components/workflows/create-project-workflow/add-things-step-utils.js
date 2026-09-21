import $ from 'jquery';

const SEARCH_TERM_CONTEXT = 'Search Term';

/**
 * selectWoo `templateResult` for the document picker of the add-things step.
 *
 * The free-text "Search Term" row is returned as a jQuery element built with
 * `.text()`, which selectWoo appends as nodes; every other row is returned as
 * its plain label, which selectWoo escapes itself. The label is API data and is
 * never interpolated into markup.
 */
export function renderTermResult(item) {
    if (item.context_label === SEARCH_TERM_CONTEXT) {
        return $('<strong>').append($('<u>').text(item.text || ''));
    }
    return item.text;
}
