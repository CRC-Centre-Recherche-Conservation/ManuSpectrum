/**
 * Import Biblissima workflow — step 3 (Create & Validate).
 *
 * Takes the cart from step 2 and, on user action, creates the resources
 * and their related Place / Group / Person dependencies in Arches.
 *
 * ## State machine (per item)
 *
 *   pending → creating → created      (happy path)
 *   pending → creating → error        (write failed, retryable)
 *   pending → linked                  (user linked to an existing resource)
 *   pending → skipped                 (user dismissed the item)
 *
 * Components additionally carry ``enrichStatus`` (pending → loading → done/error)
 * driven by `enrichComponentItems`: this must be ``done`` before the Create
 * button unlocks, to avoid racing the illumination detail fetch that fills
 * in text, rubric, descriptorLinks, Mandragore ARK, canvas dimensions, and
 * the production ``location`` that drives the Place dep.
 *
 * ## Init sequence
 *
 *     initializeItems()        // build per-item observables
 *     resolveDependencies()    // first pass — detects deps from cart data only
 *     checkDuplicates()        // ES search for duplicate main items
 *     enrichComponentItems()   // Component only — fetches each ifdata portal
 *                              // page with concurrency=5, then re-runs
 *                              // resolveDependencies so newly-surfaced
 *                              // `location` (= production place) becomes a
 *                              // Place dep.
 *
 * ## Staging
 *
 * Everything above is **read-only**: dup checks, enrichment, dep matching
 * are all ``GET`` calls against ``/api/biblissima/*``. No DB writes happen
 * until the user clicks *Create* on an item (or *Create all*). The single
 * exception is ``_addAltName`` — when `resolveDependencies` finds a
 * high-confidence match for a dep, it auto-links and POSTs the Biblissima
 * label as an altLabel on the existing resource. That's a soft annotation
 * on a resource the user already agreed to reuse, not a creation.
 *
 * ## Dependency cascade
 *
 * ``createDependency(dep)`` is recursive. A Group dep with
 * ``{ parentKey, locationKey }`` resolves its parent Group and its Place
 * before creating itself, so ``Place Paris → Group Département → Group
 * BnF`` is a single depth-first walk. ``_ensureDepsCreated`` drives this
 * from the top when the user hits Create on an item.
 *
 * ## Two Places for one Component
 *
 * Component items can carry two orthogonal places:
 *
 *   - ``item.locationLabel`` — current location of the **parent manuscript**
 *     (Wikibase-resolved), e.g. "Paris (France)" for any BnF codex. Used
 *     as the `locationKey` of Group deps (the BnF is in Paris, period).
 *   - ``item.location`` — production place of **this specific illumination**
 *     (scraped from the individual portal page), e.g. "Naples (Campanie,
 *     Italie)". Goes into ``deps.productionPlace`` on the Component tile.
 *
 * `_placeKeyForItem(item)` returns the mode-appropriate key:
 *  Component → `item.location` (production); Document → `item.locationLabel`
 *  (current location). Callers match Place deps with it.
 *
 * ## Type badge editor
 *
 * Each item carries a `typeValueId` observable backed by an inline
 * `concept-select-widget` editor. Component items additionally have a
 * `typeIsFallback` flag set by the backend resolver: it's ``true`` **only**
 * when no Biblissima input matched the type mapping at all, so that an
 * explicit "Enluminure" (which genuinely matches the mapping) isn't
 * highlighted the same as a real "couldn't resolve" case.
 */
import ko from 'knockout';
import arches from 'arches';
import 'bindings/select2-query';
import ResourceInstanceSelectViewModel from 'viewmodels/resource-instance-select';
import biblissimaCreateStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-create-step.htm';
import ParentResolver from './parentResolver';

// Type of Document: "manuscrit" valueid — default for every imported Document
// since Biblissima's search already filters on type=manuscript.
const VALUEID_MANUSCRIT = '30931466-b4e0-4527-ac93-b7290e80084c';

// Document graph ID (used by the parent-resolver manual picker).
const DOCUMENT_GRAPH_ID = '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b';

// RDM collections for the per-item inline concept-select-widget
const RDM_DOC_TYPE = '73cf3108-5fef-429b-a92f-24074871aed9';
const RDM_COMP_TYPE = 'e85080b2-c39b-4e37-b6bc-b57d34092b7b';

// Server-side fallback when no Component mapping matches (illumination générique).
// Must stay in sync with BIBLISSIMA_TYPE_DEFAULT in views/biblissima_proxy.py.
const COMPONENT_FALLBACK_TYPE_VALUEID = '3ecd8040-7c4b-4b1d-88f7-379297358f66';

// Label lookup for known Component type valueids — mirrors
// BIBLISSIMA_TYPE_VALUEID_LABELS in views/biblissima_proxy.py. Used when the
// user picks a new valueid via the inline editor so the badge can update
// without round-tripping the RDM. Any valueid not in this map falls back to
// a generic "Custom type" label.
const BIBLISSIMA_TYPE_LABELS = {
    '31158e76-817a-447d-a40c-3963731296a8': 'Lettrine',
    '2f5df709-4f32-40b4-8858-d0d54ba25d61': 'Lettre ornée',
    '63bc98e3-57de-48fc-a656-8d6f9a9acf40': 'Miniature',
    '4063b4aa-c50b-4101-947c-d8094eed6e25': 'Décor',
    '0805a584-1395-48df-8e84-4ae4b25cdeae': 'Frontispice',
    '29167061-2645-4d86-8f30-9206c1f83297': 'Vignette',
    '85e458af-0292-4ecb-84b9-5715071d45e1': 'Photographie',
    'c3168cc7-23d3-4ddb-9eac-38383b852f5a': 'Filigrane',
    '36a20d43-f316-4d0f-bf58-ec8a2cb71d0a': 'Planche',
    '3ecd8040-7c4b-4b1d-88f7-379297358f66': 'Enluminure',
};

const viewModel = function(params) {
    const self = this;

    // Workflow step interface
    this.complete = params.form?.complete || ko.observable(false);
    this.saving = ko.observable(false);
    this.loading = ko.observable(true);

    // Config from step 1
    this.config = params.configStepData || {};
    this.resourceType = this.config.resourceType || 'Document';
    this.projectId = this.config.projectId || null;
    this.isComponent = this.resourceType === 'Component';
    // RDM collection used by the inline type editor. Depends on mode, wrapped
    // as an observable because concept-select-widget expects one.
    this.typeRdmCollection = ko.observable(
        this.isComponent ? RDM_COMP_TYPE : RDM_DOC_TYPE
    );

    // Items from step 2
    this.searchData = params.searchStepData || {};
    this.selectedItems = ko.observableArray(this.searchData.selectedItems || []);

    // Dependencies resolution
    this.dependencies = ko.observableArray();
    this.dependenciesResolved = ko.observable(false);

    // Items with status tracking
    this.items = ko.observableArray();
    this.creatingAll = ko.observable(false);

    // ParentResolver (Component mode only) — resolves one parent Document
    // per Biblissima manuscript group. See parentResolver.js. We construct
    // it eagerly so the template can bind to its observables, but
    // resolveAll() is only fired in Component mode (see init sequence
    // below).
    this.parentResolver = new ParentResolver({
        cart: this.items,
        projectId: this.projectId,
        isComponent: this.isComponent,
        getCSRFToken: () => self.getCSRFToken(),
        // Lambda so parentResolver picks up createResource even though the
        // method is defined later in this constructor — at call time
        // ``self.createResource`` is bound.
        createResource: (item, opts) => self.createResource(item, opts),
    });

    this.shouldShowParentPanel = ko.computed(
        () => self.isComponent
            && (self.parentResolver.totalCount() + self.parentResolver.unidentifiedItems().length) > 0
    );

    // Stats
    this.createdCount = ko.computed(() =>
        self.items().filter((i) => i.status() === 'created').length
    );
    this.linkedCount = ko.computed(() =>
        self.items().filter((i) => i.status() === 'linked').length
    );
    this.totalCount = ko.computed(() => self.items().length);
    this.allDone = ko.computed(() =>
        self.totalCount() > 0 && self.items().every(
            (i) => i.status() === 'created' || i.status() === 'linked' || i.status() === 'skipped'
        )
    );

    // All deps resolved? (blocks "Create All")
    this.allDepsResolved = ko.computed(() =>
        self.dependencies().every((d) => {
            const action = d.action();
            return action === 'use_existing' || action === 'created';
        })
    );

    // Gate the global "Create All" button on parent-resolution AND
    // dep-resolution AND no pending enrichment AND at least one pending item.
    this.canCreateAll = ko.computed(() => {
        if (self.isComponent) {
            if (self.parentResolver.resolving()) return false;
            if (!self.parentResolver.allResolved()) return false;
        }
        if (!self.allDepsResolved()) return false;
        if (self.items().some((i) => i.enrichStatus && i.enrichStatus() === 'pending')) {
            return false;
        }
        return self.items().some((i) => i.status() === 'pending');
    });

    // Gate the per-item Create button on the item being pending AND, for
    // Component, having a resolved parent Document.
    this.canCreateItem = (item) => {
        if (item.status() !== 'pending') return false;
        if (!self.isComponent) return self.itemDepsResolved(item);
        return self.itemDepsResolved(item)
            && !!self.parentResolver.parentIdFor(item);
    };

    // Manual-picker factories used by the parent-resolver UI. We cache one
    // picker per group/item so KO doesn't re-create the underlying select2
    // on every render (which would lose its DOM state). The picker mutates
    // its `value` observable, and we forward changes to parentResolver.
    this._groupPickers = {};
    this._orphanPickers = {};

    this._makeManualPicker = () => {
        const picker = {};
        ResourceInstanceSelectViewModel.apply(picker, [{
            graphids: [DOCUMENT_GRAPH_ID],
            value: ko.observableArray([]),
            allowInstanceCreation: false,
            displayOntologyTable: false,
            renderContext: 'workflow',
            multiple: false,
            onlyManageResourceIds: true,
            disabled: ko.observable(false),
        }]);
        return picker;
    };

    this.manualPickerForGroup = (group) => {
        const key = group.portalHash || group.biblissimaQid || '';
        if (!self._groupPickers[key]) {
            const picker = self._makeManualPicker();
            // With onlyManageResourceIds=true, value is a UUID string.
            picker.value.subscribe((val) => {
                if (val && typeof val === 'string' && val.length > 10) {
                    const selected = picker.selectedItem?.();
                    const displayname = selected?._source?.displayname || val;
                    self.parentResolver.pickManual(group, val, displayname);
                }
            });
            self._groupPickers[key] = picker;
        }
        return self._groupPickers[key];
    };

    this.orphanPickerForItem = (item) => {
        const key = item.canvasId || item.arkId || '';
        if (!self._orphanPickers[key]) {
            const picker = self._makeManualPicker();
            picker.value.subscribe((val) => {
                if (val && typeof val === 'string' && val.length > 10) {
                    const selected = picker.selectedItem?.();
                    const displayname = selected?._source?.displayname || val;
                    self.parentResolver.assignManualToOrphan(item, val, displayname);
                }
            });
            self._orphanPickers[key] = picker;
        }
        return self._orphanPickers[key];
    };

    // Dep progress counts (for progress indicator)
    this.resolvedDepsCount = ko.computed(() =>
        self.dependencies().filter((d) => {
            const action = d.action();
            return action === 'use_existing' || action === 'created';
        }).length
    );
    this.totalDepsCount = ko.computed(() => self.dependencies().length);

    // Return the Place dep key for an item, mode-aware:
    //   - Document → `locationLabel` = current location of the manuscript
    //     (used for the `currentLocation` tile on Documents).
    //   - Component → `location` = production place of the illumination,
    //     scraped from the individual portal page. Component graph has no
    //     "current location" card, so the parent manuscript's shelving
    //     place is irrelevant here; we want the place of production.
    this._placeKeyForItem = (item) =>
        self.isComponent
            ? (item.location || '')
            : (item.locationLabel || item.location || '');

    // Check if deps for a specific item are resolved (blocks individual "Create")
    this.itemDepsResolved = (item) => {
        // Block Component creates until the enrichment has landed: otherwise
        // we race the illumination-detail fetch and end up missing text,
        // rubric, descriptorLinks, Mandragore ARK, canvas dimensions and
        // the Lieu de fabrication that drives the Place dep.
        if (self.isComponent) {
            const es = item.enrichStatus();
            if (es === 'pending' || es === 'loading') return false;
        }
        const locationKey = self._placeKeyForItem(item);
        return self.dependencies().every((dep) => {
            const isRelevant =
                (dep.type === 'Place' && dep.key === locationKey) ||
                (dep.type === 'Group' && dep.key === item.collectionLabel) ||
                (dep.type === 'Group' && dep.key === item.parentInstitutionLabel && dep.key !== item.collectionLabel) ||
                (dep.type === 'Person' && dep.key === item.authorLabel);
            if (!isRelevant) return true;
            const action = dep.action();
            return action === 'use_existing' || action === 'created';
        });
    };

    // Unresolved dep names for a specific item (for tooltip)
    this.unresolvedDepsLabel = (item) => {
        const unresolved = [];
        // In Component mode, the per-item Create button also requires the
        // parent Document to be resolved in the parent-resolver panel above.
        // Surface that requirement explicitly so the tooltip isn't empty when
        // Place/Person/Group are all linked but the parent group is still
        // pending — which is exactly the case after fresh /check-duplicates.
        if (self.isComponent && !self.parentResolver.parentIdFor(item)) {
            const parentLabel = item.manuscript
                || item.shelfmark
                || item.portalHash
                || item.biblissimaQid
                || '?';
            unresolved.push('Parent Document: ' + parentLabel);
        }
        const locationKey = self._placeKeyForItem(item);
        self.dependencies().forEach((dep) => {
            const isRelevant =
                (dep.type === 'Place' && dep.key === locationKey) ||
                (dep.type === 'Group' && dep.key === item.collectionLabel) ||
                (dep.type === 'Group' && dep.key === item.parentInstitutionLabel && dep.key !== item.collectionLabel) ||
                (dep.type === 'Person' && dep.key === item.authorLabel);
            if (!isRelevant) return;
            const action = dep.action();
            if (action !== 'use_existing' && action !== 'created') {
                unresolved.push(dep.type + ': ' + dep.key);
            }
        });
        return unresolved.join('\n');
    };

    // Dependency cache (shared across creations)
    this.dependencyCache = {
        places: {},
        persons: {},
        groups: {},
    };

    // Graph IDs for dependency types
    const PLACE_GRAPH_ID = '3f2b036a-b65d-474d-b692-0b21903655c5';
    const PERSON_GRAPH_ID = '5bf45c85-84cd-4a76-b64a-3ffe86eea1b8';
    const GROUP_GRAPH_ID = '4f447dca-dbb3-48d0-bc90-3f2935db8b8c';

    const DEP_TYPE_MAP = {
        Place: { graphId: PLACE_GRAPH_ID, cacheKey: 'places' },
        Group: { graphId: GROUP_GRAPH_ID, cacheKey: 'groups' },
        Person: { graphId: PERSON_GRAPH_ID, cacheKey: 'persons' },
    };

    // =============================================
    // Items
    // =============================================

    this.initializeItems = () => {
        const items = (self.searchData.selectedItems || []).map((item) => ({
            ...item,
            status: ko.observable('pending'),
            resourceId: ko.observable(null),
            errorMessage: ko.observable(''),
            suggestions: ko.observableArray([]),
            showSuggestions: ko.observable(false),
            linkedResourceId: ko.observable(null),
            linkedDisplayname: ko.observable(''),
            enrichExisting: ko.observable(true),
            // Per-item type: observable so the inline editor can mutate it and
            // the badge can re-render. Component items carry a typeValueId
            // resolved server-side from the Biblissima descriptor; Documents
            // all default to "manuscrit" (Biblissima filters on manuscripts).
            // For Document items, prefer the backend-resolved Document Type
            // valueid (from documentTypeValueId, attached by _enrich_canvases
            // and BiblissimaSearchManuscriptsView). For Component items, the
            // existing per-descriptor resolution still wins.
            typeValueId: ko.observable(
                item.typeValueId
                || (self.isComponent
                        ? COMPONENT_FALLBACK_TYPE_VALUEID
                        : (item.documentTypeValueId || VALUEID_MANUSCRIT))
            ),
            // Flag set by the backend resolver:
            //  - Component: True only when no Biblissima input matched the
            //    type mapping (distinct from an explicit "Enluminure" that
            //    correctly maps to the default valueid).
            //  - Document: True when the backend's _resolve_biblissima_document_type
            //    fell back to MANUSCRIT for an unknown nature (e.g. estampe).
            typeIsFallback: ko.observable(
                item.typeIsFallback !== undefined
                    ? !!item.typeIsFallback
                    : (self.isComponent
                        ? !item.typeValueId
                        : !!item.documentTypeIsFallback)
            ),
            typeEditing: ko.observable(false),
            // Enrichment state — Component items get lazy-enriched by fetching
            // their individual Biblissima portal page once we land on step 3.
            // The new metadata (Texte, Rubrique, descriptorLinks, Mandragore,
            // canvas dimensions…) is merged back onto the item below in
            // `_applyEnrichment` and stays in-memory until the user confirms
            // creation — nothing is persisted to the backend before the
            // explicit Create click.
            // Items with an ifdataHash will be enriched via the individual
            // portal page fetch. Items without one (IIIF descriptor search
            // path) can't be enriched — mark them as 'na' immediately so
            // the Create button doesn't stay blocked on a never-completing
            // enrichment.
            enrichStatus: ko.observable(
                self.isComponent && item.ifdataHash ? 'pending' : 'na'
            ),
            // Extra observables that the enrichment fills in. Flat storage
            // keeps the createResource payload a direct spread of the item.
            text: ko.observable(item.text || ''),
            rubric: ko.observable(item.rubric || ''),
            descriptorLinks: ko.observableArray(item.descriptorLinks || []),
            // Only take the real Mandragore ARK if the enrichment has set it.
            // item.mandragoreId is the *manuscript-level* numeric record
            // identifier from Wikibase (e.g. "1449") — it belongs to the
            // parent Document, not to this Component illumination, so we
            // must not propagate it here.
            mandragoreArk: ko.observable(item.mandragoreArk || ''),
            canvasWidth: ko.observable(item.canvasWidth || 0),
            canvasHeight: ko.observable(item.canvasHeight || 0),
            // Observable so the `<img>` template binding refreshes once the
            // enrichment returns an IIIF thumbnail URL. Backend derives it
            // generically via `{imageService}/full/200,/0/default.jpg`, so
            // any IIIF-compliant provider (Gallica, e-codices, …) works.
            thumbnail: ko.observable(item.thumbnail || ''),
        }));
        self.items(items);
    };

    // Merge fields returned by /api/biblissima/illumination/{hash} into the
    // live observable item. Only updates fields that are currently empty so
    // we never overwrite values the user might have edited in step 2.
    this._applyEnrichment = (item, data) => {
        if (!data) return;
        if (data.pageTitle) {
            // Don't overwrite a name the user already picked; just stash
            // the richer title on the item so the backend can prefer it.
            item.pageTitle = data.pageTitle;
        }
        // Type: always honour a confidently-resolved enrichment result,
        // even if the item already had a typeValueId from step 2 — the
        // individual portal page is the richer source of truth.
        if (data.typeValueId && !data.typeIsFallback) {
            item.typeValueId(data.typeValueId);
            item.typeIsFallback(false);
        } else if (data.typeIsFallback !== undefined) {
            // Enrichment confirmed the resolver still fell through to the
            // default. Leave the current valueid but sync the flag.
            item.typeIsFallback(!!data.typeIsFallback);
        }
        if (data.text && !item.text()) item.text(data.text);
        if (data.rubric && !item.rubric()) item.rubric(data.rubric);
        if (data.descriptorLinks && !item.descriptorLinks().length) {
            item.descriptorLinks(data.descriptorLinks);
        }
        if (data.mandragoreArk && !item.mandragoreArk()) {
            item.mandragoreArk(data.mandragoreArk);
        }
        // Plain (non-observable) fields that the backend scrape fills in
        // and the create-resource payload reads straight off `ko.toJS(item)`.
        // Without these merges the cart items stay stuck on their pre-
        // enrichment values (empty string from the manuscript scrape)
        // and the backend writes nothing into Period / Production / etc.
        // The date is carried both as the raw English string (for display)
        // and as pre-parsed ISO bounds + century concept (so the create
        // step can write Period + Production date tiles without re-
        // parsing and without custom French-idiom handling).
        if (data.date && !item.date) item.date = data.date;
        if (data.dateStart && !item.dateStart) item.dateStart = data.dateStart;
        if (data.dateEnd && !item.dateEnd) item.dateEnd = data.dateEnd;
        if (data.centuryConcept && !item.centuryConcept) {
            item.centuryConcept = data.centuryConcept;
        }
        if (data.typologie && !item.typologie) item.typologie = data.typologie;
        if (data.technique && !item.technique) item.technique = data.technique;
        if (data.manuscript && !item.manuscript) item.manuscript = data.manuscript;
        if (data.canvasWidth && !item.canvasWidth()) {
            item.canvasWidth(data.canvasWidth);
        }
        if (data.canvasHeight && !item.canvasHeight()) {
            item.canvasHeight(data.canvasHeight);
        }
        // Always overwrite manifestUrl/canvasId/imageServiceUrl with the
        // enrichment values. The manuscript-scrape path in step 2 stuffs
        // `item.canvasId` with the raw ifdata hash as a placeholder —
        // the illumination detail view gives us the actual IIIF Image
        // Service URL + manifest, which is what the annotation tile needs.
        if (data.manifestUrl) {
            item.manifestUrl = data.manifestUrl;
        }
        if (data.canvasId) {
            item.canvasId = data.canvasId;
        }
        if (data.imageServiceUrl) {
            item.imageServiceUrl = data.imageServiceUrl;
        }
        // `location` is what surfaces the "Lieu de fabrication" string on
        // the individual page — it's what `resolveDependencies` reads to
        // propose a Place dependency. We only fill it when the item didn't
        // already have one from the IIIF search path.
        if (data.location && !item.location) {
            item.location = data.location;
        }
        // Display-only thumbnail for the step-3 preview. Prefers a real
        // canvas thumbnail if the IIIF search path surfaced one, otherwise
        // uses `thumbnailUrl` derived provider-agnostically by
        // `_fetch_canvas_dimensions` via the IIIF Image API pattern.
        const newThumb = data.thumbnail || data.thumbnailUrl;
        if (newThumb && !item.thumbnail()) {
            item.thumbnail(newThumb);
        }
    };

    // Pooled parallel enrichment for Component cart items. We fire at most
    // `concurrency` requests at a time so 25 items don't blast 25 parallel
    // HTTP requests — the server already caches responses for 1h, so the
    // whole batch settles quickly on re-runs.
    this.enrichComponentItems = async () => {
        if (!self.isComponent) return;
        const targets = self.items().filter(
            (i) => i.ifdataHash && i.enrichStatus() === 'pending'
        );
        if (!targets.length) return;

        const concurrency = 5;
        let cursor = 0;

        const worker = async () => {
            while (cursor < targets.length) {
                const idx = cursor++;
                const item = targets[idx];
                item.enrichStatus('loading');
                try {
                    const resp = await fetch(
                        `/api/biblissima/illumination/${item.ifdataHash}`
                    );
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    const data = await resp.json();
                    self._applyEnrichment(item, data);
                    item.enrichStatus('done');
                } catch (err) {
                    console.warn(
                        `Biblissima enrichment failed for ${item.ifdataHash}`,
                        err
                    );
                    item.enrichStatus('error');
                }
            }
        };

        await Promise.all(
            Array.from(
                { length: Math.min(concurrency, targets.length) },
                () => worker()
            )
        );

        // Re-run dep resolution now that enrichment has filled in `location`
        // (production place from the individual portal page) and the other
        // per-item fields. The merge-friendly `resolveDependencies` preserves
        // deps already resolved during the first pass.
        await self.resolveDependencies();
    };

    // True when a Component item's type wasn't actually matched against the
    // Biblissima mapping (i.e. the resolver fell through to the generic
    // "Illumination" default because nothing Biblissima sent us matched a
    // known term). Document mode items never flag: they're all manuscrits.
    this.isTypeFallback = (item) => self.isComponent && item.typeIsFallback();

    // Short human label for the badge. In Component mode we deliberately show
    // the raw descriptor / typologie text from the Biblissima scrape rather
    // than looking up the concept label, since the whole point of the badge
    // is to tell the user what Biblissima sent so they can spot mis-mappings.
    // In Document mode there is no descriptor and all items default to the
    // same "manuscrit" value — so we show a generic label.
    // Short human label for the badge. Looks up the current valueid against
    // the local label map (mirrors backend BIBLISSIMA_TYPE_VALUEID_LABELS),
    // so the badge updates immediately when the user picks a new value via
    // the inline editor. Unknown valueids (rare — only if the user picks a
    // concept not in our Biblissima mapping) show as "Custom type".
    this.typeBadgeLabel = (item) => {
        const vid = item.typeValueId();
        if (!self.isComponent && vid === VALUEID_MANUSCRIT) {
            return arches.translations.biblissimaTypeManuscript || 'Manuscrit';
        }
        if (BIBLISSIMA_TYPE_LABELS[vid]) {
            return BIBLISSIMA_TYPE_LABELS[vid];
        }
        return arches.translations.biblissimaTypeCustom || 'Custom type';
    };

    this.toggleTypeEditor = (item) => {
        item.typeEditing(!item.typeEditing());
    };

    this.closeTypeEditor = (item) => {
        item.typeEditing(false);
        // Once the user confirms the editor, whatever is in typeValueId is
        // their explicit pick — clear the yellow "needs review" flag so we
        // don't keep nagging them.
        item.typeIsFallback(false);
    };

    // Count of items still resolved to the generic fallback, for the
    // "X items to review" header hint.
    this.fallbackItemsCount = ko.computed(() =>
        self.items().filter((i) =>
            i.typeIsFallback() && i.status() === 'pending'
        ).length
    );

    this.checkDuplicates = async () => {
        const graphId = self.resourceType === 'Document'
            ? '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b'
            : 'd47595b4-f8a6-419c-8f33-b388206280c4';

        const checkItems = self.items().map((i) => ({
            arkId: i.arkId || '',
            label: i.label || i.legend || '',
            shelfmark: i.shelfmark || '',
            biblissimaQid: i.biblissimaQid || '',
            portalHash: (i.arkId || '').replace('ark:/43093/', ''),
            manifestUrl: i.manifestUrl || '',
        }));

        try {
            const resp = await fetch('/api/biblissima/check-duplicates', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify({ items: checkItems, graphId }),
            });
            const data = await resp.json();
            const results = data.results || [];

            results.forEach((result) => {
                const item = self.items()[result.index];
                if (item && result.suggestions.length > 0) {
                    item.suggestions(result.suggestions);
                    item.showSuggestions(true);
                }
            });
        } catch (err) {
            console.error('Duplicate check failed:', err);
        }
        self.loading(false);
    };

    this.dismissSuggestions = (item) => {
        item.showSuggestions(false);
        item.suggestions([]);
    };

    this.useExisting = (item, suggestion) => {
        item.status('linked');
        item.linkedResourceId(suggestion.resourceId);
        item.linkedDisplayname(suggestion.displayname || '');
        item.resourceId(suggestion.resourceId);
        item.showSuggestions(false);
    };

    this.unlinkItem = (item) => {
        item.status('pending');
        item.linkedResourceId(null);
        item.linkedDisplayname('');
        item.resourceId(null);
        item.showSuggestions(true);
    };

    this.viewSuggestion = (suggestion) => {
        window.open(`/resource/${suggestion.resourceId}`, '_blank');
    };

    // =============================================
    // Dependencies
    // =============================================

    this.resolveDependencies = async () => {
        // Merge-friendly dep builder: we reuse deps that already exist on
        // self.dependencies() (keyed by `${type}:${key}`) so that reruns
        // triggered after enrichment don't blow away already-resolved
        // Place/Group/Person states. Only genuinely new keys get a fresh
        // dep instance + check-duplicates round-trip.
        const existing = new Map(
            self.dependencies().map((d) => [`${d.type}:${d.key}`, d])
        );
        const deps = [];
        const seen = new Set();

        const addDep = (key, type, graphId, parentKey, locationKey) => {
            const mapKey = `${type}:${key}`;
            if (seen.has(mapKey)) return null;
            seen.add(mapKey);
            const reused = existing.get(mapKey);
            if (reused) {
                deps.push(reused);
                return null; // already has an action, don't re-check
            }
            const dep = self._makeDep(key, type, graphId, parentKey, locationKey);
            deps.push(dep);
            return dep; // new dep → needs duplicate check
        };

        const newDeps = [];
        self.items().forEach((item) => {
            // Two distinct Places can be relevant for a single item:
            //
            //   - `ownerPlace` = where the *parent manuscript / owning
            //     institution* is kept. For both modes, this comes from
            //     `item.locationLabel` (resolved via the manuscript's
            //     Wikibase entity, e.g. "Paris (France)" for a BnF codex).
            //     - In Document mode → becomes the Document's
            //       `currentLocation` tile.
            //     - In both modes → becomes the `locationKey` of any
            //       Group dep (BnF is *in* Paris, not wherever the item
            //       was produced).
            //
            //   - `productionPlace` = where the illumination was *made*.
            //     Only surfaces in Component mode, from the individual
            //     portal page's "Lieu de fabrication" field (e.g.
            //     "Naples (Campanie, Italie)" for an illumination made
            //     in Naples and later shelved at the BnF in Paris).
            //     → becomes the Component's `productionPlace` tile.
            //
            // For Document mode, only ownerPlace is used; for Component
            // mode both can exist and end up as two separate Place deps
            // in the Related resources panel.
            const ownerPlace = item.locationLabel || "";
            const productionPlace = self.isComponent ? (item.location || "") : "";

            if (ownerPlace && ownerPlace !== "Origine inconnue") {
                const d = addDep(ownerPlace, "Place", PLACE_GRAPH_ID);
                if (d) newDeps.push(d);
            }
            if (
                productionPlace
                && productionPlace !== "Origine inconnue"
                && productionPlace !== ownerPlace
            ) {
                const d = addDep(productionPlace, "Place", PLACE_GRAPH_ID);
                if (d) newDeps.push(d);
            }

            // Groups are always located at the owner place (Paris BnF for
            // the running example) — NOT at the production place.
            const parentInst = item.parentInstitutionLabel;
            const owner = item.collectionLabel;
            if (parentInst && parentInst !== owner) {
                const d = addDep(parentInst, "Group", GROUP_GRAPH_ID, null, ownerPlace);
                if (d) newDeps.push(d);
            }
            if (owner) {
                const parentKey = (parentInst && parentInst !== owner) ? parentInst : null;
                const d = addDep(owner, "Group", GROUP_GRAPH_ID, parentKey, ownerPlace);
                if (d) newDeps.push(d);
            }

            const author = item.authorLabel;
            if (author) {
                const d = addDep(author, "Person", PERSON_GRAPH_ID);
                if (d) newDeps.push(d);
            }
        });

        self.dependencies(deps);

        for (const dep of newDeps) {
            try {
                const resp = await fetch('/api/biblissima/check-duplicates', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': self.getCSRFToken(),
                    },
                    body: JSON.stringify({
                        items: [{ label: dep.key, shelfmark: '', arkId: '', biblissimaQid: '' }],
                        graphId: dep.graphId,
                    }),
                });
                const data = await resp.json();
                const result = data.results?.[0];
                if (result?.suggestions?.length > 0) {
                    dep.suggestions(result.suggestions);
                    const best = result.suggestions.find((s) => s.confidence === 'high');
                    if (best) {
                        dep.action('use_existing');
                        dep.existingId(best.resourceId);
                        dep.existingLabel(best.displayname || dep.key);
                        self._addAltName(dep);
                    } else {
                        dep.action('has_suggestions');
                    }
                } else {
                    dep.action('create');
                }
            } catch (err) {
                console.warn('Dependency search failed for:', dep.key, err);
                dep.action('create');
            }
        }

        self.dependenciesResolved(true);
    };

    this._makeDep = (label, type, graphId, parentKey, locationKey) => ({
        key: label,
        type: type,
        graphId: graphId,
        label: ko.observable(label),
        // search | has_suggestions | pending_confirm | use_existing | create | creating | created
        action: ko.observable('search'),
        existingId: ko.observable(null),
        existingLabel: ko.observable(''),
        suggestions: ko.observableArray([]),
        creating: ko.observable(false),
        // Relationships to other deps (for Groups)
        parentKey: parentKey || null,   // key of parent Group dep (member of)
        locationKey: locationKey || null, // key of Place dep (location)
    });

    // User picks a suggestion → direct link (intentional click)
    this.useExistingDep = (dep, suggestion) => {
        dep.action('use_existing');
        dep.existingId(suggestion.resourceId);
        dep.existingLabel(suggestion.displayname || dep.key);
        self._addAltName(dep);
    };

    // User confirms the Select2 selection (from pending_confirm → use_existing)
    this.confirmDepSelection = (dep) => {
        dep.action('use_existing');
        self._addAltName(dep);
    };

    // User cancels the Select2 preview (from pending_confirm → back)
    this.cancelDepSelection = (dep) => {
        dep.existingId(null);
        dep.existingLabel('');
        dep.action(dep.suggestions().length > 0 ? 'has_suggestions' : 'create');
    };

    this.dismissDepSuggestions = (dep) => {
        dep.suggestions([]);
        dep.action('create');
    };

    // Unlink from green state → back to search area
    this.unlinkDep = (dep) => {
        dep.existingId(null);
        dep.existingLabel('');
        dep.action(dep.suggestions().length > 0 ? 'has_suggestions' : 'create');
    };

    this.viewDepSuggestion = (suggestion) => {
        window.open(`/resource/${suggestion.resourceId}`, '_blank');
    };

    // Manually create a single dependency resource (resolves parent/location first)
    this.createDependency = async (dep) => {
        if (dep.action() === 'use_existing' || dep.action() === 'created' || dep.creating()) return;

        dep.creating(true);
        dep.action('creating');

        try {
            // Ensure parent Group exists first (for "member of")
            let memberOfId = null;
            if (dep.parentKey) {
                const parentDep = self.dependencies().find(
                    (d) => d.type === 'Group' && d.key === dep.parentKey
                );
                if (parentDep) {
                    if (!parentDep.existingId()) {
                        await self.createDependency(parentDep);
                    }
                    memberOfId = parentDep.existingId();
                }
            }

            // Ensure Place exists first (for "location")
            let locationId = null;
            if (dep.locationKey) {
                const placeDep = self.dependencies().find(
                    (d) => d.type === 'Place' && d.key === dep.locationKey
                );
                if (placeDep) {
                    if (!placeDep.existingId()) {
                        await self.createDependency(placeDep);
                    }
                    locationId = placeDep.existingId();
                }
            }

            const resp = await fetch('/api/biblissima/create-resource', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify({
                    resourceType: dep.type,
                    biblissimaData: {
                        label: dep.key,
                        memberOf: memberOfId,
                        location: locationId,
                    },
                }),
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Creation failed');
            }

            const data = await resp.json();
            dep.existingId(data.resourceId);
            dep.existingLabel(data.displayname || dep.key);
            dep.action('created');

            const cacheKey = DEP_TYPE_MAP[dep.type]?.cacheKey;
            if (cacheKey) {
                self.dependencyCache[cacheKey][dep.key] = data.resourceId;
            }
        } catch (err) {
            console.error('Dependency creation failed:', dep.key, err);
            dep.action('create');
        } finally {
            dep.creating(false);
        }
    };

    // Add Biblissima label as alt name to existing resource (non-blocking)
    this._addAltName = async (dep) => {
        if (!dep.existingId() || !dep.key) return;
        try {
            await fetch('/api/biblissima/add-alt-name', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify({
                    resourceId: dep.existingId(),
                    graphId: dep.graphId,
                    label: dep.key,
                }),
            });
        } catch (err) {
            console.warn('Alt name addition failed for:', dep.key, err);
        }
    };

    // =============================================
    // Resource creation
    // =============================================

    /**
     * Create a single Arches resource from a cart item.
     *
     * Two call modes, sharing the same dep-resolution logic so that a
     * parent Document created on the fly receives the same
     * currentLocation / currentOwner / etc. tiles as a top-level Document
     * created in Document mode:
     *
     *   1. Default (`options` omitted): create the cart item itself —
     *      Component or top-level Document depending on ``self.resourceType``.
     *      Item status transitions are managed here.
     *   2. Parent mode (``options.asParent === true``): create a parent
     *      Document on behalf of ``parentResolver``. The cart item is only
     *      used as the source for dep lookups (its collectionLabel,
     *      parentInstitutionLabel, locationLabel) — the actual payload
     *      ``biblissimaData`` comes from ``options.biblissimaData`` (the
     *      Wikibase entity payload), and state updates flow through
     *      ``options.onSuccess(resourceId)`` instead of mutating
     *      ``item.status``.
     *
     * Options:
     *   - ``asParent``       (bool) flip Component→Document behavior for
     *                        this single call (Place dep → currentLocation,
     *                        no parentDocument link, etc.).
     *   - ``biblissimaData`` (object) override the payload body sent to
     *                        the backend; defaults to ``ko.toJS(item)``.
     *   - ``conceptMappings`` (object) override (defaults to ``{type: item.typeValueId}``).
     *   - ``onSuccess``      (fn) called with ``(resourceId, data)`` on
     *                        success when ``asParent`` is true. Caller is
     *                        responsible for updating the parent group state.
     *
     * Returns the created ``resourceId`` (string) or ``undefined`` on
     * skip/error in default mode. Throws in parent mode so the caller can
     * branch on success/failure.
     */
    this.createResource = async (item, options = {}) => {
        const asParent = !!options.asParent;

        if (!asParent) {
            if (item.status() === 'created' || item.status() === 'skipped') return;
            item.status('creating');
        }

        // Auto-create any unresolved deps before creating the resource.
        // ``item`` is the dep source in both modes (a representative cart
        // item from the parent group in parent mode).
        await self._ensureDepsCreated(item);

        // A parent Document creation behaves like Document mode: Place dep
        // → currentLocation tile, no parentDocument link, etc.
        const isDocumentLike = asParent || !self.isComponent;

        const deps = {
            project: self.projectId,
            parentDocument: (!asParent && self.isComponent)
                ? self.parentResolver.parentIdFor(item)
                : null,
        };

        // Place dep. For Document → currentLocation tile (where the
        // manuscript is kept). For Component → productionPlace tile
        // (where the illumination was made). The backend
        // `_create_component_tiles` reads `deps.productionPlace`, and
        // `_create_document_tiles` reads `deps.currentLocation`; we have
        // to send the right key.
        const locationKey = self._placeKeyForItem(item);
        const placeDep = self.dependencies().find(
            (d) => d.type === 'Place' && d.key === locationKey
        );
        if (placeDep && placeDep.existingId()) {
            if (isDocumentLike) {
                deps.currentLocation = placeDep.existingId();
            } else {
                deps.productionPlace = placeDep.existingId();
            }
        }

        // Owner Group deps (collection + parent institution, deduplicated)
        const ownerIds = new Set();
        const ownerDep = self.dependencies().find(
            (d) => d.type === 'Group' && d.key === item.collectionLabel
        );
        if (ownerDep && ownerDep.existingId()) {
            ownerIds.add(ownerDep.existingId());
        }
        const parentInstDep = self.dependencies().find(
            (d) => d.type === 'Group' && d.key === item.parentInstitutionLabel
                && d.key !== item.collectionLabel
        );
        if (parentInstDep && parentInstDep.existingId()) {
            ownerIds.add(parentInstDep.existingId());
        }
        if (ownerIds.size > 0) {
            deps.currentOwner = [...ownerIds];
        }

        // Person dep (author)
        const personDep = self.dependencies().find(
            (d) => d.type === 'Person' && d.key === item.authorLabel
        );
        if (personDep && personDep.existingId()) {
            deps.productionActors = [personDep.existingId()];
        }

        // Per-item resolved type (may have been corrected by the user via
        // the inline concept-select-widget). Document items default to
        // VALUEID_MANUSCRIT, Component items to the server-resolved valueid.
        // ko.toJS unwraps all observables on the item (status, typeValueId,
        // enriched text/rubric/descriptorLinks/...) so the payload is a pure
        // JSON-serializable snapshot of the current in-memory state.
        const body = {
            resourceType: asParent ? 'Document' : self.resourceType,
            transactionId: null,
            biblissimaData: options.biblissimaData || ko.toJS(item),
            dependencies: deps,
            conceptMappings: options.conceptMappings || {
                type: ko.unwrap(item.typeValueId),
            },
        };

        try {
            const resp = await fetch('/api/biblissima/create-resource', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Creation failed');
            }

            const data = await resp.json();

            if (data.createdDependencies) {
                Object.assign(self.dependencyCache.places, data.createdDependencies.places || {});
                Object.assign(self.dependencyCache.persons, data.createdDependencies.persons || {});
                Object.assign(self.dependencyCache.groups, data.createdDependencies.groups || {});
            }

            if (asParent) {
                if (options.onSuccess) options.onSuccess(data.resourceId, data);
            } else {
                item.resourceId(data.resourceId);
                item.status('created');
            }
            return data.resourceId;
        } catch (err) {
            if (asParent) {
                throw err;
            }
            item.status('error');
            item.errorMessage(err.message || 'Unknown error');
            console.error('Resource creation failed:', err);
        }
    };

    // Auto-create deps that are not yet resolved for a given item
    this._ensureDepsCreated = async (item) => {
        const itemDeps = [];
        const locationKey = self._placeKeyForItem(item);

        for (const dep of self.dependencies()) {
            if (dep.type === 'Place' && dep.key === locationKey) itemDeps.push(dep);
            if (dep.type === 'Group' && dep.key === item.collectionLabel) itemDeps.push(dep);
            if (dep.type === 'Group' && dep.key === item.parentInstitutionLabel && dep.key !== item.collectionLabel) itemDeps.push(dep);
            if (dep.type === 'Person' && dep.key === item.authorLabel) itemDeps.push(dep);
        }

        for (const dep of itemDeps) {
            if (!dep.existingId() && dep.action() !== 'creating') {
                await self.createDependency(dep);
            }
        }
    };

    this.createAll = async () => {
        self.creatingAll(true);
        const pendingItems = self.items().filter(
            (i) => i.status() === 'pending'
        );

        for (const item of pendingItems) {
            await self.createResource(item);
        }
        self.creatingAll(false);
    };

    this.skipItem = (item) => {
        item.status('skipped');
    };

    this.editResource = (item) => {
        if (item.resourceId()) {
            window.open(`/resource/${item.resourceId()}`, '_blank');
        }
    };

    this.viewDuplicate = (item) => {
        if (item.duplicateResourceId()) {
            window.open(`/resource/${item.duplicateResourceId()}`, '_blank');
        }
    };

    this.forceCreate = (item) => {
        item.status('pending');
        item.duplicateResourceId(null);
        self.createResource(item);
    };

    this.refreshItem = async (item) => {
        if (!item.resourceId()) return;
        try {
            const resp = await fetch(
                `${arches.urls.api_resources(item.resourceId())}?format=json&compact=false&v=beta`
            );
            if (resp.ok) {
                const data = await resp.json();
                if (data.displayname) {
                    item.label = data.displayname;
                    self.items.valueHasMutated();
                }
            }
        } catch (err) {
            console.warn('Failed to refresh item:', err);
        }
    };

    this._focusHandler = () => {
        self.items().forEach((item) => {
            if (item.status() === 'created' && item.resourceId()) {
                self.refreshItem(item);
            }
        });
    };
    window.addEventListener('focus', this._focusHandler);

    this.dispose = () => {
        window.removeEventListener('focus', self._focusHandler);
    };

    // =============================================
    // Dep picker (Select2) — selection goes to pending_confirm
    // =============================================

    this.buildDepPickerConfig = (dep) => {
        const selectedValue = ko.observable(null);
        selectedValue.subscribe((val) => {
            if (val && typeof val === 'string' && val.length > 10) {
                fetch(`${arches.urls.api_resources(val)}?format=json&compact=false&v=beta`)
                    .then((r) => r.ok ? r.json() : null)
                    .then((data) => {
                        dep.existingId(val);
                        dep.existingLabel(data?.displayname || dep.key);
                        dep.action('pending_confirm');
                    })
                    .catch(() => {
                        dep.existingId(val);
                        dep.existingLabel(dep.key);
                        dep.action('pending_confirm');
                    });
            }
        });

        return {
            value: selectedValue,
            clickBubble: true,
            multiple: false,
            closeOnSelect: true,
            allowClear: true,
            placeholder: arches.translations.biblissimaSearchExisting || 'Search existing resource...',
            minimumInputLength: 0,
            ajax: {
                url: arches.urls.search_results,
                dataType: 'json',
                quietMillis: 250,
                data: (requestParams) => {
                    const params = {
                        'paging-filter': 1,
                        'resource-type-filter': JSON.stringify([
                            { graphid: dep.graphId, inverted: false }
                        ]),
                    };
                    const term = (requestParams.term || '').trim();
                    if (term) {
                        params['term-filter'] = JSON.stringify([{
                            inverted: false,
                            type: 'string',
                            context: '',
                            context_label: '',
                            id: term,
                            text: term,
                            value: term,
                        }]);
                    }
                    return params;
                },
                processResults: (data) => {
                    const hits = data?.results?.hits?.hits || [];
                    return {
                        results: hits.map((hit) => ({
                            id: hit._id,
                            text: hit._source?.displayname || hit._id,
                        })).filter((r) => r.text && r.text !== 'Undefined'),
                    };
                },
            },
            templateResult: (item) => item.text || '',
            templateSelection: (item) => item.text || '',
            escapeMarkup: (m) => m,
        };
    };

    // =============================================
    // Submit
    // =============================================

    this.submit = () => {
        const created = self.items().filter((i) => i.status() === 'created');
        const linked = self.items().filter((i) => i.status() === 'linked');

        params.value({
            createdResources: created.map((i) => ({
                resourceId: i.resourceId(),
                label: i.label || i.legend || '',
                arkId: i.arkId,
                manuscript: i.manuscript,
                shelfmark: i.shelfmark || '',
                folio: i.folio || '',
                date: i.date || '',
                thumbnail: (typeof i.thumbnail === 'function' ? i.thumbnail() : i.thumbnail) || '',
            })),
            linkedResources: linked.map((i) => ({
                resourceId: i.linkedResourceId(),
                displayname: i.linkedDisplayname(),
                biblissimaLabel: i.label || i.legend || '',
                arkId: i.arkId,
                biblissimaQid: i.biblissimaQid || '',
                manifestUrl: i.manifestUrl || '',
                shelfmark: i.shelfmark || '',
                enrichExisting: i.enrichExisting(),
            })),
            skippedCount: self.items().filter((i) => i.status() === 'skipped').length,
            errorCount: self.items().filter((i) => i.status() === 'error').length,
            resourceType: self.resourceType,
            projectId: self.projectId,
        });
        self.complete(true);
    };

    // =============================================
    // Helpers
    // =============================================

    this.getCSRFToken = () => {
        const cookie = document.cookie.split(';').find((c) => c.trim().startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    };

    this.statusClass = (status) => {
        const map = {
            pending: '',
            creating: 'info',
            created: 'success',
            linked: 'linked',
            error: 'danger',
            skipped: 'warning',
            duplicate: 'warning',
        };
        return map[status] || '';
    };

    this.statusLabel = (status) => {
        const map = {
            pending: arches.translations.biblissimaPending || 'Pending',
            creating: arches.translations.biblissimaCreating || 'Creating...',
            created: arches.translations.biblissimaCreated || 'Created',
            linked: arches.translations.biblissimaLinked || 'Linked',
            error: arches.translations.biblissimaError || 'Error',
            skipped: arches.translations.biblissimaSkipped || 'Skipped',
            duplicate: arches.translations.biblissimaDuplicate || 'Duplicate',
        };
        return map[status] || status;
    };

    // =============================================
    // Init
    // =============================================

    // Init sequence — proper ordering to avoid race conditions:
    // 1. Build items from cart data (sync)
    // 2. First dep resolution pass from cart data (await: must complete
    //    before enrichment's second pass can merge correctly)
    // 3. Duplicate check + enrichment run in parallel
    // 4. Enrichment ends with its own resolveDependencies (second pass)
    //    that merge-adds newly discovered deps (e.g. Naples production
    //    place) without losing the first-pass deps (Paris, Groups).
    this.initializeItems();
    (async () => {
        // Parent-resolver runs in parallel with deps/enrichment in
        // Component mode — they are independent: parent resolution hits
        // /check-duplicates on Documents, deps hit Place/Person/Group.
        const parentPromise = self.isComponent
            ? self.parentResolver.resolveAll()
            : Promise.resolve();
        await self.resolveDependencies();
        self.checkDuplicates();
        await self.enrichComponentItems();
        await parentPromise;
    })();
};

ko.components.register('biblissima-create-step', {
    viewModel: viewModel,
    template: biblissimaCreateStepTemplate,
});

export default viewModel;
