import $ from 'jquery';
import ko from 'knockout';
import arches from 'arches';
import WidgetViewModel from 'viewmodels/widget';
import 'bindings/select2-query';
import {
    mapSuggestItemToValue,
    renderSuggestItem,
    isReferentialUrl,
    isPortalArk,
} from 'views/components/widgets/biblissima-concept-utils';
import biblissimaConceptWidgetTemplate from 'templates/views/components/widgets/biblissima-concept-widget.htm';

const name = 'biblissima-concept-widget';
const ENTITY_TYPES = ['descriptor', 'manuscript'];

const viewModel = function(params) {
    const self = this;
    params.configKeys = ['entityType', 'placeholder', 'link_color'];
    params.valueProperties = ['url', 'url_label'];

    // Django-settings-sourced Biblissima URL bases (javascript.htm →
    // arches.translations), always rendered server-side per request. The
    // JS module carries no real-URL fallback: if a base is ever missing
    // (e.g. a stale cached page), the helpers degrade to "not referential"
    // rather than matching against a hardcoded literal.
    const portalBase = arches.translations.biblissimaPortalUrl || undefined;
    const entityUriBase = arches.translations.biblissimaEntityUriBase || undefined;

    WidgetViewModel.apply(this, [params]);

    // --- value ↔ url/url_label resync (core urldatatype behaviour, #10027:
    // WidgetViewModel leaves the observables empty on existing tiles) -----
    if (ko.isObservable(this.value)) {
        if (this.value()) {
            this.url(this.value().url);
            this.url_label(this.value().url_label);
        }
        this.value.subscribe(function(newValue) {
            if (newValue) {
                self.url(newValue.url || null);
                if (newValue.url_label) {
                    self.url_label(newValue.url_label);
                } else {
                    self.url_label(null);
                    newValue.url_label = null;
                }
            } else {
                self.url(null);
                self.url_label(null);
            }
        });
    } else if (this.value) {
        this.value.url.subscribe(function(newUrl) {
            self.url(newUrl || null);
        });
        this.value.url_label.subscribe(function(newUrlLabel) {
            self.url_label(newUrlLabel || null);
        });
    }

    // Trim every write path (manual typing included): the core URL regex
    // does not reject trailing whitespace, which is how stray values like
    // "…Q292273 " reached the database.
    ['url', 'url_label'].forEach(function(property) {
        self[property].subscribe(function(newValue) {
            if (typeof newValue === 'string' && newValue !== newValue.trim()) {
                self[property](newValue.trim());
            }
        });
    });

    this.urlPreviewText = ko.pureComputed(function() {
        if (self.url()) {
            return self.url_label() || self.url();
        }
        return '--';
    });

    this.isReferential = ko.pureComputed(function() {
        return isReferentialUrl(self.url(), portalBase, entityUriBase);
    });

    // 3-way provenance: persistent portal ARK vs. the ~4% entity-URI
    // fallback (referential but no persistent portal ARK) vs. manual entry.
    this.isPortalArk = ko.pureComputed(function() {
        return isPortalArk(self.url(), portalBase);
    });
    this.isEntityFallback = ko.pureComputed(function() {
        return self.isReferential() && !self.isPortalArk();
    });

    // Manual mode: pre-activated when the stored value is off-referential,
    // so the editor never looks empty. Toggling back never clears anything —
    // the value only changes on a new selection or manual edit.
    this.manualMode = ko.observable(
        Boolean(self.url() && !isReferentialUrl(self.url(), portalBase, entityUriBase)));
    this.toggleManualMode = function() {
        if (self.manualMode()) {
            // leaving manual -> back to search: re-seed the select's value so the
            // re-created select2 shows the current tile value (its pre-selected
            // <option> is keyed by url, but a live ajax selection left selectValue
            // holding the item id).
            self.selectValue(self.url() || null);
        }
        self.manualMode(!self.manualMode());
    };

    const configuredType = ko.unwrap(self.entityType);
    const entityType = ENTITY_TYPES.indexOf(configuredType) !== -1
        ? configuredType
        : 'descriptor';

    this.searchDegraded = ko.observable(false);
    this.selectValue = ko.observable(self.url() || null);

    this.conceptSelectConfig = {
        value: self.selectValue,
        clickBubble: true,
        disabled: self.disabled,
        multiple: false,
        closeOnSelect: true,
        allowClear: false,
        minimumInputLength: 2,
        placeholder: ko.unwrap(self.placeholder) || arches.translations.biblissimaConceptPlaceholder,
        ajax: {
            url: '/api/biblissima/suggest',
            dataType: 'json',
            delay: 300, // selectWoo option — NOT the ignored v3 quietMillis
            data: (requestParams) => ({
                q: requestParams.term || '',
                type: entityType,
                lang: arches.activeLanguage,
            }),
            processResults: (data) => {
                self.searchDegraded(Boolean(data.degraded));
                return {
                    results: (data.results || []).map((item) => ({
                        ...item,
                        text: item.label,
                    })),
                };
            },
        },
        templateResult: (item) => {
            const rendered = renderSuggestItem(
                item, arches.translations.biblissimaConceptEnBadge);
            return typeof rendered === 'string' ? rendered : $(rendered);
        },
        templateSelection: (item) => item.text || item.id,
        language: {
            searching: () => arches.translations.biblissimaConceptSearching,
            errorLoading: () => arches.translations.biblissimaConceptUnavailable,
            inputTooShort: () => arches.translations.biblissimaConceptInputTooShort,
            noResults: () => (self.searchDegraded()
                ? arches.translations.biblissimaConceptUnavailable
                : arches.translations.biblissimaConceptNoResults),
        },
        onSelect: (item) => {
            if (!item || !item.id) {
                return;
            }
            // Single atomic write — writing self.url()/self.url_label()
            // separately would emit a transient inconsistent value.
            self.value(mapSuggestItemToValue(item, entityUriBase));
        },
    };
};

ko.components.register(name, {
    viewModel: viewModel,
    template: biblissimaConceptWidgetTemplate,
});

export default name;
