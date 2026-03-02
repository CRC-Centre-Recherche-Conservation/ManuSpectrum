import ko from 'knockout';
import $ from 'jquery';
import Dropzone from 'dropzone'; // eslint-disable-line no-unused-vars
import uuid from 'uuid';
import 'bindings/select2-query';
import 'bindings/dropzone';
import WidgetViewModel from 'viewmodels/widget';
import arches from 'arches';
import manifestWidgetTemplate from 'templates/views/components/widgets/manifest-widget.htm';

const viewModel = function(params) {
    const self = this;

    params.configKeys = ['defaultManifest'];
    WidgetViewModel.apply(this, [params]);

    self.expandGallery = ko.observable(false);
    self.showGallery = ko.observable(true);

    self.state = params.state || 'form';
    self.hideEmptyNodes = params.hideEmptyNodes || false;

    self.manifest = ko.observable();
    self.manifestId = ko.observable();
    self.manifestUrl = ko.observable();
    self.manifestData = ko.observable();
    self.manifestLabel = ko.observable();
    self.manifestDescription = ko.observable();
    self.manifestThumbnail = ko.observable();

    self.loading = ko.observable(false);
    self.manifestError = ko.observable(false);
    self.errorMessage = ko.observable('');

    self.showCreatePanel = ko.observable(false);
    self.newManifestTitle = ko.observable('');
    self.isUploading = ko.observable(false);
    self.uploadError = ko.observable('');

    self.transactionId = uuid.generate();
    self.uniqueId = uuid.generate();
    self.uniqueidClass = ko.computed(function() {
        return "unique_id_" + self.uniqueId;
    });

    self.defaultManifest = self.config.defaultManifest;

    self.buildFullUrl = function(url) {
        if (!url) return url;
        if (url.startsWith('http://') || url.startsWith('https://')) {
            return url;
        }
        const baseUrl = window.location.origin;
        return baseUrl + url;
    };

    self.manifestSelectConfig = {
        value: self.manifest,
        clickBubble: true,
        disabled: self.disabled,
        multiple: false,
        placeholder: 'Search for a manifest or enter a URL...',
        allowClear: true,
        minimumResultsForSearch: 0,
        minimumInputLength: 0,
        tags: true,

        ajax: {
            url: '/iiifmanifest',
            dataType: 'json',
            delay: 250,
            data: function(params) {
                return { query: params.term, start: 0, limit: 20 };
            },
            processResults: function(data) {
                return {
                    results: (data.results || []).map(function(manifest) {
                        const url = manifest.url;
                        return {
                            id: url,
                            text: manifest.label || url,
                            manifest: { ...manifest, url: url }
                        };
                    })
                };
            },
            cache: false
        },

        templateResult: function(item) {
            if (item.loading) return item.text;
            if (item.newTag) {
                return $('<div>').append(
                    $('<i>').addClass('fa fa-plus').css('margin-right', '5px')
                ).append(item.text);
            }
            if (!item.manifest) return item.text;

            const $result = $('<div>');
            $result.append($('<strong>').text(item.manifest.label || 'IIIF Manifest'));
            if (item.manifest.description) {
                $result.append($('<br>'));
                $result.append($('<small>').css('color', '#999').text(item.manifest.description));
            }
            if (item.manifest.url) {
                $result.append($('<br>'));
                $result.append($('<small>').css('color', '#ccc').text(item.manifest.url));
            }
            return $result;
        },

        templateSelection: function(item) {
            if (item.manifest) {
                return item.manifest.label || item.text;
            }
            if (item.newTag && item.id) {
                return item.id;
            }
            return item.text;
        },

        createTag: function(params) {
            const term = params.term.trim();
            if (term === '') return null;
            if (term.startsWith('http://') || term.startsWith('https://')) {
                return { id: term, text: 'Use URL: ' + term, newTag: true };
            }
            return null;
        },

        language: {
            noResults: function() {
                return 'No manifests found. Enter a full URL starting with http:// or https://';
            },
            searching: function() {
                return 'Searching...';
            }
        }
    };

    self._lastManifestValue = null;
    self.manifest.subscribe(function(newValue) {
        if (newValue === self._lastManifestValue) return;
        self._lastManifestValue = newValue;

        if (newValue) {
            const fullUrl = self.buildFullUrl(newValue);
            self.manifestUrl(fullUrl);
            self.loadManifestData(fullUrl)
                .then(() => self.updateValue())
                .catch(() => self.updateValue());
        } else {
            self.clearManifest();
        }
    });

    self.loadManifestFromId = function(manifestId) {
        self.loading(true);
        self.manifestError(false);
        var manifestPath = '/manifest/' + manifestId;
        var fullUrl = self.buildFullUrl(manifestPath);
        self.manifestUrl(fullUrl);
        self.manifestId(manifestId);
        self.loadManifestData(fullUrl)
            .catch(function() {
                self.manifestError(true);
                self.errorMessage('Unable to load manifest');
                self.loading(false);
            });
    };

    self.quickValidateUrl = function(url) {
        if (!url) return { valid: false, error: 'URL is required' };
        try {
            new URL(url);
            return { valid: true };
        } catch {
            return { valid: false, error: 'Invalid URL format' };
        }
    };

    self.loadManifestData = function(url) {
        if (!url) return Promise.reject('No URL provided');

        const validation = self.quickValidateUrl(url);
        if (!validation.valid) {
            self.manifestError(true);
            self.errorMessage(validation.error);
            return Promise.reject(validation.error);
        }

        self.loading(true);
        self.manifestError(false);
        self.errorMessage('');

        return fetch(url, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            mode: 'cors'
        })
            .then(response => {
                if (!response.ok) {
                    let message = `Unable to load manifest (HTTP ${response.status}).`;
                    if (response.status === 404) message = 'Manifest not found.';
                    if (response.status === 403) message = 'Access forbidden.';
                    if (response.status >= 500) message = 'Server error.';
                    throw new Error(message);
                }
                return response.json();
            })
            .then(data => {
                self.manifestData(data);

                const label = self.getManifestValue(data, 'label');
                const description = self.getManifestValue(data, 'description') || self.getManifestValue(data, 'summary');
                const thumbnail = self.getThumbnail(data);

                self.manifestLabel(label || 'IIIF Manifest');
                self.manifestDescription(description || '');
                self.manifestThumbnail(thumbnail || '');
                self.loading(false);
                return data;
            })
            .catch(error => {
                self.manifestError(true);
                let friendlyMessage = error.message;
                if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
                    friendlyMessage = 'Unable to connect to the manifest URL. This might be a CORS or network issue.';
                }
                self.errorMessage(friendlyMessage);
                self.loading(false);
                throw error;
            });
    };

    self.getManifestValue = function(manifest, property) {
        if (!manifest) return '';
        const value = manifest[property];
        if (!value) return '';

        if (typeof value === 'object' && !Array.isArray(value)) {
            const lang = value['en'] || value['none'] || Object.values(value)[0];
            if (Array.isArray(lang)) return lang[0] || '';
            return lang || '';
        }

        if (Array.isArray(value) && value[0]) {
            if (typeof value[0] === 'object' && value[0]['@value']) return value[0]['@value'];
            return value[0];
        }

        if (typeof value === 'string') return value;
        return '';
    };

    self.getThumbnail = function(manifest) {
        if (!manifest) return '';

        if (manifest.thumbnail) {
            if (typeof manifest.thumbnail === 'string') return self.buildFullUrl(manifest.thumbnail);
            if (manifest.thumbnail['@id'] || manifest.thumbnail['id']) {
                return self.buildFullUrl(manifest.thumbnail['@id'] || manifest.thumbnail['id']);
            } else if (Array.isArray(manifest.thumbnail) && manifest.thumbnail[0]) {
                const thumb = manifest.thumbnail[0];
                const thumbUrl = thumb['@id'] || thumb['id'] || thumb;
                return self.buildFullUrl(thumbUrl);
            }
        }

        if (manifest.sequences?.[0]?.canvases?.[0]) {
            const firstCanvas = manifest.sequences[0].canvases[0];
            if (firstCanvas.thumbnail) {
                if (typeof firstCanvas.thumbnail === 'string') return self.buildFullUrl(firstCanvas.thumbnail);
                if (firstCanvas.thumbnail['@id']) return self.buildFullUrl(firstCanvas.thumbnail['@id']);
            }
            if (firstCanvas.images?.[0]?.resource?.['@id']) {
                const imageUrl = firstCanvas.images[0].resource['@id'];
                const fullImageUrl = self.buildFullUrl(imageUrl);
                return fullImageUrl.includes('/full/full/')
                    ? fullImageUrl.replace('/full/full/', '/full/200,/')
                    : fullImageUrl;
            }
        }

        if (manifest.items?.[0]?.thumbnail?.[0]) {
            return self.buildFullUrl(manifest.items[0].thumbnail[0].id);
        }

        return '';
    };

    self.updateValue = function() {
        const url = self.manifestUrl();
        if (url) {
            const fullUrl = self.buildFullUrl(url);
            self.value(fullUrl);
        } else {
            self.value(null);
        }
    };

    self.clearManifest = function() {
        self.manifest(null);
        self.manifestId(null);
        self.manifestUrl(null);
        self.manifestData(null);
        self.manifestLabel(null);
        self.manifestDescription(null);
        self.manifestThumbnail(null);
        self.value(null);
        self.manifestError(false);
        self.errorMessage('');
    };

    self.openCreatePanel = function() {
        self.showCreatePanel(true);
    };

    self.closeCreatePanel = function() {
        self.showCreatePanel(false);
        self.newManifestTitle('');
        self.uploadError('');
        self.isUploading(false);
        if (self.dropzone) {
            self.dropzone.removeAllFiles(true);
        }
    };

    self.formData = new window.FormData();

    self.createManifest = function(fileList) {
        self.formData.delete("files");
        self.formData = new window.FormData();

        Array.from(fileList).forEach(function(file) {
            self.formData.append("files", file, file.name);
        });
        self.formData.append("manifest_title", self.newManifestTitle() || 'Untitled manifest');
        self.formData.append("operation", "create");
        self.formData.append("transaction_id", self.transactionId);

        self.isUploading(true);
        self.uploadError('');

        $.ajax({
            type: "POST",
            url: arches.urls.manifest_manager,
            data: self.formData,
            cache: false,
            processData: false,
            contentType: false,
            success: function(response) {
                self.isUploading(false);
                self.closeCreatePanel();

                // manifest_manager already created the DB record.
                // Set display state directly, bypassing select2 subscription.
                var fullUrl = self.buildFullUrl(response.url);

                self._lastManifestValue = response.url;
                self.manifestUrl(fullUrl);
                self.manifestLabel(response.label || self.newManifestTitle() || 'IIIF Manifest');
                self.manifestDescription(response.description || '');
                self.value(fullUrl);

                // Load full manifest data for thumbnail preview
                self.loadManifestData(fullUrl).catch(function() {});
            },
            error: function(response) {
                self.isUploading(false);
                self.uploadError(
                    (response.responseJSON && response.responseJSON.message) ||
                    arches.translations.manifestCreateError
                );
                if (self.dropzone) {
                    self.dropzone.removeAllFiles(true);
                }
            }
        });
    };

    self.dropzoneOptions = {
        url: "arches.urls.root",
        dictDefaultMessage: '',
        autoProcessQueue: false,
        uploadMultiple: true,
        acceptedFiles: ["image/jpeg", "image/png", "image/tiff"].join(','),
        autoQueue: false,
        clickable: ".fileinput-create-button." + self.uniqueidClass(),
        previewsContainer: '#hidden-dz-manifest-previews-' + self.uniqueId,
        init: function() {
            self.dropzone = this;
            this.on("addedfiles", self.createManifest);
            this.on("error", function(file, error) {
                file.error = error;
            });
        }
    };

    self.displayValue = ko.computed(function() {
        if (self.state === 'report') {
            return self.manifestUrl() || self.value() || '';
        }
        return self.manifestLabel() || self.manifestUrl() || '';
    });

    if (self.value()) {
        const valueStr = ko.unwrap(self.value());
        if (self.state === 'report') {
            self.manifestUrl(valueStr);
            if (valueStr) self.loadManifestData(valueStr).catch(() => {
                self.manifestLabel('IIIF Manifest');
            });
        } else {
            try {
                if (valueStr.match(/^[0-9a-f-]{36}$/i)) {
                    self.loadManifestFromId(valueStr);
                } else {
                    self.manifestUrl(valueStr);
                    self.manifest(valueStr);
                    self.loadManifestData(valueStr);
                }
            } catch {
                self.manifestUrl(valueStr);
                self.manifest(valueStr);
                self.loadManifestData(valueStr);
            }
        }
    }
};

ko.components.register('manifest-widget', {
    viewModel: viewModel,
    template: manifestWidgetTemplate
});

export default viewModel;
