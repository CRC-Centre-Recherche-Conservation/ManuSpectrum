/**
 * parentResolver.js — Step 3 helper for import-biblissima-workflow.
 *
 * Resolves the parent Document of every Component in the cart by grouping
 * cart items on their Biblissima manuscript (portalHash), then for each
 * group offering a match-or-create flow against Arches:
 *
 *   - GET  /api/biblissima/illumination/<hash>   (best-effort orphan resolution)
 *   - POST /api/biblissima/check-duplicates       (find existing Documents)
 *   - GET  /api/biblissima/entity/<qid>           (fresh manuscript payload)
 *   - POST /api/biblissima/create-resource        (create the Document)
 *   - POST /api/biblissima/add-alt-name           (enrich a matched Document, optional)
 *   - POST /api/biblissima/link-to-project        (matched/manual parents only)
 *
 * State machine per group (mirrors the Place/Person/Group dependency pattern
 * already in use in biblissima-create-step.js):
 *
 *   search → has_suggestions → resolved
 *                            → error    (retry → has_suggestions)
 *
 * Only the Component flow uses this resolver — Document mode creates one
 * Document per cart item with no parent concept.
 */
import ko from "knockout";
import arches from "arches";

const DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b";

// Cap parallel /check-duplicates requests so we don't slam the proxy when
// the cart spans many manuscripts. 3 is enough to feel instant on typical
// carts (1–5 distinct manuscripts) and stays gentle on the backend.
const CHECK_DUPLICATES_PARALLELISM = 3;
// Same idea for the orphan best-effort resolution.
const ORPHAN_RESOLUTION_PARALLELISM = 5;

/**
 * Build a ParentGroup observable bag.
 * @param {object} seed  - { portalHash, biblissimaQid, label, shelfmark, items }
 */
function makeGroup(seed) {
    return {
        portalHash: seed.portalHash,
        biblissimaQid: seed.biblissimaQid,
        label: seed.label,
        shelfmark: seed.shelfmark,
        items: ko.observableArray(seed.items || []),

        state: ko.observable("search"),
        suggestions: ko.observableArray([]),
        resolvedResourceId: ko.observable(null),
        resolvedDisplayname: ko.observable(""),
        resolutionMode: ko.observable(null), // 'matched' | 'created' | 'manual'
        enrichExisting: ko.observable(false),
        creating: ko.observable(false),
        typeIsFallback: ko.observable(false),
        typeValueId: ko.observable(null),
        errorMessage: ko.observable(""),
    };
}

/**
 * Run an async function over a list with bounded parallelism.
 * Does not stop on error; per-task failures are captured in the result slot
 * as `{ error }` so partial successes still propagate.
 */
async function mapBounded(items, limit, fn) {
    const results = new Array(items.length);
    let next = 0;
    async function worker() {
        while (next < items.length) {
            const idx = next++;
            try {
                results[idx] = await fn(items[idx], idx);
            } catch (err) {
                results[idx] = { error: err };
            }
        }
    }
    const workers = Array.from({ length: Math.min(limit, items.length) }, () =>
        worker(),
    );
    await Promise.all(workers);
    return results;
}

export default function ParentResolver(params) {
    const self = this;
    const cart = params.cart; // ko.observableArray
    const projectId = params.projectId; // string | null
    const isComponent = params.isComponent; // boolean
    const getCSRFToken = params.getCSRFToken; // () => string

    self.groups = ko.observableArray([]);
    self.unidentifiedItems = ko.observableArray([]);
    self.orphanAssignments = {}; // canvasId → resourceId
    self.resolving = ko.observable(false);
    self.resolveError = ko.observable(null);

    self.allResolved = ko.computed(() => {
        if (!isComponent) return true;
        if (self.resolving()) return false;
        const groupsOk = self.groups().every((g) => g.state() === "resolved");
        const orphansOk = self
            .unidentifiedItems()
            .every((it) => !!self.orphanAssignments[it.canvasId]);
        return groupsOk && orphansOk;
    });

    self.resolvedCount = ko.computed(
        () => self.groups().filter((g) => g.state() === "resolved").length,
    );
    self.totalCount = ko.computed(() => self.groups().length);

    // -------------------------------------------------------------------
    // Public API: resolveAll() — entry point invoked at step-3 mount.
    // -------------------------------------------------------------------
    self.resolveAll = async () => {
        if (!isComponent) return;
        self.resolving(true);
        self.resolveError(null);
        try {
            const items = ko.unwrap(cart);
            const { groupSeeds, orphans } = await self._buildGroups(items);
            self._reconcileGroups(groupSeeds);
            self.unidentifiedItems(orphans);
            await self._fetchSuggestions();
        } catch (err) {
            self.resolveError(err.message || String(err));
        } finally {
            self.resolving(false);
        }
    };

    // -------------------------------------------------------------------
    // Step 1: groupBy(portalHash || biblissimaQid || manuscriptArk).
    //
    // We derive portalHash from manuscriptArk when both portalHash and
    // biblissimaQid are missing — this happens when _enrich_canvases failed
    // to resolve the manuscript on Wikibase (e.g. wbsearchentities on a
    // shelfmark that is just a number like "579" returns garbage candidates,
    // none of which match the portalHash). The IIIF manifest still gives us
    // a canonical manuscriptArk per canvas, so we never lose track of which
    // manuscript an illumination belongs to.
    //
    // Items still without ANY identifier go to orphans; orphans with an
    // ifdataHash get a best-effort resolution via
    // /api/biblissima/illumination/<hash>, which often surfaces the parent
    // manuscript and lets us re-route the item to the correct group.
    // -------------------------------------------------------------------
    self._buildGroups = async (items) => {
        const groupSeeds = new Map(); // key → seed
        const orphans = [];
        for (const item of items) {
            // Derive portalHash from manuscriptArk when missing (failed
            // Wikibase enrichment fallback).
            let portalHash = item.portalHash || null;
            if (!portalHash && item.manuscriptArk) {
                portalHash = String(item.manuscriptArk).replace(
                    /^ark:\/43093\//,
                    "",
                );
                // Hydrate the cart item so parentIdFor() finds it later via
                // the same key path as natively-grouped items.
                item.portalHash = portalHash;
            }
            const key = portalHash || item.biblissimaQid;
            if (!key) {
                orphans.push(item);
                continue;
            }
            if (!groupSeeds.has(key)) {
                groupSeeds.set(key, {
                    portalHash: portalHash,
                    biblissimaQid: item.biblissimaQid || null,
                    label: item.manuscript || item.shelfmark || key,
                    shelfmark: item.shelfmark || "",
                    items: [],
                });
            }
            groupSeeds.get(key).items.push(item);
        }

        // Best-effort orphan resolution.
        const stillOrphans = [];
        await mapBounded(
            orphans,
            ORPHAN_RESOLUTION_PARALLELISM,
            async (orphan) => {
                const hash = orphan.ifdataHash;
                if (!hash) {
                    stillOrphans.push(orphan);
                    return;
                }
                try {
                    const resp = await fetch(
                        `/api/biblissima/illumination/${hash}`,
                    );
                    if (!resp.ok) {
                        stillOrphans.push(orphan);
                        return;
                    }
                    const data = await resp.json();
                    const newKey =
                        data.parentPortalHash || data.parentBiblissimaQid;
                    if (!newKey) {
                        stillOrphans.push(orphan);
                        return;
                    }
                    if (!groupSeeds.has(newKey)) {
                        groupSeeds.set(newKey, {
                            portalHash: data.parentPortalHash || null,
                            biblissimaQid: data.parentBiblissimaQid || null,
                            label:
                                data.parentLabel || data.manuscript || newKey,
                            shelfmark: data.parentShelfmark || "",
                            items: [],
                        });
                    }
                    // Hydrate the orphan with the freshly-discovered parent ids
                    // so parentIdFor() can find it via the same key path as the
                    // already-grouped items.
                    orphan.portalHash =
                        data.parentPortalHash || orphan.portalHash;
                    orphan.biblissimaQid =
                        data.parentBiblissimaQid || orphan.biblissimaQid;
                    groupSeeds.get(newKey).items.push(orphan);
                } catch {
                    stillOrphans.push(orphan);
                }
            },
        );

        return {
            groupSeeds: Array.from(groupSeeds.values()),
            orphans: stillOrphans,
        };
    };

    // -------------------------------------------------------------------
    // Diff-merge groupSeeds into self.groups so that revisits to step 3
    // do not lose user-resolved state (cf. design 7.8).
    // -------------------------------------------------------------------
    self._reconcileGroups = (seeds) => {
        const seedKeys = new Set(
            seeds.map((s) => s.portalHash || s.biblissimaQid),
        );
        const existing = self.groups();
        // Drop groups whose key disappeared.
        const kept = existing.filter((g) => {
            const k = g.portalHash || g.biblissimaQid;
            return seedKeys.has(k);
        });
        const keptByKey = new Map(
            kept.map((g) => [g.portalHash || g.biblissimaQid, g]),
        );
        const merged = seeds.map((seed) => {
            const k = seed.portalHash || seed.biblissimaQid;
            if (keptByKey.has(k)) {
                const g = keptByKey.get(k);
                g.items(seed.items);
                return g;
            }
            return makeGroup(seed);
        });
        self.groups(merged);
    };

    // -------------------------------------------------------------------
    // Step 2: for every group still in 'search', POST /check-duplicates and
    // surface the suggestions. Errors are captured per-group so a single
    // failure does not cascade.
    // -------------------------------------------------------------------
    self._fetchSuggestions = async () => {
        const targets = self.groups().filter((g) => g.state() === "search");
        await mapBounded(
            targets,
            CHECK_DUPLICATES_PARALLELISM,
            async (group) => {
                try {
                    const resp = await fetch(
                        "/api/biblissima/check-duplicates",
                        {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json",
                                "X-CSRFToken": getCSRFToken(),
                            },
                            body: JSON.stringify({
                                graphId: DOCUMENT_GRAPH_ID,
                                items: [
                                    {
                                        arkId: group.portalHash
                                            ? `ark:/43093/${group.portalHash}`
                                            : null,
                                        portalHash: group.portalHash || "",
                                        biblissimaQid:
                                            group.biblissimaQid || "",
                                        shelfmark: group.shelfmark || "",
                                        label: group.label || "",
                                    },
                                ],
                            }),
                        },
                    );
                    if (!resp.ok) {
                        group.suggestions([]);
                    } else {
                        const data = await resp.json();
                        const first = (data.results || [])[0] || {};
                        group.suggestions(first.suggestions || []);
                    }
                } catch (e) {
                    group.suggestions([]);
                    group.errorMessage(e.message || String(e));
                } finally {
                    group.state("has_suggestions");
                }
            },
        );
    };

    // -------------------------------------------------------------------
    // Resolution actions (user-driven).
    // -------------------------------------------------------------------
    self.useMatch = async (group, suggestion) => {
        group.resolvedResourceId(suggestion.resourceId);
        group.resolvedDisplayname(suggestion.displayname || "");
        group.resolutionMode("matched");
        group.state("resolved");
        if (group.enrichExisting()) {
            await self._addAltName(group);
        }
        if (projectId) {
            await self._linkToProject(group);
        }
    };

    self.pickManual = async (group, resourceId, displayname) => {
        group.resolvedResourceId(resourceId);
        group.resolvedDisplayname(displayname || "");
        group.resolutionMode("manual");
        group.state("resolved");
        if (projectId) {
            await self._linkToProject(group);
        }
    };

    self.unlinkParent = (group) => {
        group.resolvedResourceId(null);
        group.resolvedDisplayname("");
        group.resolutionMode(null);
        group.state("has_suggestions");
        group.errorMessage("");
    };

    self.toggleEnrichExisting = (group) => {
        group.enrichExisting(!group.enrichExisting());
    };

    self.assignManualToOrphan = (item, resourceId, displayname) => {
        self.orphanAssignments[item.canvasId] = resourceId;
        // Trigger a recompute of allResolved by mutating the array.
        self.unidentifiedItems.valueHasMutated();
        // Display name surfaced via item.linkedDisplayname for the template.
        if (item.linkedDisplayname) item.linkedDisplayname(displayname || "");
    };

    self.createParent = async (group) => {
        group.creating(true);
        group.errorMessage("");
        try {
            // If the group only carries a portalHash (Wikibase enrichment
            // failed in _enrich_canvases — typical for shelfmark-only labels
            // like "579" that wbsearchentities can't disambiguate), resolve
            // the QID from the portalHash via the suggest endpoint first.
            // The suggest backend matches portalHash against P129 statements.
            if (!group.biblissimaQid && group.portalHash) {
                const suggestResp = await fetch(
                    `/api/biblissima/suggest?q=${encodeURIComponent(
                        group.portalHash,
                    )}&limit=5`,
                );
                if (suggestResp.ok) {
                    const suggestData = await suggestResp.json();
                    const first = (suggestData.results || [])[0];
                    if (first && first.id) {
                        group.biblissimaQid = first.id;
                    }
                }
            }
            if (!group.biblissimaQid) {
                throw new Error(
                    arches.translations.biblissimaParentResolverNoQid ||
                        "Cannot create parent — no Biblissima QID",
                );
            }
            const entityResp = await fetch(
                `/api/biblissima/entity/${group.biblissimaQid}`,
            );
            if (!entityResp.ok) {
                throw new Error(
                    `entity/${group.biblissimaQid} → ${entityResp.status}`,
                );
            }
            const entityData = await entityResp.json();

            const body = {
                resourceType: "Document",
                transactionId: null,
                biblissimaData: entityData,
                dependencies: projectId ? { project: projectId } : {},
                conceptMappings: {
                    type: entityData.documentTypeValueId || null,
                },
            };
            const createResp = await fetch("/api/biblissima/create-resource", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken(),
                },
                body: JSON.stringify(body),
            });
            if (!createResp.ok) {
                const err = await createResp.json().catch(() => ({}));
                throw new Error(
                    err.error || `create-resource → ${createResp.status}`,
                );
            }
            const data = await createResp.json();
            group.resolvedResourceId(data.resourceId);
            group.resolvedDisplayname(entityData.label || group.label);
            group.resolutionMode("created");
            group.typeValueId(entityData.documentTypeValueId || null);
            group.typeIsFallback(!!entityData.documentTypeIsFallback);
            group.state("resolved");
        } catch (err) {
            group.errorMessage(err.message || String(err));
            group.state("error");
        } finally {
            group.creating(false);
        }
    };

    self._addAltName = async (group) => {
        try {
            await fetch("/api/biblissima/add-alt-name", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken(),
                },
                body: JSON.stringify({
                    resourceId: group.resolvedResourceId(),
                    graphId: DOCUMENT_GRAPH_ID,
                    label: group.portalHash
                        ? `ark:/43093/${group.portalHash}`
                        : group.biblissimaQid || group.label,
                }),
            });
        } catch (e) {
            // Non-fatal: the link succeeded; alt-name is just a niceness.
            console.warn("add-alt-name failed for parent group", e);
        }
    };

    self._linkToProject = async (group) => {
        // Created parents are linked server-side via dependencies.project
        // during create-resource (skip here to avoid a redundant call).
        // Matched / manually-picked parents are linked via a dedicated
        // endpoint, which is idempotent on the backend (cf. Task 1.7's
        // _link_to_project dedup).
        if (!projectId || !group.resolvedResourceId()) return;
        if (group.resolutionMode() === "created") return;
        try {
            await fetch("/api/biblissima/link-to-project", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken(),
                },
                body: JSON.stringify({
                    resourceId: group.resolvedResourceId(),
                    projectId,
                }),
            });
        } catch (e) {
            console.warn("link-to-project failed for parent group", e);
        }
    };

    // -------------------------------------------------------------------
    // Lookup consumed by createResource in biblissima-create-step.js.
    // -------------------------------------------------------------------
    self.parentIdFor = (item) => {
        const key = item.portalHash || item.biblissimaQid;
        if (!key) {
            return self.orphanAssignments[item.canvasId] || null;
        }
        const group = self
            .groups()
            .find((g) => (g.portalHash || g.biblissimaQid) === key);
        return group ? group.resolvedResourceId() : null;
    };

    self.shouldEnrichExisting = (item) => {
        const key = item.portalHash || item.biblissimaQid;
        if (!key) return false;
        const group = self
            .groups()
            .find((g) => (g.portalHash || g.biblissimaQid) === key);
        return group ? group.enrichExisting() : false;
    };
}
